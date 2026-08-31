from __future__ import annotations

import json
import base64
import io
import os
import stat
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from pathlib import Path

from llm_hardtest.backends import Backend, BackendError, CodexBackend, OpenAICompatBackend
from llm_hardtest.cli import _selftest_source_paths, discover_models, doctor_config, main
from llm_hardtest.common import answer_matches, answer_text, load_json, save_json
from llm_hardtest.orchestrator import _campaign_units, run as run_campaign, validate_config
from llm_hardtest.progress import TerminalDashboard, _duration
from llm_hardtest.report import collect, generate, render
from llm_hardtest.results import item_status, result_counts
from llm_hardtest.inspection import inspect_run, render_inspection
from llm_hardtest.replay import make_replay_config
from llm_hardtest.packs import validate_pack
from llm_hardtest.public_results import (
    build_public_result, export_public_bundle, load_public_bundle,
    validate_public_result,
)
from llm_hardtest.github_submit import (
    open_submission_pr, preview_submission, submission_document,
    submission_relative_path,
)
from llm_hardtest.community_results import (
    aggregate_submissions, build_index, load_submission_directory, render_index,
)
from llm_hardtest.calibration import analyze_runs, render_analysis, write_analysis
from llm_hardtest.pilot_analysis import analyze_pilots, write_pilot_analysis
from llm_hardtest.round5 import run_pilot
from llm_hardtest.round12 import run as run_round12
from llm_hardtest.round3 import _fields, _grade
from llm_hardtest.round4 import run as run_round4


class AnswerTests(unittest.TestCase):
    def test_extracts_last_answer_line(self):
        self.assertEqual(answer_text("work\nANSWER: 42"), "42")

    def test_normalization_is_stable(self):
        self.assertTrue(answer_matches("1,024 %", "1024"))
        self.assertFalse(answer_matches("1025", "1024"))

    def test_partial_answer_is_not_accepted(self):
        self.assertFalse(answer_matches("142", "42"))
        self.assertEqual(answer_text("The answer might be 42."), "")


class ResultStatusTests(unittest.TestCase):
    def test_legacy_output_limit_is_inferred_as_incomplete(self):
        row = {"correct": False, "finish_reason": "length"}
        self.assertEqual(item_status(row), "INCOMPLETE")
        self.assertEqual(result_counts({"score": 0, "total": 1, "results": [row]}), {
            "PASS": 0, "FAIL": 0, "INCOMPLETE": 1, "REVIEW": 0, "INVALID": 0,
        })

    def test_aggregate_only_legacy_payload_remains_reportable(self):
        self.assertEqual(result_counts({
            "score": 2, "total": 3, "manual_review": 1,
            "infrastructure_errors": 1,
        }), {
            "PASS": 2, "FAIL": 1, "INCOMPLETE": 0, "REVIEW": 1, "INVALID": 1,
        })


class InspectionTests(unittest.TestCase):
    def test_inspection_reads_legacy_and_current_unresolved_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run-one"
            save_json(root / "config.json", {
                "models": [{"key": "m", "model": "m"}],
            })
            save_json(root / "m/round1/attempt-1/result.json", {
                "attempt": 1,
                "results": [
                    {"id": 1, "correct": True},
                    {"id": 2, "correct": False, "extracted": "7"},
                    {"id": 3, "correct": False, "finish_reason": "length"},
                    {"id": 4, "correct": None, "valid": False,
                     "error": "server unavailable"},
                ],
            })
            summary = inspect_run(root)
        self.assertEqual(summary["unresolved"], 3)
        self.assertEqual([item["status"] for item in summary["items"]],
                         ["FAIL", "INCOMPLETE", "INVALID"])
        text = render_inspection(summary)
        self.assertIn("q2\tFAIL\textracted=7", text)
        self.assertIn("q3\tINCOMPLETE\tlength", text)
        self.assertIn("q4\tINVALID\tserver unavailable", text)

    def test_clean_inspection_has_stable_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "clean-run"
            save_json(root / "config.json", {"models": []})
            summary = inspect_run(root)
        self.assertEqual(render_inspection(summary), "clean-run: no unresolved items")

    def test_inspection_requires_a_run_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "config.json"):
                inspect_run(Path(tmp))

    def test_inspection_rejects_a_traversing_model_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            save_json(root / "config.json", {"models": [{"key": "../escape"}]})
            with self.assertRaisesRegex(ValueError, "unsafe model key"):
                inspect_run(root)


class ReplayTests(unittest.TestCase):
    def test_replay_config_selects_only_unresolved_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source-run"
            config = {
                "name": "source", "repetitions": 5, "rounds": [1, 2],
                "models": [
                    {"key": "a", "model": "a", "transport": "openai_compat",
                     "rounds": [1, 2]},
                    {"key": "b", "model": "b", "transport": "openai_compat",
                     "rounds": [1]},
                ],
            }
            save_json(root / "config.json", config)
            save_json(root / "a/round1/attempt-1/result.json", {"results": [
                {"id": 1, "correct": True},
                {"id": 4, "correct": False, "finish_reason": "length"},
            ]})
            save_json(root / "a/round2/attempt-1/result.json", {"results": [
                {"id": 3, "correct": False, "extracted": "wrong"},
            ]})
            replay = make_replay_config(root)
        self.assertEqual(replay["name"], "source-replay")
        self.assertEqual(replay["repetitions"], 1)
        self.assertEqual(replay["rounds"], [1, 2])
        self.assertEqual(len(replay["models"]), 1)
        self.assertEqual(replay["models"][0]["item_filters"], {"1": [4], "2": [3]})
        self.assertEqual(replay["replay"]["parent_run_id"], "source-run")
        validate_config(replay)
        self.assertEqual(_campaign_units(replay), 2)

    def test_replay_skips_review_unless_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source-run"
            save_json(root / "config.json", {
                "name": "source", "repetitions": 1, "rounds": [3],
                "models": [{"key": "m", "model": "m",
                            "transport": "openai_compat", "rounds": [3]}],
            })
            save_json(root / "m/round3/attempt-1/result.json", {"results": [
                {"id": 25, "correct": None, "manual_review_required": True},
            ]})
            self.assertIsNone(make_replay_config(root))
            replay = make_replay_config(root, include_review=True)
        self.assertEqual(replay["models"][0]["item_filters"], {"3": [25]})

    def test_item_filters_are_validated(self):
        config = {
            "name": "test", "repetitions": 1, "rounds": [1],
            "models": [{"key": "m", "model": "m", "transport": "openai_compat",
                        "rounds": [1], "item_filters": {"1": [999]}}],
        }
        with self.assertRaisesRegex(ValueError, "unknown round 1 item"):
            validate_config(config)
        config["models"][0]["item_filters"] = {"01": [1]}
        with self.assertRaisesRegex(ValueError, "canonical strings"):
            validate_config(config)

    def test_campaign_forwards_focused_question_filter(self):
        config = {
            "name": "test", "repetitions": 1, "rounds": [1],
            "models": [{"key": "m", "model": "m", "transport": "openai_compat",
                        "rounds": [1], "item_filters": {"1": [4, 7]}}],
        }
        with tempfile.TemporaryDirectory() as tmp, \
                patch("llm_hardtest.orchestrator.round12.run") as focused:
            run_campaign(config, Path(tmp), dry_run=False)
        self.assertEqual(focused.call_args.kwargs["question_filter"], {4, 7})


class ProgressTests(unittest.TestCase):
    def test_campaign_total_respects_model_rounds_and_repetitions(self):
        self.assertEqual(_campaign_units({
            "repetitions": 2, "rounds": [1, 3, 4],
            "models": [{"rounds": [1, 4]}],
        }), 52)

    def test_duration_formats_short_and_long_runs(self):
        self.assertEqual(_duration(None), "--:--")
        self.assertEqual(_duration(65), "01:05")
        self.assertEqual(_duration(3661), "01:01:01")

    def test_forced_dashboard_renders_progress_and_counters(self):
        output = io.StringIO()
        dashboard = TerminalDashboard(
            "demo", 4, Path("runs/demo"), mode="dashboard", stream=output)
        dashboard.start("model-a", 1, 1, 1, "q1")
        dashboard.record("PASS", "model-a", 1, 1, 1, "q1", 2.5)
        dashboard.record("INVALID", "model-a", 1, 1, 1, "q2")
        dashboard.finish()
        text = output.getvalue()
        self.assertIn("LLM Hardtest | demo", text)
        self.assertIn("2/4 ( 50.0%)", text)
        self.assertIn("PASS 1 | FAIL 0 | INCOMPLETE 0 | REVIEW 0 | INVALID 1", text)
        self.assertIn("model-a | Round 1 | attempt 1/1 | q2", text)
        self.assertIn("\x1b[", text)

    def test_plain_mode_keeps_line_oriented_logs(self):
        output = io.StringIO()
        dashboard = TerminalDashboard(
            "demo", 1, Path("runs/demo"), mode="plain", stream=output)
        dashboard.record("FAIL", "model-a", 2, 1, 1, "q7")
        dashboard.finish()
        self.assertEqual(output.getvalue(), "    r2 q7: FAIL\n")


class BackendTests(unittest.TestCase):
    def test_custom_codex_home_does_not_persist_real_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"AUDIT_API_KEY": "real-secret"}):
                backend = CodexBackend({
                    "key": "m", "model": "m", "codex_provider": "custom",
                    "api_key_env": "AUDIT_API_KEY",
                }, Path(tmp))
                backend._env()
            auth = Path(tmp) / "codex-homes/m/auth.json"
            self.assertNotIn("real-secret", auth.read_text())
            self.assertEqual(stat.S_IMODE(auth.stat().st_mode), 0o600)

    def test_custom_codex_state_paths_are_absolute(self):
        backend = CodexBackend({
            "key": "m", "model": "m", "codex_provider": "custom",
        }, Path("relative-state"))
        self.assertTrue(backend.state_dir.is_absolute())

    def test_codex_nonzero_exit_with_partial_output_is_infrastructure_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = CodexBackend({
                "key": "m", "model": "m", "codex_provider": "openai",
            }, Path(tmp))

            def failed_run(command, **_kwargs):
                Path(command[command.index("-o") + 1]).write_text("partial answer")
                return type("Process", (), {
                    "returncode": 1, "stdout": "", "stderr": "provider failed",
                })()

            with patch("subprocess.run", side_effect=failed_run):
                with self.assertRaisesRegex(BackendError, "codex exited 1"):
                    backend.complete([{"role": "user", "content": "test"}], 10)

    def test_typed_content_parts_are_joined(self):
        response = {
            "choices": [{"message": {"content": [
                {"type": "text", "text": "ANSWER: "},
                {"type": "text", "text": "42"},
            ]}, "finish_reason": "stop"}],
            "usage": {},
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return json.dumps(response).encode()

        backend = OpenAICompatBackend(
            {"model": "m", "base_url": "http://localhost:8000/v1"}, Path(".")
        )
        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            result = backend.complete([{"role": "user", "content": "test"}], 10)
        self.assertEqual(result["content"], "ANSWER: 42")

    def test_codex_session_fallback_is_scoped_to_current_workdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "work"
            work.mkdir()
            sessions = root / "home/sessions/2026/08/31"
            sessions.mkdir(parents=True)
            wanted = "11111111-1111-1111-1111-111111111111"
            distractor = "22222222-2222-2222-2222-222222222222"
            (sessions / f"rollout-{wanted}.jsonl").write_text(
                json.dumps({"cwd": str(work)}), encoding="utf-8")
            (sessions / f"rollout-{distractor}.jsonl").write_text(
                json.dumps({"cwd": str(root / "other")}), encoding="utf-8")
            backend = CodexBackend({"key": "m", "model": "m"}, root / "state")
            actual = backend._session_id(
                "", {"CODEX_HOME": str(root / "home")}, work, 0)
        self.assertEqual(actual, wanted)

    def test_codex_agent_disables_unsupported_multi_agent_feature(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "work"
            work.mkdir()
            backend = CodexBackend({
                "key": "m", "model": "m", "codex_provider": "openai",
            }, root / "state")

            class FakeProcess:
                pid = 1

                def wait(self, timeout):
                    return 0

            commands = []

            def fake_popen(command, **_kwargs):
                commands.append(command)
                output = Path(command[command.index("-o") + 1])
                output.write_text("done", encoding="utf-8")
                return FakeProcess()

            with patch("subprocess.Popen", side_effect=fake_popen):
                backend.agent_turn(
                    "first", work, root / "evidence", 1, 10, "read-only")
                backend.agent_turn(
                    "next", work, root / "evidence", 2, 10, "workspace-write",
                    "11111111-1111-1111-1111-111111111111")
        for command in commands:
            position = command.index("--disable")
            self.assertEqual(command[position + 1], "multi_agent")

    def test_missing_choices_is_provider_error(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return b'{"choices": []}'

        backend = OpenAICompatBackend(
            {"model": "m", "base_url": "http://localhost:8000/v1"}, Path(".")
        )
        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            with self.assertRaises(BackendError):
                backend.complete([{"role": "user", "content": "test"}], 10)


class ServerSetupTests(unittest.TestCase):
    def test_doctor_probes_responses_for_codex_repository_rounds(self):
        config = {
            "name": "test", "repetitions": 1, "rounds": [4],
            "round4_tasks": ["q26_hidden_tests"],
            "models": [{"key": "local", "model": "local/model",
                        "transport": "codex_cli", "codex_provider": "custom",
                        "base_url": "http://127.0.0.1:8000/v1", "rounds": [4]}],
        }
        with patch("llm_hardtest.cli.discover_models", return_value=["local/model"]), \
                patch("llm_hardtest.orchestrator.shutil.which",
                      return_value="/usr/bin/codex"), \
                patch("llm_hardtest.cli._probe_codex") as probe:
            self.assertEqual(doctor_config(config), 0)
        probe.assert_called_once_with(config["models"][0], 30)

    def test_doctor_rejects_output_limited_short_probe(self):
        config = {
            "name": "test", "repetitions": 1, "rounds": [1],
            "models": [{"key": "local", "model": "local/model",
                        "transport": "openai_compat",
                        "base_url": "http://127.0.0.1:8000/v1", "rounds": [1]}],
        }
        limited = {"content": "O", "finish_reason": "length"}
        with patch("llm_hardtest.cli.discover_models", return_value=["local/model"]), \
                patch("llm_hardtest.cli.OpenAICompatBackend.complete",
                      return_value=limited), \
                patch("sys.stderr", new_callable=io.StringIO) as error:
            self.assertEqual(doctor_config(config), 1)
        self.assertIn("output limit", error.getvalue())

    def test_discover_and_doctor_use_auth_and_exact_model_id(self):
        seen_auth = []

        class Handler(BaseHTTPRequestHandler):
            def _json(self, payload):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                seen_auth.append(self.headers.get("Authorization"))
                self._json({"data": [{"id": "local/model"}]})

            def do_POST(self):
                seen_auth.append(self.headers.get("Authorization"))
                self._json({"choices": [{"message": {"content": "OK"},
                                          "finish_reason": "stop"}], "usage": {}})

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}/v1"
        try:
            with patch.dict(os.environ, {"TEST_SERVER_KEY": "secret"}):
                self.assertEqual(discover_models(base_url, "TEST_SERVER_KEY"),
                                 ["local/model"])
                status = doctor_config({
                    "name": "test", "repetitions": 1, "rounds": [1],
                    "models": [{"key": "local", "model": "local/model",
                                "transport": "openai_compat", "base_url": base_url,
                                "api_key_env": "TEST_SERVER_KEY", "rounds": [1]}],
                })
            self.assertEqual(status, 0)
            self.assertEqual(seen_auth, ["Bearer secret"] * 3)
        finally:
            server.shutdown()
            server.server_close()


class RoundThreeTests(unittest.TestCase):
    def test_q21_structured_grade(self):
        text = """=== ANSWER ===
CLAIM_VALID: NO
GREEDY_REWARD: 20
GREEDY_ORDER: A,E,F
OPTIMAL_REWARD: 31
OPTIMAL_ORDER: A,B,C,D,E
"""
        result = _grade(21, _fields(text))
        self.assertTrue(result["correct"])


class RoundFourProgressTests(unittest.TestCase):
    def test_dashboard_events_are_forwarded_and_verbose_output_is_logged(self):
        class FakeRunner:
            MODELS = {}

            def main(self, _args, progress_callback=None):
                print("verbose harness output")
                progress_callback({"event": "start", "item": "q26_hidden_tests",
                                   "attempt": 1})
                progress_callback({"event": "complete", "item": "q26_hidden_tests",
                                   "attempt": 1, "status": "PASS", "wall": 3.0})
                return 0

        class FakeGrader:
            @staticmethod
            def available_tasks():
                return ["q26_hidden_tests"]

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "model/round4"
            with patch("llm_hardtest.round4.importlib.import_module",
                       side_effect=[FakeRunner(), FakeGrader()]):
                status = run_round4(
                    {"key": "m", "model": "m", "codex_provider": "custom"},
                    1, out, 10, ["q26_hidden_tests"], progress=events.append)
            self.assertEqual(status, 0)
            self.assertEqual([event["event"] for event in events], ["start", "complete"])
            self.assertIn("verbose harness output", (out / "harness.log").read_text())


class RoundOneTwoTests(unittest.TestCase):
    def test_output_limit_is_incomplete_not_wrong(self):
        class LimitedBackend(Backend):
            def complete(self, messages, timeout):
                return {"content": "partial reasoning", "wall": 1.0,
                        "finish_reason": "length", "completion_tokens": 4096}

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            payload = run_round12(
                1, {"key": "m", "model": "m"},
                LimitedBackend({}, Path(tmp)), 1, Path(tmp), 10, {1}, events.append)
        self.assertEqual(payload["score"], 0)
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["incomplete"], 1)
        self.assertEqual(payload["results"][0]["status"], "INCOMPLETE")
        self.assertIsNone(payload["results"][0]["correct"])
        self.assertEqual(events[-1]["status"], "INCOMPLETE")

    def test_stopped_response_without_answer_is_still_wrong(self):
        class FormatBreakingBackend(Backend):
            def complete(self, messages, timeout):
                return {"content": "The value is 286.", "wall": 1.0,
                        "finish_reason": "stop"}

        with tempfile.TemporaryDirectory() as tmp:
            payload = run_round12(
                1, {"key": "m", "model": "m"},
                FormatBreakingBackend({}, Path(tmp)), 1, Path(tmp), 10, {1})
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["results"][0]["status"], "FAIL")

    def test_question_progress_events_wrap_each_model_call(self):
        class AnswerBackend(Backend):
            def complete(self, messages, timeout):
                return {"content": "ANSWER: 286", "wall": 1.25}

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            payload = run_round12(
                1, {"key": "m", "model": "m"},
                AnswerBackend({}, Path(tmp)), 1, Path(tmp), 10, {1}, events.append)
        self.assertEqual(payload["score"], 1)
        self.assertEqual(events[0], {"event": "start", "item": "q1"})
        self.assertEqual(events[1]["event"], "complete")
        self.assertEqual(events[1]["status"], "PASS")
        self.assertEqual(events[1]["wall"], 1.25)

    def test_backend_failure_is_not_scored_as_a_wrong_answer(self):
        class BrokenBackend(Backend):
            def complete(self, messages, timeout):
                raise BackendError("server unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            payload = run_round12(
                1, {"key": "m", "model": "m"},
                BrokenBackend({}, Path(tmp)), 1, Path(tmp), 10, {1})
        self.assertEqual(payload["planned"], 1)
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["score"], 0)
        self.assertEqual(payload["infrastructure_errors"], 1)
        self.assertIsNone(payload["results"][0]["correct"])


class ConfigurationTests(unittest.TestCase):
    def test_selftest_source_scan_excludes_generated_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "runs/local/_state").mkdir(parents=True)
            (root / "dist").mkdir()
            source = root / "src/kept.py"
            source.write_text("source", encoding="utf-8")
            (root / "runs/local/_state/generated.js").write_text(
                "generated", encoding="utf-8")
            (root / "dist/archive.txt").write_text("built", encoding="utf-8")
            paths = list(_selftest_source_paths(root))
        self.assertEqual(paths, [source])

    def test_minimal_config(self):
        validate_config({
            "repetitions": 1,
            "rounds": [1],
            "models": [{"key": "m", "model": "example", "transport": "openai_compat"}],
        })

    def test_duplicate_keys_rejected(self):
        with self.assertRaises(ValueError):
            validate_config({
                "repetitions": 1,
                "rounds": [1],
                "models": [
                    {"key": "m", "model": "one", "transport": "openai_compat"},
                    {"key": "m", "model": "two", "transport": "openai_compat"},
                ],
            })

    def test_keys_that_collide_after_slugging_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_config({
                "repetitions": 1,
                "rounds": [1],
                "models": [
                    {"key": "model one", "model": "one", "transport": "openai_compat"},
                    {"key": "model-one", "model": "two", "transport": "openai_compat"},
                ],
            })

    def test_non_filesystem_safe_key_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_config({
                "repetitions": 1,
                "rounds": [1],
                "models": [{
                    "key": "model/one", "model": "one", "transport": "openai_compat"
                }],
            })

    def test_dot_path_keys_are_rejected(self):
        for key in (".", ".."):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_config({
                    "repetitions": 1, "rounds": [1],
                    "models": [{"key": key, "model": "one",
                                "transport": "openai_compat"}],
                })

    def test_windows_reserved_path_names_are_rejected(self):
        for key in ("CON", "nul.txt", "LPT1"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_config({
                    "repetitions": 1, "rounds": [1],
                    "models": [{"key": key, "model": "one",
                                "transport": "openai_compat"}],
                })

    def test_wrong_collection_types_are_rejected_cleanly(self):
        with self.assertRaisesRegex(ValueError, "models"):
            validate_config({"repetitions": 1, "rounds": [1], "models": "model"})
        with self.assertRaisesRegex(ValueError, "JSON list"):
            validate_config({
                "repetitions": 1, "rounds": "1",
                "models": [{"key": "m", "model": "one",
                            "transport": "openai_compat"}],
            })

    def test_provider_environment_and_round4_tasks_are_validated(self):
        base = {
            "repetitions": 1, "rounds": [1],
            "models": [{"key": "m", "model": "one",
                        "transport": "openai_compat"}],
        }
        for change in (
            {"codex_provider": "typo"},
            {"api_key_env": "NOT-PORTABLE"},
            {"max_tokens": 0},
        ):
            config = json.loads(json.dumps(base))
            config["models"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_config(config)
        config = json.loads(json.dumps(base))
        config["round4_tasks"] = ["not-a-task"]
        with self.assertRaisesRegex(ValueError, "unknown round4_tasks"):
            validate_config(config)

    def test_unsafe_campaign_name_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_config({
                "name": "../escape", "repetitions": 1, "rounds": [1],
                "models": [{"key": "m", "model": "one",
                            "transport": "openai_compat"}],
            })

    def test_model_specific_rounds_must_be_campaign_subset(self):
        validate_config({
            "repetitions": 1, "rounds": [1, 4],
            "models": [{"key": "m", "model": "one", "rounds": [1],
                        "transport": "openai_compat"}],
        }, check_runtime=False)
        with self.assertRaises(ValueError):
            validate_config({
                "repetitions": 1, "rounds": [1],
                "models": [{"key": "m", "model": "one", "rounds": [4],
                            "transport": "openai_compat"}],
            }, check_runtime=False)

    def test_string_round_four_still_checks_runtime(self):
        config = {
            "repetitions": 1,
            "rounds": ["4"],
            "models": [{"key": "m", "model": "example", "transport": "codex_cli"}],
        }
        # Configuration generation may happen before Codex is installed.
        validate_config(config, check_runtime=False)

    def test_bad_base_url_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_config({
                "repetitions": 1,
                "rounds": [1],
                "models": [{
                    "key": "m", "model": "example", "transport": "openai_compat",
                    "base_url": "localhost:8000/v1",
                }],
            })

    def test_resume_retries_an_infrastructure_invalid_attempt(self):
        config = {
            "name": "test", "repetitions": 1, "rounds": [1],
            "models": [{"key": "m", "model": "one",
                        "transport": "openai_compat"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "saved-run"
            save_json(run_dir / "config.json", config)
            save_json(run_dir / "m/round1/attempt-1/result.json", {
                "score": 0, "total": 0, "infrastructure_errors": 1,
            })
            with patch("llm_hardtest.orchestrator.round12.run") as rerun:
                run_campaign(config, Path(tmp), resume=run_dir)
            rerun.assert_called_once()

    def test_resume_retries_an_incomplete_attempt(self):
        config = {
            "name": "test", "repetitions": 1, "rounds": [1],
            "models": [{"key": "m", "model": "one",
                        "transport": "openai_compat"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "saved-run"
            save_json(run_dir / "config.json", config)
            save_json(run_dir / "m/round1/attempt-1/result.json", {
                "score": 19, "total": 19, "incomplete": 1,
            })
            with patch("llm_hardtest.orchestrator.round12.run") as rerun:
                run_campaign(config, Path(tmp), resume=run_dir)
            rerun.assert_called_once()


class PackTests(unittest.TestCase):
    def _pack(self, root, **changes):
        manifest = {
            "schema_version": 1, "id": "demo-pack", "title": "Demo",
            "runner_kind": "reasoning", "capabilities": ["chat_completions"],
            "unit_count": 1, "time_limit_seconds": 30,
            "result_schema": "demo.v1", "assets": ["questions.json"],
            "controls": [],
        }
        manifest.update(changes)
        save_json(root / "manifest.json", manifest)
        save_json(root / "questions.json", [{"id": 1}])

    def test_pack_fingerprint_changes_with_graded_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._pack(root)
            first = validate_pack(root)
            save_json(root / "questions.json", [{"id": 2}])
            second = validate_pack(root)
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])

    def test_generated_caches_do_not_change_pack_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._pack(root, assets=["**/*"])
            first = validate_pack(root)
            cache = root / "nested/__pycache__/module.cpython-314.pyc"
            cache.parent.mkdir(parents=True)
            cache.write_bytes(b"machine-specific cache")
            second = validate_pack(root)
        self.assertEqual(first["fingerprint"], second["fingerprint"])

    def test_pack_rejects_traversal_and_unknown_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._pack(root, assets=["../outside.json"])
            with self.assertRaisesRegex(ValueError, "unsafe pack asset"):
                validate_pack(root)
            self._pack(root, schema_version=999)
            with self.assertRaisesRegex(ValueError, "schema_version"):
                validate_pack(root)

    def test_pack_rejects_asset_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "pack"
            root.mkdir()
            self._pack(root, assets=["escaped.json"])
            outside = parent / "outside.json"
            save_json(outside, {"private": True})
            (root / "escaped.json").symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "escapes"):
                validate_pack(root)

    def test_all_bundled_packs_validate(self):
        root = Path(__file__).resolve().parents[1]
        metadata = [validate_pack(root / "rounds" / f"round{number}")
                    for number in (1, 2, 3, 4, 5)]
        self.assertEqual([item["unit_count"] for item in metadata], [20, 20, 5, 6, 1])


class RoundFiveResearchTests(unittest.TestCase):
    def _config(self, transport="codex_cli"):
        return {
            "name": "round-five-research", "repetitions": 1, "rounds": [4],
            "timeout_seconds": 30, "round4_tasks": ["q26_hidden_tests"],
            "models": [{
                "key": "m", "label": "M", "model": "fake-model",
                "transport": transport, "codex_provider": "openai", "rounds": [4],
            }],
        }

    class FakeAgent:
        def __init__(self, mode="correct"):
            self.mode = mode
            self.calls = []

        def agent_turn(self, prompt, workdir, evidence_dir, turn, timeout,
                       sandbox, session_id=None):
            self.calls.append((turn, sandbox, session_id))
            if self.mode == "early-edit" and turn == 1:
                (workdir / "sessions.py").write_text("# unauthorized\n", encoding="utf-8")
            if self.mode == "correct" and turn == 3:
                path = workdir / "sessions.py"
                text = path.read_text(encoding="utf-8")
                text = text.replace("store_operation = uuid.uuid4().hex",
                                    'store_operation = f"{session_id}:{request_id}"')
                text = text.replace("notify_operation = uuid.uuid4().hex",
                                    'notify_operation = f"{session_id}:{request_id}"')
                path.write_text(text, encoding="utf-8")
            if turn == 1:
                content = "Fresh UUID operation IDs defeat idempotency; use a stable scoped key."
            elif turn == 2:
                content = ("Version-1 old clients reject unknown fields, so any new response "
                           "schema field is invalid and must be omitted.")
            else:
                content = (
                    "=== PILOT REPORT ===\n"
                    "ROOT_CAUSE_FILE: sessions.py\n"
                    "ROOT_CAUSE_FUNCTION: SessionService.refresh\n"
                    "INVALIDATED_PLAN: adding a response field\n"
                    "FILES_CHANGED: sessions.py\n"
                    "PUBLIC_TESTS: 4/4\n"
                    "CONFIDENCE: high\n"
                    "REMAINING_RISKS: none observed\n")
            if self.mode == "empty" and turn == 1:
                content = ""
            (evidence_dir / f"transcript_turn{turn}.txt").write_text(
                content + ("\nERROR unsupported call: tool_code"
                           if self.mode == "unsupported" and turn == 1 else ""),
                encoding="utf-8")
            (evidence_dir / f"last_message_turn{turn}.txt").write_text(
                content, encoding="utf-8")
            timed_out = self.mode == "timeout" and turn == 1
            transcript = content + ("\nERROR unsupported call: tool_code"
                                    if self.mode == "unsupported" and turn == 1 else "")
            return {"content": content, "transcript": transcript,
                    "session_id": "00000000-0000-0000-0000-000000000001",
                    "wall": 0.1, "tokens": 10, "timed_out": timed_out,
                    "returncode": -9 if timed_out else 0, "sandbox": sandbox}

    def test_round_five_correct_research_attempt_is_fully_graded(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self.FakeAgent()
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: agent)
            summary = load_json(root / "pilot_summary.json")
            grade = summary["attempts"][0]["grade"]
            report = (root / "PILOT_REPORT.md").read_text(encoding="utf-8")
        self.assertEqual(agent.calls, [
            (1, "read-only", None),
            (2, "read-only", "00000000-0000-0000-0000-000000000001"),
            (3, "workspace-write", "00000000-0000-0000-0000-000000000001"),
        ])
        self.assertTrue(grade["no_edit_before_approval"])
        self.assertTrue(grade["evidence_revision_observed"])
        self.assertTrue(grade["release_ready"])
        self.assertEqual(grade["hidden"], {"passed": 9, "total": 9, "timed_out": False})
        self.assertTrue(grade["final_report"]["changed_files_claim_accurate"])
        self.assertTrue(grade["final_report"]["root_cause_accurate"])
        self.assertTrue(grade["final_report"]["invalidated_plan_accurate"])
        self.assertTrue(grade["final_report"]["accurate"])
        self.assertIn("Not a canonical benchmark score", report)

    def test_round_five_stops_on_preapproval_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self.FakeAgent("early-edit")
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: agent)
            grade = load_json(root / "pilot_summary.json")["attempts"][0]["grade"]
        self.assertEqual(len(agent.calls), 1)
        self.assertFalse(grade["no_edit_before_approval"])
        self.assertEqual(grade["preapproval_changed_files"], ["sessions.py"])
        self.assertFalse(grade["release_ready"])

    def test_round_five_timeout_is_incomplete_not_a_model_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self.FakeAgent("timeout")
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: agent)
            grade = load_json(root / "pilot_summary.json")["attempts"][0]["grade"]
        self.assertEqual(grade["status"], "INCOMPLETE")
        self.assertEqual(grade["turns_completed"], 1)
        self.assertFalse(grade["release_ready"])

    def test_round_five_empty_agent_output_stops_and_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self.FakeAgent("empty")
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: agent)
            grade = load_json(root / "pilot_summary.json")["attempts"][0]["grade"]
        self.assertEqual(len(agent.calls), 1)
        self.assertEqual(grade["status"], "INCOMPLETE")
        self.assertFalse(grade["turns"][0]["output_valid"])
        self.assertFalse(grade["release_ready"])

    def test_round_five_records_unsupported_tool_protocol_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self.FakeAgent("unsupported")
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: agent)
            grade = load_json(root / "pilot_summary.json")["attempts"][0]["grade"]
            report = (root / "PILOT_REPORT.md").read_text(encoding="utf-8")
        self.assertFalse(grade["tool_protocol_clean"])
        self.assertEqual(grade["unsupported_tool_calls"], 1)
        self.assertEqual(grade["unsupported_tool_names"], ["tool_code"])
        self.assertIn("Protocol errors", report)

    def test_round_five_requires_repository_agent_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "codex_cli"):
                run_pilot(self._config("openai_compat"), Path(tmp), ["m"], 1)

    def test_round_five_report_template_mentions_do_not_count_as_a_report(self):
        from llm_hardtest.round5 import _report_fields
        text = "Discussing ROOT_CAUSE_FILE: sessions.py without the required marker."
        self.assertEqual(_report_fields(text), {})


class PilotAnalysisTests(unittest.TestCase):
    PACK = "sha256:" + "c" * 64

    def _grade(self, attempt: int, strong: bool) -> dict:
        fields = ({
            "ROOT_CAUSE_FILE": "sessions.py",
            "ROOT_CAUSE_FUNCTION": "SessionService.refresh",
            "INVALIDATED_PLAN": "adding a response field",
            "FILES_CHANGED": "sessions.py",
            "PUBLIC_TESTS": "4/4", "CONFIDENCE": "high",
            "REMAINING_RISKS": "none observed",
        } if strong else {})
        return {
            "status": "COMPLETE", "turns_completed": 3,
            "no_edit_before_approval": True,
            "preapproval_changed_files": [],
            "evidence_revision_observed": strong,
            "public": {"passed": 4 if strong else 1, "total": 4,
                       "timed_out": False},
            "hidden": {"passed": 9 if strong else 6, "total": 9,
                       "timed_out": False},
            "release_ready": strong,
            "final_changed_files": ["sessions.py"] if strong else [],
            "final_report": {
                "fields": fields, "complete": strong,
                "root_cause_accurate": strong,
                "invalidated_plan_accurate": strong,
                "public_test_claim_accurate": strong,
                "changed_files_claim_accurate": True,
                "accurate": strong,
            },
            "pilot_id": "q32_retry_compatibility", "attempt": attempt,
            "turns": [{
                "content": (("=== PILOT REPORT ===\n"
                             "ROOT_CAUSE_FILE: sessions.py\n"
                             "ROOT_CAUSE_FUNCTION: SessionService.refresh\n"
                             "INVALIDATED_PLAN: adding a response field\n"
                             "FILES_CHANGED: sessions.py\n"
                             "PUBLIC_TESTS: 4/4\n"
                             "CONFIDENCE: high\n"
                             "REMAINING_RISKS: none observed\n")
                            if strong and number == 3 else f"turn {number}"),
                "wall": float(number),
                "tokens": number * 10, "output_valid": True,
                "returncode": 0, "timed_out": False,
                "sandbox": "read-only" if number < 3 else "workspace-write",
            } for number in (1, 2, 3)],
        }

    def _pilot_run(self, root: Path) -> Path:
        models = [
            {"key": "strong", "label": "Private Strong", "model": "private/strong",
             "transport": "codex_cli", "rounds": [4]},
            {"key": "weak", "label": "Private Weak", "model": "private/weak",
             "transport": "codex_cli", "rounds": [4]},
        ]
        save_json(root / "config.json", {"rounds": [4], "models": models})
        rows = []
        for model in models:
            for attempt in (1, 2):
                grade = self._grade(attempt, model["key"] == "strong")
                attempt_dir = root / model["key"] / "round5" / f"attempt-{attempt}"
                save_json(attempt_dir / "research_grade.json", grade)
                for turn in (1, 2, 3):
                    text = "normal transcript"
                    if model["key"] == "weak" and turn == 3:
                        text += "\nERROR unsupported call: tool_code"
                    (attempt_dir / f"transcript_turn{turn}.txt").write_text(
                        text, encoding="utf-8")
                (attempt_dir / "changes.patch").write_text(
                    "--- a/sessions.py\n+++ b/sessions.py\n@@ -1 +1 @@\n-old\n+new\n"
                    if model["key"] == "strong" else "", encoding="utf-8")
                rows.append({"model": model["key"], "grade": grade})
        save_json(root / "pilot_summary.json", {
            "schema_version": 1, "pilot_id": "q32_retry_compatibility",
            "pack": self.PACK, "canonical_score": False, "attempts": rows,
        })
        return root

    def test_cross_pilot_analysis_separates_models_from_repeat_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self._pilot_run(Path(tmp) / "pilot")
            group = analyze_pilots([run])["groups"][0]
        self.assertEqual(group["attempts"], 4)
        self.assertEqual(group["model_configurations"], 2)
        self.assertEqual(group["pairwise"]["within_configuration_pairs"], 2)
        self.assertEqual(group["pairwise"]["within_configuration_distance"], 0.0)
        self.assertEqual(group["pairwise"]["between_configuration_pairs"], 4)
        self.assertGreater(group["pairwise"]["net_separation"], 0.6)
        self.assertTrue(group["ready_for_manual_ambiguity_review"])
        self.assertFalse(group["canonical_promotion_ready"])
        rows = {row["configuration"]: row for row in group["configurations"]}
        self.assertEqual(sum(row["unsupported_tool_calls"] for row in rows.values()), 2)

    def test_pilot_analysis_is_anonymous_unless_labels_are_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._pilot_run(root / "private-pilot")
            markdown, machine, analysis = write_pilot_analysis(
                [run], root / "analysis.md")
            default_text = markdown.read_text(encoding="utf-8") + machine.read_text(
                encoding="utf-8")
            labeled, _, labeled_analysis = write_pilot_analysis(
                [run], root / "labeled.md", include_model_labels=True)
            labeled_text = labeled.read_text(encoding="utf-8")
            machine_payload = json.loads(machine.read_text(encoding="utf-8"))
        self.assertEqual(machine_payload, analysis)
        for private in ("Private Strong", "Private Weak", "private/strong",
                        "private/weak", str(run)):
            self.assertNotIn(private, default_text)
        self.assertIn("Private Strong", labeled_text)
        self.assertTrue(labeled_analysis["model_labels_included"])

    def test_pilot_analysis_rejects_summary_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self._pilot_run(Path(tmp) / "pilot")
            summary = load_json(run / "pilot_summary.json")
            summary["attempts"][0]["grade"]["release_ready"] = False
            save_json(run / "pilot_summary.json", summary)
            with self.assertRaisesRegex(ValueError, "does not match"):
                analyze_pilots([run])

    def test_pilot_analysis_recomputes_release_invariant(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self._pilot_run(Path(tmp) / "pilot")
            grade_path = run / "weak/round5/attempt-1/research_grade.json"
            grade = load_json(grade_path)
            grade["release_ready"] = True
            save_json(grade_path, grade)
            summary = load_json(run / "pilot_summary.json")
            for row in summary["attempts"]:
                if row["model"] == "weak" and row["grade"]["attempt"] == 1:
                    row["grade"] = grade
            save_json(run / "pilot_summary.json", summary)
            with self.assertRaisesRegex(ValueError, "release_ready contradicts"):
                analyze_pilots([run])

    def test_pilot_analysis_does_not_turn_unobserved_tests_into_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self._pilot_run(Path(tmp) / "pilot")
            grade_path = run / "weak/round5/attempt-1/research_grade.json"
            grade = load_json(grade_path)
            grade.update({
                "status": "INCOMPLETE", "turns_completed": 1,
                "public": {"passed": 0, "total": 0, "timed_out": True},
                "hidden": {"passed": 0, "total": 0, "timed_out": True},
                "turns": grade["turns"][:1],
            })
            save_json(grade_path, grade)
            summary = load_json(run / "pilot_summary.json")
            for row in summary["attempts"]:
                if row["model"] == "weak" and row["grade"]["attempt"] == 1:
                    row["grade"] = grade
            save_json(run / "pilot_summary.json", summary)
            group = analyze_pilots([run])["groups"][0]
        weak = next(row for row in group["configurations"] if row["incomplete"] == 1)
        self.assertEqual(weak["public_pass_rate"], 0.25)
        self.assertEqual(weak["hidden_pass_rate"], round(6 / 9, 6))
        self.assertFalse(group["ready_for_manual_ambiguity_review"])

    def test_pilot_analysis_rejects_transcript_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            run = self._pilot_run(parent / "pilot")
            transcript = run / "strong/round5/attempt-1/transcript_turn1.txt"
            outside = parent / "outside.txt"
            transcript.rename(outside)
            transcript.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "escapes"):
                analyze_pilots([run])

    def test_pilot_analysis_rejects_duplicate_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self._pilot_run(Path(tmp) / "pilot")
            with self.assertRaisesRegex(ValueError, "more than once"):
                analyze_pilots([run, run / "."])

    def test_pilot_analysis_requires_markdown_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self._pilot_run(Path(tmp) / "pilot")
            with self.assertRaisesRegex(ValueError, r"\.md"):
                write_pilot_analysis([run], Path(tmp) / "analysis.json")


class CalibrationTests(unittest.TestCase):
    PACK_A = "sha256:" + "a" * 64
    PACK_B = "sha256:" + "b" * 64

    def _calibration_run(self, root: Path, pack: str = PACK_A,
                         model_count: int = 6) -> Path:
        models = [{
            "key": f"m{index}", "label": f"Private {index}",
            "model": f"private/model-{index}", "transport": "openai_compat",
            "base_url": f"http://127.0.0.1:{8000 + index}/v1",
        } for index in range(model_count)]
        save_json(root / "config.json", {
            "name": "private-calibration", "repetitions": 1,
            "rounds": [1], "models": models,
        })
        save_json(root / "summary.json", {"packs": {"1": pack}})
        for index, model in enumerate(models):
            rows = [
                {"id": 1, "correct": index >= 3},
                {"id": 2, "correct": index >= 2},
                {"id": 3, "correct": index >= 4},
                {"id": 4, "correct": index < 3},
                {"id": 5, "correct": True},
                {"id": 6, "correct": False, "finish_reason": "length"},
            ]
            save_json(root / model["key"] / "round1/attempt-1/result.json", {
                "attempt": 1, "results": rows,
            })
        return root

    def test_calibration_flags_ceiling_negative_and_incomplete_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self._calibration_run(Path(tmp) / "run")
            analysis = analyze_runs([run])
        self.assertEqual(len(analysis["groups"]), 1)
        group = analysis["groups"][0]
        self.assertEqual(group["respondents"], 6)
        self.assertEqual(group["model_configurations"], 6)
        self.assertEqual(group["pairwise"]["between_configuration_pairs"], 15)
        items = {item["item"]: item for item in group["items"]}
        self.assertEqual(items["q4"]["classification"], "NEGATIVE")
        self.assertEqual(items["q5"]["classification"], "CEILING")
        self.assertEqual(items["q6"]["classification"], "INSUFFICIENT")
        self.assertEqual(items["q6"]["incomplete"], 6)

    def test_calibration_separates_pack_fingerprints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._calibration_run(root / "first", self.PACK_A, 1)
            second = self._calibration_run(root / "second", self.PACK_B, 1)
            analysis = analyze_runs([first, second])
        self.assertEqual(len(analysis["groups"]), 2)
        self.assertEqual({group["pack"] for group in analysis["groups"]},
                         {self.PACK_A, self.PACK_B})

    def test_calibration_outputs_do_not_copy_private_identifiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._calibration_run(root / "run")
            markdown, machine, analysis = write_analysis(
                [run], root / "calibration.md")
            text = markdown.read_text(encoding="utf-8")
            raw = machine.read_text(encoding="utf-8")
        self.assertEqual(json.loads(raw), analysis)
        for private in ("private/model", "Private 0", "127.0.0.1", str(run)):
            self.assertNotIn(private, text)
            self.assertNotIn(private, raw)
        self.assertIn("Corrected discrimination", text)

    def test_calibration_rejects_missing_or_invalid_pack_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self._calibration_run(Path(tmp) / "run")
            save_json(run / "summary.json", {"packs": {"1": "not-a-fingerprint"}})
            with self.assertRaisesRegex(ValueError, "invalid pack"):
                analyze_runs([run])

    def test_calibration_requires_item_level_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            save_json(root / "config.json", {"models": []})
            save_json(root / "summary.json", {"packs": {"1": self.PACK_A}})
            with self.assertRaisesRegex(ValueError, "no item-level"):
                analyze_runs([root])

    def test_calibration_rejects_duplicate_run_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self._calibration_run(Path(tmp) / "run")
            with self.assertRaisesRegex(ValueError, "more than once"):
                analyze_runs([run, run / "."])

    def test_calibration_rejects_evidence_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            run = self._calibration_run(parent / "run", model_count=1)
            result = run / "m0/round1/attempt-1/result.json"
            outside = parent / "outside.json"
            result.rename(outside)
            result.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "escapes"):
                analyze_runs([run])

    def test_calibration_measures_same_configuration_repeat_instability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._calibration_run(root / "first", model_count=1)
            second = self._calibration_run(root / "second", model_count=1)
            result = load_json(second / "m0/round1/attempt-1/result.json")
            result["results"][0]["correct"] = not result["results"][0]["correct"]
            save_json(second / "m0/round1/attempt-1/result.json", result)
            group = analyze_runs([first, second])["groups"][0]
        pairwise = group["pairwise"]
        self.assertEqual(group["model_configurations"], 1)
        self.assertEqual(pairwise["within_configuration_pairs"], 1)
        self.assertEqual(pairwise["between_configuration_pairs"], 0)
        self.assertEqual(pairwise["within_configuration_disagreement"], 0.2)

    def test_calibration_collects_round_four_release_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            models = [{"key": "a", "model": "model-a", "transport": "codex_cli"},
                      {"key": "b", "model": "model-b", "transport": "codex_cli"}]
            save_json(root / "config.json", {"rounds": [4], "models": models})
            save_json(root / "summary.json", {"packs": {"4": self.PACK_A}})
            for index, model in enumerate(models):
                save_json(root / model["key"] / "round4/run.json", {
                    "grades": [
                        {"task": "q26", "run_meta": {"attempt": 1},
                         "flags": {"attempt_pass": index == 0}},
                        {"task": "q27", "run_meta": {"attempt": 1},
                         "flags": {"attempt_pass": True}},
                    ], "errors": [],
                })
            group = analyze_runs([root])["groups"][0]
        self.assertEqual(group["round"], 4)
        self.assertEqual(group["pairwise"]["between_configuration_pairs"], 1)
        items = {item["item"]: item for item in group["items"]}
        self.assertEqual((items["q26"]["pass"], items["q26"]["fail"]), (1, 1))

    def test_analysis_output_requires_markdown_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self._calibration_run(Path(tmp) / "run", model_count=1)
            with self.assertRaisesRegex(ValueError, r"\.md"):
                write_analysis([run], Path(tmp) / "analysis.json")


class PublicResultTests(unittest.TestCase):
    def _run(self, root, model_name="org/model"):
        config = {
            "name": "private-campaign-name", "repetitions": 1, "rounds": [1],
            "timeout_seconds": 30,
            "models": [{
                "key": "private-user-key", "label": "Private User Label",
                "model": model_name, "transport": "openai_compat",
                "base_url": "http://127.0.0.1:8000/v1",
                "api_key_env": "VERY_PRIVATE_API_KEY", "max_tokens": 2048,
                "public_metadata": {"quantization": "Q4_K_M", "unknown": "drop-me"},
            }],
        }
        save_json(root / "config.json", config)
        save_json(root / "private-user-key/round1/attempt-1/result.json", {
            "attempt": 1, "score": 1, "total": 1, "planned": 1, "wall": 2.0,
            "results": [{
                "id": 1, "correct": True, "content": "private raw response",
                "transcript": "/Users/private/work and sk-secret-secret-secret",
            }],
        })
        generate(root)

    def test_public_export_is_allowlist_only_and_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            self._run(root)
            first = Path(tmp) / "first.zip"
            second = Path(tmp) / "second.zip"
            _, payload, warnings = export_public_bundle(root, first)
            export_public_bundle(root, second)
            raw = first.read_bytes()
            second_raw = second.read_bytes()
            loaded = load_public_bundle(first)
        self.assertEqual(raw, second_raw)
        text = json.dumps(payload)
        for private in ("private-campaign-name", "Private User Label", "private-user-key",
                        "127.0.0.1", "VERY_PRIVATE_API_KEY", "private raw response",
                        "/Users/private", "drop-me"):
            self.assertNotIn(private, text)
        self.assertEqual(payload["models"][0]["public_name"], "org/model")
        self.assertEqual(payload["models"][0]["public_metadata"],
                         {"quantization": "Q4_K_M"})
        self.assertFalse(warnings)
        self.assertEqual(loaded, payload)

    def test_private_model_path_is_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            self._run(root, "/Users/alice/models/private.gguf")
            payload, warnings = build_public_result(root)
        self.assertEqual(payload["models"][0]["public_name"], "model-1")
        self.assertTrue(warnings)
        self.assertNotIn("alice", json.dumps(payload))

    def test_relative_path_traversal_model_name_is_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            self._run(root, "../private/model.gguf")
            payload, warnings = build_public_result(root)
        self.assertEqual(payload["models"][0]["public_name"], "model-1")
        self.assertTrue(warnings)

    def test_public_result_rejects_content_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            self._run(root)
            payload, _ = build_public_result(root)
        payload["models"][0]["public_name"] = "changed/model"
        with self.assertRaisesRegex(ValueError, "bundle_id"):
            validate_public_result(payload)

    def test_public_export_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            self._run(root)
            output = Path(tmp) / "result.zip"
            export_public_bundle(root, output)
            with self.assertRaisesRegex(ValueError, "overwrite"):
                export_public_bundle(root, output)

    def test_public_bundle_rejects_unexpected_archive_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("../private.txt", "secret")
            with self.assertRaisesRegex(ValueError, "unexpected files"):
                load_public_bundle(path)

    def test_privacy_validator_rejects_a_rehashed_private_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            self._run(root)
            payload, _ = build_public_result(root)
        payload["models"][0]["rounds"]["1"]["content"] = "/Users/alice/private"
        from llm_hardtest.public_results import _bundle_id
        body = {key: value for key, value in payload.items() if key != "bundle_id"}
        payload["bundle_id"] = _bundle_id(body)
        with self.assertRaisesRegex(ValueError, "extra fields"):
            validate_public_result(payload)

    def test_submission_preview_and_explicit_consent_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            self._run(root)
            bundle = Path(tmp) / "result.zip"
            _, payload, _ = export_public_bundle(root, bundle)
            previewed, relative, document = preview_submission(bundle)
            self.assertEqual(previewed, payload)
            self.assertEqual(relative, submission_relative_path(payload))
            self.assertEqual(json.loads(document), payload)
            with patch("llm_hardtest.cli.open_submission_pr") as opened:
                self.assertEqual(main(["submit", str(bundle), "--open-pr"]), 2)
                opened.assert_not_called()

    def test_submit_cli_only_writes_after_yes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            self._run(root)
            bundle = Path(tmp) / "result.zip"
            export_public_bundle(root, bundle)
            with patch("llm_hardtest.cli.open_submission_pr",
                       return_value="https://github.com/o/r/pull/1") as opened:
                self.assertEqual(
                    main(["submit", str(bundle), "--open-pr", "--yes"]), 0)
                opened.assert_called_once()

    def test_github_submit_rejects_malicious_repository_and_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            self._run(root)
            payload, _ = build_public_result(root)
        for repository in ("owner/..", "../repo", "owner/repo/extra", "owner/-repo"):
            with self.subTest(repository=repository):
                with self.assertRaisesRegex(ValueError, "OWNER/NAME"):
                    open_submission_pr(payload, repository, client=object())

        class DuplicateClient:
            def request(self, method, endpoint, fields=None, allow_missing=False):
                if endpoint == "user":
                    return {"login": "owner"}
                if endpoint == "repos/owner/repo":
                    return {"default_branch": "main"}
                return {"already": "present"}

        with self.assertRaisesRegex(ValueError, "already published"):
            open_submission_pr(payload, "owner/repo", DuplicateClient())

    def test_github_submit_creates_owner_branch_file_and_pull_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            self._run(root)
            payload, _ = build_public_result(root)

        class RecordingClient:
            def __init__(self):
                self.calls = []

            def request(self, method, endpoint, fields=None, allow_missing=False):
                self.calls.append((method, endpoint, fields, allow_missing))
                if endpoint == "user":
                    return {"login": "owner"}
                if endpoint == "repos/owner/repo":
                    return {"default_branch": "main"}
                if "/contents/results/submissions/" in endpoint and method == "GET":
                    return None
                if endpoint.endswith("/git/ref/heads/main"):
                    return {"object": {"sha": "abc123"}}
                if endpoint == "repos/owner/repo/pulls":
                    return {"html_url": "https://github.com/owner/repo/pull/7"}
                return {}

        client = RecordingClient()
        url = open_submission_pr(payload, "owner/repo", client)
        self.assertEqual(url, "https://github.com/owner/repo/pull/7")
        calls = {(method, endpoint): fields for method, endpoint, fields, _ in client.calls}
        digest = payload["bundle_id"].removeprefix("sha256:")
        branch = f"llm-hardtest-result/{digest[:12]}"
        self.assertEqual(calls[("POST", "repos/owner/repo/git/refs")], {
            "ref": f"refs/heads/{branch}", "sha": "abc123",
        })
        content_call = next(fields for method, endpoint, fields, _ in client.calls
                            if method == "PUT" and "/contents/" in endpoint)
        self.assertEqual(json.loads(base64.b64decode(
            content_call["content"])), payload)
        self.assertEqual(calls[("POST", "repos/owner/repo/pulls")]["head"], branch)

    def test_github_submit_uses_a_contributor_fork(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            self._run(root)
            payload, _ = build_public_result(root)

        class ForkClient:
            def __init__(self):
                self.calls = []

            def request(self, method, endpoint, fields=None, allow_missing=False):
                self.calls.append((method, endpoint, fields, allow_missing))
                if endpoint == "user":
                    return {"login": "contributor"}
                if endpoint == "repos/owner/repo":
                    return {"default_branch": "main"}
                if endpoint.startswith("repos/owner/repo/contents/"):
                    return None
                if endpoint == "repos/contributor/repo":
                    return {"full_name": "contributor/repo"}
                if endpoint.endswith("/git/ref/heads/main"):
                    return {"object": {"sha": "forksha"}}
                if endpoint == "repos/owner/repo/pulls":
                    return {"html_url": "https://github.com/owner/repo/pull/8"}
                return {}

        client = ForkClient()
        self.assertEqual(open_submission_pr(payload, "owner/repo", client),
                         "https://github.com/owner/repo/pull/8")
        self.assertIn(("POST", "repos/contributor/repo/merge-upstream",
                       {"branch": "main"}, False), client.calls)
        pull = next(fields for method, endpoint, fields, _ in client.calls
                    if method == "POST" and endpoint == "repos/owner/repo/pulls")
        self.assertTrue(pull["head"].startswith("contributor:llm-hardtest-result/"))

    def test_public_round_four_task_types_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            save_json(root / "config.json", {
                "name": "round-four", "repetitions": 1, "rounds": [4],
                "round4_tasks": ["q26_hidden_tests"],
                "models": [{
                    "key": "m", "label": "M", "model": "org/model",
                    "transport": "codex_cli", "codex_provider": "openai",
                }],
            })
            save_json(root / "m/round4/run.json", {"attempts": 1, "tasks": ["q26_hidden_tests"],
                "errors": [], "grades": [{
                    "task": "q26_hidden_tests",
                    "public": {"passed": 2, "total": 2},
                    "hidden": {"passed": 1, "total": 1},
                    "score_auto": 65,
                    "flags": {"attempt_pass": True, "manager_utility_pass": None,
                              "false_green": False, "test_tampering": False},
                    "run_meta": {"attempt": 1, "wall": 1.5, "tokens": None},
                }]})
            generate(root)
            payload, _ = build_public_result(root)
        self.assertTrue(payload["models"][0]["rounds"]["4"]["tasks"][0]["release_ready"])

    def test_community_directory_validation_and_sparse_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            self._run(run)
            payload, _ = build_public_result(run)
            submissions = Path(tmp) / "submissions"
            submissions.mkdir()
            digest = payload["bundle_id"].removeprefix("sha256:")
            (submissions / f"{digest}.json").write_text(
                submission_document(payload), encoding="utf-8")
            loaded = load_submission_directory(submissions)
            rows = aggregate_submissions(loaded)
            self.assertEqual((len(loaded), len(rows)), (1, 1))
            self.assertEqual(rows[0]["passed"], 1)
            self.assertIn("withheld (<5 bundles)", render_index(loaded))
            output = Path(tmp) / "INDEX.md"
            self.assertEqual(build_index(submissions, output), (1, 1))
            self.assertEqual(build_index(submissions, output, check=True), (1, 1))
            output.write_text("stale\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "stale"):
                build_index(submissions, output, check=True)

    def test_community_baseline_requires_five_distinct_bundles(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            self._run(run)
            original, _ = build_public_result(run)
            submissions = []
            from llm_hardtest.public_results import _bundle_id
            for index in range(5):
                payload = json.loads(json.dumps(original))
                payload["tool"]["version"] = f"2.1.{index}"
                body = {key: value for key, value in payload.items() if key != "bundle_id"}
                payload["bundle_id"] = _bundle_id(body)
                validate_public_result(payload)
                submissions.append(payload)
        document = render_index(submissions)
        self.assertIn("5/5", document)
        self.assertIn("100.0% observed", document)

    def test_duplicate_model_entries_do_not_raise_the_baseline_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            self._run(run)
            payload, _ = build_public_result(run)
        payload["models"] = payload["models"] * 5
        from llm_hardtest.public_results import _bundle_id
        body = {key: value for key, value in payload.items() if key != "bundle_id"}
        payload["bundle_id"] = _bundle_id(body)
        validate_public_result(payload)
        rows = aggregate_submissions([payload])
        self.assertEqual(rows[0]["runs"], 5)
        self.assertEqual(rows[0]["submissions"], 1)
        self.assertIn("withheld (<5 bundles)", render_index([payload]))

    def test_community_validation_rejects_wrong_filename_and_extra_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            self._run(run)
            payload, _ = build_public_result(run)
            submissions = Path(tmp) / "submissions"
            submissions.mkdir()
            (submissions / "wrong.json").write_text(
                submission_document(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "filename"):
                load_submission_directory(submissions)
            (submissions / "wrong.json").unlink()
            (submissions / "notes.txt").write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unexpected"):
                load_submission_directory(submissions)


class ReportTests(unittest.TestCase):
    def test_legacy_truncation_is_separate_from_correctness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_json(root / "config.json", {
                "name": "test", "repetitions": 1, "rounds": [1],
                "models": [{"key": "m", "label": "M", "model": "m"}],
            })
            save_json(root / "m/round1/attempt-1/result.json", {
                "score": 1, "total": 2, "wall": 2,
                "results": [
                    {"id": 1, "correct": True, "finish_reason": "stop"},
                    {"id": 2, "correct": False, "finish_reason": "length"},
                ],
            })
            document = render(collect(root))
        self.assertIn("1/1 (+1 incomplete)", document)
        self.assertIn("incomplete items 1", document)

    def test_report_from_saved_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {
                "name": "test",
                "repetitions": 1,
                "rounds": [1],
                "models": [{"key": "m", "label": "Model M", "model": "m"}],
            }
            save_json(root / "config.json", config)
            save_json(root / "m/round1/attempt-1/result.json", {
                "score": 20, "total": 20, "wall": 10.0,
            })
            save_json(root / "m/round4/run.json", {"grades": [{
                "task": "q26_hidden_tests",
                "public": {"passed": 20, "total": 20},
                "hidden": {"passed": 7, "total": 7},
                "score_auto": 65.0,
                "flags": {
                    "attempt_pass": True,
                    "manager_utility_pass": None,
                    "false_green": False,
                    "test_tampering": False,
                },
                "run_meta": {"attempt": 1, "wall": 12.5, "tokens": 1000},
            }]})
            summary = collect(root)
            document = render(summary)
            self.assertIn("Model M", document)
            self.assertIn("20/20", document)
            self.assertIn("q26_hidden_tests", document)
            self.assertIn("7/7", document)
            json.dumps(summary)

    def test_infrastructure_errors_are_reported(self):
        document = render({
            "run_id": "test", "generated_at": "now",
            "config": {"repetitions": 1, "rounds": [1]},
            "models": [{"key": "m", "label": "M", "rounds": {
                "1": {"passed": 0, "total": 0, "attempts": 1,
                      "mean_wall_seconds": 1, "manual_review": 0,
                      "infrastructure_errors": 20}
            }}],
        })
        self.assertIn("infrastructure errors 20", document)

    def test_model_label_cannot_break_markdown(self):
        document = render({
            "run_id": "test", "generated_at": "now",
            "config": {"repetitions": 1, "rounds": [1]},
            "models": [{"key": "m", "label": "A | <script>", "rounds": {}}],
        })
        self.assertIn("A \\| &lt;script&gt;", document)
        self.assertNotIn("<script>", document)


if __name__ == "__main__":
    unittest.main()
