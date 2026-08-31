from __future__ import annotations

import json
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
from llm_hardtest.cli import discover_models, doctor_config, main
from llm_hardtest.common import answer_matches, answer_text, save_json
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
    open_submission_pr, preview_submission, submission_relative_path,
)
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
        self.assertEqual(json.loads(__import__("base64").b64decode(
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
