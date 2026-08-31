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
    open_submission_pr, preview_pilot_submission, preview_submission, submission_document,
    submission_relative_path,
)
from llm_hardtest.community_results import (
    aggregate_item_diagnostics, aggregate_pilot_submissions, aggregate_submissions, build_index,
    build_pilot_index, load_pilot_submission_directory, load_submission_directory,
    recommend_configurations, render_index, render_pilot_index, render_recommendation,
)
from llm_hardtest.calibration import (
    _configuration_comparisons, _configuration_item_coverage,
    _discriminative_item_panel,
    _item_metrics, _item_relationships,
    _item_repeat_separation,
    analyze_runs, render_analysis, write_analysis,
)
from llm_hardtest.pilot_analysis import analyze_pilots, write_pilot_analysis
from llm_hardtest.public_pilots import (
    build_public_pilot_result, export_public_pilot_bundle,
    load_public_pilot_bundle, validate_public_pilot_result,
)
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

    def test_codex_session_fallback_reads_only_a_bounded_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "work"
            work.mkdir()
            session = root / "home/sessions/2026/09/01"
            session.mkdir(parents=True)
            session_id = "11111111-1111-1111-1111-111111111111"
            path = session / f"rollout-{session_id}.jsonl"
            with path.open("w", encoding="utf-8") as stream:
                stream.write(str(work) + "\n")
                stream.write("x" * 1_000_000)
            backend = CodexBackend({
                "key": "m", "model": "m", "codex_provider": "openai",
            }, root / "state")
            with patch.object(Path, "read_text",
                              side_effect=AssertionError("unbounded read")):
                found = backend._session_id(
                    "", {"CODEX_HOME": str(root / "home")}, work, 0)
            self.assertEqual(found, session_id)

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
                content + ("\nERROR codex_core::tools::router: "
                           "error=unsupported call: tool_code"
                           if self.mode == "unsupported" and turn == 1 else ""),
                encoding="utf-8")
            (evidence_dir / f"last_message_turn{turn}.txt").write_text(
                content, encoding="utf-8")
            timed_out = self.mode == "timeout" and turn == 1
            transcript = content + ("\nERROR codex_core::tools::router: "
                                    "error=unsupported call: tool_code"
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
                        text += ("\nERROR codex_core::tools::router: "
                                 "error=unsupported call: tool_code")
                    if model["key"] == "strong" and turn == 1:
                        text += "\nmodel discussion: unsupported call: harmless"
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


class PublicPilotResultTests(unittest.TestCase):
    def _run(self, root: Path) -> Path:
        run = PilotAnalysisTests()._pilot_run(root)
        config = load_json(run / "config.json")
        for index, model in enumerate(config["models"], 1):
            model.update({
                "public_name": f"example/model-{index}",
                "base_url": "http://127.0.0.1:9999/v1",
                "api_key_env": "PRIVATE_PILOT_KEY",
                "reasoning_effort": "high",
                "max_tokens": 4096,
            })
        save_json(run / "config.json", config)
        return run

    def test_export_is_allowlist_only_and_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._run(root / "run")
            first, second = root / "first.zip", root / "second.zip"
            _, payload, warnings = export_public_pilot_bundle(run, first)
            export_public_pilot_bundle(run, second)
            loaded = load_public_pilot_bundle(first)
            first_bytes, second_bytes = first.read_bytes(), second.read_bytes()
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(loaded, payload)
        self.assertFalse(warnings)
        text = json.dumps(payload)
        for private in ("Private Strong", "private/strong", "127.0.0.1",
                        "PRIVATE_PILOT_KEY", "normal transcript", "sessions.py"):
            self.assertNotIn(private, text)
        self.assertEqual(payload["models"][0]["attempts"][0]["public"], {
            "passed": 4, "total": 4, "timed_out": False,
        })

    def test_rehashed_semantic_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, _ = build_public_pilot_result(self._run(Path(tmp) / "run"))
        payload["models"][0]["attempts"][0]["release_ready"] = False
        from llm_hardtest.public_results import _bundle_id
        body = {key: value for key, value in payload.items() if key != "bundle_id"}
        payload["bundle_id"] = _bundle_id(body)
        with self.assertRaisesRegex(ValueError, "release_ready"):
            validate_public_pilot_result(payload)

    def test_bundle_rejects_unexpected_archive_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("submission.json", "{}")
                archive.writestr("PRIVACY.txt", "notice")
                archive.writestr("transcript.txt", "private")
            with self.assertRaisesRegex(ValueError, "unexpected files"):
                load_public_pilot_bundle(path)

    def test_preview_path_and_explicit_consent_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self._run(Path(tmp) / "run")
            bundle = Path(tmp) / "pilot.zip"
            _, payload, _ = export_public_pilot_bundle(run, bundle)
            previewed, relative, document = preview_pilot_submission(bundle)
            self.assertEqual(previewed, payload)
            self.assertTrue(relative.startswith("results/pilots/"))
            self.assertEqual(json.loads(document), payload)
            with patch("llm_hardtest.cli.open_submission_pr") as opened:
                self.assertEqual(main([
                    "pilot", "submit", str(bundle), "--open-pr"]), 2)
                opened.assert_not_called()

    def test_github_submission_targets_pilot_directory_and_labels_pr(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, _ = build_public_pilot_result(self._run(Path(tmp) / "run"))

        class RecordingClient:
            def __init__(self):
                self.calls = []

            def request(self, method, endpoint, fields=None, allow_missing=False):
                self.calls.append((method, endpoint, fields, allow_missing))
                if endpoint == "user":
                    return {"login": "owner"}
                if endpoint == "repos/owner/repo":
                    return {"default_branch": "main"}
                if "/contents/results/pilots/" in endpoint and method == "GET":
                    return None
                if endpoint.endswith("/git/ref/heads/main"):
                    return {"object": {"sha": "abc123"}}
                if endpoint == "repos/owner/repo/pulls":
                    return {"html_url": "https://github.com/owner/repo/pull/9"}
                return {}

        client = RecordingClient()
        self.assertEqual(open_submission_pr(payload, "owner/repo", client),
                         "https://github.com/owner/repo/pull/9")
        put_endpoint = next(endpoint for method, endpoint, _, _ in client.calls
                            if method == "PUT")
        self.assertIn("/contents/results/pilots/", put_endpoint)
        pull = next(fields for method, endpoint, fields, _ in client.calls
                    if method == "POST" and endpoint == "repos/owner/repo/pulls")
        self.assertIn("Round 5 pilot", pull["body"])
        self.assertIn(payload["pilot"]["pack"], pull["body"])

    def test_community_index_withholds_sparse_baseline_and_preserves_unobserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._run(root / "run")
            payload, _ = build_public_pilot_result(run)
            for attempt in payload["models"][1]["attempts"]:
                attempt["public"] = {"passed": 0, "total": 0, "timed_out": True}
            from llm_hardtest.public_results import _bundle_id
            body = {key: value for key, value in payload.items() if key != "bundle_id"}
            payload["bundle_id"] = _bundle_id(body)
            validate_public_pilot_result(payload)
            directory = root / "pilots"
            directory.mkdir()
            digest = payload["bundle_id"].removeprefix("sha256:")
            (directory / f"{digest}.json").write_text(
                submission_document(payload), encoding="utf-8")
            loaded = load_pilot_submission_directory(directory)
            rows = aggregate_pilot_submissions(loaded)
            document = render_pilot_index(loaded)
            output = root / "PILOTS.md"
            self.assertEqual(build_pilot_index(directory, output), (1, 2))
            self.assertEqual(build_pilot_index(directory, output, check=True), (1, 2))
        self.assertEqual(len(rows), 2)
        self.assertIn("withheld (<5 bundles)", document)
        self.assertIn("n/a", document)

    def test_baseline_requires_five_distinct_bundles(self):
        with tempfile.TemporaryDirectory() as tmp:
            original, _ = build_public_pilot_result(self._run(Path(tmp) / "run"))
        from llm_hardtest.public_results import _bundle_id
        submissions = []
        for index in range(5):
            payload = json.loads(json.dumps(original))
            payload["tool"]["version"] = f"2.6.{index}"
            body = {key: value for key, value in payload.items() if key != "bundle_id"}
            payload["bundle_id"] = _bundle_id(body)
            validate_public_pilot_result(payload)
            submissions.append(payload)
        document = render_pilot_index(submissions)
        self.assertIn("release 100.0% [56.6–100.0%], n=5 bundles", document)
        self.assertIn("release 0.0% [0.0–43.4%], n=5 bundles", document)


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
        self.assertEqual(items["q2"]["robust_classification"], "INSUFFICIENT")
        self.assertIsNone(items["q2"]["discrimination_interval95"])

    def test_item_bootstrap_separates_robust_signal_from_point_estimates(self):
        matrix = {}
        for respondent in range(30):
            matrix[(respondent,)] = {
                "q1": "PASS" if respondent >= 15 else "FAIL",
                "q2": "PASS" if respondent < 15 else "FAIL",
                "q3": "PASS" if respondent >= 10 else "FAIL",
                "q4": "PASS" if respondent >= 20 else "FAIL",
                "q5": "PASS" if respondent >= 5 else "FAIL",
                "q6": "PASS",
            }
        first = {row["item"]: row for row in _item_metrics(matrix)}
        second = {row["item"]: row for row in _item_metrics(matrix)}

        self.assertEqual(first, second)
        self.assertEqual(first["q2"]["robust_classification"], "ROBUST_NEGATIVE")
        self.assertLess(first["q2"]["discrimination_interval95"]["high"], 0)
        self.assertEqual(first["q3"]["robust_classification"], "ROBUST_USEFUL")
        self.assertGreaterEqual(first["q3"]["discrimination_interval95"]["low"], 0.15)
        self.assertEqual(first["q6"]["robust_classification"], "ROBUST_CEILING")
        self.assertGreaterEqual(first["q6"]["pass_rate_interval95"]["low"], 0.8)
        self.assertEqual(first["q1"]["classification"], "USEFUL")
        self.assertEqual(first["q1"]["robust_classification"], "UNCERTAIN")

    def test_item_bootstrap_withholds_interval_when_resamples_are_undefined(self):
        matrix = {}
        for respondent in range(10):
            matrix[(respondent,)] = {
                "rare": "PASS" if respondent == 0 else "FAIL",
                "anchor1": "PASS" if respondent < 5 else "FAIL",
                "anchor2": "PASS" if respondent < 5 else "FAIL",
            }
        rare = {row["item"]: row for row in _item_metrics(matrix)}["rare"]
        self.assertIsNone(rare["discrimination_interval95"])
        self.assertEqual(rare["robust_classification"], "UNSTABLE")

    def test_item_bootstrap_weights_independent_clusters_not_duplicate_rows(self):
        matrix, clusters = {}, {}
        for attempt in range(100):
            respondent = ("bulk", attempt)
            matrix[respondent] = {
                "q": "PASS" if attempt < 50 else "FAIL",
                "anchor": "FAIL" if attempt < 50 else "PASS",
            }
            clusters[respondent] = "bundle-0"
        for bundle in range(1, 10):
            respondent = ("single", bundle)
            status = "PASS" if bundle % 2 == 0 else "FAIL"
            matrix[respondent] = {"q": status, "anchor": status}
            clusters[respondent] = f"bundle-{bundle}"

        item = {row["item"]: row for row in _item_metrics(matrix, clusters)}["q"]
        self.assertLess(item["corrected_item_total_correlation"], 0)
        self.assertGreater(item["clustered_corrected_discrimination"], 0.15)
        self.assertEqual(item["independent_units"], 10)
        self.assertEqual(item["robust_classification"], "ROBUST_USEFUL")

    def test_item_relationships_separate_redundant_opposing_and_distinct_pairs(self):
        matrix = {}
        for respondent in range(30):
            base = respondent >= 15
            alternating = respondent % 2 == 0
            matrix[(respondent,)] = {
                "base": "PASS" if base else "FAIL",
                "duplicate": "PASS" if base else "FAIL",
                "opposite": "FAIL" if base else "PASS",
                "distinct": "PASS" if alternating else "FAIL",
            }
        first = {(row["left"], row["right"]): row
                 for row in _item_relationships(matrix)}
        second = {(row["left"], row["right"]): row
                  for row in _item_relationships(matrix)}

        self.assertEqual(first, second)
        duplicate = first[("base", "duplicate")]
        self.assertEqual(duplicate["phi_correlation"], 1.0)
        self.assertEqual(duplicate["robust_classification"],
                         "ROBUST_REDUNDANCY_CANDIDATE")
        self.assertGreaterEqual(duplicate["correlation_interval95"]["low"], 0.8)
        opposite = first[("base", "opposite")]
        self.assertEqual(opposite["phi_correlation"], -1.0)
        self.assertEqual(opposite["robust_classification"],
                         "ROBUST_OPPOSING_CANDIDATE")
        self.assertLessEqual(opposite["correlation_interval95"]["high"], -0.8)
        self.assertEqual(first[("base", "distinct")]["classification"], "DISTINCT")

    def test_item_relationships_do_not_count_repeated_bundle_rows_as_independent(self):
        matrix, clusters = {}, {}
        for attempt in range(100):
            respondent = ("one-bundle", attempt)
            outcome = attempt % 2 == 0
            matrix[respondent] = {
                "left": "PASS" if outcome else "FAIL",
                "right": "PASS" if outcome else "FAIL",
            }
            clusters[respondent] = "bundle-1"
        relationship = _item_relationships(matrix, clusters)[0]

        self.assertEqual(relationship["common_scored"], 100)
        self.assertEqual(relationship["independent_units"], 1)
        self.assertEqual(relationship["classification"], "REDUNDANCY_CANDIDATE")
        self.assertEqual(relationship["robust_classification"], "INSUFFICIENT")
        self.assertIsNone(relationship["correlation_interval95"])

    def test_item_relationships_equal_cluster_weight_resists_bulk_duplicates(self):
        matrix, clusters = {}, {}
        for attempt in range(100):
            respondent = ("bulk", attempt)
            outcome = attempt % 2 == 0
            matrix[respondent] = {
                "left": "PASS" if outcome else "FAIL",
                "right": "PASS" if outcome else "FAIL",
            }
            clusters[respondent] = "bundle-0"
        for bundle in range(1, 10):
            respondent = ("single", bundle)
            outcome = bundle % 2 == 0
            matrix[respondent] = {
                "left": "PASS" if outcome else "FAIL",
                "right": "FAIL" if outcome else "PASS",
            }
            clusters[respondent] = f"bundle-{bundle}"

        relationship = _item_relationships(matrix, clusters)[0]
        self.assertGreater(relationship["phi_correlation"], 0.5)
        self.assertLess(relationship["clustered_phi_correlation"], -0.5)
        self.assertEqual(relationship["independent_units"], 10)
        self.assertEqual(relationship["classification"], "REDUNDANCY_CANDIDATE")
        self.assertEqual(relationship["robust_classification"], "UNCERTAIN")

    def test_item_repeat_separation_distinguishes_signal_from_repeat_noise(self):
        matrix, models = {}, {}
        for configuration in ("strong", "weak"):
            for attempt in range(20):
                respondent = (configuration, attempt)
                models[respondent] = configuration
                stable = configuration == "strong"
                noisy = attempt % 2 == 0
                matrix[respondent] = {
                    "stable": "PASS" if stable else "FAIL",
                    "noisy": "PASS" if noisy else "FAIL",
                    "same": "PASS",
                }
        rows = {row["item"]: row
                for row in _item_repeat_separation(matrix, models)}

        stable = rows["stable"]
        self.assertEqual(stable["between_configuration_separation"], 1.0)
        self.assertEqual(stable["within_configuration_instability"], 0.0)
        self.assertEqual(stable["robust_classification"], "ROBUST_SEPARATING")
        self.assertGreaterEqual(stable["net_separation_interval95"]["low"], 0.1)
        noisy = rows["noisy"]
        self.assertEqual(noisy["between_configuration_separation"], 0.0)
        self.assertLess(noisy["net_repeat_adjusted_separation"], 0)
        self.assertEqual(noisy["classification"], "NOISE_DOMINATED")
        self.assertEqual(noisy["robust_classification"],
                         "ROBUST_NOISE_DOMINATED")
        self.assertLess(noisy["net_separation_interval95"]["high"], 0)
        same = rows["same"]
        self.assertEqual(same["classification"], "NO_SEPARATION")
        self.assertEqual(same["robust_classification"], "ROBUST_NO_SEPARATION")

    def test_item_repeat_separation_uses_bundles_as_shared_clusters(self):
        matrix, models, clusters = {}, {}, {}
        for attempt in range(100):
            for configuration, outcome in (("a", True), ("b", False)):
                respondent = ("bulk", configuration, attempt)
                matrix[respondent] = {"q": "PASS" if outcome else "FAIL"}
                models[respondent] = configuration
                clusters[respondent] = "bundle-0"
        rows = _item_repeat_separation(matrix, models, clusters)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["configurations"], 2)
        self.assertEqual(rows[0]["independent_units"], 1)
        self.assertEqual(rows[0]["repeat_configurations"], 0)
        self.assertEqual(rows[0]["robust_classification"], "INSUFFICIENT")

    def test_item_repeat_separation_shared_bundle_bootstrap_is_deterministic(self):
        matrix, models, clusters = {}, {}, {}
        for bundle in range(10):
            for configuration, outcome in (("a", True), ("b", False)):
                respondent = (bundle, configuration)
                matrix[respondent] = {"q": "PASS" if outcome else "FAIL"}
                models[respondent] = configuration
                clusters[respondent] = f"bundle-{bundle}"
        first = _item_repeat_separation(matrix, models, clusters)
        second = _item_repeat_separation(matrix, models, clusters)
        self.assertEqual(first, second)
        self.assertEqual(first[0]["robust_classification"], "ROBUST_SEPARATING")
        self.assertEqual(first[0]["net_separation_interval95"]["method"],
                         "shared_cluster_hierarchical_bootstrap_95")

    def test_pair_specific_item_coverage_finds_stable_specialist_items(self):
        matrix, models = {}, {}
        for configuration in ("a", "b"):
            for attempt in range(10):
                respondent = (configuration, attempt)
                models[respondent] = configuration
                matrix[respondent] = {
                    "specialist": "PASS" if configuration == "a" else "FAIL",
                    "shared": "PASS" if attempt % 2 == 0 else "FAIL",
                }
        coverage = _configuration_item_coverage(
            matrix, models, {"a": "C1", "b": "C2"})
        pair = coverage["comparisons"][0]
        items = {row["item"]: row for row in pair["items"]}

        self.assertEqual(pair["classification"], "SEPARATING")
        self.assertEqual(items["specialist"]["classification"], "LEFT_HIGHER")
        self.assertGreaterEqual(
            items["specialist"]["simultaneous_interval"]["low"], 0.1)
        self.assertEqual(items["specialist"]["simultaneous_interval"]["high"], 1.0)
        self.assertEqual(items["shared"]["classification"], "UNCERTAIN")
        self.assertEqual(coverage["item_coverage"][0]["item"], "specialist")
        self.assertEqual(coverage["item_coverage"][0]["decisive_configuration_pairs"], 1)

    def test_pair_specific_item_coverage_controls_a_noisy_item_family(self):
        matrix, models = {}, {}
        for configuration in ("a", "b"):
            for attempt in range(20):
                respondent = (configuration, attempt)
                models[respondent] = configuration
                matrix[respondent] = {
                    f"q{item}": "PASS" if (attempt + item) % 2 == 0 else "FAIL"
                    for item in range(20)
                }
        pair = _configuration_item_coverage(
            matrix, models, {"a": "C1", "b": "C2"})["comparisons"][0]
        self.assertEqual(pair["eligible_items"], 20)
        self.assertEqual(pair["decisive_items"], 0)
        self.assertEqual(pair["classification"], "UNCERTAIN")
        self.assertEqual({row["classification"] for row in pair["items"]},
                         {"UNCERTAIN"})

    def test_pair_specific_item_coverage_allocates_error_across_config_pairs(self):
        matrix, models = {}, {}
        for configuration in ("a", "b", "c"):
            for attempt in range(5):
                respondent = (configuration, attempt)
                models[respondent] = configuration
                matrix[respondent] = {
                    "q": "FAIL" if configuration == "b" else "PASS"}
        coverage = _configuration_item_coverage(
            matrix, models, {"a": "C1", "b": "C2", "c": "C3"})
        self.assertEqual(coverage["eligible_configuration_pairs"], 3)
        self.assertEqual(coverage["bonferroni_familywise_alpha"], 0.01666667)
        self.assertEqual({pair["familywise_alpha"]
                          for pair in coverage["comparisons"]}, {0.01666667})

    def test_pair_specific_item_coverage_uses_shared_bundle_clusters(self):
        matrix, models, clusters = {}, {}, {}
        for attempt in range(100):
            for configuration, outcome in (("a", True), ("b", False)):
                respondent = ("bulk", configuration, attempt)
                matrix[respondent] = {"q": "PASS" if outcome else "FAIL"}
                models[respondent] = configuration
                clusters[respondent] = "bundle-0"
        sparse = _configuration_item_coverage(
            matrix, models, {"a": "a", "b": "b"}, clusters)
        self.assertEqual(sparse["eligible_configuration_pairs"], 0)
        self.assertEqual(sparse["comparisons"][0]["classification"], "INSUFFICIENT")

        matrix, models, clusters = {}, {}, {}
        for bundle in range(10):
            for configuration, outcome in (("a", True), ("b", False)):
                respondent = (bundle, configuration)
                matrix[respondent] = {"q": "PASS" if outcome else "FAIL"}
                models[respondent] = configuration
                clusters[respondent] = f"bundle-{bundle}"
        first = _configuration_item_coverage(
            matrix, models, {"a": "a", "b": "b"}, clusters)
        second = _configuration_item_coverage(
            matrix, models, {"a": "a", "b": "b"}, clusters)
        self.assertEqual(first, second)
        pair = first["comparisons"][0]
        self.assertEqual(pair["items"][0]["classification"], "LEFT_HIGHER")
        self.assertEqual(pair["interval"]["method"],
                         "shared_cluster_max_error_bootstrap")

    def test_discriminative_panel_covers_pair_directions_compactly(self):
        coverage = {
            "eligible_configuration_pairs": 2,
            "comparisons": [
                {"left": "C1", "right": "C2", "items": [
                    {"item": "multi", "classification": "LEFT_HIGHER",
                     "pass_rate_difference": 0.8,
                     "simultaneous_interval": {"low": 0.4, "high": 1.0}},
                    {"item": "only12", "classification": "LEFT_HIGHER",
                     "pass_rate_difference": 0.7,
                     "simultaneous_interval": {"low": 0.3, "high": 1.0}},
                ]},
                {"left": "C1", "right": "C3", "items": [
                    {"item": "multi", "classification": "LEFT_HIGHER",
                     "pass_rate_difference": 0.6,
                     "simultaneous_interval": {"low": 0.2, "high": 0.9}},
                    {"item": "only13", "classification": "LEFT_HIGHER",
                     "pass_rate_difference": 0.5,
                     "simultaneous_interval": {"low": 0.15, "high": 0.8}},
                ]},
            ],
        }
        first = _discriminative_item_panel(coverage, [])
        second = _discriminative_item_panel(coverage, [])
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "COMPLETE")
        self.assertEqual(first["directional_targets"], 2)
        self.assertEqual([row["item"] for row in first["selected_items"]],
                         ["multi"])
        self.assertEqual(first["selected_items"][0]["minimum_simultaneous_margin"],
                         0.2)

    def test_discriminative_panel_preserves_opposite_specialties(self):
        coverage = {
            "eligible_configuration_pairs": 1,
            "comparisons": [{"left": "C1", "right": "C2", "items": [
                {"item": "left_skill", "classification": "LEFT_HIGHER",
                 "pass_rate_difference": 0.8,
                 "simultaneous_interval": {"low": 0.4, "high": 1.0}},
                {"item": "right_skill", "classification": "RIGHT_HIGHER",
                 "pass_rate_difference": -0.7,
                 "simultaneous_interval": {"low": -1.0, "high": -0.3}},
            ]}],
        }
        panel = _discriminative_item_panel(coverage, [])
        self.assertEqual(panel["directional_targets"], 2)
        self.assertEqual(panel["covered_directional_targets"], 2)
        self.assertEqual({row["item"] for row in panel["selected_items"]},
                         {"left_skill", "right_skill"})
        self.assertEqual({target for row in panel["selected_items"]
                          for target in row["new_directional_targets"]},
                         {"C1>C2", "C2>C1"})

    def test_discriminative_panel_penalizes_robust_dependencies(self):
        def item(name):
            return {"item": name, "classification": "LEFT_HIGHER",
                    "pass_rate_difference": 0.6,
                    "simultaneous_interval": {"low": 0.2, "high": 0.9}}
        coverage = {
            "eligible_configuration_pairs": 2,
            "comparisons": [
                {"left": "C1", "right": "C2",
                 "items": [item("a_anchor"), item("b_alternative")]},
                {"left": "C1", "right": "C3",
                 "items": [item("c_dependent"), item("d_distinct")]},
            ],
        }
        relationships = [
            {"left": left, "right": "c_dependent",
             "robust_classification": "ROBUST_REDUNDANCY_CANDIDATE"}
            for left in ("a_anchor", "b_alternative")
        ]
        panel = _discriminative_item_panel(coverage, relationships)
        self.assertEqual([row["item"] for row in panel["selected_items"]],
                         ["d_distinct", "a_anchor"])
        self.assertEqual(panel["robust_dependency_pairs_considered"], 2)
        self.assertEqual(panel["selected_items"][0]["robust_dependency_degree"], 0)
        self.assertEqual(panel["selected_items"][1]["robust_dependency_degree"], 1)
        self.assertTrue(all(not row["robustly_dependent_with_selected"]
                            for row in panel["selected_items"]))

    def test_discriminative_panel_exposes_budget_shortfall_and_no_signal(self):
        coverage = {
            "eligible_configuration_pairs": 2,
            "comparisons": [
                {"left": "C1", "right": "C2", "items": [{
                    "item": "q1", "classification": "LEFT_HIGHER",
                    "pass_rate_difference": 0.7,
                    "simultaneous_interval": {"low": 0.3, "high": 1.0}}]},
                {"left": "C1", "right": "C3", "items": [{
                    "item": "q2", "classification": "LEFT_HIGHER",
                    "pass_rate_difference": 0.7,
                    "simultaneous_interval": {"low": 0.3, "high": 1.0}}]},
            ],
        }
        partial = _discriminative_item_panel(coverage, [], max_items=1)
        self.assertEqual(partial["status"], "PARTIAL")
        self.assertEqual(partial["covered_directional_targets"], 1)
        self.assertEqual(len(partial["uncovered_directional_targets"]), 1)
        with self.assertRaisesRegex(ValueError, "positive integer"):
            _discriminative_item_panel(coverage, [], max_items=0)
        no_signal = _discriminative_item_panel({
            "eligible_configuration_pairs": 1,
            "comparisons": [{"left": "C1", "right": "C2", "items": [{
                "item": "q", "classification": "UNCERTAIN",
                "pass_rate_difference": 0,
                "simultaneous_interval": {"low": -0.2, "high": 0.2}}]}],
        }, [])
        self.assertEqual(no_signal["status"], "NO_DECISIVE_ITEMS")
        insufficient = _discriminative_item_panel({
            "eligible_configuration_pairs": 0, "comparisons": []}, [])
        self.assertEqual(insufficient["status"], "INSUFFICIENT")

    def test_calibration_proves_directional_configuration_separation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = []
            for repeat in range(1, 6):
                run = root / f"run-{repeat}"
                models = [
                    {"key": "strong", "label": "Secret Strong", "model": "private/a",
                     "transport": "openai_compat", "base_url": "http://secret-a/v1"},
                    {"key": "weak", "label": "Secret Weak", "model": "private/b",
                     "transport": "openai_compat", "base_url": "http://secret-b/v1"},
                ]
                save_json(run / "config.json", {
                    "name": "directional", "repetitions": 1,
                    "rounds": [1], "models": models,
                })
                save_json(run / "summary.json", {"packs": {"1": self.PACK_A}})
                for model, correct in zip(models, (True, False)):
                    save_json(run / model["key"] / "round1/attempt-1/result.json", {
                        "attempt": 1,
                        "results": [{"id": item, "correct": correct}
                                    for item in range(1, 11)],
                    })
                runs.append(run)
            analysis = analyze_runs(runs)
            rendered = render_analysis(analysis)

        self.assertEqual(analysis["schema_version"], 7)
        group = analysis["groups"][0]
        self.assertEqual(
            [(row["configuration"], row["sources"], row["respondents"])
             for row in group["configurations"]],
            [("C1", ["r1/m1", "r2/m1", "r3/m1", "r4/m1", "r5/m1"], 5),
             ("C2", ["r1/m2", "r2/m2", "r3/m2", "r4/m2", "r5/m2"], 5)],
        )
        self.assertEqual(
            group["configurations"][0]["respondent_pass_rate_interval95"]["low"],
            0.565509,
        )
        comparison = group["configuration_comparisons"][0]
        self.assertEqual(comparison["classification"], "LEFT_HIGHER")
        self.assertEqual(comparison["common_items"], 10)
        self.assertEqual(
            (comparison["left_item_wins"], comparison["right_item_wins"],
             comparison["item_ties"]), (10, 0, 0))
        self.assertEqual(comparison["mean_pass_rate_difference"], 1.0)
        self.assertEqual(comparison["difference_interval95"]["low"], 1.0)
        self.assertEqual(comparison["sign_test_p_holm"], 0.001953)
        panel = group["discriminative_item_panel"]
        self.assertEqual(panel["status"], "COMPLETE")
        self.assertEqual(panel["candidate_items"], 10)
        self.assertEqual(panel["directional_targets"], 1)
        self.assertEqual([row["item"] for row in panel["selected_items"]], ["q1"])
        self.assertEqual(panel["robust_dependency_pairs_considered"], 45)
        self.assertIn("Decisive after Holm correction: **1/1**", rendered)
        self.assertIn("Discriminative item panel", rendered)
        for private in ("Secret Strong", "private/a", "secret-a"):
            self.assertNotIn(private, rendered)

    def test_calibration_withholds_direction_below_repeat_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self._calibration_run(Path(tmp) / "run", model_count=2)
            group = analyze_runs([run])["groups"][0]
        comparison = group["configuration_comparisons"][0]
        self.assertEqual(comparison["classification"], "INSUFFICIENT")
        self.assertIsNone(comparison["difference_interval95"])
        self.assertIsNone(comparison["sign_test_p_holm"])

    def test_calibration_holm_correction_prevents_pairwise_false_winners(self):
        matrix, models = {}, {}
        patterns = {
            "a": [True] * 10,
            "b": [False] * 10,
            "c": [index % 2 == 0 for index in range(10)],
        }
        for config_index, (identity, outcomes) in enumerate(patterns.items(), 1):
            for attempt in range(1, 6):
                respondent = (1, config_index, str(attempt))
                models[respondent] = identity
                matrix[respondent] = {
                    f"q{item}": "PASS" if outcome else "FAIL"
                    for item, outcome in enumerate(outcomes, 1)
                }
        rows = _configuration_comparisons(
            matrix, models, {"a": "C1", "b": "C2", "c": "C3"})
        by_pair = {(row["left"], row["right"]): row for row in rows}
        self.assertEqual(by_pair[("C1", "C2")]["classification"], "LEFT_HIGHER")
        self.assertEqual(by_pair[("C1", "C2")]["sign_test_p_holm"], 0.005859)
        self.assertEqual(by_pair[("C1", "C3")]["classification"], "UNCERTAIN")
        self.assertEqual(by_pair[("C2", "C3")]["classification"], "UNCERTAIN")

    def test_calibration_repeat_instability_blocks_fragile_item_winner(self):
        matrix, models = {}, {}
        for config_index, identity in enumerate(("a", "b"), 1):
            passing_respondents = 3 if identity == "a" else 2
            for attempt in range(1, 6):
                respondent = (1, config_index, str(attempt))
                models[respondent] = identity
                outcome = "PASS" if attempt <= passing_respondents else "FAIL"
                matrix[respondent] = {f"q{item}": outcome for item in range(1, 11)}
        row = _configuration_comparisons(
            matrix, models, {"a": "C1", "b": "C2"})[0]
        self.assertLess(row["sign_test_p_holm"], 0.05)
        self.assertLessEqual(row["difference_interval95"]["low"], 0)
        self.assertGreaterEqual(row["difference_interval95"]["high"], 0)
        self.assertEqual(row["classification"], "UNCERTAIN")

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
            with self.assertRaisesRegex(ValueError, "panel max items"):
                analyze_runs([run], panel_max_items=0)


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
                "public_metadata": {
                    "quantization": "Q4_K_M", "server_version": "1.2.3",
                    "accelerator_count": 2, "unknown": "drop-me",
                },
            }],
        }
        save_json(root / "config.json", config)
        save_json(root / "private-user-key/round1/attempt-1/result.json", {
            "attempt": 1, "score": 1, "total": 1, "planned": 1, "wall": 2.0,
            "results": [{
                "id": 1, "correct": True, "content": "private raw response",
                "transcript": "/Users/private/work and sk-secret-secret-secret",
                "wall": 2.0, "completion_tokens": 20,
            }],
        })
        generate(root)

    def _recommendation_submissions(self, count=5):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            self._run(run)
            original, _ = build_public_result(run)
        from llm_hardtest.public_results import _bundle_id
        models = []
        for name, passed, wall, memory in (
                ("org/fast", 8, 1.0, 8), ("org/accurate", 9, 4.0, 24)):
            model = json.loads(json.dumps(original["models"][0]))
            model["public_name"] = name
            model["public_metadata"] = {
                "accelerator": "Example GPU", "memory_gb": memory,
                "server": "Example Server", "quantization": "Q4_K_M",
            }
            items = [
                {"item": f"q{item}", "attempt": 1,
                 "status": "PASS" if item <= passed else "FAIL",
                 "wall_seconds": wall, "tokens": 20}
                for item in range(1, 11)
            ]
            result = model["rounds"]["1"]
            result.update({"passed": passed, "total": 10, "incomplete": 0,
                           "manual_review": 0, "infrastructure_errors": 0,
                           "items": items})
            models.append(model)
        submissions = []
        for index in range(count):
            payload = json.loads(json.dumps(original))
            payload["benchmark"] = {
                "rounds": [1], "packs": {"1": "sha256:" + "a" * 64}}
            payload["models"] = json.loads(json.dumps(models))
            payload["tool"]["version"] = f"recommendation-control-{index}"
            body = {key: value for key, value in payload.items() if key != "bundle_id"}
            payload["bundle_id"] = _bundle_id(body)
            validate_public_result(payload)
            submissions.append(payload)
        return submissions

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
                         {"accelerator_count": 2, "quantization": "Q4_K_M",
                          "server_version": "1.2.3"})
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(payload["models"][0]["rounds"]["1"]["items"], [{
            "item": "q1", "attempt": 1, "status": "PASS",
            "wall_seconds": 2.0, "tokens": 20,
        }])
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

    def test_schema_v2_rejects_aggregate_item_contradictions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            self._run(root)
            payload, _ = build_public_result(root)
        payload["models"][0]["rounds"]["1"]["passed"] = 0
        from llm_hardtest.public_results import _bundle_id
        body = {key: value for key, value in payload.items() if key != "bundle_id"}
        payload["bundle_id"] = _bundle_id(body)
        with self.assertRaisesRegex(ValueError, "contradicts item outcomes"):
            validate_public_result(payload)

    def test_schema_v1_aggregate_bundles_remain_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            self._run(root)
            payload, _ = build_public_result(root)
        payload["schema_version"] = 1
        for model in payload["models"]:
            for result in model["rounds"].values():
                result.pop("items", None)
        from llm_hardtest.public_results import _bundle_id
        body = {key: value for key, value in payload.items() if key != "bundle_id"}
        payload["bundle_id"] = _bundle_id(body)
        self.assertEqual(validate_public_result(payload), payload)

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
        community = aggregate_submissions([payload])[0]
        self.assertEqual((community["passed"], community["total"]), (1, 1))

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
            self.assertEqual(rows[0]["bundle_item_wall_p50_seconds"], 2.0)
            self.assertEqual(rows[0]["bundle_tokens_per_second_p50"], 10.0)
            self.assertIn("withheld (<5 observed bundles)", render_index(loaded))
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
        self.assertIn("[56.6–100.0%], n=5 bundles", document)

    def test_recommendation_uses_conservative_pareto_objectives(self):
        submissions = self._recommendation_submissions()
        accuracy = recommend_configurations(
            submissions, round_number=1, objectives=["accuracy"])
        tradeoff = recommend_configurations(
            submissions, round_number=1, objectives=["accuracy", "latency"])
        self.assertEqual(accuracy["status"], "DESCRIPTIVE_CANDIDATES")
        self.assertEqual([row["model"] for row in accuracy["candidates"]],
                         ["org/accurate"])
        self.assertEqual(accuracy["excluded"]["dominated"], 1)
        self.assertEqual({row["model"] for row in tradeoff["candidates"]},
                         {"org/accurate", "org/fast"})
        self.assertTrue(all(row["independent_bundles"] == 5
                            for row in tradeoff["candidates"]))
        self.assertIn("not a prediction", tradeoff["reason"])

    def test_recommendation_constraints_do_not_infer_missing_metadata(self):
        submissions = self._recommendation_submissions()
        result = recommend_configurations(
            submissions, round_number=1,
            constraints={"accelerator": "example gpu", "max_memory_gb": 16},
            objectives=["accuracy", "latency"])
        self.assertEqual(result["status"], "SINGLE_ELIGIBLE_CONFIGURATION")
        self.assertEqual(result["candidates"][0]["model"], "org/fast")
        missing = json.loads(json.dumps(submissions))
        from llm_hardtest.public_results import _bundle_id
        for payload in missing:
            for model in payload["models"]:
                model["public_metadata"].pop("accelerator")
            body = {key: value for key, value in payload.items() if key != "bundle_id"}
            payload["bundle_id"] = _bundle_id(body)
            validate_public_result(payload)
        withheld = recommend_configurations(
            missing, round_number=1, constraints={"accelerator": "Example GPU"})
        self.assertEqual(withheld["status"], "NO_MATCH")
        self.assertEqual(withheld["excluded"]["constraints"], 2)

    def test_recommendation_requires_independent_bundles_and_exact_pack(self):
        sparse = self._recommendation_submissions(1)
        sparse[0]["models"] = sparse[0]["models"] * 100
        from llm_hardtest.public_results import _bundle_id
        body = {key: value for key, value in sparse[0].items() if key != "bundle_id"}
        sparse[0]["bundle_id"] = _bundle_id(body)
        validate_public_result(sparse[0])
        result = recommend_configurations(sparse, round_number=1)
        self.assertEqual(result["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["eligible_configurations"], 0)
        self.assertEqual(result["excluded"]["insufficient_bundles"], 2)

        mixed = self._recommendation_submissions()
        for index, payload in enumerate(mixed):
            if index % 2:
                payload["benchmark"]["packs"]["1"] = "sha256:" + "b" * 64
                body = {key: value for key, value in payload.items()
                        if key != "bundle_id"}
                payload["bundle_id"] = _bundle_id(body)
                validate_public_result(payload)
        ambiguous = recommend_configurations(mixed, round_number=1)
        self.assertEqual(ambiguous["status"], "PACK_REQUIRED")
        self.assertEqual(len(ambiguous["available_packs"]), 2)

    def test_recommendation_floor_rendering_and_privacy(self):
        result = recommend_configurations(
            self._recommendation_submissions(), round_number=1,
            objectives=["accuracy", "throughput"], accuracy_floor=0.4)
        document = render_recommendation(result)
        self.assertIn("Descriptive Serving Candidates", document)
        self.assertIn("Accuracy lower / observed", document)
        self.assertIn("server=Example Server", document)
        self.assertIn("memory GB=24", document)
        self.assertIn("(n=5)", document)
        self.assertIn("hardware capacity is an observation filter", document)
        serialized = json.dumps(result)
        self.assertNotIn("bundle_id", serialized)
        self.assertNotIn("recommendation-control", serialized)

    def test_recommendation_performance_objectives_require_five_bundles(self):
        submissions = self._recommendation_submissions()
        from llm_hardtest.public_results import _bundle_id
        for model in submissions[-1]["models"]:
            for item in model["rounds"]["1"]["items"]:
                item["wall_seconds"] = None
                item["tokens"] = None
        body = {key: value for key, value in submissions[-1].items()
                if key != "bundle_id"}
        submissions[-1]["bundle_id"] = _bundle_id(body)
        validate_public_result(submissions[-1])
        result = recommend_configurations(
            submissions, round_number=1, objectives=["latency", "throughput"])
        self.assertEqual(result["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["excluded"]["missing_objective"], 2)
        self.assertFalse(result["candidates"])

    def test_recommendation_rejects_ambiguous_query_contracts(self):
        submissions = self._recommendation_submissions()
        with self.assertRaisesRegex(ValueError, "exact sha256"):
            recommend_configurations(submissions, round_number=1, pack="latest")
        with self.assertRaisesRegex(ValueError, "must be a list"):
            recommend_configurations(
                submissions, round_number=1, objectives="accuracy")
        with self.assertRaisesRegex(ValueError, "safe text"):
            recommend_configurations(
                submissions, round_number=1, constraints={"server": "\n"})
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            recommend_configurations(
                submissions, round_number=1, accuracy_floor=1.01)

    def test_results_recommend_cli_emits_json_without_writes(self):
        submissions = self._recommendation_submissions()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            for payload in submissions:
                digest = payload["bundle_id"].removeprefix("sha256:")
                (directory / f"{digest}.json").write_text(
                    submission_document(payload), encoding="utf-8")
            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                exit_code = main(["results", "recommend", str(directory),
                                  "--round", "1", "--objective", "accuracy",
                                  "--json"])
        self.assertEqual(exit_code, 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["status"], "DESCRIPTIVE_CANDIDATES")
        self.assertEqual(result["candidates"][0]["model"], "org/accurate")

    def test_unobserved_bundles_do_not_unlock_a_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            self._run(run)
            original, _ = build_public_result(run)
        from llm_hardtest.public_results import _bundle_id
        submissions = []
        for index in range(5):
            payload = json.loads(json.dumps(original))
            payload["schema_version"] = 1
            result = payload["models"][0]["rounds"]["1"]
            result.pop("items")
            result["passed"] = 0
            result["total"] = 0
            payload["tool"]["version"] = f"legacy-{index}"
            body = {key: value for key, value in payload.items() if key != "bundle_id"}
            payload["bundle_id"] = _bundle_id(body)
            validate_public_result(payload)
            submissions.append(payload)
        row = aggregate_submissions(submissions)[0]
        self.assertEqual(row["observed_submissions"], 0)
        self.assertIsNone(row["bundle_pass_rate_interval95"])
        self.assertIn("withheld (<5 observed bundles)", render_index(submissions))

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
        self.assertIsNone(rows[0]["bundle_pass_rate_interval95"])
        self.assertIn("withheld (<5 observed bundles)", render_index([payload]))

    def test_schema_v2_community_recomputes_item_discrimination(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = CalibrationTests()._calibration_run(Path(tmp) / "run")
            for path in run.glob("m*/round1/attempt-1/result.json"):
                result = load_json(path)
                counts = result_counts(result)
                result["score"] = counts["PASS"]
                result["total"] = counts["PASS"] + counts["FAIL"]
                save_json(path, result)
            payload, _ = build_public_result(run)
        diagnostics = aggregate_item_diagnostics([payload])
        self.assertEqual(len(diagnostics), 1)
        items = {item["item"]: item for item in diagnostics[0]["items"]}
        self.assertEqual(items["q4"]["classification"], "NEGATIVE")
        self.assertEqual(items["q5"]["classification"], "CEILING")
        self.assertEqual(items["q4"]["independent_units"], 1)
        self.assertEqual(items["q4"]["robust_classification"], "INSUFFICIENT")
        self.assertIsNone(items["q4"]["discrimination_interval95"])
        relationships = diagnostics[0]["item_relationships"]
        self.assertEqual(len(relationships), 15)
        self.assertEqual({row["independent_units"] for row in relationships}, {0, 1})
        self.assertEqual({row["robust_classification"] for row in relationships},
                         {"INSUFFICIENT"})
        repeat_separation = diagnostics[0]["item_repeat_separation"]
        self.assertEqual(len(repeat_separation), 6)
        self.assertEqual({row["robust_classification"]
                          for row in repeat_separation}, {"INSUFFICIENT"})
        coverage = diagnostics[0]["configuration_item_coverage"]
        self.assertEqual(coverage["eligible_configuration_pairs"], 0)
        self.assertEqual(diagnostics[0]["discriminative_item_panel"]["status"],
                         "INSUFFICIENT")
        document = render_index([payload])
        self.assertIn("Community Item Diagnostics", document)
        self.assertIn("Community item dependency candidates", document)
        self.assertIn("Community repeat-adjusted item separation", document)
        self.assertIn("Community pair-specific item coverage", document)
        self.assertIn("Community discriminative item panel", document)
        self.assertIn("Corrected discrimination", document)
        self.assertIn("Independent bundles", document)
        self.assertIn("Robust", document)

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
