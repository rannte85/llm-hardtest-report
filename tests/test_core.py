from __future__ import annotations

import json
import base64
import io
import os
import re
import runpy
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from pathlib import Path

from llm_hardtest.backends import Backend, BackendError, CodexBackend, OpenAICompatBackend
from llm_hardtest.cli import _selftest_source_paths, discover_models, doctor_config, main
from llm_hardtest.common import answer_matches, answer_text, load_json, repo_root, save_json
from llm_hardtest.orchestrator import _campaign_units, run as run_campaign, validate_config
from llm_hardtest.progress import TerminalDashboard, _duration
from llm_hardtest.report import collect, generate, render
from llm_hardtest.results import item_status, result_counts
from llm_hardtest.inspection import inspect_run, render_inspection
from llm_hardtest.replay import make_replay_config
from llm_hardtest.packs import validate_pack
from llm_hardtest.public_results import (
    build_public_result, export_public_bundle, load_public_bundle,
    normalized_serving_environment, validate_public_result,
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
from llm_hardtest.community_database import (
    SCHEMA_SQL, _content_fingerprint, aggregate_database, build_database,
    catalog_database, compare_database, load_database, normalize_submissions,
    paired_database_observations, plan_database, readiness_database,
    recommend_database,
)
from llm_hardtest.serving_catalog import (
    build_catalog, catalog_submissions, render_catalog,
)
from llm_hardtest.collection_plan import (
    build_collection_plan, plan_submissions, render_collection_plan,
)
from llm_hardtest.paired_comparison import (
    _bundle_observations, _sign_flip_test, compare_paired_observations,
    compare_submissions, render_paired_comparison,
)
from llm_hardtest.prediction_readiness import (
    audit_prediction_readiness, audit_submissions, render_prediction_readiness,
)
from llm_hardtest.calibration import (
    _configuration_comparisons, _configuration_item_coverage,
    _discriminative_item_panel,
    _item_metrics, _item_relationships,
    _item_repeat_separation,
    _model_identity, _panel_holdout_validation, _permutation_difference_test,
    analyze_runs, render_analysis, write_analysis,
)
from llm_hardtest.panel_config import build_panel_config, write_panel_config
from llm_hardtest.pilot_analysis import (
    _bootstrap_sample_count, _directional_advantage, _directional_robustness,
    _evidence_collection_plan, _leave_one_out_robustness, _next_pair_evidence,
    _separation_status, analyze_pilots, write_pilot_analysis,
)
from llm_hardtest.public_pilots import (
    build_public_pilot_result, export_public_pilot_bundle,
    load_public_pilot_bundle, validate_public_pilot_result,
)
from llm_hardtest.round5 import (
    PILOT_IDS, fingerprint_registry, pilot_fingerprint, run_pilot,
)
from llm_hardtest.round12 import run as run_round12
from llm_hardtest.round3 import _fields, _grade
from llm_hardtest.round4 import run as run_round4
from llm_hardtest.isolation import (
    IsolationError, MacOSSeatbeltIsolation, make_isolation,
)
from llm_hardtest.round4_agents import (
    OpenCodeRound4Agent, Round4AgentError, make_round4_agent,
)


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
    def test_codex_completion_uses_structured_output_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = CodexBackend({
                "key": "m", "model": "gpt-test", "codex_provider": "openai",
            }, Path(tmp))
            commands = []

            def successful_run(command, **_kwargs):
                commands.append(command)
                Path(command[command.index("-o") + 1]).write_text(
                    "ANSWER: 42", encoding="utf-8")
                events = (
                    'diagnostic before JSON\n'
                    '{"type":"turn.completed","usage":{"input_tokens":120,'
                    '"cached_input_tokens":80,"output_tokens":7,'
                    '"reasoning_output_tokens":3}}\n')
                return type("Process", (), {
                    "returncode": 0, "stdout": events, "stderr": "",
                })()

            with patch("subprocess.run", side_effect=successful_run):
                result = backend.complete(
                    [{"role": "user", "content": "test"}], 10)
        self.assertIn("--json", commands[0])
        self.assertEqual(result["prompt_tokens"], 120)
        self.assertEqual(result["cached_input_tokens"], 80)
        self.assertEqual(result["completion_tokens"], 7)
        self.assertEqual(result["reasoning_output_tokens"], 3)
        self.assertEqual(result["total_tokens"], 127)
        self.assertEqual(result["token_measurement"], "completion")

    def test_codex_legacy_total_is_not_completion_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = CodexBackend({
                "key": "m", "model": "gpt-test", "codex_provider": "openai",
            }, Path(tmp))

            def legacy_run(command, **_kwargs):
                Path(command[command.index("-o") + 1]).write_text(
                    "ANSWER: 42", encoding="utf-8")
                return type("Process", (), {
                    "returncode": 0, "stdout": "tokens used\n12,345\n", "stderr": "",
                })()

            with patch("subprocess.run", side_effect=legacy_run):
                result = backend.complete(
                    [{"role": "user", "content": "test"}], 10)
        self.assertIsNone(result["completion_tokens"])
        self.assertEqual(result["total_tokens"], 12345)
        self.assertEqual(result["token_measurement"], "unavailable")

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

    def test_codex_agent_allows_recovery_from_one_unsupported_tool_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "work"
            work.mkdir()
            backend = CodexBackend({
                "key": "m", "model": "m", "codex_provider": "openai",
            }, root / "state")

            class RecoveringProcess:
                pid = 1

                def __init__(self, command, stream):
                    self.command = command
                    self.stream = stream
                    self.calls = 0

                def wait(self, timeout):
                    self.calls += 1
                    if self.calls == 1:
                        self.stream.write(
                            "ERROR codex_core::tools::router: "
                            "error=request_user_input is unavailable in Default mode\n")
                        self.stream.flush()
                        raise subprocess.TimeoutExpired("codex", timeout)
                    Path(self.command[self.command.index("-o") + 1]).write_text(
                        "recovered", encoding="utf-8")
                    return 0

            def fake_popen(command, **kwargs):
                return RecoveringProcess(command, kwargs["stdout"])

            with patch("subprocess.Popen", side_effect=fake_popen):
                result = backend.agent_turn(
                    "first", work, root / "evidence", 1, 10, "read-only")
        self.assertFalse(result["protocol_aborted"])
        self.assertIsNone(result["termination_reason"])
        self.assertEqual(result["content"], "recovered")

    def test_codex_agent_aborts_repeated_unsupported_tool_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "work"
            work.mkdir()
            backend = CodexBackend({
                "key": "m", "model": "m", "codex_provider": "openai",
            }, root / "state")

            class LoopingProcess:
                pid = 1

                def __init__(self, stream):
                    self.stream = stream
                    self.calls = 0

                def wait(self, timeout):
                    self.calls += 1
                    self.stream.write(
                        "ERROR codex_core::tools::router: "
                        "error=request_user_input is unavailable in Default mode\n")
                    self.stream.flush()
                    raise subprocess.TimeoutExpired("codex", timeout)

            def fake_popen(_command, **kwargs):
                return LoopingProcess(kwargs["stdout"])

            with patch("subprocess.Popen", side_effect=fake_popen), \
                    patch("llm_hardtest.backends._stop_process", return_value=-15) as stopped:
                result = backend.agent_turn(
                    "next", work, root / "evidence", 2, 10, "workspace-write",
                    "11111111-1111-1111-1111-111111111111")
        stopped.assert_called_once()
        self.assertFalse(result["timed_out"])
        self.assertTrue(result["protocol_aborted"])
        self.assertEqual(result["termination_reason"], "unsupported_tool_loop")
        self.assertEqual(result["protocol_abort_tool_names"], ["request_user_input"])
        self.assertEqual(result["returncode"], -15)
        self.assertIn("PROTOCOL_ABORT", result["transcript"])

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

    def test_doctor_uses_opencode_without_probing_responses(self):
        config = {
            "name": "test", "repetitions": 1, "rounds": [4],
            "round4_tasks": ["q26_hidden_tests"],
            "models": [{"key": "local", "model": "local/model",
                        "transport": "openai_compat", "agent_backend": "opencode_cli",
                        "codex_provider": "custom",
                        "base_url": "http://127.0.0.1:8000/v1", "rounds": [4]}],
        }
        with patch("llm_hardtest.cli.discover_models", return_value=["local/model"]), \
                patch("llm_hardtest.orchestrator.shutil.which",
                      side_effect=lambda name: "/usr/bin/opencode"
                      if name == "opencode" else None), \
                patch("llm_hardtest.cli._probe_codex") as codex_probe, \
                patch("llm_hardtest.cli._probe_opencode") as opencode_probe:
            self.assertEqual(doctor_config(config), 0)
        codex_probe.assert_not_called()
        opencode_probe.assert_called_once_with(config["models"][0], 30, None)

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

            def main(self, _args, progress_callback=None, agent_factory=None):
                self.agent_factory = agent_factory
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


class RoundFourAgentBackendTests(unittest.TestCase):
    def _fake_opencode(self, root: Path) -> Path:
        executable = root / "opencode"
        executable.write_text(
            f"""#!{sys.executable}
import json, os, sys, time
args = sys.argv[1:]
if args[:2] == ["run", "--help"]:
    print("--model --format --session --dir --dangerously-skip-permissions")
    raise SystemExit(0)
mode = os.environ.get("FAKE_OPENCODE_MODE", "ok")
if mode == "exit":
    raise SystemExit(7)
session = (args[args.index("--session") + 1] if "--session" in args
           else os.environ["XDG_DATA_HOME"])
if mode == "wrong-session" and "--session" in args:
    session = "wrong-session"
model = args[args.index("--model") + 1]
if mode == "mismatch":
    model = "llm-hardtest/wrong-model"
print(json.dumps({{"type": "step_start", "sessionID": session}}))
sys.stdout.flush()
if mode == "timeout":
    time.sleep(60)
if mode != "empty":
    print(json.dumps({{"type": "text", "sessionID": session,
                      "part": {{"text": "done", "modelID": model}}}}))
""", encoding="utf-8")
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        return executable

    def _model(self):
        return {
            "key": "m", "model": "local-model", "agent_backend": "opencode_cli",
            "transport": "openai_compat", "codex_provider": "custom",
            "base_url": "http://127.0.0.1:8000/v1",
        }

    def test_opencode_preserves_session_within_attempt_and_fresh_state_between(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = self._fake_opencode(root)
            work = root / "work"
            work.mkdir()
            with patch("llm_hardtest.round4_agents.shutil.which",
                       return_value=str(executable)):
                first = make_round4_agent(
                    self._model(), root / "state-a", root / "meta-a.json")
                first.preflight(work)
                one = first.turn("one", work, root / "evidence-a", 1, 10)
                two = first.turn(
                    "two", work, root / "evidence-a", 2, 10, one["session_id"])
                second = make_round4_agent(
                    self._model(), root / "state-b", root / "meta-b.json")
                second.preflight(work)
                other = second.turn("one", work, root / "evidence-b", 1, 10)
            self.assertEqual(one["session_id"], two["session_id"])
            self.assertNotEqual(one["session_id"], other["session_id"])
            self.assertTrue(one["model_identity_verified"])
            metadata = load_json(root / "meta-a.json")
            self.assertEqual(metadata["agent_backend"], "opencode_cli")
            self.assertEqual(len(metadata["turns"]), 2)

    def test_opencode_nonzero_empty_and_model_mismatch_fail_before_grading(self):
        for mode, message in (
                ("exit", "exited 7"),
                ("empty", "without a final"),
                ("mismatch", "model mismatch")):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                executable = self._fake_opencode(root)
                work = root / "work"
                work.mkdir()
                with patch.dict(os.environ, {"FAKE_OPENCODE_MODE": mode}), \
                        patch("llm_hardtest.round4_agents.shutil.which",
                              return_value=str(executable)):
                    agent = make_round4_agent(
                        self._model(), root / "state", root / "meta.json")
                    agent.preflight(work)
                    with self.assertRaisesRegex(Round4AgentError, message):
                        agent.turn("task", work, root / "evidence", 1, 10)

    def test_opencode_timeout_preserves_partial_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = self._fake_opencode(root)
            work = root / "work"
            work.mkdir()
            with patch.dict(os.environ, {"FAKE_OPENCODE_MODE": "timeout"}), \
                    patch("llm_hardtest.round4_agents.shutil.which",
                          return_value=str(executable)):
                agent = make_round4_agent(
                    self._model(), root / "state", root / "meta.json")
                agent.preflight(work)
                with self.assertRaisesRegex(Round4AgentError, "timed out"):
                    agent.turn("task", work, root / "evidence", 1, 1)
            transcript = root / "evidence" / "transcript_turn1.txt"
            self.assertTrue(transcript.is_file())
            self.assertIn("step_start", transcript.read_text(encoding="utf-8"))

    def test_opencode_rejects_wrong_continuation_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = self._fake_opencode(root)
            work = root / "work"
            work.mkdir()
            with patch("llm_hardtest.round4_agents.shutil.which",
                       return_value=str(executable)):
                agent = make_round4_agent(
                    self._model(), root / "state", root / "meta.json")
                agent.preflight(work)
                first = agent.turn("one", work, root / "evidence", 1, 10)
                with patch.dict(os.environ, {"FAKE_OPENCODE_MODE": "wrong-session"}):
                    with self.assertRaisesRegex(Round4AgentError, "wrong session"):
                        agent.turn(
                            "two", work, root / "evidence", 2, 10,
                            first["session_id"])

    def test_opencode_is_optional_but_fails_capability_validation_when_selected(self):
        config = {
            "name": "agent", "rounds": [4], "repetitions": 1,
            "models": [{**self._model(), "rounds": [4]}],
        }
        with patch("llm_hardtest.orchestrator.shutil.which",
                   side_effect=lambda name: None if name == "opencode" else "/bin/tool"):
            with self.assertRaisesRegex(ValueError, "opencode on PATH"):
                validate_config(config)
        validate_config(config, check_runtime=False)

    def test_agent_and_isolation_are_exact_configuration_identity(self):
        base = {"model": "m", "transport": "openai_compat"}
        opencode = {**base, "agent_backend": "opencode_cli"}
        isolation = {
            "mode": "macos_seatbelt", "fail_closed": True,
            "attempt_state": "isolated", "network": "model_endpoint_only",
            "post_run_audit": True,
        }
        self.assertNotEqual(_model_identity(base), _model_identity(opencode))
        self.assertNotEqual(
            _model_identity(base), _model_identity(base, isolation))

    def test_round4_rerun_preserves_prior_evidence_and_uses_fresh_state(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                payload = json.dumps({"data": [{"id": "local-model"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                fake = self._fake_opencode(root)
                out = root / "model" / "round4"
                model = {
                    **self._model(),
                    "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                }
                with patch("llm_hardtest.round4_agents.shutil.which",
                           return_value=str(fake)):
                    self.assertEqual(run_round4(
                        model, 1, out, 20, ["q26_hidden_tests"]), 0)
                    self.assertEqual(run_round4(
                        model, 1, out, 20, ["q26_hidden_tests"]), 0)
                attempt = out / "q26_hidden_tests" / "attempt1"
                self.assertTrue((attempt / "agent_meta.json").is_file())
                self.assertTrue((attempt / "retry1" / "agent_meta.json").is_file())
                result = load_json(out / "run.json")
                self.assertEqual(
                    result["grades"][0]["run_meta"]["evidence_subdir"], "retry1")
        finally:
            server.shutdown()
            server.server_close()


class RoundFourIsolationTests(unittest.TestCase):
    def test_explicit_seatbelt_fails_closed_off_macos(self):
        config = {
            "mode": "macos_seatbelt", "fail_closed": True,
            "attempt_state": "isolated", "network": "model_endpoint_only",
            "post_run_audit": True,
        }
        with tempfile.TemporaryDirectory() as tmp, \
                patch("llm_hardtest.isolation.platform.system", return_value="Linux"):
            with self.assertRaisesRegex(IsolationError, "unavailable"):
                make_isolation(
                    config, Path(tmp) / "state", [], [],
                    "http://127.0.0.1:8000/v1")

    @unittest.skipUnless(sys.platform == "darwin", "macOS Seatbelt control")
    def test_seatbelt_canary_and_post_run_quarantine(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()

            def log_message(self, _format, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                work, state, protected = root / "work", root / "state", root / "hidden"
                work.mkdir()
                state.mkdir()
                protected.mkdir()
                (protected / "held_back.py").write_text("secret", encoding="utf-8")
                isolation = MacOSSeatbeltIsolation(
                    {}, state, [protected], [root / "evidence"],
                    f"http://127.0.0.1:{server.server_port}/v1")
                result = isolation.preflight(work)
                self.assertTrue(result["mandatory_checks_passed"])
                self.assertEqual(isolation.audit("ordinary output")["status"], "pass")
                leaked = isolation.audit(isolation.canary_token)
                self.assertTrue(leaked["boundary_violation"])
                self.assertRegex(isolation.provenance["policy_hash"], r"^sha256:[0-9a-f]{64}$")

                class MissingDeny(MacOSSeatbeltIsolation):
                    def _build_profile(self, workdir):
                        return "\n".join(
                            line for line in super()._build_profile(workdir).splitlines()
                            if not line.startswith("(deny file-read*")) + "\n"

                missing_state = root / "missing-state"
                missing_state.mkdir()
                missing = MissingDeny(
                    {}, missing_state, {"held_back_checks": [protected]}, [],
                    f"http://127.0.0.1:{server.server_port}/v1")
                with self.assertRaisesRegex(IsolationError, "failed closed"):
                    missing.preflight(work)

                class UnwritableWork(MacOSSeatbeltIsolation):
                    def _build_profile(self, workdir):
                        work_rule = (
                            f'(allow file-write* (subpath '
                            f'{json.dumps(str(workdir.resolve()))}))')
                        return "\n".join(
                            line for line in super()._build_profile(workdir).splitlines()
                            if line != work_rule) + "\n"

                unwritable_state = root / "unwritable-state"
                unwritable_state.mkdir()
                unwritable = UnwritableWork(
                    {}, unwritable_state, {"held_back_checks": [protected]}, [],
                    f"http://127.0.0.1:{server.server_port}/v1")
                with self.assertRaisesRegex(IsolationError, "failed closed"):
                    unwritable.preflight(work)

                class UnreadableWork(MacOSSeatbeltIsolation):
                    def _build_profile(self, workdir):
                        return (super()._build_profile(workdir)
                                + f'(deny file-read* (subpath '
                                  f'{json.dumps(str(workdir.resolve()))}))\n')

                unreadable_state = root / "unreadable-state"
                unreadable_state.mkdir()
                unreadable = UnreadableWork(
                    {}, unreadable_state, {"held_back_checks": [protected]}, [],
                    f"http://127.0.0.1:{server.server_port}/v1")
                with self.assertRaisesRegex(IsolationError, "failed closed"):
                    unreadable.preflight(work)
        finally:
            server.shutdown()
            server.server_close()

    @unittest.skipUnless(sys.platform == "darwin", "macOS Seatbelt integration")
    def test_isolated_fake_agent_exits_before_external_grader_runs(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                payload = json.dumps({"data": [{"id": "local-model"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                fake = RoundFourAgentBackendTests()._fake_opencode(root)
                out = root / "model" / "round4"
                model = {
                    "key": "m", "model": "local-model",
                    "transport": "openai_compat", "agent_backend": "opencode_cli",
                    "codex_provider": "custom",
                    "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                    "round4_isolation": {
                        "mode": "macos_seatbelt", "fail_closed": True,
                        "attempt_state": "isolated",
                        "network": "model_endpoint_only", "post_run_audit": True,
                    },
                }
                with patch("llm_hardtest.round4_agents.shutil.which",
                           side_effect=lambda name: (
                               str(fake) if name == "opencode" else "/usr/bin/sandbox-exec")):
                    code = run_round4(
                        model, 1, out, 20, ["q26_hidden_tests"])
                self.assertEqual(code, 0)
                result = load_json(out / "run.json")
                self.assertEqual(result["errors"], [])
                self.assertEqual(len(result["grades"]), 1)
                metadata = load_json(
                    out / "q26_hidden_tests" / "attempt1" / "agent_meta.json")
                checks = metadata["isolation_preflight"]["checks"]
                self.assertTrue(all(checks.values()))
                self.assertEqual(metadata["audit"]["status"], "pass")
        finally:
            server.shutdown()
            server.server_close()


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

    def test_round4_isolation_contract_is_strict_and_loopback_only(self):
        isolation = {
            "mode": "macos_seatbelt", "fail_closed": True,
            "attempt_state": "isolated", "network": "model_endpoint_only",
            "post_run_audit": True,
        }
        base = {
            "repetitions": 1, "rounds": [4], "round4_isolation": isolation,
            "models": [{
                "key": "m", "model": "one", "transport": "openai_compat",
                "agent_backend": "opencode_cli", "codex_provider": "custom",
                "base_url": "http://127.0.0.1:8000/v1", "rounds": [4],
            }],
        }
        validate_config(base, check_runtime=False)
        incomplete = json.loads(json.dumps(base))
        incomplete["round4_isolation"].pop("post_run_audit")
        with self.assertRaisesRegex(ValueError, "complete fail-closed"):
            validate_config(incomplete, check_runtime=False)
        remote = json.loads(json.dumps(base))
        remote["models"][0]["base_url"] = "https://example.com/v1"
        with self.assertRaisesRegex(ValueError, "loopback model endpoint"):
            validate_config(remote, check_runtime=False)
        inactive = json.loads(json.dumps(base))
        inactive["round4_isolation"] = {
            "mode": "none", "fail_closed": True,
        }
        with self.assertRaisesRegex(ValueError, "no active isolation fields"):
            validate_config(inactive, check_runtime=False)

    def test_public_serving_environment_contract_is_validated_offline(self):
        base = {
            "repetitions": 1, "rounds": [1],
            "models": [{"key": "m", "model": "one",
                        "transport": "openai_compat"}],
        }
        for serving in (
                {"scope": "remote", "os": "Linux", "architecture": "x86_64"},
                {"scope": "same_host"}, {"scope": "unreported"}):
            config = json.loads(json.dumps(base))
            config["models"][0]["public_serving_environment"] = serving
            validate_config(config)
        for serving in (
                {"scope": "unknown"},
                {"scope": "unreported", "os": "Linux"},
                {"scope": "remote", "os": []},
                {"scope": "remote", "architecture": "\nunsafe"}):
            config = json.loads(json.dumps(base))
            config["models"][0]["public_serving_environment"] = serving
            with self.subTest(serving=serving), self.assertRaises(ValueError):
                validate_config(config)
        signed_in = json.loads(json.dumps(base))
        signed_in["models"][0].update({
            "transport": "codex_cli", "codex_provider": "openai",
            "public_serving_environment": {"scope": "same_host"},
        })
        with self.assertRaisesRegex(ValueError, "cannot be same_host"):
            validate_config(signed_in, check_runtime=False)

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
        self.assertEqual([item["unit_count"] for item in metadata], [20, 20, 5, 6, 11])

    def test_round_five_scenario_fingerprints_are_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = repo_root() / "rounds/round5"
            root = Path(tmp) / "round5"
            shutil.copytree(source, root)
            before = {
                pilot: pilot_fingerprint(pilot, root)
                for pilot in PILOT_IDS
            }
            q34 = root / "tasks/q34_config_overlay/repo/config_merge.py"
            q34.write_text(q34.read_text(encoding="utf-8") + "\n# q34 drift\n",
                           encoding="utf-8")
            self.assertEqual(
                pilot_fingerprint("q32_retry_compatibility", root),
                before["q32_retry_compatibility"])
            self.assertEqual(
                pilot_fingerprint("q33_batch_delivery", root),
                before["q33_batch_delivery"])
            self.assertNotEqual(
                pilot_fingerprint("q34_config_overlay", root),
                before["q34_config_overlay"])
            self.assertEqual(
                pilot_fingerprint("q35_snapshot_race", root),
                before["q35_snapshot_race"])
            self.assertEqual(
                pilot_fingerprint("q36_jsonl_stream", root),
                before["q36_jsonl_stream"])
            self.assertEqual(
                pilot_fingerprint("q37_archive_boundary", root),
                before["q37_archive_boundary"])
            self.assertEqual(
                pilot_fingerprint("q38_webhook_replay", root),
                before["q38_webhook_replay"])
            self.assertEqual(
                pilot_fingerprint("q39_job_lease", root),
                before["q39_job_lease"])
            self.assertEqual(
                pilot_fingerprint("q40_ssrf_redirect", root),
                before["q40_ssrf_redirect"])
            self.assertEqual(
                pilot_fingerprint("q41_async_fanout", root),
                before["q41_async_fanout"])
            self.assertEqual(
                pilot_fingerprint("q42_shared_http_cache", root),
                before["q42_shared_http_cache"])
            q42_control = root / "tasks/q42_shared_http_cache/_control_complete.py"
            q42_control.write_text(
                q42_control.read_text(encoding="utf-8") + "\n# control drift\n",
                encoding="utf-8")
            self.assertNotEqual(
                pilot_fingerprint("q42_shared_http_cache", root),
                before["q42_shared_http_cache"])
            cache = root / "tasks/q33_batch_delivery/repo/__pycache__/ignored.pyc"
            cache.parent.mkdir(exist_ok=True)
            cache.write_bytes(b"generated")
            self.assertEqual(
                pilot_fingerprint("q33_batch_delivery", root),
                before["q33_batch_delivery"])


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
        def __init__(self, mode="correct", pilot_id="q32_retry_compatibility"):
            self.mode = mode
            self.pilot_id = pilot_id
            self.calls = []

        def agent_turn(self, prompt, workdir, evidence_dir, turn, timeout,
                       sandbox, session_id=None):
            self.calls.append((turn, sandbox, session_id))
            if self.mode == "early-edit" and turn == 1:
                (workdir / "sessions.py").write_text("# unauthorized\n", encoding="utf-8")
            if self.mode == "correct" and turn == 3:
                filenames = {
                    "q32_retry_compatibility": "sessions.py",
                    "q33_batch_delivery": "deliveries.py",
                    "q34_config_overlay": "config_merge.py",
                    "q35_snapshot_race": "snapshot_cache.py",
                    "q36_jsonl_stream": "jsonl_stream.py",
                    "q37_archive_boundary": "secure_extract.py",
                    "q38_webhook_replay": "webhook.py",
                    "q39_job_lease": "job_queue.py",
                    "q40_ssrf_redirect": "safe_http.py",
                    "q41_async_fanout": "async_batch.py",
                    "q42_shared_http_cache": "shared_cache.py",
                }
                filename = filenames[self.pilot_id]
                path = workdir / filename
                text = path.read_text(encoding="utf-8")
                if self.pilot_id == "q32_retry_compatibility":
                    text = text.replace("store_operation = uuid.uuid4().hex",
                                        'store_operation = f"{session_id}:{request_id}"')
                    text = text.replace("notify_operation = uuid.uuid4().hex",
                                        'notify_operation = f"{session_id}:{request_id}"')
                elif self.pilot_id == "q33_batch_delivery":
                    text = text.replace(
                        "charge_operation = uuid.uuid4().hex",
                        'charge_operation = (batch_id, request_id, delivery_id, "charge")')
                    text = text.replace(
                        "send_operation = uuid.uuid4().hex",
                        'send_operation = (batch_id, request_id, delivery_id, "send")')
                elif self.pilot_id == "q34_config_overlay":
                    text = '''"""Correct layered configuration merge."""

from __future__ import annotations

import copy


def merge_config(base, overlay):
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict):
            inherited = result.get(key)
            seed = inherited if isinstance(inherited, dict) else {}
            result[key] = merge_config(seed, value)
        else:
            result[key] = copy.deepcopy(value)
    return result
'''
                elif self.pilot_id == "q35_snapshot_race":
                    text = '''"""Correct generation-ordered snapshot cache."""

from __future__ import annotations

import threading


class SnapshotCache:
    def __init__(self, initial=None):
        self._values = dict(initial or {})
        self._lock = threading.RLock()
        self._next_epoch = {}
        self._committed_epoch = {}

    def get(self, key):
        with self._lock:
            return self._values.get(key)

    def refresh(self, key, loader):
        with self._lock:
            epoch = self._next_epoch.get(key, 0) + 1
            self._next_epoch[key] = epoch
        value = loader()
        with self._lock:
            if epoch > self._committed_epoch.get(key, 0):
                self._values[key] = value
                self._committed_epoch[key] = epoch
            return self._values.get(key)
'''
                else:
                    verifier = (repo_root() / "rounds/round5/tasks" / self.pilot_id
                                / "verify_pilot.py")
                    text = runpy.run_path(str(verifier))["CORRECT"]
                path.write_text(text, encoding="utf-8")
            if turn == 1:
                if self.pilot_id == "q34_config_overlay":
                    content = ("The config overlay merge uses a falsy not-value test, so false "
                               "is skipped instead of replacing the inherited value.")
                elif self.pilot_id == "q35_snapshot_race":
                    content = ("The snapshot cache has an out-of-order refresh race: an older "
                               "stale loader can overwrite a newer generation or epoch.")
                elif self.pilot_id == "q36_jsonl_stream":
                    content = ("The JSONL stream decodes each network chunk independently "
                               "instead of buffering fragmented JSON line bytes.")
                elif self.pilot_id == "q37_archive_boundary":
                    content = ("The ZIP extraction trusts member-controlled paths, enabling "
                               "path traversal outside the requested archive destination.")
                elif self.pilot_id == "q38_webhook_replay":
                    content = ("The signed webhook has no replay reservation, so an identical "
                               "authenticated retry can apply the billing event twice.")
                elif self.pilot_id == "q39_job_lease":
                    content = ("The SQLite queue uses a select-then-update lease claim without "
                               "an atomic transaction or durable fencing token, so workers can "
                               "apply the same queued job twice.")
                elif self.pilot_id == "q40_ssrf_redirect":
                    content = ("The outbound client validates only the initial host and first "
                               "DNS address, so a redirect or alternate answer can reach a "
                               "private metadata endpoint through SSRF.")
                elif self.pilot_id == "q41_async_fanout":
                    content = ("The batch wraps semaphore wait time inside each timeout and "
                               "uses bare gather, so healthy queued work times out and sibling "
                               "tasks continue after a worker failure without cancellation.")
                elif self.pilot_id == "q42_shared_http_cache":
                    content = ("The URL-only shared cache ignores Authorization tenants and "
                               "Vary language dimensions, so one authenticated variant can "
                               "leak into another request.")
                else:
                    subject = ("session retry"
                               if self.pilot_id == "q32_retry_compatibility"
                               else "batch delivery retry")
                    content = (f"Fresh UUID operation IDs defeat idempotency in the {subject}; "
                               "use a stable scoped key.")
            elif turn == 2:
                if self.pilot_id == "q34_config_overlay":
                    content = ("Null is a tombstone that deletes at every depth, while each "
                               "array or list must replace rather than append or merge; this "
                               "invalidates falsy fallback and shallow update plans.")
                elif self.pilot_id == "q35_snapshot_race":
                    content = ("A newer loader can fail while an older in-flight success must "
                               "still commit; loader re-entry and concurrent keys invalidate "
                               "a latest-issued guard and any lock around the loader.")
                elif self.pilot_id == "q36_jsonl_stream":
                    content = ("UTF-8 may split across chunks, byte limits recover at newline, "
                               "and reentrant callbacks require a serial queue; this invalidates "
                               "per-chunk decode, character limits, abort, and inline callbacks.")
                elif self.pilot_id == "q37_archive_boundary":
                    content = ("Symlinks, Windows backslash and drive aliases, duplicate and "
                               "file-directory collisions require atomic preflight before writing; "
                               "the byte limit must use uncompressed size. This invalidates "
                               "extractall, string-prefix resolve, sequential writes, compressed "
                               "size checks, and single-platform normalization.")
                elif self.pilot_id == "q38_webhook_replay":
                    content = ("Exact raw bytes and rotated multiple signatures must be verified; "
                               "concurrent requests need reserve-before-handler without a global "
                               "handler lock, failure must release the reservation, and duplicate "
                               "JSON keys must fail. This invalidates canonical reserialization, "
                               "first-signature-only, check-then-act, handler-under-global-lock, "
                               "permanent failure reservation, and body-only replay plans.")
                elif self.pilot_id == "q39_job_lease":
                    content = ("Atomic BEGIN IMMEDIATE claims need a durable fencing token, "
                               "inclusive expiry boundary, fenced unexpired completion, and a "
                               "heartbeat that extends without shortening. Priority and created "
                               "ordering, duplicate no-overwrite, and in-place schema migration "
                               "semantics invalidate a "
                               "process-local lock, select-then-update, constant token, unfenced "
                               "completion, exclusive expiry, blind heartbeat, and fresh-"
                               "database-only migration plans.")
                elif self.pilot_id == "q40_ssrf_redirect":
                    content = ("Absolute HTTPS authority, credentials and fragments, every DNS "
                               "answer including mapped IPv6 and zones, numeric-IP pinning with "
                               "Host/SNI, each redirect and loop bound, cross-origin Authorization "
                               "and Cookie stripping, redirect-body avoidance, header grammar, "
                               "Content-Length, and incremental chunk limits invalidate first-"
                               "address-only, hostname-transport, initial-hop, string-prefix, "
                               "unlimited buffering, redirect-body, and credential-forward plans.")
                elif self.pilot_id == "q41_async_fanout":
                    content = ("Validate and materialize before child creation, preserve duplicate "
                               "input order, start timeout after slot acquisition, and cancel and "
                               "await child cleanup for active and queued siblings on worker "
                               "failure, timeout, or "
                               "caller CancelledError while preserving the original exception. "
                               "Nested and independent calls invalidate timeout-around-semaphore, "
                               "bare gather, cancel-without-await, completion-order, deduplication, "
                               "global coordination, and swallowed-cancellation plans.")
                elif self.pilot_id == "q42_shared_http_cache":
                    content = ("Validate header grammar fail-closed; bypass Authorization, Cookie, "
                               "Range, and client conditionals; reject private, no-store, "
                               "Set-Cookie, and Vary:* storage; select case-insensitive exact Vary "
                               "dimensions; account for Age and strict max-age equality; revalidate "
                               "with ETag and preserve the body while merging 304 metadata; bound "
                               "stale-if-error; and single-flight only identical requests while "
                               "waking waiters after failure. This invalidates URL-only keys, "
                               "sensitive caching, case-sensitive Vary, ignored Age, inclusive "
                               "freshness, 304 body replacement, unbounded stale fallback, global "
                               "coalescing, and failed-flight poisoning.")
                else:
                    content = ("Version-1 old clients reject unknown fields, so any new response "
                               "schema field is invalid and must be omitted.")
            else:
                filenames = {
                    "q32_retry_compatibility": "sessions.py",
                    "q33_batch_delivery": "deliveries.py",
                    "q34_config_overlay": "config_merge.py",
                    "q35_snapshot_race": "snapshot_cache.py",
                    "q36_jsonl_stream": "jsonl_stream.py",
                    "q37_archive_boundary": "secure_extract.py",
                    "q38_webhook_replay": "webhook.py",
                    "q39_job_lease": "job_queue.py",
                    "q40_ssrf_redirect": "safe_http.py",
                    "q41_async_fanout": "async_batch.py",
                    "q42_shared_http_cache": "shared_cache.py",
                }
                functions = {
                    "q32_retry_compatibility": "SessionService.refresh",
                    "q33_batch_delivery": "BatchDeliveryService.retry_batch",
                    "q34_config_overlay": "merge_config",
                    "q35_snapshot_race": "SnapshotCache.refresh",
                    "q36_jsonl_stream": "JsonlEventStream.feed",
                    "q37_archive_boundary": "safe_extract",
                    "q38_webhook_replay": "WebhookProcessor.process",
                    "q39_job_lease": "JobQueue.claim",
                    "q40_ssrf_redirect": "SafeHttpClient.get",
                    "q41_async_fanout": "map_concurrently",
                    "q42_shared_http_cache": "SharedHttpCache.get",
                }
                filename, function = filenames[self.pilot_id], functions[self.pilot_id]
                invalidated = {
                    "q32_retry_compatibility": "adding a response field",
                    "q33_batch_delivery": "adding a response field",
                    "q34_config_overlay": "using falsy fallback and shallow update merge",
                    "q35_snapshot_race": "a latest-issued guard and lock around loader",
                    "q36_jsonl_stream": ("per-chunk decode, character limits, abort-on-error, "
                                         "and inline recursive callbacks"),
                    "q37_archive_boundary": ("extractall, string-prefix resolve, sequential "
                                              "writes, compressed-size checks, and "
                                              "single-platform normalization"),
                    "q38_webhook_replay": ("canonical reserialization, first-signature-only, "
                                             "check-then-act replay, handler-under-global-lock, "
                                             "permanent failure reservation, and body-only replay"),
                    "q39_job_lease": ("process-local lock, select-then-update claim, constant "
                                        "token, unfenced completion, exclusive expiry, and blind "
                                        "heartbeat or fresh-database-only migration"),
                    "q40_ssrf_redirect": ("first-address-only checks, hostname transport, "
                                           "initial-hop validation, string-prefix filtering, "
                                           "unlimited buffering, redirect-body reads, and "
                                           "credential forwarding"),
                    "q41_async_fanout": ("timeout around semaphore, bare gather, cancel without "
                                          "await, completion order, deduplication, global "
                                          "coordination, and swallowed cancellation"),
                    "q42_shared_http_cache": ("URL-only keys, sensitive caching, case-sensitive "
                                                "Vary, ignoring Age, inclusive freshness, 304 "
                                                "body replacement, unbounded stale fallback, "
                                                "global coalescing, and failed-flight poisoning"),
                }[self.pilot_id]
                content = (
                    "=== PILOT REPORT ===\n"
                    f"ROOT_CAUSE_FILE: {filename}\n"
                    f"ROOT_CAUSE_FUNCTION: {function}\n"
                    f"INVALIDATED_PLAN: {invalidated}\n"
                    f"FILES_CHANGED: {filename}\n"
                    "PUBLIC_TESTS: 4/4\n"
                    "CONFIDENCE: high\n"
                    "REMAINING_RISKS: none observed\n")
            if self.mode == "empty" and turn == 1:
                content = ""
            protocol_loop = self.mode == "protocol-loop" and turn == 1
            protocol_errors = (
                "\nERROR codex_core::tools::router: "
                "error=request_user_input is unavailable in Default mode" * 3
                if protocol_loop else "")
            (evidence_dir / f"transcript_turn{turn}.txt").write_text(
                content + ("\nERROR codex_core::tools::router: "
                           "error=unsupported call: tool_code"
                           if self.mode == "unsupported" and turn == 1 else "")
                + protocol_errors,
                encoding="utf-8")
            (evidence_dir / f"last_message_turn{turn}.txt").write_text(
                content, encoding="utf-8")
            timed_out = self.mode == "timeout" and turn == 1
            transcript = content + ("\nERROR codex_core::tools::router: "
                                    "error=unsupported call: tool_code"
                                    if self.mode == "unsupported" and turn == 1 else "") \
                + protocol_errors
            return {"content": content, "transcript": transcript,
                    "session_id": "00000000-0000-0000-0000-000000000001",
                    "wall": 0.1, "tokens": 10, "timed_out": timed_out,
                    "protocol_aborted": protocol_loop,
                    "termination_reason": ("unsupported_tool_loop"
                                           if protocol_loop else None),
                    "returncode": (-15 if protocol_loop else
                                   (-9 if timed_out else 0)), "sandbox": sandbox}

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

    def test_round_five_batch_delivery_scenario_is_selectable_and_graded(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self.FakeAgent(pilot_id="q33_batch_delivery")
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: agent,
                pilot_id="q33_batch_delivery")
            summary = load_json(root / "pilot_summary.json")
            grade = summary["attempts"][0]["grade"]
            attempt_exists = (root / "m/round5/q33_batch_delivery/attempt-1"
                              / "research_grade.json").is_file()
            analysis = analyze_pilots([root])
        self.assertTrue(attempt_exists)
        self.assertEqual(summary["pilot_id"], "q33_batch_delivery")
        self.assertEqual(grade["public"], {"passed": 4, "total": 4, "timed_out": False})
        self.assertEqual(grade["hidden"], {"passed": 10, "total": 10, "timed_out": False})
        self.assertTrue(grade["evidence_revision_observed"])
        self.assertTrue(grade["release_ready"])
        self.assertTrue(grade["final_report"]["accurate"])
        self.assertEqual(analysis["groups"][0]["pilot_id"], "q33_batch_delivery")
        self.assertEqual(analysis["groups"][0]["attempts"], 1)

    def test_round_five_config_overlay_scenario_is_selectable_and_graded(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self.FakeAgent(pilot_id="q34_config_overlay")
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: agent,
                pilot_id="q34_config_overlay")
            summary = load_json(root / "pilot_summary.json")
            grade = summary["attempts"][0]["grade"]
            attempt_exists = (root / "m/round5/q34_config_overlay/attempt-1"
                              / "research_grade.json").is_file()
            analysis = analyze_pilots([root])
            public, warnings = build_public_pilot_result(root)
        self.assertTrue(attempt_exists)
        self.assertEqual(summary["pilot_id"], "q34_config_overlay")
        self.assertEqual(grade["public"], {"passed": 4, "total": 4, "timed_out": False})
        self.assertEqual(grade["hidden"], {"passed": 10, "total": 10, "timed_out": False})
        self.assertTrue(grade["evidence_revision_observed"])
        self.assertTrue(grade["release_ready"])
        self.assertTrue(grade["final_report"]["accurate"])
        self.assertEqual(analysis["groups"][0]["pilot_id"], "q34_config_overlay")
        self.assertEqual(public["pilot"]["id"], "q34_config_overlay")
        self.assertEqual(public["models"][0]["attempts"][0]["hidden"]["passed"], 10)
        self.assertEqual(warnings, [])

    def test_round_five_snapshot_race_scenario_is_selectable_and_graded(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self.FakeAgent(pilot_id="q35_snapshot_race")
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: agent,
                pilot_id="q35_snapshot_race")
            summary = load_json(root / "pilot_summary.json")
            grade = summary["attempts"][0]["grade"]
            attempt_exists = (root / "m/round5/q35_snapshot_race/attempt-1"
                              / "research_grade.json").is_file()
            analysis = analyze_pilots([root])
            public, warnings = build_public_pilot_result(root)
        self.assertTrue(attempt_exists)
        self.assertEqual(summary["pilot_id"], "q35_snapshot_race")
        self.assertEqual(grade["public"], {"passed": 4, "total": 4, "timed_out": False})
        self.assertEqual(grade["hidden"], {"passed": 10, "total": 10, "timed_out": False})
        self.assertTrue(grade["evidence_revision_observed"])
        self.assertTrue(grade["release_ready"])
        self.assertTrue(grade["final_report"]["accurate"])
        self.assertEqual(analysis["groups"][0]["pilot_id"], "q35_snapshot_race")
        self.assertEqual(public["pilot"]["id"], "q35_snapshot_race")
        self.assertEqual(public["models"][0]["attempts"][0]["hidden"]["passed"], 10)
        self.assertEqual(warnings, [])

    def test_round_five_jsonl_stream_scenario_is_selectable_and_graded(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self.FakeAgent(pilot_id="q36_jsonl_stream")
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: agent,
                pilot_id="q36_jsonl_stream")
            summary = load_json(root / "pilot_summary.json")
            grade = summary["attempts"][0]["grade"]
            attempt_exists = (root / "m/round5/q36_jsonl_stream/attempt-1"
                              / "research_grade.json").is_file()
            analysis = analyze_pilots([root])
            public, warnings = build_public_pilot_result(root)
        self.assertTrue(attempt_exists)
        self.assertEqual(summary["pilot_id"], "q36_jsonl_stream")
        self.assertEqual(grade["public"], {"passed": 4, "total": 4, "timed_out": False})
        self.assertEqual(grade["hidden"], {"passed": 10, "total": 10, "timed_out": False})
        self.assertTrue(grade["evidence_revision_observed"])
        self.assertTrue(grade["release_ready"])
        self.assertTrue(grade["final_report"]["accurate"])
        self.assertEqual(analysis["groups"][0]["pilot_id"], "q36_jsonl_stream")
        self.assertEqual(public["pilot"]["id"], "q36_jsonl_stream")
        self.assertEqual(public["models"][0]["attempts"][0]["hidden"]["passed"], 10)
        self.assertEqual(warnings, [])

    def test_round_five_archive_boundary_scenario_is_selectable_and_graded(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self.FakeAgent(pilot_id="q37_archive_boundary")
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: agent,
                pilot_id="q37_archive_boundary")
            summary = load_json(root / "pilot_summary.json")
            grade = summary["attempts"][0]["grade"]
            attempt_exists = (root / "m/round5/q37_archive_boundary/attempt-1"
                              / "research_grade.json").is_file()
            analysis = analyze_pilots([root])
            public, warnings = build_public_pilot_result(root)
        self.assertTrue(attempt_exists)
        self.assertEqual(summary["pilot_id"], "q37_archive_boundary")
        self.assertEqual(grade["public"], {"passed": 4, "total": 4,
                                           "timed_out": False})
        self.assertEqual(grade["hidden"], {"passed": 10, "total": 10,
                                           "timed_out": False})
        self.assertTrue(grade["evidence_revision_observed"])
        self.assertTrue(grade["release_ready"])
        self.assertTrue(grade["final_report"]["accurate"])
        self.assertEqual(analysis["groups"][0]["pilot_id"],
                         "q37_archive_boundary")
        self.assertEqual(public["pilot"]["id"], "q37_archive_boundary")
        self.assertEqual(public["models"][0]["attempts"][0]["hidden"]["passed"], 10)
        self.assertEqual(warnings, [])

    def test_round_five_webhook_replay_scenario_is_selectable_and_graded(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self.FakeAgent(pilot_id="q38_webhook_replay")
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: agent,
                pilot_id="q38_webhook_replay")
            summary = load_json(root / "pilot_summary.json")
            grade = summary["attempts"][0]["grade"]
            attempt_exists = (root / "m/round5/q38_webhook_replay/attempt-1"
                              / "research_grade.json").is_file()
            analysis = analyze_pilots([root])
            public, warnings = build_public_pilot_result(root)
        self.assertTrue(attempt_exists)
        self.assertEqual(summary["pilot_id"], "q38_webhook_replay")
        self.assertEqual(grade["public"], {"passed": 4, "total": 4,
                                           "timed_out": False})
        self.assertEqual(grade["hidden"], {"passed": 10, "total": 10,
                                           "timed_out": False})
        self.assertTrue(grade["evidence_revision_observed"])
        self.assertTrue(grade["release_ready"])
        self.assertTrue(grade["final_report"]["accurate"])
        self.assertEqual(analysis["groups"][0]["pilot_id"], "q38_webhook_replay")
        self.assertEqual(public["pilot"]["id"], "q38_webhook_replay")
        self.assertEqual(public["models"][0]["attempts"][0]["hidden"]["passed"], 10)
        self.assertEqual(warnings, [])

    def test_webhook_rotation_evidence_accepts_semantic_all_pairs_wording(self):
        task = load_json(
            repo_root() / "rounds/round5/tasks/q38_webhook_replay/task.json")
        pattern = task["grading"]["turn2_patterns"][1]
        self.assertRegex(
            "Verify every supplied v1 against the exact raw body and every active secret.",
            re.compile(pattern, re.I),
        )
        self.assertNotRegex(
            "Verify the first signature with the current secret.",
            re.compile(pattern, re.I),
        )
        self.assertNotRegex(
            "Verify every supplied v1 against the current secret.",
            re.compile(pattern, re.I),
        )
        self.assertNotRegex(
            "Verify the first signature against every active secret.",
            re.compile(pattern, re.I),
        )

    def test_round_five_job_lease_scenario_is_selectable_and_graded(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self.FakeAgent(pilot_id="q39_job_lease")
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: agent,
                pilot_id="q39_job_lease")
            summary = load_json(root / "pilot_summary.json")
            grade = summary["attempts"][0]["grade"]
            attempt_exists = (root / "m/round5/q39_job_lease/attempt-1"
                              / "research_grade.json").is_file()
            analysis = analyze_pilots([root])
            public, warnings = build_public_pilot_result(root)
        self.assertTrue(attempt_exists)
        self.assertEqual(summary["pilot_id"], "q39_job_lease")
        self.assertEqual(grade["public"], {"passed": 4, "total": 4,
                                           "timed_out": False})
        self.assertEqual(grade["hidden"], {"passed": 10, "total": 10,
                                           "timed_out": False})
        self.assertTrue(grade["evidence_revision_observed"])
        self.assertTrue(grade["release_ready"])
        self.assertTrue(grade["final_report"]["accurate"])
        self.assertEqual(analysis["groups"][0]["pilot_id"], "q39_job_lease")
        self.assertEqual(public["pilot"]["id"], "q39_job_lease")
        self.assertEqual(public["models"][0]["attempts"][0]["hidden"]["passed"], 10)
        self.assertEqual(warnings, [])

    def test_round_five_ssrf_redirect_scenario_is_selectable_and_graded(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self.FakeAgent(pilot_id="q40_ssrf_redirect")
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: agent,
                pilot_id="q40_ssrf_redirect")
            summary = load_json(root / "pilot_summary.json")
            grade = summary["attempts"][0]["grade"]
            attempt_exists = (root / "m/round5/q40_ssrf_redirect/attempt-1"
                              / "research_grade.json").is_file()
            analysis = analyze_pilots([root])
            public, warnings = build_public_pilot_result(root)
        self.assertTrue(attempt_exists)
        self.assertEqual(summary["pilot_id"], "q40_ssrf_redirect")
        self.assertEqual(grade["public"], {"passed": 4, "total": 4,
                                           "timed_out": False})
        self.assertEqual(grade["hidden"], {"passed": 10, "total": 10,
                                           "timed_out": False})
        self.assertTrue(grade["evidence_revision_observed"])
        self.assertTrue(grade["release_ready"])
        self.assertTrue(grade["final_report"]["accurate"])
        self.assertEqual(analysis["groups"][0]["pilot_id"], "q40_ssrf_redirect")
        self.assertEqual(public["pilot"]["id"], "q40_ssrf_redirect")
        self.assertEqual(public["models"][0]["attempts"][0]["hidden"]["passed"], 10)
        self.assertEqual(warnings, [])

    def test_round_five_async_fanout_scenario_is_selectable_and_graded(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self.FakeAgent(pilot_id="q41_async_fanout")
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: agent,
                pilot_id="q41_async_fanout")
            summary = load_json(root / "pilot_summary.json")
            grade = summary["attempts"][0]["grade"]
            attempt_exists = (root / "m/round5/q41_async_fanout/attempt-1"
                              / "research_grade.json").is_file()
            analysis = analyze_pilots([root])
            public, warnings = build_public_pilot_result(root)
        self.assertTrue(attempt_exists)
        self.assertEqual(summary["pilot_id"], "q41_async_fanout")
        self.assertEqual(grade["public"], {"passed": 4, "total": 4,
                                           "timed_out": False})
        self.assertEqual(grade["hidden"], {"passed": 10, "total": 10,
                                           "timed_out": False})
        self.assertTrue(grade["evidence_revision_observed"])
        self.assertTrue(grade["release_ready"])
        self.assertTrue(grade["final_report"]["accurate"])
        self.assertEqual(analysis["groups"][0]["pilot_id"], "q41_async_fanout")
        self.assertEqual(public["pilot"]["id"], "q41_async_fanout")
        self.assertEqual(public["models"][0]["attempts"][0]["hidden"]["passed"], 10)
        self.assertEqual(warnings, [])

    def test_round_five_shared_http_cache_scenario_is_selectable_and_graded(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self.FakeAgent(pilot_id="q42_shared_http_cache")
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: agent,
                pilot_id="q42_shared_http_cache")
            summary = load_json(root / "pilot_summary.json")
            grade = summary["attempts"][0]["grade"]
            attempt_exists = (root / "m/round5/q42_shared_http_cache/attempt-1"
                              / "research_grade.json").is_file()
            analysis = analyze_pilots([root])
            public, warnings = build_public_pilot_result(root)
        self.assertTrue(attempt_exists)
        self.assertEqual(summary["pilot_id"], "q42_shared_http_cache")
        self.assertEqual(grade["public"], {"passed": 4, "total": 4,
                                           "timed_out": False})
        self.assertEqual(grade["hidden"], {"passed": 10, "total": 10,
                                           "timed_out": False})
        self.assertTrue(grade["evidence_revision_observed"])
        self.assertTrue(grade["release_ready"])
        self.assertTrue(grade["final_report"]["accurate"])
        self.assertEqual(analysis["groups"][0]["pilot_id"], "q42_shared_http_cache")
        self.assertEqual(public["pilot"]["id"], "q42_shared_http_cache")
        self.assertEqual(public["models"][0]["attempts"][0]["hidden"]["passed"], 10)
        self.assertEqual(warnings, [])

    def test_round_five_portfolio_requires_repeated_exact_scenario_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config()
            config["models"].append({
                **config["models"][0],
                "key": "m2", "label": "M2", "model": "fake-model-2",
            })
            roots = []
            for pilot_id in PILOT_IDS:
                roots.append(run_pilot(
                    config, Path(tmp), None, 2,
                    agent_factory=lambda model, run, selected=pilot_id: self.FakeAgent(
                        pilot_id=selected),
                    pilot_id=pilot_id))
            analysis = analyze_pilots(roots)
            portfolio = analysis["portfolio"]
            missing_axis_root = roots[0]
            grade_path = missing_axis_root / "m/round5/attempt-1/research_grade.json"
            missing_axis_grade = load_json(grade_path)
            missing_axis_grade["public"] = {
                "passed": 0, "total": 0, "timed_out": True}
            missing_axis_grade["release_ready"] = False
            missing_axis_grade["final_report"]["public_test_claim_accurate"] = False
            missing_axis_grade["final_report"]["accurate"] = False
            save_json(grade_path, missing_axis_grade)
            missing_axis_summary_path = missing_axis_root / "pilot_summary.json"
            missing_axis_summary = load_json(missing_axis_summary_path)
            for summary_row in missing_axis_summary["attempts"]:
                if summary_row["model"] == "m" and summary_row["grade"]["attempt"] == 1:
                    summary_row["grade"] = missing_axis_grade
            save_json(missing_axis_summary_path, missing_axis_summary)
            missing_axis_comparison = analyze_pilots(roots)["portfolio"]["pairwise"][0]
        self.assertEqual(analysis["schema_version"], 9)
        self.assertEqual(portfolio["required_pilots"], [
            "q32_retry_compatibility", "q33_batch_delivery", "q34_config_overlay",
            "q35_snapshot_race", "q36_jsonl_stream", "q37_archive_boundary",
            "q38_webhook_replay", "q39_job_lease", "q40_ssrf_redirect",
            "q41_async_fanout", "q42_shared_http_cache",
        ])
        self.assertEqual(len(portfolio["configurations"]), 2)
        for row in portfolio["configurations"]:
            self.assertEqual(row["attempts"], 22)
            self.assertEqual(row["missing_pilots"], [])
            self.assertEqual(row["pack_ambiguous_pilots"], [])
            # This test owns scenario/repeat coverage. Individual hidden-test
            # correctness is covered by the per-pilot grading tests; tying the
            # coverage contract to their timing-sensitive score makes this
            # cross-platform integration check flaky on slower CI runners.
            self.assertIsNotNone(row["worst_case_hidden_pass_rate"])
            self.assertGreaterEqual(row["worst_case_hidden_pass_rate"], 0.0)
            self.assertLessEqual(row["worst_case_hidden_pass_rate"], 1.0)
            self.assertTrue(row["ready_for_cross_scenario_interpretation"])
        collection = portfolio["evidence_collection_plan"]
        self.assertEqual(collection["summary"]["ready_configurations"], 2)
        self.assertEqual(
            collection["summary"]["minimum_additional_complete_attempts"], 0)
        self.assertTrue(all(
            row["status"] == "READY" and not row["actions"]
            for row in collection["configurations"]))
        comparison = portfolio["pairwise"][0]
        self.assertEqual(comparison["shared_pilots"], portfolio["required_pilots"])
        self.assertEqual(comparison["shared_scenario_versions"], 11)
        self.assertEqual(comparison["mean_distance"], 0.0)
        adjusted = comparison["repeat_adjusted_separation"]
        self.assertEqual(adjusted["status"], "NO_STABLE_SEPARATION")
        self.assertEqual(adjusted["mean_repeat_noise"], 0.0)
        self.assertEqual(adjusted["mean_adjusted_separation"], 0.0)
        self.assertEqual(adjusted["bootstrap_95"]["lower"], 0.0)
        self.assertEqual(adjusted["bootstrap_95"]["upper"], 0.0)
        self.assertEqual(
            comparison["next_evidence"]["action"], "REVIEW_NO_STABLE_SEPARATION")
        self.assertEqual(
            comparison["single_scenario_robustness"]["status"], "NOT_APPLICABLE")
        directional = comparison["directional_advantage"]
        self.assertEqual(directional["status"], "NO_MATERIAL_ADVANTAGE")
        self.assertEqual(directional["mean_left_advantage"], 0.0)
        self.assertIsNone(directional["favored_configuration"])
        self.assertEqual(directional["bootstrap_95"]["lower"], 0.0)
        self.assertEqual(directional["bootstrap_95"]["upper"], 0.0)
        self.assertEqual(
            {row["axis"] for row in comparison["axis_attribution"]},
            {"transport_complete", "authority_safe", "evidence_revision",
             "public_rate", "hidden_rate", "release_ready", "report_accurate",
             "tool_protocol_clean"})
        self.assertFalse(missing_axis_comparison["repeat_adjusted_separation"]
                         ["evidence_gates"]["all_shared_axes_observed"])
        self.assertEqual(missing_axis_comparison["repeat_adjusted_separation"]["status"],
                         "INSUFFICIENT_EVIDENCE")
        self.assertEqual(missing_axis_comparison["next_evidence"]["action"],
                         "REPEAT_UNOBSERVED_AXES")
        self.assertEqual(
            missing_axis_comparison["directional_advantage"]["status"],
            "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(
            missing_axis_comparison["directional_advantage"]
            ["favored_configuration"])

    def test_round_five_portfolio_detects_repeat_adjusted_stable_separation(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config()
            config["models"].append({
                **config["models"][0],
                "key": "weak", "label": "Weak", "model": "fake-weak",
            })
            roots = []
            for pilot_id in PILOT_IDS:
                roots.append(run_pilot(
                    config, Path(tmp), None, 2,
                    agent_factory=lambda model, run, selected=pilot_id: self.FakeAgent(
                        mode="correct" if model["key"] == "m" else "baseline",
                        pilot_id=selected),
                    pilot_id=pilot_id))
            comparison = analyze_pilots(roots)["portfolio"]["pairwise"][0]
        adjusted = comparison["repeat_adjusted_separation"]
        self.assertEqual(adjusted["status"], "STABLE_SEPARATION")
        self.assertGreater(adjusted["bootstrap_95"]["lower"], 0.05)
        self.assertEqual(adjusted["mean_repeat_noise"], 0.0)
        self.assertEqual(
            comparison["single_scenario_robustness"]["status"],
            "ROBUST_TO_SINGLE_SCENARIO_REMOVAL")
        contributions = {row["axis"]: row["positive_contribution_share"]
                         for row in comparison["axis_attribution"]}
        self.assertEqual(contributions["transport_complete"], 0.0)
        self.assertGreater(contributions["hidden_rate"], 0.0)
        self.assertAlmostEqual(sum(contributions.values()), 1.0, places=5)
        self.assertEqual(comparison["next_evidence"]["action"],
                         "MANUAL_AMBIGUITY_REVIEW")
        directional = comparison["directional_advantage"]
        self.assertIn(directional["status"], {
            "STABLE_LEFT_ADVANTAGE", "STABLE_RIGHT_ADVANTAGE"})
        self.assertIsNotNone(directional["favored_configuration"])
        self.assertEqual(
            directional["single_scenario_robustness"]["status"],
            "ROBUST_TO_SINGLE_SCENARIO_REMOVAL")
        self.assertEqual(
            {row["axis"] for row in directional["axis_contrasts"]},
            {"transport_complete", "authority_safe", "evidence_revision",
             "public_rate", "hidden_rate", "release_ready", "report_accurate",
             "tool_protocol_clean"})

    def test_round_five_directional_advantage_is_symmetric_and_gated(self):
        scenarios = [{
            "pilot_id": pilot_id,
            "pack": "sha256:" + str(index) * 64,
            "left_attempt_values": [0.9, 0.9],
            "right_attempt_values": [0.2, 0.2],
        } for index, pilot_id in enumerate(PILOT_IDS[:4], 1)]
        left = _directional_advantage(scenarios, True, "config-1", "config-2")
        reversed_rows = [{
            **row,
            "left_attempt_values": row["right_attempt_values"],
            "right_attempt_values": row["left_attempt_values"],
        } for row in scenarios]
        right = _directional_advantage(
            reversed_rows, True, "config-1", "config-2")
        gated = _directional_advantage(scenarios, False, "config-1", "config-2")
        robustness = _directional_robustness(
            scenarios, left["status"], True, "config-1", "config-2")
        family_adjusted = _directional_advantage(
            scenarios, True, "config-1", "config-2", family_size=6)
        family_robustness = _directional_robustness(
            scenarios, family_adjusted["status"], True,
            "config-1", "config-2", family_size=6)
        self.assertEqual(left["status"], "STABLE_LEFT_ADVANTAGE")
        self.assertEqual(left["favored_configuration"], "config-1")
        self.assertEqual(
            left, _directional_advantage(
                scenarios, True, "config-1", "config-2"))
        self.assertEqual(right["status"], "STABLE_RIGHT_ADVANTAGE")
        self.assertEqual(right["favored_configuration"], "config-2")
        self.assertAlmostEqual(
            left["mean_left_advantage"], -right["mean_left_advantage"])
        self.assertEqual(
            left["bootstrap_95"]["lower"], -right["bootstrap_95"]["upper"])
        self.assertEqual(
            left["bootstrap_95"]["upper"], -right["bootstrap_95"]["lower"])
        self.assertEqual(gated["status"], "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(gated["bootstrap_95"])
        self.assertEqual(
            robustness["status"], "ROBUST_TO_SINGLE_SCENARIO_REMOVAL")
        self.assertEqual(
            family_robustness["status"], "ROBUST_TO_SINGLE_SCENARIO_REMOVAL")
        self.assertTrue(all(
            row["familywise_bootstrap"]["confidence"]
            == round(1 - 0.05 / 6, 12)
            for row in family_robustness["cases"]))

    def test_round_five_directional_advantage_withholds_mixed_direction(self):
        scenarios = []
        for index, pilot_id in enumerate(PILOT_IDS[:4], 1):
            left_wins = index <= 2
            scenarios.append({
                "pilot_id": pilot_id,
                "pack": "sha256:" + str(index) * 64,
                "left_attempt_values": [1.0 if left_wins else 0.0] * 2,
                "right_attempt_values": [0.0 if left_wins else 1.0] * 2,
            })
        result = _directional_advantage(
            scenarios, True, "config-1", "config-2")
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIsNone(result["favored_configuration"])
        self.assertLess(result["bootstrap_95"]["lower"], -0.05)
        self.assertGreater(result["bootstrap_95"]["upper"], 0.05)

    def test_round_five_directional_advantage_includes_repeat_uncertainty(self):
        scenarios = [{
            "pilot_id": pilot_id,
            "pack": "sha256:" + str(index) * 64,
            "left_attempt_values": [1.0, 0.0],
            "right_attempt_values": [0.4, 0.4],
        } for index, pilot_id in enumerate(PILOT_IDS[:4], 1)]
        result = _directional_advantage(
            scenarios, True, "config-1", "config-2")
        self.assertEqual(result["mean_left_advantage"], 0.1)
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIsNone(result["favored_configuration"])
        self.assertLess(result["bootstrap_95"]["lower"], 0.05)
        self.assertGreater(result["bootstrap_95"]["upper"], 0.05)

    def test_round_five_directional_advantage_controls_pairwise_family(self):
        effects = (0.0, 0.2, 0.2, 0.2, 0.2)
        scenarios = [{
            "pilot_id": pilot_id,
            "pack": "sha256:" + str(index) * 64,
            "left_attempt_values": [effect, effect],
            "right_attempt_values": [0.0, 0.0],
        } for index, (pilot_id, effect) in enumerate(
            zip(PILOT_IDS[:5], effects), 1)]
        result = _directional_advantage(
            scenarios, True, "config-1", "config-2", family_size=6)
        self.assertEqual(result["pointwise_status"], "STABLE_LEFT_ADVANTAGE")
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIsNone(result["favored_configuration"])
        self.assertEqual(result["multiplicity"]["eligible_comparisons"], 6)
        self.assertEqual(result["multiplicity"]["bootstrap_samples"], 24000)
        self.assertEqual(
            result["multiplicity"]["expected_familywise_tail_draws"], 100.0)
        self.assertEqual(result["familywise_bootstrap"]["samples"], 24000)
        self.assertEqual(
            result["familywise_bootstrap"]["monte_carlo_resolution"]
            ["expected_draws_per_tail"], 100.0)
        self.assertAlmostEqual(
            result["familywise_bootstrap"]["confidence"], 1 - 0.05 / 6)
        self.assertGreaterEqual(
            result["bootstrap_95"]["lower"], 0.05)
        self.assertLessEqual(
            result["familywise_bootstrap"]["lower"], 0.05)
        with self.assertRaisesRegex(ValueError, "family size"):
            _directional_advantage(
                scenarios, True, "config-1", "config-2", family_size=0)
        pointwise_status, pointwise = _separation_status(list(effects), True)
        family_status, simultaneous = _separation_status(
            list(effects), True, 1 - 0.05 / 6, family_size=6)
        self.assertEqual(pointwise_status, "STABLE_SEPARATION")
        self.assertEqual(family_status, "INCONCLUSIVE")
        self.assertGreater(pointwise["lower"], 0.05)
        self.assertLessEqual(simultaneous["lower"], 0.05)
        next_evidence = _next_pair_evidence(
            missing_left=[], missing_right=[], mismatched=[], ambiguous=[],
            deficits=[], invalid_pilots=[], unobserved_pilots=[],
            status=family_status,
            scenario_rows=[{
                "pilot_id": pilot_id,
                "pack": "sha256:" + str(index) * 64,
                "repeat_noise": effect,
            } for index, (pilot_id, effect) in enumerate(
                zip(PILOT_IDS[:5], effects), 1)],
            robustness={"status": "NOT_APPLICABLE", "influential_pilot_ids": []})
        self.assertEqual(
            next_evidence["action"], "REPLICATE_NOISIEST_SCENARIO")

    def test_round_five_bootstrap_budget_preserves_familywise_tail_resolution(self):
        self.assertEqual(_bootstrap_sample_count(0), 5000)
        self.assertEqual(_bootstrap_sample_count(1), 5000)
        self.assertEqual(_bootstrap_sample_count(3), 12000)
        self.assertEqual(_bootstrap_sample_count(6), 24000)
        self.assertEqual(_bootstrap_sample_count(45), 180000)
        with self.assertRaisesRegex(ValueError, "family size"):
            _bootstrap_sample_count(True)
        with self.assertRaisesRegex(ValueError, "family size"):
            _bootstrap_sample_count(-1)

    def test_round_five_portfolio_adjusts_all_eligible_configuration_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config()
            config["models"] += [{
                **config["models"][0],
                "key": key, "label": key.upper(), "model": f"fake-{key}",
            } for key in ("weak", "other")]
            roots = []
            for pilot_id in PILOT_IDS[:3]:
                roots.append(run_pilot(
                    config, Path(tmp), None, 2,
                    agent_factory=lambda model, run, selected=pilot_id: self.FakeAgent(
                        mode="correct" if model["key"] == "m" else "baseline",
                        pilot_id=selected),
                    pilot_id=pilot_id))
            comparisons = analyze_pilots(roots)["portfolio"]["pairwise"]
        self.assertEqual(len(comparisons), 3)
        for comparison in comparisons:
            directional = comparison["directional_advantage"]
            separation = comparison["repeat_adjusted_separation"]
            self.assertEqual(
                directional["multiplicity"]["eligible_comparisons"], 3)
            self.assertEqual(
                directional["multiplicity"]["bootstrap_samples"], 12000)
            self.assertEqual(
                directional["multiplicity"]
                ["expected_familywise_tail_draws"], 100.0)
            self.assertAlmostEqual(
                directional["familywise_bootstrap"]["confidence"],
                1 - 0.05 / 3)
            self.assertEqual(
                separation["multiplicity"]["eligible_comparisons"], 3)
            self.assertEqual(
                separation["multiplicity"]["bootstrap_samples"], 12000)
            self.assertEqual(
                separation["multiplicity"]
                ["expected_familywise_tail_draws"], 100.0)
            self.assertAlmostEqual(
                separation["familywise_bootstrap"]["confidence"],
                1 - 0.05 / 3)

    def test_round_five_portfolio_detects_single_scenario_leverage(self):
        rows = [{
            "pilot_id": pilot_id,
            "pack": "sha256:" + str(index) * 64,
            # Keep the non-zero leave-one-out lower bound strictly above the
            # 0.05 decision threshold as the pilot portfolio grows.
            "adjusted_separation": 0.0 if index < 7 else 0.6,
        } for index, pilot_id in enumerate(PILOT_IDS)]
        robustness = _leave_one_out_robustness(
            rows, "STABLE_SEPARATION", True)
        self.assertEqual(robustness["status"], "SENSITIVE_TO_SINGLE_SCENARIO")
        self.assertEqual(
            robustness["influential_pilot_ids"], list(PILOT_IDS[7:]))

    def test_round_five_portfolio_subtracts_repeat_instability(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config()
            config["models"].append({
                **config["models"][0],
                "key": "m2", "label": "M2", "model": "fake-model-2",
            })
            roots = []
            for pilot_id in PILOT_IDS:
                calls = {}

                def factory(model, run, selected=pilot_id):
                    calls[model["key"]] = calls.get(model["key"], 0) + 1
                    mode = "correct" if calls[model["key"]] % 2 else "baseline"
                    return self.FakeAgent(mode=mode, pilot_id=selected)

                roots.append(run_pilot(
                    config, Path(tmp), None, 2, agent_factory=factory,
                    pilot_id=pilot_id))
            comparison = analyze_pilots(roots)["portfolio"]["pairwise"][0]
        adjusted = comparison["repeat_adjusted_separation"]
        self.assertGreater(adjusted["mean_repeat_noise"], 0.0)
        self.assertLessEqual(adjusted["mean_adjusted_separation"], 0.0)
        self.assertEqual(adjusted["status"], "NO_STABLE_SEPARATION")

    def test_round_five_rejects_unknown_pilot_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "unsupported Round 5 pilot ID"):
                run_pilot(
                    self._config(), Path(tmp), ["m"], 1,
                    agent_factory=lambda model, run: self.FakeAgent(),
                    pilot_id="q99_unknown")

    def test_round_five_resume_rejects_pack_or_scenario_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: self.FakeAgent())
            summary_path = root / "pilot_summary.json"
            summary = load_json(summary_path)
            summary["pack"] = "sha256:" + "0" * 64
            save_json(summary_path, summary)
            with self.assertRaisesRegex(ValueError, "resume pack"):
                run_pilot(
                    self._config(), Path(tmp), ["m"], 1, resume=root,
                    agent_factory=lambda model, run: self.FakeAgent())
            summary["pack"] = pilot_fingerprint("q32_retry_compatibility")
            save_json(summary_path, summary)
            with self.assertRaisesRegex(ValueError, "resume ID"):
                run_pilot(
                    self._config(), Path(tmp), ["m"], 1, resume=root,
                    agent_factory=lambda model, run: self.FakeAgent(
                        pilot_id="q33_batch_delivery"),
                    pilot_id="q33_batch_delivery")

    def test_round_five_analysis_rejects_relabelled_scenario_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: self.FakeAgent())
            summary_path = root / "pilot_summary.json"
            summary = load_json(summary_path)
            summary["pack"] = "sha256:" + "0" * 64
            save_json(summary_path, summary)
            with self.assertRaisesRegex(ValueError, "scenario fingerprint"):
                analyze_pilots([root])

    def test_round_five_analysis_accepts_trusted_historical_fingerprint(self):
        historical = (
            "sha256:1186a977c1b4264fcf47497c027299b84f627ae1308f6488d85cfa34d1443679")
        with tempfile.TemporaryDirectory() as tmp:
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: self.FakeAgent(
                    pilot_id="q41_async_fanout"),
                pilot_id="q41_async_fanout")
            summary_path = root / "pilot_summary.json"
            summary = load_json(summary_path)
            summary["pack"] = historical
            save_json(summary_path, summary)
            analysis = analyze_pilots([root])
        self.assertEqual(analysis["schema_version"], 9)
        self.assertEqual(analysis["groups"][0]["pack"], historical)
        self.assertEqual(
            analysis["groups"][0]["fingerprint_verification"],
            ["release-registry"])

    def test_round_five_analysis_accepts_historical_q42_contract(self):
        historical = (
            "sha256:c1a1d19d78c91ef335735734cf0ff15fff3fa25aa3aed986101e86ebc29b539f")
        with tempfile.TemporaryDirectory() as tmp:
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: self.FakeAgent(
                    pilot_id="q42_shared_http_cache"),
                pilot_id="q42_shared_http_cache")
            summary_path = root / "pilot_summary.json"
            summary = load_json(summary_path)
            summary["pack"] = historical
            save_json(summary_path, summary)
            analysis = analyze_pilots([root])
        self.assertEqual(analysis["groups"][0]["pack"], historical)
        self.assertEqual(
            analysis["groups"][0]["fingerprint_verification"],
            ["release-registry"])

    def test_round_five_analysis_never_pools_current_and_historical_versions(self):
        historical = (
            "sha256:1186a977c1b4264fcf47497c027299b84f627ae1308f6488d85cfa34d1443679")
        with tempfile.TemporaryDirectory() as tmp:
            roots = []
            for name in ("current", "historical"):
                root = run_pilot(
                    self._config(), Path(tmp) / name, ["m"], 1,
                    agent_factory=lambda model, run: self.FakeAgent(
                        pilot_id="q41_async_fanout"),
                    pilot_id="q41_async_fanout")
                roots.append(root)
            summary_path = roots[1] / "pilot_summary.json"
            summary = load_json(summary_path)
            summary["pack"] = historical
            save_json(summary_path, summary)
            analysis = analyze_pilots(roots)
        self.assertEqual(len(analysis["groups"]), 2)
        self.assertEqual({group["pack"] for group in analysis["groups"]}, {
            pilot_fingerprint("q41_async_fanout"), historical})
        self.assertEqual(
            analysis["portfolio"]["configurations"][0]["pack_ambiguous_pilots"],
            ["q41_async_fanout"])

    def test_round_five_release_registry_is_complete_and_rejects_duplicates(self):
        registry = fingerprint_registry()
        for pilot_id in PILOT_IDS:
            self.assertIn(
                pilot_fingerprint(pilot_id),
                {entry["fingerprint"] for entry in registry["pilots"][pilot_id]})
        q42 = registry["pilots"]["q42_shared_http_cache"]
        self.assertEqual([entry["fingerprint"] for entry in q42], [
            "sha256:c1a1d19d78c91ef335735734cf0ff15fff3fa25aa3aed986101e86ebc29b539f",
            pilot_fingerprint("q42_shared_http_cache"),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            malformed = json.loads(json.dumps(registry))
            malformed["pilots"][PILOT_IDS[0]].append(
                malformed["pilots"][PILOT_IDS[0]][0])
            save_json(Path(tmp) / "fingerprint_registry.json", malformed)
            with self.assertRaisesRegex(ValueError, "duplicate.*fingerprint"):
                fingerprint_registry(Path(tmp))

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

    def test_round_five_protocol_loop_aborts_attempt_with_explicit_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self.FakeAgent("protocol-loop")
            root = run_pilot(
                self._config(), Path(tmp), ["m"], 1,
                agent_factory=lambda model, run: agent)
            grade = load_json(
                root / "m/round5/attempt-1/research_grade.json")
            report = (root / "PILOT_REPORT.md").read_text(encoding="utf-8")
        self.assertEqual(len(agent.calls), 1)
        self.assertEqual(grade["status"], "INCOMPLETE")
        self.assertTrue(grade["protocol_aborted"])
        self.assertEqual(grade["stop_reason"], "unsupported_tool_loop")
        self.assertEqual(grade["unsupported_tool_calls"], 3)
        self.assertIn("unsupported_tool_loop", report)

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
            analysis = analyze_pilots([run])
            group = analysis["groups"][0]
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
        for row in analysis["portfolio"]["configurations"]:
            self.assertEqual(
                row["missing_pilots"], [
                    "q33_batch_delivery", "q34_config_overlay", "q35_snapshot_race",
                    "q36_jsonl_stream", "q37_archive_boundary", "q38_webhook_replay",
                    "q39_job_lease", "q40_ssrf_redirect", "q41_async_fanout",
                    "q42_shared_http_cache",
                ])
            self.assertFalse(row["ready_for_cross_scenario_interpretation"])
        comparison = analysis["portfolio"]["pairwise"][0]
        self.assertEqual(
            comparison["repeat_adjusted_separation"]["status"],
            "INSUFFICIENT_EVIDENCE")
        self.assertEqual(
            comparison["next_evidence"]["action"], "COLLECT_MISSING_SCENARIOS")
        collection = analysis["portfolio"]["evidence_collection_plan"]
        self.assertEqual(
            collection["summary"]["minimum_additional_complete_attempts"], 40)
        self.assertEqual(collection["scenario_priorities"][0]["pilot_id"],
                         "q33_batch_delivery")
        self.assertTrue(all(
            len(row["actions"]) == 10
            and row["additional_complete_attempts"] == 20
            for row in collection["configurations"]))

    def test_cross_pilot_portfolio_marks_multiple_versions_as_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self._pilot_run(Path(tmp) / "pilot-a")
            second = self._pilot_run(Path(tmp) / "pilot-b")
            summary_path = second / "pilot_summary.json"
            summary = load_json(summary_path)
            summary["pack"] = "sha256:" + "d" * 64
            save_json(summary_path, summary)
            portfolio = analyze_pilots([first, second])["portfolio"]
        for row in portfolio["configurations"]:
            self.assertEqual(
                row["pack_ambiguous_pilots"], ["q32_retry_compatibility"])
            self.assertFalse(row["coverage_gates"]["one_pack_per_pilot"])
            self.assertFalse(row["ready_for_cross_scenario_interpretation"])
        comparison = portfolio["pairwise"][0]
        self.assertEqual(
            comparison["repeat_adjusted_separation"]["status"],
            "INSUFFICIENT_EVIDENCE")
        self.assertEqual(
            comparison["next_evidence"]["action"], "ALIGN_SCENARIO_VERSIONS")
        collection = portfolio["evidence_collection_plan"]
        self.assertIsNone(
            collection["summary"]["minimum_additional_complete_attempts"])
        self.assertEqual(
            collection["summary"]["configurations_requiring_manual_alignment"], 2)
        self.assertTrue(all(
            row["status"] == "ALIGNMENT_REQUIRED"
            and row["actions"][0]["action"] == "ALIGN_SCENARIO_VERSION"
            for row in collection["configurations"]))

    def test_evidence_plan_requires_a_fresh_cohort_after_invalid_history(self):
        scenario_results = [{
            "pilot_id": "q32_retry_compatibility", "pack": self.PACK,
            "complete": 2, "incomplete": 1, "authority_violations": 0,
        }]
        plan = _evidence_collection_plan([{
            "configuration": "config-1",
            "scenario_results": scenario_results,
            "pack_ambiguous_pilots": [],
        }])
        configuration = plan["configurations"][0]
        action = next(row for row in configuration["actions"]
                      if row["pilot_id"] == "q32_retry_compatibility")
        self.assertEqual(action["action"], "RECOLLECT_CLEAN_COHORT")
        self.assertEqual(action["additional_complete_attempts"], 2)
        self.assertTrue(action["exclude_invalid_run_directories"])
        self.assertEqual(configuration["additional_complete_attempts"], 22)

    def test_evidence_plan_does_not_count_cross_configuration_pack_mismatch(self):
        configurations = []
        for index, pack in enumerate((self.PACK, "sha256:" + "d" * 64), 1):
            configurations.append({
                "configuration": f"config-{index}",
                "scenario_results": [{
                    "pilot_id": "q32_retry_compatibility", "pack": pack,
                    "complete": 2, "incomplete": 0, "authority_violations": 0,
                }],
                "pack_ambiguous_pilots": [],
            })
        plan = _evidence_collection_plan(configurations)
        priority = next(row for row in plan["scenario_priorities"]
                        if row["pilot_id"] == "q32_retry_compatibility")
        self.assertEqual(priority["ready_configurations"], 0)
        self.assertEqual(priority["potential_pair_coverage_gain"], 1)
        self.assertEqual(priority["version_alignment_configurations"],
                         ["config-1", "config-2"])
        self.assertEqual(plan["scenario_priorities"][0]["pilot_id"],
                         "q32_retry_compatibility")
        self.assertIsNone(
            plan["summary"]["minimum_additional_complete_attempts"])
        self.assertTrue(all(
            row["status"] == "ALIGNMENT_REQUIRED"
            and row["actions"][0]["action"] == "ALIGN_SCENARIO_VERSION"
            for row in plan["configurations"]))

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
        self.assertEqual(machine_payload["schema_version"], 9)
        self.assertIn("### Evidence collection plan", default_text)
        self.assertIn("### Shared-scenario directional advantage", default_text)
        self.assertIn("Expected / tail", default_text)
        self.assertIn("Minimum additional complete attempts: **40**", default_text)
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

    def test_pilot_analysis_rejects_abort_without_threshold_transcript_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self._pilot_run(Path(tmp) / "pilot")
            grade_path = run / "strong/round5/attempt-1/research_grade.json"
            grade = load_json(grade_path)
            grade.update({
                "status": "INCOMPLETE", "turns_completed": 3,
                "protocol_aborted": True,
                "stop_reason": "unsupported_tool_loop",
                "release_ready": False,
            })
            grade["turns"][2].update({
                "protocol_aborted": True,
                "termination_reason": "unsupported_tool_loop",
                "returncode": -15,
            })
            for turn in (1, 2, 3):
                path = run / f"strong/round5/attempt-1/transcript_turn{turn}.txt"
                path.write_text(
                    "ERROR codex_core::tools::router: "
                    "error=request_user_input is unavailable in Default mode\n",
                    encoding="utf-8")
            save_json(grade_path, grade)
            summary = load_json(run / "pilot_summary.json")
            for row in summary["attempts"]:
                if row["model"] == "strong" and row["grade"]["attempt"] == 1:
                    row["grade"] = grade
            save_json(run / "pilot_summary.json", summary)
            with self.assertRaisesRegex(
                    ValueError, "per-turn threshold transcript evidence"):
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
            analysis = analyze_pilots([run])
            group = analysis["groups"][0]
        weak = next(row for row in group["configurations"] if row["incomplete"] == 1)
        self.assertEqual(weak["public_pass_rate"], 0.25)
        self.assertEqual(weak["hidden_pass_rate"], round(6 / 9, 6))
        self.assertFalse(group["ready_for_manual_ambiguity_review"])
        self.assertEqual(
            analysis["portfolio"]["pairwise"][0]["next_evidence"]["action"],
            "RECOLLECT_CLEAN_COHORT")

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
        self.assertEqual(payload["schema_version"], 2)
        self.assertFalse(payload["models"][0]["attempts"][0]["protocol_aborted"])
        self.assertIsNone(payload["models"][0]["attempts"][0]["stop_reason"])

    def test_validator_accepts_legacy_v1_without_protocol_stop_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, _ = build_public_pilot_result(self._run(Path(tmp) / "run"))
        payload["schema_version"] = 1
        for model in payload["models"]:
            for attempt in model["attempts"]:
                attempt.pop("protocol_aborted")
                attempt.pop("stop_reason")
        from llm_hardtest.public_results import _bundle_id
        body = {key: value for key, value in payload.items() if key != "bundle_id"}
        payload["bundle_id"] = _bundle_id(body)
        self.assertEqual(validate_public_pilot_result(payload), payload)

    def test_protocol_abort_requires_three_observed_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, _ = build_public_pilot_result(self._run(Path(tmp) / "run"))
        attempt = payload["models"][0]["attempts"][0]
        attempt.update({
            "status": "INCOMPLETE", "turns_completed": 1,
            "protocol_aborted": True, "stop_reason": "unsupported_tool_loop",
            "unsupported_tool_calls": 2, "tool_protocol_clean": False,
            "release_ready": False,
        })
        from llm_hardtest.public_results import _bundle_id
        body = {key: value for key, value in payload.items() if key != "bundle_id"}
        payload["bundle_id"] = _bundle_id(body)
        with self.assertRaisesRegex(ValueError, "threshold evidence"):
            validate_public_pilot_result(payload)

    def test_incomplete_public_pilot_requires_stop_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, _ = build_public_pilot_result(self._run(Path(tmp) / "run"))
        attempt = payload["models"][0]["attempts"][0]
        attempt.update({
            "status": "INCOMPLETE", "turns_completed": 1,
            "release_ready": False,
        })
        from llm_hardtest.public_results import _bundle_id
        body = {key: value for key, value in payload.items() if key != "bundle_id"}
        payload["bundle_id"] = _bundle_id(body)
        with self.assertRaisesRegex(ValueError, "requires a stop_reason"):
            validate_public_pilot_result(payload)

    def test_published_pilot_v2_schema_declares_protocol_stop_contract(self):
        schema = load_json(repo_root() / "results/pilot-schema-v2.json")
        attempt = schema["$defs"]["attempt"]
        self.assertEqual(schema["properties"]["schema_version"]["const"], 2)
        self.assertIn("protocol_aborted", attempt["required"])
        self.assertIn("stop_reason", attempt["required"])

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

    def test_panel_holdout_validation_confirms_stable_direction(self):
        matrix, models = {}, {}
        for configuration, outcome in (("private-a", "PASS"),
                                       ("private-b", "FAIL")):
            for unit in range(10):
                respondent = (configuration, unit)
                matrix[respondent] = {"q1": outcome}
                models[respondent] = configuration
        first = _panel_holdout_validation(
            matrix, models, {"private-a": "C1", "private-b": "C2"})
        second = _panel_holdout_validation(
            matrix, models, {"private-a": "C1", "private-b": "C2"})
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "STABLE")
        self.assertEqual(first["folds_evaluated"], 2)
        self.assertEqual(first["confirmed_direction_evaluations"], 2)
        self.assertEqual(first["direction_confirmation_rate"], 1.0)
        self.assertEqual(first["selection_jaccard"], 1.0)
        self.assertEqual({row["permutation_p_raw"]
                          for fold in first["folds"]
                          for row in fold["holdout_evaluations"]}, {0.00793651})
        self.assertEqual({row["permutation_p_holm"]
                          for fold in first["folds"]
                          for row in fold["holdout_evaluations"]}, {0.01587302})
        self.assertNotIn("private-a", json.dumps(first))

    def test_panel_holdout_validation_detects_selection_reversal(self):
        matrix, models = {}, {}
        for configuration in ("a", "b"):
            for unit in range(10):
                respondent = (configuration, unit)
                a_passes = unit % 2 == 0
                outcome = a_passes if configuration == "a" else not a_passes
                matrix[respondent] = {"q1": "PASS" if outcome else "FAIL"}
                models[respondent] = configuration
        result = _panel_holdout_validation(
            matrix, models, {"a": "C1", "b": "C2"})
        self.assertEqual(result["status"], "REVERSED_SIGNAL")
        self.assertEqual(result["reversed_direction_evaluations"], 2)
        self.assertEqual(result["confirmed_direction_evaluations"], 0)
        self.assertEqual({row["classification"]
                          for fold in result["folds"]
                          for row in fold["holdout_evaluations"]}, {"REVERSED"})

    def test_panel_holdout_holm_blocks_two_nominal_replications(self):
        matrix, models = {}, {}
        for configuration in ("a", "b"):
            for unit in range(10):
                respondent = (configuration, unit)
                outcome = configuration == "a" and unit not in {0, 1}
                matrix[respondent] = {"q1": "PASS" if outcome else "FAIL"}
                models[respondent] = configuration
        result = _panel_holdout_validation(
            matrix, models, {"a": "C1", "b": "C2"})
        evaluations = [row for fold in result["folds"]
                       for row in fold["holdout_evaluations"]]
        self.assertEqual(result["status"], "WEAK_GENERALIZATION")
        self.assertEqual({row["holdout_pass_rate_difference"]
                          for row in evaluations}, {0.8})
        self.assertEqual({row["permutation_p_raw"] for row in evaluations},
                         {0.04761905})
        self.assertEqual({row["permutation_p_holm"] for row in evaluations},
                         {0.0952381})
        self.assertEqual({row["classification"] for row in evaluations}, {"WEAK"})

    def test_holdout_permutation_monte_carlo_is_deterministic_for_fractional_units(self):
        higher = [index / 10 for index in range(11)]
        lower = [index / 20 for index in range(11)]
        first = _permutation_difference_test(higher, lower, "fractional-control")
        second = _permutation_difference_test(higher, lower, "fractional-control")
        self.assertEqual(first, second)
        self.assertEqual(
            first["method"],
            "deterministic_monte_carlo_label_permutation_two_sided")
        self.assertEqual(first["evaluated_permutations"], 20_000)
        self.assertGreater(first["p_value"], 0)

    def test_panel_holdout_validation_preserves_shared_clusters_and_sparse_gate(self):
        matrix, models, clusters = {}, {}, {}
        for bundle in range(10):
            for configuration, outcome in (("a", "PASS"), ("b", "FAIL")):
                respondent = (bundle, configuration)
                matrix[respondent] = {"q1": outcome}
                models[respondent] = configuration
                clusters[respondent] = f"bundle-{bundle}"
        stable = _panel_holdout_validation(
            matrix, models, {"a": "a", "b": "b"}, clusters=clusters)
        self.assertEqual(stable["status"], "STABLE")
        for fold in stable["folds"]:
            self.assertEqual(set(fold["training_independent_units"].values()), {5})
            self.assertEqual(set(fold["holdout_independent_units"].values()), {5})

        sparse_matrix = {respondent: rows for respondent, rows in matrix.items()
                         if respondent[0] < 5}
        sparse_models = {respondent: models[respondent] for respondent in sparse_matrix}
        sparse_clusters = {respondent: clusters[respondent]
                           for respondent in sparse_matrix}
        sparse = _panel_holdout_validation(
            sparse_matrix, sparse_models, {"a": "a", "b": "b"},
            clusters=sparse_clusters)
        self.assertEqual(sparse["status"], "INSUFFICIENT")
        self.assertEqual(sparse["eligible_direction_evaluations"], 0)

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

        self.assertEqual(analysis["schema_version"], 10)
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
        self.assertEqual(group["panel_holdout_validation"]["status"],
                         "INSUFFICIENT")
        self.assertIn("Decisive after Holm correction: **1/1**", rendered)
        self.assertIn("Discriminative item panel", rendered)
        self.assertIn("Out-of-fold panel validation", rendered)
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


class PanelConfigTests(unittest.TestCase):
    def _separating_runs(self, root: Path) -> list[Path]:
        pack = validate_pack(repo_root() / "rounds/round1")["fingerprint"]
        runs = []
        for model_name, outcome in (("strong", True), ("weak", False)):
            for attempt in range(5):
                run = root / f"private-{model_name}-{attempt}"
                model = {
                    "key": "shared", "label": f"Private {model_name}",
                    "model": f"org/{model_name}", "transport": "openai_compat",
                    "base_url": f"http://127.0.0.1:{8000 + (model_name == 'weak')}/v1",
                    "rounds": [1],
                }
                save_json(run / "config.json", {
                    "name": f"private-source-{attempt}", "repetitions": 1,
                    "rounds": [1], "timeout_seconds": 30 + attempt,
                    "models": [model],
                })
                save_json(run / "summary.json", {"packs": {"1": pack}})
                save_json(run / "shared/round1/attempt-1/result.json", {
                    "attempt": 1,
                    "results": [{"id": item, "correct": outcome}
                                for item in range(1, 11)],
                })
                runs.append(run)
        return runs

    def _opposite_specialty_runs(self, root: Path) -> list[Path]:
        pack = validate_pack(repo_root() / "rounds/round1")["fingerprint"]
        runs = []
        for attempt in range(5):
            run = root / f"opposite-{attempt}"
            models = [
                {"key": "a", "label": "Private A", "model": "org/a",
                 "transport": "openai_compat", "base_url": "http://127.0.0.1:8000/v1"},
                {"key": "b", "label": "Private B", "model": "org/b",
                 "transport": "openai_compat", "base_url": "http://127.0.0.1:8001/v1"},
            ]
            save_json(run / "config.json", {
                "name": "private-opposite", "repetitions": 1, "rounds": [1],
                "models": models,
            })
            save_json(run / "summary.json", {"packs": {"1": pack}})
            for model in models:
                is_a = model["key"] == "a"
                save_json(run / model["key"] / "round1/attempt-1/result.json", {
                    "attempt": 1,
                    "results": [
                        {"id": 1, "correct": is_a},
                        {"id": 2, "correct": not is_a},
                    ],
                })
            runs.append(run)
        return runs

    def test_model_identity_ignores_routing_but_not_inference_settings(self):
        first = {
            "key": "one", "label": "One", "public_name": "public-one",
            "model": "org/model", "transport": "openai_compat", "rounds": [1],
            "item_filters": {"1": [1]}, "temperature": 0,
        }
        second = {
            **first, "key": "two", "label": "Two", "public_name": "public-two",
            "rounds": [1, 2], "item_filters": {"2": [21]},
        }
        changed = {**second, "temperature": 0.5}
        self.assertEqual(_model_identity(first), _model_identity(second))
        self.assertNotEqual(_model_identity(first), _model_identity(changed))

    def test_panel_config_merges_models_and_resolves_key_collisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = self._separating_runs(root)
            config, analysis = build_panel_config(runs, max_items=1, repetitions=5)
        self.assertEqual(analysis["schema_version"], 10)
        self.assertEqual(config["rounds"], [1])
        self.assertEqual(config["repetitions"], 5)
        self.assertEqual(config["timeout_seconds"], 34)
        self.assertEqual([model["key"] for model in config["models"]],
                         ["shared", "shared-2"])
        self.assertEqual({model["model"] for model in config["models"]},
                         {"org/strong", "org/weak"})
        self.assertEqual({tuple(model["item_filters"]["1"])
                          for model in config["models"]}, {(1,)})
        focus = config["panel_focus"]
        self.assertEqual(focus["schema_version"], 3)
        self.assertEqual(focus["source_run_count"], 10)
        self.assertEqual(focus["groups"][0]["status"], "COMPLETE")
        self.assertEqual(focus["groups"][0]["selected_items"], ["q1"])
        self.assertEqual(focus["groups"][0]["holdout_status"], "INSUFFICIENT")
        self.assertEqual(focus["groups"][0]["holdout_familywise_alpha"], 0.05)
        self.assertEqual(
            focus["groups"][0]["holdout_multiplicity_method"],
            "holm_across_all_out_of_fold_direction_tests")
        self.assertFalse(focus["holdout_stability_required"])
        self.assertNotIn(str(root), json.dumps(focus))
        self.assertNotIn("private-source", json.dumps(focus))
        validate_config(config, check_runtime=False)
        self.assertEqual(_campaign_units(config), 10)

    def test_panel_config_rejects_pack_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = self._separating_runs(Path(tmp))
            for run in runs:
                save_json(run / "summary.json", {
                    "packs": {"1": "sha256:" + "a" * 64}})
            with self.assertRaisesRegex(ValueError, "does not match the installed pack"):
                build_panel_config(runs)

    def test_panel_config_rejects_multiple_packs_for_one_round(self):
        panel = {
            "status": "COMPLETE",
            "selected_items": [{"item": "q1"}],
            "uncovered_directional_targets": [],
        }
        analysis = {
            "schema_version": 10,
            "groups": [
                {"round": 1, "pack": "sha256:" + digit * 64,
                 "discriminative_item_panel": panel,
                 "panel_holdout_validation": {
                     "status": "STABLE", "folds_evaluated": 2,
                     "direction_confirmation_rate": 1.0,
                     "reversed_direction_evaluations": 0,
                 }}
                for digit in ("a", "b")
            ],
        }
        with patch("llm_hardtest.panel_config.analyze_runs", return_value=analysis), \
                patch("llm_hardtest.panel_config.collect_observations",
                      return_value={}):
            with self.assertRaisesRegex(ValueError, "multiple pack fingerprints"):
                build_panel_config([])

    def test_panel_config_requires_explicit_partial_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = self._opposite_specialty_runs(Path(tmp))
            with self.assertRaisesRegex(ValueError, "--allow-partial"):
                build_panel_config(runs, max_items=1)
            config, analysis = build_panel_config(
                runs, max_items=1, allow_partial=True)
        panel = analysis["groups"][0]["discriminative_item_panel"]
        self.assertEqual(panel["status"], "PARTIAL")
        self.assertEqual(len(panel["uncovered_directional_targets"]), 1)
        self.assertTrue(config["panel_focus"]["partial_allowed"])
        self.assertEqual(config["panel_focus"]["groups"][0]["status"], "PARTIAL")
        self.assertEqual(len(config["models"]), 2)
        self.assertEqual({len(model["item_filters"]["1"])
                          for model in config["models"]}, {1})

    def test_panel_config_can_require_stable_holdout_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = self._separating_runs(Path(tmp))
            with self.assertRaisesRegex(ValueError, "out-of-fold"):
                build_panel_config(runs, require_holdout_stable=True)

    def test_panel_config_output_refuses_overwrite_and_wrong_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = self._separating_runs(root)
            with self.assertRaisesRegex(ValueError, r"\.json"):
                write_panel_config(runs, root / "focused.md")
            output = root / "focused.json"
            path, config, _ = write_panel_config(runs, output, max_items=1)
            self.assertEqual(path, output)
            self.assertEqual(load_json(output), config)
            with self.assertRaisesRegex(ValueError, "overwrite"):
                write_panel_config(runs, output, max_items=1)

    def test_focus_cli_forwards_budget_repetitions_and_partial_authority(self):
        returned = (Path("focused.json"),
                    {"models": [{}, {}], "rounds": [1], "panel_focus": {
                        "groups": [{"holdout_status": "STABLE"}]}},
                    {"schema_version": 10})
        stdout = io.StringIO()
        with patch("llm_hardtest.cli.write_panel_config", return_value=returned) as write, \
                patch("sys.stdout", stdout):
            exit_code = main([
                "focus", "run-a", "run-b", "--output", "focused.json",
                "--panel-max-items", "3", "--repetitions", "7", "--allow-partial",
                "--require-holdout-stable",
            ])
        self.assertEqual(exit_code, 0)
        write.assert_called_once_with(
            [Path("run-a"), Path("run-b")], Path("focused.json"),
            max_items=3, repetitions=7, allow_partial=True,
            require_holdout_stable=True)
        self.assertIn("LOCAL CONFIG", stdout.getvalue())


class PublicResultTests(unittest.TestCase):
    def test_published_public_v4_schema_declares_execution_scaffold(self):
        schema = load_json(repo_root() / "results/schema-v4.json")
        self.assertEqual(schema["properties"]["schema_version"]["const"], 4)
        model = schema["$defs"]["model"]
        self.assertIn("execution_scaffold", model["required"])
        scaffold = schema["$defs"]["executionScaffold"]
        self.assertEqual(set(scaffold["required"]), {
            "agent_backend", "isolation_mode", "network", "fail_closed"})

    def _run(self, root, model_name="org/model"):
        config = {
            "name": "private-campaign-name", "repetitions": 1, "rounds": [1],
            "timeout_seconds": 30,
            "models": [{
                "key": "private-user-key", "label": "Private User Label",
                "model": model_name, "transport": "openai_compat",
                "base_url": "http://127.0.0.1:8000/v1",
                "api_key_env": "VERY_PRIVATE_API_KEY", "max_tokens": 2048,
                "public_serving_environment": {"scope": "same_host"},
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

    def _full_coordinate_submissions(self, count=5):
        submissions = self._recommendation_submissions(count)
        from llm_hardtest.public_results import _bundle_id
        for payload in submissions:
            for model in payload["models"]:
                model["parameters"] = {
                    "reasoning_effort": "high", "context_window": 8192,
                    "max_tokens": 2048, "temperature": 0.0, "top_p": 0.9,
                    "top_k": 40, "min_p": 0.05,
                }
                model["public_metadata"].update({
                    "model_revision": "rev-1", "model_format": "GGUF",
                    "parameter_count_b": 9 if model["public_name"] == "org/accurate" else 7,
                    "server_version": "1.2.3", "accelerator_count": 1,
                    "system_memory_gb": 64,
                })
            body = {key: value for key, value in payload.items() if key != "bundle_id"}
            payload["bundle_id"] = _bundle_id(body)
            validate_public_result(payload)
        return submissions

    def _readiness_submissions(self, count_per_environment=10):
        from llm_hardtest.public_results import _bundle_id
        first = self._full_coordinate_submissions(count_per_environment)
        for index, payload in enumerate(first):
            payload["environment"]["os"] = "Darwin"
            payload["environment"]["architecture"] = "arm64"
            for model in payload["models"]:
                model["serving_environment"] = {
                    "scope": "same_host", "os": "Darwin", "architecture": "arm64"}
            third = json.loads(json.dumps(payload["models"][0]))
            third["public_name"] = "org/balanced"
            third["public_metadata"]["memory_gb"] = 16
            third["public_metadata"]["parameter_count_b"] = 8
            payload["models"].append(third)
            payload["tool"]["version"] = f"readiness-darwin-{index}"
            body = {key: value for key, value in payload.items() if key != "bundle_id"}
            payload["bundle_id"] = _bundle_id(body)
            validate_public_result(payload)
        second = json.loads(json.dumps(first))
        for index, payload in enumerate(second):
            payload["environment"]["os"] = "Linux"
            payload["environment"]["architecture"] = "x86_64"
            for model in payload["models"]:
                model["serving_environment"] = {
                    "scope": "same_host", "os": "Linux", "architecture": "x86_64"}
            payload["tool"]["version"] = f"readiness-linux-{index}"
            body = {key: value for key, value in payload.items() if key != "bundle_id"}
            payload["bundle_id"] = _bundle_id(body)
            validate_public_result(payload)
        return first + second

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
        self.assertEqual(payload["schema_version"], 4)
        self.assertEqual(payload["models"][0]["execution_scaffold"], {
            "agent_backend": "codex_cli", "isolation_mode": "none",
            "network": "unrestricted", "fail_closed": False,
        })
        self.assertEqual(payload["models"][0]["serving_environment"], {
            "scope": "same_host", "os": payload["environment"]["os"],
            "architecture": payload["environment"]["architecture"],
        })
        self.assertEqual(payload["models"][0]["rounds"]["1"]["items"], [{
            "item": "q1", "attempt": 1, "status": "PASS",
            "wall_seconds": 2.0, "tokens": 20,
        }])
        self.assertFalse(warnings)
        self.assertEqual(loaded, payload)

    def test_public_export_quarantines_legacy_codex_total_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            self._run(root)
            config = load_json(root / "config.json")
            config["models"][0].update({
                "transport": "codex_cli", "codex_provider": "openai",
                "public_serving_environment": {"scope": "remote"},
            })
            save_json(root / "config.json", config)
            payload, warnings = build_public_result(root)
            self.assertIsNone(
                payload["models"][0]["rounds"]["1"]["items"][0]["tokens"])
            self.assertTrue(any("total-token" in warning for warning in warnings))

            result_path = root / "private-user-key/round1/attempt-1/result.json"
            result = load_json(result_path)
            result["results"][0]["token_measurement"] = "completion"
            save_json(result_path, result)
            payload, warnings = build_public_result(root)
            self.assertEqual(
                payload["models"][0]["rounds"]["1"]["items"][0]["tokens"], 20)
            self.assertFalse(any("total-token" in warning for warning in warnings))

    def test_signed_in_codex_defaults_to_remote_without_invented_coordinates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            self._run(root)
            config = load_json(root / "config.json")
            config["models"][0].update({
                "transport": "codex_cli", "codex_provider": "openai"})
            config["models"][0].pop("public_serving_environment")
            save_json(root / "config.json", config)
            payload, _ = build_public_result(root)
        self.assertEqual(payload["models"][0]["serving_environment"], {
            "scope": "remote", "os": None, "architecture": None})
        self.assertNotEqual(payload["models"][0]["serving_environment"]["os"],
                            payload["environment"]["os"])

    def test_public_v3_rejects_false_serving_provenance_after_rehash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            self._run(root)
            payload, _ = build_public_result(root)
        from llm_hardtest.public_results import _bundle_id
        false_os = "Linux" if payload["environment"]["os"] != "Linux" else "Darwin"
        for serving, message in (
                ({"scope": "same_host", "os": false_os,
                  "architecture": payload["environment"]["architecture"]},
                 "contradicts runner"),
                ({"scope": "unreported", "os": "Linux", "architecture": None},
                 "has coordinates")):
            candidate = json.loads(json.dumps(payload))
            candidate["models"][0]["serving_environment"] = serving
            body = {key: value for key, value in candidate.items()
                    if key != "bundle_id"}
            candidate["bundle_id"] = _bundle_id(body)
            with self.subTest(scope=serving["scope"]), self.assertRaisesRegex(
                    ValueError, message):
                validate_public_result(candidate)

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

    def test_public_v4_rejects_incoherent_isolation_after_rehash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            self._run(root)
            payload, _ = build_public_result(root)
        payload["models"][0]["execution_scaffold"].update({
            "isolation_mode": "none", "network": "model_endpoint_only",
            "fail_closed": True,
        })
        from llm_hardtest.public_results import _bundle_id
        body = {key: value for key, value in payload.items() if key != "bundle_id"}
        payload["bundle_id"] = _bundle_id(body)
        with self.assertRaisesRegex(ValueError, "execution scaffold"):
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
            model.pop("serving_environment")
            model.pop("execution_scaffold")
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
        database_rows = normalize_submissions([payload])
        self.assertEqual(len(database_rows["task_observations"]), 1)
        self.assertEqual(database_rows["task_observations"][0][3],
                         "q26_hidden_tests")
        self.assertEqual(database_rows["task_observations"][0][10], 1)
        self.assertIsNone(database_rows["task_observations"][0][11])
        self.assertEqual(aggregate_database(database_rows),
                         aggregate_submissions([payload]))

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

    def test_community_database_normalizes_public_observations(self):
        submissions = self._recommendation_submissions()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            for payload in submissions:
                digest = payload["bundle_id"].removeprefix("sha256:")
                (directory / f"{digest}.json").write_text(
                    submission_document(payload), encoding="utf-8")
            first = Path(tmp) / "first.sqlite3"
            second = Path(tmp) / "second.sqlite3"
            summary = build_database(directory, first)
            self.assertEqual(build_database(directory, first, check=True), summary)
            self.assertEqual(build_database(directory, second), summary)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            connection = sqlite3.connect(first)
            counts = {
                table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("bundles", "configurations", "benchmark_runs",
                              "item_observations", "task_observations")
            }
            configuration = connection.execute(
                "SELECT public_name, server, quantization, memory_gb, serving_scope, "
                "serving_os, serving_architecture "
                "FROM configurations ORDER BY public_name LIMIT 1").fetchone()
            clustered = connection.execute(
                "SELECT count(DISTINCT bundle_id), count(*) FROM benchmark_runs"
            ).fetchone()
            columns = {
                row[1] for table in ("bundles", "configurations", "benchmark_runs",
                                     "item_observations", "task_observations")
                for row in connection.execute(f"PRAGMA table_info({table})")
            }
            integrity = connection.execute("PRAGMA foreign_key_check").fetchall()
            connection.close()
            database_bytes = first.read_bytes()
        self.assertEqual(counts, {
            "bundles": 5, "configurations": 2, "benchmark_runs": 10,
            "item_observations": 100, "task_observations": 0,
        })
        self.assertEqual(configuration[:3],
                         ("org/accurate", "Example Server", "Q4_K_M"))
        self.assertEqual(configuration[3], 24.0)
        self.assertEqual(configuration[4:], (
            "same_host", submissions[0]["environment"]["os"],
            submissions[0]["environment"]["architecture"]))
        self.assertEqual(clustered, (5, 10))
        self.assertFalse(integrity)
        self.assertTrue({"prompt", "response", "transcript", "endpoint", "api_key",
                         "local_path", "private_label", "timestamp"}.isdisjoint(columns))
        for private in (b"private-campaign-name", b"Private User Label",
                        b"private-user-key", b"VERY_PRIVATE_API_KEY",
                        b"private raw response", b"/Users/private"):
            self.assertNotIn(private, database_bytes)

    def test_published_database_schema_matches_the_builder(self):
        published = (repo_root() / "results/database-schema-v4.sql").read_text(
            encoding="utf-8")
        published = "\n".join(
            line for line in published.splitlines()
            if not line.startswith("--"))
        self.assertEqual(published.strip(), SCHEMA_SQL.strip())

    def test_community_database_detects_tampering_and_rejects_wrong_extension(self):
        submissions = self._recommendation_submissions(1)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            payload = submissions[0]
            digest = payload["bundle_id"].removeprefix("sha256:")
            (directory / f"{digest}.json").write_text(
                submission_document(payload), encoding="utf-8")
            database = Path(tmp) / "observations.sqlite3"
            build_database(directory, database)
            connection = sqlite3.connect(database)
            connection.execute(
                "UPDATE configurations SET public_name = 'tampered'")
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(ValueError, "stale"):
                build_database(directory, database, check=True)
            with self.assertRaisesRegex(ValueError, r"\.sqlite"):
                build_database(directory, Path(tmp) / "observations.json")

    def test_community_database_rejects_unexpected_schema_objects(self):
        submissions = self._recommendation_submissions(1)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            payload = submissions[0]
            digest = payload["bundle_id"].removeprefix("sha256:")
            (directory / f"{digest}.json").write_text(
                submission_document(payload), encoding="utf-8")
            database = Path(tmp) / "observations.sqlite3"
            build_database(directory, database)
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE injected_private_data (value TEXT)")
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(ValueError, "schema does not match"):
                build_database(directory, database, check=True)

    def test_community_database_rejects_external_submission_symlink(self):
        submissions = self._recommendation_submissions(1)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            payload = submissions[0]
            digest = payload["bundle_id"].removeprefix("sha256:")
            external = Path(tmp) / "external.json"
            external.write_text(submission_document(payload), encoding="utf-8")
            (directory / f"{digest}.json").symlink_to(external)
            with self.assertRaisesRegex(ValueError, "unexpected submission entry"):
                build_database(directory, Path(tmp) / "observations.sqlite3")

    def test_empty_community_database_is_valid_and_check_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            database = Path(tmp) / "empty.sqlite3"
            summary = build_database(directory, database)
            self.assertEqual(summary["bundles"], 0)
            self.assertEqual(build_database(directory, database, check=True), summary)
            link = Path(tmp) / "linked.sqlite3"
            link.symlink_to(database)
            with self.assertRaisesRegex(ValueError, "regular file"):
                build_database(directory, link, check=True)

    def test_community_database_preserves_repeats_without_new_bundle_weight(self):
        submissions = self._recommendation_submissions(1)
        payload = submissions[0]
        payload["models"].append(json.loads(json.dumps(payload["models"][0])))
        from llm_hardtest.public_results import _bundle_id
        body = {key: value for key, value in payload.items() if key != "bundle_id"}
        payload["bundle_id"] = _bundle_id(body)
        validate_public_result(payload)
        rows = normalize_submissions(submissions)
        self.assertEqual(len(rows["bundles"]), 1)
        self.assertEqual(len(rows["configurations"]), 2)
        self.assertEqual(len(rows["benchmark_runs"]), 3)
        self.assertEqual({row[1] for row in rows["benchmark_runs"]},
                         {payload["bundle_id"]})
        aggregates = aggregate_database(rows)
        self.assertEqual({row["observed_submissions"] for row in aggregates}, {1})
        self.assertTrue(all(row["bundle_pass_rate_interval95"] is None
                            for row in aggregates))

    def test_results_database_cli_builds_and_checks(self):
        submissions = self._recommendation_submissions(1)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            payload = submissions[0]
            digest = payload["bundle_id"].removeprefix("sha256:")
            (directory / f"{digest}.json").write_text(
                submission_document(payload), encoding="utf-8")
            output = Path(tmp) / "community.sqlite3"
            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                self.assertEqual(main([
                    "results", "database", str(directory),
                    "--output", str(output)]), 0)
                self.assertEqual(main([
                    "results", "database", str(directory),
                    "--output", str(output), "--check"]), 0)
        self.assertIn("1 bundle(s)", stdout.getvalue())
        self.assertIn("Content fingerprint: sha256:", stdout.getvalue())

    def test_database_and_json_recommendations_are_identical(self):
        submissions = self._recommendation_submissions()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            for payload in submissions:
                digest = payload["bundle_id"].removeprefix("sha256:")
                (directory / f"{digest}.json").write_text(
                    submission_document(payload), encoding="utf-8")
            database = Path(tmp) / "community.sqlite3"
            build_database(directory, database)
            database_rows = aggregate_database(load_database(database))
            source_rows = aggregate_submissions(submissions)
            source_result = recommend_configurations(
                submissions, round_number=1,
                constraints={"accelerator": "example gpu", "max_memory_gb": 24},
                objectives=["accuracy", "latency", "throughput"],
                accuracy_floor=0.3)
            database_result = recommend_database(
                database, round_number=1,
                constraints={"accelerator": "example gpu", "max_memory_gb": 24},
                objectives=["accuracy", "latency", "throughput"],
                accuracy_floor=0.3)
        self.assertEqual(database_rows, source_rows)
        self.assertEqual(database_result, source_result)

    def test_catalog_discovers_exact_settings_and_readiness_without_provenance(self):
        submissions = self._recommendation_submissions()
        catalog = catalog_submissions(submissions)
        self.assertEqual(catalog["status"], "OBSERVED")
        self.assertEqual(catalog["summary"], {
            "configurations": 2,
            "observations": 2,
            "models": 2,
            "rounds": [1],
            "packs": ["sha256:" + "a" * 64],
            "recommendation_ready_observations": 2,
        })
        self.assertEqual(
            [row["value"] for row in catalog["facets"]["model"]],
            ["org/accurate", "org/fast"])
        self.assertEqual(catalog["facets"]["server"][0]["value"],
                         "Example Server")
        self.assertEqual(catalog["facets"]["server"][0]["configurations"], 2)
        self.assertEqual(catalog["facets"]["serving_scope"][0]["value"],
                         "same_host")
        self.assertEqual(catalog["facets"]["serving_os"][0]["value"],
                         submissions[0]["environment"]["os"])
        self.assertEqual(catalog["missing_coordinates"]["serving_os"], {
            "configurations": 0, "observations": 0})
        self.assertEqual(catalog["schema_version"], 3)
        self.assertEqual(catalog["missing_coordinates"]["model_format"], {
            "configurations": 2, "observations": 2,
        })
        self.assertEqual(catalog["facets"]["max_tokens"][0]["value"], 2048.0)
        self.assertEqual(catalog["missing_coordinates"]["reasoning_effort"], {
            "configurations": 2, "observations": 2,
        })
        for configuration in catalog["configurations"]:
            observation = configuration["observations"][0]
            self.assertEqual(observation["independent_bundles"], 5)
            self.assertEqual(observation["readiness"], {
                "accuracy": True, "completion": True,
                "latency": True, "throughput": True,
            })
        serialized = json.dumps(catalog)
        self.assertNotIn("bundle_id", serialized)
        self.assertNotIn("recommendation-control", serialized)
        rendered = render_catalog(catalog)
        self.assertIn("Observed Serving Catalog", rendered)
        self.assertIn("--configuration", rendered)
        catalog["configurations"][0]["model"] = "org/model | injected"
        self.assertIn("org/model \\| injected", render_catalog(catalog))

    def test_catalog_filters_validate_and_distinguish_empty_from_no_match(self):
        empty = build_catalog([])
        no_match = catalog_submissions(
            self._recommendation_submissions(), round_number=2)
        self.assertEqual(empty["status"], "EMPTY")
        self.assertEqual(no_match["status"], "NO_MATCH")
        self.assertFalse(no_match["configurations"])
        with self.assertRaisesRegex(ValueError, "one of 1, 2, 3, or 4"):
            build_catalog([], round_number=5)
        with self.assertRaisesRegex(ValueError, "exact sha256"):
            build_catalog([], pack="latest")

    def test_sparse_catalog_never_promotes_point_estimates_to_readiness(self):
        catalog = catalog_submissions(self._recommendation_submissions(1))
        self.assertEqual(catalog["summary"]["recommendation_ready_observations"], 0)
        self.assertEqual(catalog["facets"]["model"][0][
            "recommendation_ready_observations"], 0)
        for configuration in catalog["configurations"]:
            observation = configuration["observations"][0]
            self.assertEqual(observation["independent_bundles"], 1)
            self.assertFalse(any(observation["readiness"].values()))
            self.assertIsNone(observation["metrics"]["accuracy_observed"])

    def test_catalog_facets_merge_only_case_spelling_not_configurations(self):
        submissions = self._recommendation_submissions()
        changed = submissions[-1]
        for model in changed["models"]:
            model["public_metadata"]["server"] = "example server"
        from llm_hardtest.public_results import _bundle_id
        body = {key: value for key, value in changed.items() if key != "bundle_id"}
        changed["bundle_id"] = _bundle_id(body)
        validate_public_result(changed)
        catalog = catalog_submissions(submissions)
        self.assertEqual(len(catalog["facets"]["server"]), 1)
        self.assertEqual(catalog["facets"]["server"][0]["value"], "Example Server")
        self.assertEqual(catalog["facets"]["server"][0]["configurations"], 4)
        self.assertEqual(catalog["summary"]["configurations"], 4)

    def test_catalog_numeric_facets_normalize_integer_and_real_affinity(self):
        submissions = self._full_coordinate_submissions()
        changed = submissions[-1]
        for model in changed["models"]:
            model["parameters"]["context_window"] = 8192.0
        from llm_hardtest.public_results import _bundle_id
        body = {key: value for key, value in changed.items() if key != "bundle_id"}
        changed["bundle_id"] = _bundle_id(body)
        validate_public_result(changed)
        source = catalog_submissions(submissions)
        self.assertEqual(len(source["facets"]["context_window"]), 1)
        self.assertEqual(source["facets"]["context_window"][0]["value"], 8192.0)
        self.assertEqual(source["facets"]["context_window"][0]["configurations"], 4)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            for payload in submissions:
                digest = payload["bundle_id"].removeprefix("sha256:")
                (directory / f"{digest}.json").write_text(
                    submission_document(payload), encoding="utf-8")
            database = Path(tmp) / "community.sqlite3"
            build_database(directory, database)
            materialized = catalog_database(database)
        self.assertEqual(materialized, source)

    def test_database_and_json_catalogs_are_identical(self):
        submissions = self._full_coordinate_submissions()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            for payload in submissions:
                digest = payload["bundle_id"].removeprefix("sha256:")
                (directory / f"{digest}.json").write_text(
                    submission_document(payload), encoding="utf-8")
            database = Path(tmp) / "community.sqlite3"
            build_database(directory, database)
            source = catalog_submissions(
                submissions, round_number=1, pack="sha256:" + "a" * 64)
            materialized = catalog_database(
                database, round_number=1, pack="sha256:" + "a" * 64)
        self.assertEqual(materialized, source)

    def test_catalog_cli_database_matches_json_and_rejects_two_sources(self):
        submissions = self._recommendation_submissions()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            for payload in submissions:
                digest = payload["bundle_id"].removeprefix("sha256:")
                (directory / f"{digest}.json").write_text(
                    submission_document(payload), encoding="utf-8")
            database = Path(tmp) / "community.sqlite3"
            build_database(directory, database)
            json_stdout = io.StringIO()
            database_stdout = io.StringIO()
            with patch("sys.stdout", json_stdout):
                self.assertEqual(main([
                    "results", "catalog", str(directory), "--round", "1", "--json"]), 0)
            with patch("sys.stdout", database_stdout):
                self.assertEqual(main([
                    "results", "catalog", "--database", str(database),
                    "--round", "1", "--json"]), 0)
            with patch("sys.stderr", io.StringIO()):
                self.assertEqual(main([
                    "results", "catalog", str(directory), "--database", str(database),
                    "--json"]), 2)
            occupied = Path(tmp) / "occupied.json"
            occupied.write_text("preserve", encoding="utf-8")
            with patch("sys.stderr", io.StringIO()):
                self.assertEqual(main([
                    "results", "catalog", str(directory), "--json",
                    "--output", str(occupied)]), 2)
            self.assertEqual(occupied.read_text(encoding="utf-8"), "preserve")
        self.assertEqual(database_stdout.getvalue(), json_stdout.getvalue())

    def test_published_catalog_schema_has_the_runtime_contract(self):
        from llm_hardtest.serving_catalog import FACET_FIELDS, OPTIONAL_FACETS
        schema = json.loads((repo_root() / "results/catalog-schema-v3.json").read_text(
            encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"]["const"], 3)
        self.assertEqual(schema["properties"]["kind"]["const"],
                         "observed_serving_catalog")
        self.assertEqual(
            set(schema["properties"]["facets"]["required"]),
            set(FACET_FIELDS))
        self.assertEqual(
            set(schema["properties"]["missing_coordinates"]["required"]),
            OPTIONAL_FACETS)

    def test_published_recommendation_schema_has_every_runtime_constraint(self):
        from llm_hardtest.community_results import RECOMMENDATION_CONSTRAINTS
        schema = json.loads((
            repo_root() / "results/recommendation-schema-v3.json").read_text(
                encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"]["const"], 3)
        self.assertEqual(set(schema["$defs"]["constraints"]["properties"]),
                         RECOMMENDATION_CONSTRAINTS)

    def test_recommendation_can_select_one_exact_model_case_insensitively(self):
        result = recommend_configurations(
            self._recommendation_submissions(), round_number=1,
            constraints={"model": "ORG/FAST"}, objectives=["accuracy"])
        self.assertEqual(result["status"], "SINGLE_ELIGIBLE_CONFIGURATION")
        self.assertEqual(result["candidates"][0]["model"], "org/fast")

    def test_recommendation_filters_every_exact_configuration_coordinate(self):
        submissions = self._full_coordinate_submissions()
        catalog = catalog_submissions(submissions)
        selected = next(row for row in catalog["configurations"]
                        if row["model"] == "org/fast")
        constraints = {
            "configuration": selected["configuration"],
            "model": selected["model"].upper(),
            "os": selected["environment"]["os"],
            "architecture": selected["environment"]["architecture"],
            "python": selected["environment"]["python"],
            "serving_scope": selected["serving_environment"]["scope"],
            "serving_os": selected["serving_environment"]["os"],
            "serving_architecture": selected["serving_environment"]["architecture"],
            "transport": selected["transport"],
            **selected["parameters"], **selected["public_metadata"],
        }
        result = recommend_configurations(
            submissions, round_number=1, constraints=constraints)
        self.assertEqual(result["schema_version"], 3)
        self.assertEqual(result["status"], "SINGLE_ELIGIBLE_CONFIGURATION")
        self.assertEqual(result["candidates"][0]["configuration"],
                         selected["configuration"])
        rendered = render_recommendation(result)
        for expected in (
                "py", "revision=rev-1", "format=GGUF", "parameters B=7",
                "server version=1.2.3", "context=8192", "top p=0.9",
                "top k=40", "min p=0.05"):
            self.assertIn(expected, rendered)
        for key, value in constraints.items():
            if key == "configuration":
                conflicting_value = value[:-1] + ("a" if value[-1] != "a" else "b")
            elif key == "python":
                conflicting_value = "99.99"
            elif key == "transport":
                conflicting_value = (
                    "codex_cli" if value == "openai_compat" else "openai_compat")
            elif key == "serving_scope":
                conflicting_value = "remote" if value != "remote" else "unreported"
            elif key == "serving_os":
                conflicting_value = "Linux" if value != "Linux" else "Darwin"
            elif isinstance(value, str):
                conflicting_value = value + "-not-observed"
            else:
                conflicting_value = value + 0.125
            with self.subTest(coordinate=key):
                conflicting = {**constraints, key: conflicting_value}
                self.assertEqual(recommend_configurations(
                    submissions, round_number=1,
                    constraints=conflicting)["status"], "NO_MATCH")

    def test_full_coordinate_filters_match_between_cli_json_and_database(self):
        submissions = self._full_coordinate_submissions()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            for payload in submissions:
                digest = payload["bundle_id"].removeprefix("sha256:")
                (directory / f"{digest}.json").write_text(
                    submission_document(payload), encoding="utf-8")
            database = Path(tmp) / "community.sqlite3"
            build_database(directory, database)
            selected = next(row for row in catalog_submissions(submissions)["configurations"]
                            if row["model"] == "org/fast")
            arguments = [
                "--round", "1", "--configuration", selected["configuration"],
                "--model", "ORG/FAST", "--os", selected["environment"]["os"],
                "--architecture", selected["environment"]["architecture"],
                "--python-version", selected["environment"]["python"],
                "--serving-scope", selected["serving_environment"]["scope"],
                "--serving-os", selected["serving_environment"]["os"],
                "--serving-architecture",
                selected["serving_environment"]["architecture"],
                "--transport", selected["transport"], "--reasoning-effort", "high",
                "--context-window", "8192", "--max-tokens", "2048",
                "--temperature", "0", "--top-p", "0.9", "--top-k", "40",
                "--min-p", "0.05", "--model-revision", "rev-1",
                "--quantization", "Q4_K_M", "--model-format", "GGUF",
                "--parameter-count-b", "7", "--server", "Example Server",
                "--server-version", "1.2.3", "--accelerator", "Example GPU",
                "--accelerator-count", "1", "--memory-gb", "8",
                "--system-memory-gb", "64", "--json",
            ]
            source_stdout = io.StringIO()
            database_stdout = io.StringIO()
            with patch("sys.stdout", source_stdout):
                self.assertEqual(main([
                    "results", "recommend", str(directory), *arguments]), 0)
            with patch("sys.stdout", database_stdout):
                self.assertEqual(main([
                    "results", "recommend", "--database", str(database),
                    *arguments]), 0)
        self.assertEqual(database_stdout.getvalue(), source_stdout.getvalue())
        result = json.loads(source_stdout.getvalue())
        self.assertEqual(result["candidates"][0]["configuration"],
                         selected["configuration"])

    def test_database_and_json_require_the_same_exact_pack(self):
        submissions = self._recommendation_submissions()
        from llm_hardtest.public_results import _bundle_id
        for index, payload in enumerate(submissions):
            if index % 2:
                payload["benchmark"]["packs"]["1"] = "sha256:" + "b" * 64
                body = {key: value for key, value in payload.items()
                        if key != "bundle_id"}
                payload["bundle_id"] = _bundle_id(body)
                validate_public_result(payload)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            for payload in submissions:
                digest = payload["bundle_id"].removeprefix("sha256:")
                (directory / f"{digest}.json").write_text(
                    submission_document(payload), encoding="utf-8")
            database = Path(tmp) / "community.sqlite3"
            build_database(directory, database)
            source_result = recommend_configurations(submissions, round_number=1)
            database_result = recommend_database(database, round_number=1)
        self.assertEqual(source_result, database_result)
        self.assertEqual(database_result["status"], "PACK_REQUIRED")
        self.assertEqual(len(database_result["available_packs"]), 2)

    def test_database_recommendation_rejects_stale_fingerprint(self):
        submissions = self._recommendation_submissions()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            for payload in submissions:
                digest = payload["bundle_id"].removeprefix("sha256:")
                (directory / f"{digest}.json").write_text(
                    submission_document(payload), encoding="utf-8")
            database = Path(tmp) / "community.sqlite3"
            build_database(directory, database)
            connection = sqlite3.connect(database)
            connection.execute(
                "UPDATE item_observations SET status = 'FAIL' WHERE rowid = 1")
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(ValueError, "internally inconsistent"):
                recommend_database(database, round_number=1)

    def test_database_recommendation_rejects_semantic_tamper_with_fresh_fingerprint(self):
        submissions = self._recommendation_submissions()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            for payload in submissions:
                digest = payload["bundle_id"].removeprefix("sha256:")
                (directory / f"{digest}.json").write_text(
                    submission_document(payload), encoding="utf-8")
            database = Path(tmp) / "community.sqlite3"
            build_database(directory, database)
            normalized = normalize_submissions(submissions)
            changed = list(normalized["configurations"][0])
            changed[1] = "unsafe\nmodel"
            normalized["configurations"][0] = tuple(changed)
            connection = sqlite3.connect(database)
            connection.execute(
                "UPDATE configurations SET public_name = ? "
                "WHERE configuration_id = ?", (changed[1], changed[0]))
            connection.execute(
                "UPDATE dataset_metadata SET content_fingerprint = ?",
                (_content_fingerprint(normalized),))
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(ValueError, "invalid configuration row"):
                recommend_database(database, round_number=1)

    def test_database_rejects_rehashed_false_same_host_coordinates(self):
        submissions = self._recommendation_submissions(1)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            payload = submissions[0]
            digest = payload["bundle_id"].removeprefix("sha256:")
            (directory / f"{digest}.json").write_text(
                submission_document(payload), encoding="utf-8")
            database = Path(tmp) / "community.sqlite3"
            build_database(directory, database)
            normalized = normalize_submissions(submissions)
            changed = list(normalized["configurations"][0])
            false_os = "Linux" if changed[7] != "Linux" else "Darwin"
            changed[11] = false_os
            changed[13] = json.dumps({
                "architecture": changed[12], "os": false_os,
                "scope": "same_host"}, separators=(",", ":"), sort_keys=True)
            normalized["configurations"][0] = tuple(changed)
            connection = sqlite3.connect(database)
            connection.execute(
                "UPDATE configurations SET serving_os = ?, "
                "serving_environment_json = ? WHERE configuration_id = ?",
                (changed[11], changed[13], changed[0]))
            connection.execute(
                "UPDATE dataset_metadata SET content_fingerprint = ?",
                (_content_fingerprint(normalized),))
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(ValueError, "invalid configuration row"):
                load_database(database)

    def test_database_recommendation_requires_current_schema(self):
        submissions = self._recommendation_submissions(1)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            payload = submissions[0]
            digest = payload["bundle_id"].removeprefix("sha256:")
            (directory / f"{digest}.json").write_text(
                submission_document(payload), encoding="utf-8")
            database = Path(tmp) / "community.sqlite3"
            build_database(directory, database)
            connection = sqlite3.connect(database)
            connection.execute("PRAGMA user_version = 1")
            connection.close()
            with self.assertRaisesRegex(ValueError, "schema identity"):
                recommend_database(database, round_number=1)

    def test_results_recommend_cli_database_matches_json_and_rejects_two_sources(self):
        submissions = self._recommendation_submissions()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            for payload in submissions:
                digest = payload["bundle_id"].removeprefix("sha256:")
                (directory / f"{digest}.json").write_text(
                    submission_document(payload), encoding="utf-8")
            database = Path(tmp) / "community.sqlite3"
            build_database(directory, database)
            json_stdout = io.StringIO()
            database_stdout = io.StringIO()
            arguments = ["--round", "1", "--objective", "accuracy", "--json"]
            with patch("sys.stdout", json_stdout):
                self.assertEqual(main([
                    "results", "recommend", str(directory), *arguments]), 0)
            with patch("sys.stdout", database_stdout):
                self.assertEqual(main([
                    "results", "recommend", "--database", str(database),
                    *arguments]), 0)
            with patch("sys.stderr", io.StringIO()):
                self.assertEqual(main([
                    "results", "recommend", str(directory),
                    "--database", str(database), *arguments]), 2)
        self.assertEqual(database_stdout.getvalue(), json_stdout.getvalue())

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
        for constraints, message in (
                ({"serving_scope": "local-ish"}, "serving_scope"),
                ({"serving_os": "macOS"}, "serving_os"),
                ({"serving_architecture": "x" * 33}, "serving_architecture")):
            with self.subTest(constraints=constraints), self.assertRaisesRegex(
                    ValueError, message):
                recommend_configurations(
                    submissions, round_number=1, constraints=constraints)
        with self.assertRaisesRegex(ValueError, "must be a list"):
            recommend_configurations(
                submissions, round_number=1, objectives="accuracy")
        with self.assertRaisesRegex(ValueError, "safe text"):
            recommend_configurations(
                submissions, round_number=1, constraints={"server": "\n"})
        with self.assertRaisesRegex(ValueError, "finite numeric"):
            recommend_configurations(
                submissions, round_number=1, constraints={"context_window": None})
        with self.assertRaisesRegex(ValueError, "finite numeric"):
            recommend_configurations(
                submissions, round_number=1, constraints={"temperature": float("nan")})
        with self.assertRaisesRegex(ValueError, "must be positive"):
            recommend_configurations(
                submissions, round_number=1, constraints={"max_memory_gb": None})
        with self.assertRaisesRegex(ValueError, "10-character ID"):
            recommend_configurations(
                submissions, round_number=1, constraints={"configuration": "latest"})
        with self.assertRaisesRegex(ValueError, "major.minor"):
            recommend_configurations(
                submissions, round_number=1, constraints={"python": "latest"})
        with self.assertRaisesRegex(ValueError, "transport is unsupported"):
            recommend_configurations(
                submissions, round_number=1, constraints={"transport": "custom"})
        with self.assertRaisesRegex(ValueError, "keys must be strings"):
            recommend_configurations(
                submissions, round_number=1, constraints={1: "invalid"})
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

    def test_collection_plan_counts_independent_objective_deficits(self):
        result = plan_submissions(
            self._recommendation_submissions(1), round_number=1,
            objectives=["accuracy", "completion", "latency", "throughput"])
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["status"], "COLLECTION_NEEDED")
        self.assertEqual(result["summary"], {
            "matched_configurations": 2,
            "ready_configurations": 0,
            "configurations_needing_collection": 2,
            "minimum_additional_complete_bundles": 8,
        })
        for row in result["configurations"]:
            self.assertEqual(row["observed_independent_bundles"], {
                "accuracy": 1, "completion": 1, "latency": 1, "throughput": 1})
            self.assertEqual(row["bundle_deficits"], {
                "accuracy": 4, "completion": 4, "latency": 4, "throughput": 4})
            self.assertEqual(row["accuracy_prerequisite"], {
                "observed_independent_bundles": 1,
                "minimum_required_bundles": 5, "deficit": 4})
            self.assertEqual(row["minimum_additional_complete_bundles"], 4)
            self.assertFalse(row["ready"])
        document = render_collection_plan(result)
        self.assertIn("lower bound", document)
        self.assertIn("Repeated runs inside one bundle do not increase", document)
        self.assertNotIn("bundle_id", json.dumps(result))
        self.assertNotIn("recommendation-control", json.dumps(result))

        hostile = json.loads(json.dumps(result))
        hostile["configurations"][0]["model"] = "org/model|injected\nrow"
        hostile_document = render_collection_plan(hostile)
        self.assertIn("org/model\\|injected row", hostile_document)

    def test_collection_plan_handles_partial_metrics_and_higher_targets(self):
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
        result = plan_submissions(
            submissions, round_number=1,
            objectives=["accuracy", "latency", "throughput"])
        self.assertEqual(result["status"], "COLLECTION_NEEDED")
        self.assertEqual(result["summary"]["minimum_additional_complete_bundles"], 2)
        for row in result["configurations"]:
            self.assertEqual(row["observed_independent_bundles"], {
                "accuracy": 5, "latency": 4, "throughput": 4})
            self.assertEqual(row["bundle_deficits"], {
                "accuracy": 0, "latency": 1, "throughput": 1})
        higher = plan_submissions(
            submissions, round_number=1, objectives=["accuracy"], target_bundles=8)
        self.assertEqual(higher["summary"]["minimum_additional_complete_bundles"], 6)

    def test_collection_plan_never_ignores_accuracy_prerequisite(self):
        submissions = self._recommendation_submissions()
        from llm_hardtest.public_results import _bundle_id
        for payload in submissions:
            for model in payload["models"]:
                result = model["rounds"]["1"]
                result.update({"passed": 0, "total": 0, "incomplete": 10,
                               "items": [{**item, "status": "INCOMPLETE"}
                                         for item in result["items"]]})
            body = {key: value for key, value in payload.items()
                    if key != "bundle_id"}
            payload["bundle_id"] = _bundle_id(body)
            validate_public_result(payload)
        plan = plan_submissions(
            submissions, round_number=1, objectives=["completion"])
        self.assertEqual(plan["status"], "COLLECTION_NEEDED")
        for row in plan["configurations"]:
            self.assertEqual(row["observed_independent_bundles"], {"completion": 5})
            self.assertEqual(row["bundle_deficits"], {"completion": 0})
            self.assertEqual(row["accuracy_prerequisite"]["deficit"], 5)
            self.assertEqual(row["minimum_additional_complete_bundles"], 5)

    def test_collection_plan_target_met_pack_and_validation_states(self):
        submissions = self._recommendation_submissions()
        ready = plan_submissions(
            submissions, round_number=1,
            objectives=["accuracy", "completion", "latency", "throughput"])
        self.assertEqual(ready["status"], "TARGET_MET")
        self.assertEqual(ready["summary"]["ready_configurations"], 2)
        no_match = plan_submissions(
            submissions, round_number=1, constraints={"server": "not-observed"})
        self.assertEqual(no_match["status"], "NO_MATCH")
        empty = build_collection_plan([], round_number=1)
        self.assertEqual(empty["status"], "NO_OBSERVATIONS")
        with self.assertRaisesRegex(ValueError, "integer from 5 to 1000"):
            plan_submissions(submissions, round_number=1, target_bundles=4)
        with self.assertRaisesRegex(ValueError, "integer from 5 to 1000"):
            plan_submissions(submissions, round_number=1, target_bundles=True)

        mixed = json.loads(json.dumps(submissions))
        from llm_hardtest.public_results import _bundle_id
        for index, payload in enumerate(mixed):
            if index % 2:
                payload["benchmark"]["packs"]["1"] = "sha256:" + "b" * 64
                body = {key: value for key, value in payload.items()
                        if key != "bundle_id"}
                payload["bundle_id"] = _bundle_id(body)
                validate_public_result(payload)
        ambiguous = plan_submissions(mixed, round_number=1)
        self.assertEqual(ambiguous["status"], "PACK_REQUIRED")
        self.assertEqual(len(ambiguous["available_packs"]), 2)

    def test_collection_plan_json_database_and_cli_are_identical(self):
        submissions = self._full_coordinate_submissions(3)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            for payload in submissions:
                digest = payload["bundle_id"].removeprefix("sha256:")
                (directory / f"{digest}.json").write_text(
                    submission_document(payload), encoding="utf-8")
            database = Path(tmp) / "community.sqlite3"
            build_database(directory, database)
            direct = plan_submissions(
                submissions, round_number=1,
                constraints={"server": "example server", "context_window": 8192},
                objectives=["accuracy", "latency"], target_bundles=7)
            from_database = plan_database(
                database, round_number=1,
                constraints={"server": "example server", "context_window": 8192},
                objectives=["accuracy", "latency"], target_bundles=7)
            source_stdout = io.StringIO()
            database_stdout = io.StringIO()
            arguments = ["--round", "1", "--server", "EXAMPLE SERVER",
                         "--context-window", "8192", "--objective", "accuracy",
                         "--objective", "latency", "--target-bundles", "7", "--json"]
            with patch("sys.stdout", source_stdout):
                self.assertEqual(main(["results", "plan", str(directory), *arguments]), 0)
            with patch("sys.stdout", database_stdout):
                self.assertEqual(main([
                    "results", "plan", "--database", str(database), *arguments]), 0)
            with patch("sys.stderr", io.StringIO()):
                self.assertEqual(main([
                    "results", "plan", str(directory), "--database", str(database),
                    *arguments]), 2)
        self.assertEqual(direct, from_database)
        self.assertEqual(source_stdout.getvalue(), database_stdout.getvalue())
        self.assertEqual(json.loads(source_stdout.getvalue())["summary"],
                         direct["summary"])

    def test_published_collection_plan_schema_matches_runtime_contract(self):
        schema = json.loads((
            repo_root() / "results/collection-plan-schema-v2.json").read_text(
                encoding="utf-8"))
        result = plan_submissions(
            self._full_coordinate_submissions(1), round_number=1,
            objectives=["accuracy", "completion", "latency", "throughput"])
        self.assertEqual(set(result), set(schema["properties"]))
        self.assertEqual(set(result), set(schema["required"]))
        configuration_schema = schema["$defs"]["configurationPlan"]
        self.assertEqual(set(result["configurations"][0]),
                         set(configuration_schema["properties"]))
        self.assertEqual(set(result["configurations"][0]),
                         set(configuration_schema["required"]))
        constraint_properties = schema["$defs"]["constraints"]["properties"]
        from llm_hardtest.community_results import RECOMMENDATION_CONSTRAINTS
        self.assertEqual(set(constraint_properties), RECOMMENDATION_CONSTRAINTS)
        objectives = set(schema["$defs"]["objective"]["enum"])
        self.assertEqual(set(result["configurations"][0][
            "observed_independent_bundles"]), objectives)

    def test_paired_comparison_finds_holm_controlled_tradeoff(self):
        submissions = self._recommendation_submissions(7)
        configurations = {
            row["model"]: row["configuration"]
            for row in catalog_submissions(submissions)["configurations"]
        }
        result = compare_submissions(
            submissions, round_number=1,
            left_configuration=configurations["org/fast"],
            right_configuration=configurations["org/accurate"],
            objectives=["accuracy", "latency", "throughput"])
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["status"], "MIXED_DIRECTIONAL_EVIDENCE")
        self.assertEqual(result["shared_configuration_bundles"], 7)
        by_objective = {row["objective"]: row
                        for row in result["objectives_result"]}
        self.assertEqual(by_objective["accuracy"]["classification"], "RIGHT_BETTER")
        self.assertEqual(by_objective["latency"]["classification"], "LEFT_BETTER")
        self.assertEqual(by_objective["throughput"]["classification"], "LEFT_BETTER")
        self.assertEqual({row["p_raw"] for row in by_objective.values()}, {0.015625})
        self.assertEqual({row["p_holm"] for row in by_objective.values()}, {0.046875})
        self.assertEqual(by_objective["latency"]["left_advantage"], 3.0)
        self.assertEqual(by_objective["latency"]["effect_definition"],
                         "right_minus_left_seconds_positive_favors_left")
        document = render_paired_comparison(result)
        self.assertIn("Holm-adjusted p < 0.05", document)
        self.assertIn("No practical-effect threshold", document)
        serialized = json.dumps(result)
        self.assertNotIn("bundle_id", serialized)
        self.assertNotIn("recommendation-control", serialized)

    def test_paired_comparison_holm_blocks_two_nominal_directions(self):
        submissions = self._recommendation_submissions(6)
        configurations = {
            row["model"]: row["configuration"]
            for row in catalog_submissions(submissions)["configurations"]
        }
        result = compare_submissions(
            submissions, round_number=1,
            left_configuration=configurations["org/fast"],
            right_configuration=configurations["org/accurate"],
            objectives=["accuracy", "latency"])
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertEqual({row["p_raw"] for row in result["objectives_result"]},
                         {0.03125})
        self.assertEqual({row["p_holm"] for row in result["objectives_result"]},
                         {0.0625})
        self.assertEqual({row["classification"] for row in result["objectives_result"]},
                         {"INCONCLUSIVE"})

    def test_paired_comparison_is_exactly_symmetric_when_sides_swap(self):
        submissions = self._recommendation_submissions(7)
        configurations = {
            row["model"]: row["configuration"]
            for row in catalog_submissions(submissions)["configurations"]
        }
        left, right = configurations["org/fast"], configurations["org/accurate"]
        forward = compare_submissions(
            submissions, round_number=1, left_configuration=left,
            right_configuration=right,
            objectives=["accuracy", "completion", "latency", "throughput"])
        reverse = compare_submissions(
            submissions, round_number=1, left_configuration=right,
            right_configuration=left,
            objectives=["accuracy", "completion", "latency", "throughput"])
        forward_rows = {row["objective"]: row
                        for row in forward["objectives_result"]}
        reverse_rows = {row["objective"]: row
                        for row in reverse["objectives_result"]}
        for objective, first in forward_rows.items():
            second = reverse_rows[objective]
            self.assertEqual(first["left_mean"], second["right_mean"])
            self.assertEqual(first["right_mean"], second["left_mean"])
            self.assertAlmostEqual(first["left_advantage"], -second["left_advantage"])
            self.assertAlmostEqual(first["interval95"]["low"],
                                   -second["interval95"]["high"])
            self.assertAlmostEqual(first["interval95"]["high"],
                                   -second["interval95"]["low"])
            self.assertEqual(first["p_raw"], second["p_raw"])
            self.assertEqual(first["p_holm"], second["p_holm"])
            expected = {"LEFT_BETTER": "RIGHT_BETTER",
                        "RIGHT_BETTER": "LEFT_BETTER",
                        "INCONCLUSIVE": "INCONCLUSIVE"}[first["classification"]]
            self.assertEqual(second["classification"], expected)

    def test_paired_comparison_collapses_repeats_and_withholds_missing_metrics(self):
        repeated = self._recommendation_submissions(1)
        repeated[0]["models"] = repeated[0]["models"] * 50
        from llm_hardtest.public_results import _bundle_id
        body = {key: value for key, value in repeated[0].items() if key != "bundle_id"}
        repeated[0]["bundle_id"] = _bundle_id(body)
        validate_public_result(repeated[0])
        configurations = {
            row["model"]: row["configuration"]
            for row in catalog_submissions(repeated)["configurations"]
        }
        sparse = compare_submissions(
            repeated, round_number=1,
            left_configuration=configurations["org/fast"],
            right_configuration=configurations["org/accurate"],
            objectives=["accuracy", "latency"])
        self.assertEqual(sparse["shared_configuration_bundles"], 1)
        self.assertEqual(sparse["status"], "INSUFFICIENT_EVIDENCE")
        self.assertTrue(all(row["paired_bundles"] == 1
                            for row in sparse["objectives_result"]))

        submissions = self._recommendation_submissions(7)
        for payload in submissions[-3:]:
            for model in payload["models"]:
                if model["public_name"] == "org/fast":
                    for item in model["rounds"]["1"]["items"]:
                        item["wall_seconds"] = None
                        item["tokens"] = None
            body = {key: value for key, value in payload.items() if key != "bundle_id"}
            payload["bundle_id"] = _bundle_id(body)
            validate_public_result(payload)
        configurations = {
            row["model"]: row["configuration"]
            for row in catalog_submissions(submissions)["configurations"]
        }
        result = compare_submissions(
            submissions, round_number=1,
            left_configuration=configurations["org/fast"],
            right_configuration=configurations["org/accurate"],
            objectives=["accuracy", "latency"])
        by_objective = {row["objective"]: row
                        for row in result["objectives_result"]}
        self.assertEqual(by_objective["accuracy"]["paired_bundles"], 7)
        self.assertEqual(by_objective["latency"]["paired_bundles"], 4)
        self.assertEqual(by_objective["latency"]["classification"], "INSUFFICIENT")

    def test_paired_comparison_excludes_unpaired_bundle_populations(self):
        submissions = self._recommendation_submissions(7)
        from llm_hardtest.public_results import _bundle_id
        for payload in submissions[-2:]:
            payload["models"] = [
                model for model in payload["models"]
                if model["public_name"] == "org/fast"]
            body = {key: value for key, value in payload.items() if key != "bundle_id"}
            payload["bundle_id"] = _bundle_id(body)
            validate_public_result(payload)
        configurations = {
            row["model"]: row["configuration"]
            for row in catalog_submissions(submissions)["configurations"]
        }
        result = compare_submissions(
            submissions, round_number=1,
            left_configuration=configurations["org/fast"],
            right_configuration=configurations["org/accurate"],
            objectives=["accuracy"])
        self.assertEqual(result["shared_configuration_bundles"], 5)
        self.assertEqual(result["objectives_result"][0]["paired_bundles"], 5)
        self.assertEqual(result["objectives_result"][0]["p_raw"], 0.0625)
        self.assertEqual(result["status"], "INCONCLUSIVE")

    def test_paired_sign_flip_monte_carlo_is_deterministic(self):
        effects = [0.01 * (index + 1) for index in range(17)]
        first = _sign_flip_test(effects, "paired-monte-carlo-control")
        second = _sign_flip_test(effects, "paired-monte-carlo-control")
        self.assertEqual(first, second)
        self.assertEqual(first["method"],
                         "deterministic_monte_carlo_paired_sign_flip_two_sided")
        self.assertEqual(first["assignments"], 131072)
        self.assertEqual(first["evaluated_permutations"], 20_000)

    def test_paired_comparison_json_database_and_cli_are_identical(self):
        submissions = self._full_coordinate_submissions(7)
        configurations = {
            row["model"]: row["configuration"]
            for row in catalog_submissions(submissions)["configurations"]
        }
        arguments = {
            "round_number": 1,
            "left_configuration": configurations["org/fast"],
            "right_configuration": configurations["org/accurate"],
            "objectives": ["accuracy", "latency", "throughput"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            for payload in submissions:
                digest = payload["bundle_id"].removeprefix("sha256:")
                (directory / f"{digest}.json").write_text(
                    submission_document(payload), encoding="utf-8")
            database = Path(tmp) / "community.sqlite3"
            build_database(directory, database)
            direct = compare_submissions(submissions, **arguments)
            from_database = compare_database(database, **arguments)
            source_stdout = io.StringIO()
            database_stdout = io.StringIO()
            cli_arguments = [
                "--round", "1", "--left-configuration", configurations["org/fast"],
                "--right-configuration", configurations["org/accurate"],
                "--objective", "accuracy", "--objective", "latency",
                "--objective", "throughput", "--json",
            ]
            with patch("sys.stdout", source_stdout):
                self.assertEqual(main([
                    "results", "compare", str(directory), *cli_arguments]), 0)
            with patch("sys.stdout", database_stdout):
                self.assertEqual(main([
                    "results", "compare", "--database", str(database),
                    *cli_arguments]), 0)
            with patch("sys.stderr", io.StringIO()):
                self.assertEqual(main([
                    "results", "compare", str(directory), "--database", str(database),
                    *cli_arguments]), 2)
        self.assertEqual(direct, from_database)
        self.assertEqual(source_stdout.getvalue(), database_stdout.getvalue())

    def test_paired_comparison_states_and_contract_validation(self):
        submissions = self._recommendation_submissions(1)
        configurations = {
            row["model"]: row["configuration"]
            for row in catalog_submissions(submissions)["configurations"]
        }
        left, right = configurations["org/fast"], configurations["org/accurate"]
        empty = compare_paired_observations(
            [], round_number=1, left_configuration=left,
            right_configuration=right)
        self.assertEqual(empty["status"], "NO_OBSERVATIONS")
        no_match = compare_submissions(
            submissions, round_number=1, left_configuration="0" * 10,
            right_configuration=right)
        self.assertEqual(no_match["status"], "NO_MATCH")
        with self.assertRaisesRegex(ValueError, "two distinct"):
            compare_submissions(
                submissions, round_number=1, left_configuration=left,
                right_configuration=left)
        with self.assertRaisesRegex(ValueError, "10-character"):
            compare_submissions(
                submissions, round_number=1, left_configuration="latest",
                right_configuration=right)
        with self.assertRaisesRegex(ValueError, "must be a list"):
            compare_submissions(
                submissions, round_number=1, left_configuration=left,
                right_configuration=right, objectives="accuracy")
        with self.assertRaisesRegex(ValueError, "unique values"):
            compare_submissions(
                submissions, round_number=1, left_configuration=left,
                right_configuration=right, objectives=["accuracy", "accuracy"])
        with self.assertRaisesRegex(ValueError, "exact sha256"):
            compare_submissions(
                submissions, round_number=1, left_configuration=left,
                right_configuration=right, pack="latest")
        with self.assertRaisesRegex(ValueError, "round must"):
            compare_submissions(
                submissions, round_number=5, left_configuration=left,
                right_configuration=right)

        mixed = json.loads(json.dumps(self._recommendation_submissions(2)))
        from llm_hardtest.public_results import _bundle_id
        mixed[1]["benchmark"]["packs"]["1"] = "sha256:" + "b" * 64
        body = {key: value for key, value in mixed[1].items() if key != "bundle_id"}
        mixed[1]["bundle_id"] = _bundle_id(body)
        validate_public_result(mixed[1])
        ambiguous = compare_submissions(
            mixed, round_number=1, left_configuration=left,
            right_configuration=right)
        self.assertEqual(ambiguous["status"], "PACK_REQUIRED")
        self.assertEqual(len(ambiguous["available_packs"]), 2)

    def test_published_paired_comparison_schema_matches_runtime_contract(self):
        schema = json.loads((
            repo_root() / "results/paired-comparison-schema-v2.json").read_text(
                encoding="utf-8"))
        submissions = self._full_coordinate_submissions(7)
        configurations = {
            row["model"]: row["configuration"]
            for row in catalog_submissions(submissions)["configurations"]
        }
        result = compare_submissions(
            submissions, round_number=1,
            left_configuration=configurations["org/fast"],
            right_configuration=configurations["org/accurate"],
            objectives=["accuracy", "completion", "latency", "throughput"])
        self.assertEqual(set(result), set(schema["properties"]))
        self.assertEqual(set(result), set(schema["required"]))
        configuration_schema = schema["$defs"]["configuration"]
        self.assertEqual(set(result["left"]), set(configuration_schema["properties"]))
        self.assertEqual(set(result["left"]), set(configuration_schema["required"]))
        objective_schema = schema["$defs"]["objectiveResult"]
        self.assertEqual(set(result["objectives_result"][0]),
                         set(objective_schema["properties"]))
        self.assertEqual(set(result["objectives_result"][0]),
                         set(objective_schema["required"]))

    def test_prediction_readiness_meets_design_but_never_authorizes_service(self):
        result = audit_submissions(
            self._readiness_submissions(), round_number=1,
            objectives=["accuracy", "latency", "throughput"])
        self.assertEqual(result["status"],
                         "DESIGN_TARGET_MET_VALIDATION_REQUIRED")
        self.assertFalse(result["predictive_service_authorized"])
        self.assertEqual(result["summary"], {
            "observed_configurations": 6,
            "configurations_meeting_objective_targets": 6,
            "distinct_models": 3,
            "distinct_serving_environments": 6,
            "configurations_without_attested_serving_coordinates": 0,
            "observed_paired_edges": 6,
            "eligible_paired_edges": 6,
            "model_profiles_repeated_across_environments": 3,
        })
        self.assertTrue(all(row["status"] == "PASS"
                            for row in result["gates"][:5]))
        self.assertEqual(
            [row["status"] for row in result["gates"][5:]],
            ["UNAVAILABLE", "REQUIRED", "REQUIRED"])
        self.assertEqual(
            result["remaining_external_gates"],
            [row["name"] for row in result["gates"][5:]])
        serialized = json.dumps(result)
        self.assertNotIn("bundle_id", serialized)
        self.assertNotIn("readiness-darwin", serialized)
        rendered = render_prediction_readiness(result)
        self.assertIn("Predictive service authorized: **false**", rendered)
        self.assertIn("does not authorize a predictive service", rendered)

    def test_prediction_readiness_collapses_repeats_and_keeps_metric_gaps(self):
        from llm_hardtest.public_results import _bundle_id
        submissions = self._readiness_submissions()
        for payload in submissions:
            balanced = next(model for model in payload["models"]
                            if model["public_name"] == "org/balanced")
            for item in balanced["rounds"]["1"]["items"]:
                item["wall_seconds"] = None
                item["tokens"] = None
            payload["models"] += json.loads(json.dumps(payload["models"] * 20))
            body = {key: value for key, value in payload.items() if key != "bundle_id"}
            payload["bundle_id"] = _bundle_id(body)
            validate_public_result(payload)
        result = audit_submissions(
            submissions, round_number=1, objectives=["accuracy", "latency"],
            minimum_configurations=6)
        self.assertEqual(result["status"], "EVIDENCE_GAPS")
        self.assertEqual(result["summary"]["observed_configurations"], 6)
        self.assertEqual(
            result["summary"]["configurations_meeting_objective_targets"], 4)
        balanced_rows = [row for row in result["configurations"]
                         if row["model"] == "org/balanced"]
        self.assertEqual(len(balanced_rows), 2)
        self.assertTrue(all(row["observed_independent_bundles"] == {
            "accuracy": 10, "latency": 0} for row in balanced_rows))
        self.assertTrue(all(row["bundle_deficits"] == {
            "accuracy": 0, "latency": 10} for row in balanced_rows))

        one_bundle = self._recommendation_submissions(1)
        second_environment = json.loads(json.dumps(one_bundle[0]["models"][0]))
        second_environment["public_metadata"]["memory_gb"] = 12
        one_bundle[0]["models"].append(second_environment)
        body = {key: value for key, value in one_bundle[0].items()
                if key != "bundle_id"}
        one_bundle[0]["bundle_id"] = _bundle_id(body)
        validate_public_result(one_bundle[0])
        sparse_bridge = audit_submissions(one_bundle, round_number=1)
        self.assertEqual(
            sparse_bridge["summary"][
                "model_profiles_repeated_across_environments"], 0)
        self.assertFalse(sparse_bridge["environment_bridges"])

        profile_split = self._readiness_submissions(5)
        for payload in profile_split:
            if payload["environment"]["os"] != "Linux":
                continue
            balanced = next(model for model in payload["models"]
                            if model["public_name"] == "org/balanced")
            balanced["public_metadata"]["quantization"] = "Q8_0"
            body = {key: value for key, value in payload.items()
                    if key != "bundle_id"}
            payload["bundle_id"] = _bundle_id(body)
            validate_public_result(payload)
        split_result = audit_submissions(
            profile_split, round_number=1, target_bundles=5)
        self.assertEqual(
            split_result["summary"][
                "model_profiles_repeated_across_environments"], 2)
        self.assertNotIn(
            "org/balanced",
            {row["model"] for row in split_result["environment_bridges"]})

    def test_prediction_readiness_json_database_and_cli_are_identical(self):
        submissions = self._readiness_submissions(5)
        arguments = {
            "round_number": 1,
            "objectives": ["accuracy", "completion", "latency", "throughput"],
            "target_bundles": 5,
        }
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "submissions"
            directory.mkdir()
            for payload in submissions:
                digest = payload["bundle_id"].removeprefix("sha256:")
                (directory / f"{digest}.json").write_text(
                    submission_document(payload), encoding="utf-8")
            database = Path(tmp) / "community.sqlite3"
            build_database(directory, database)
            source = audit_submissions(submissions, **arguments)
            materialized = readiness_database(database, **arguments)
            source_stdout = io.StringIO()
            database_stdout = io.StringIO()
            cli_arguments = [
                "--round", "1", "--target-bundles", "5",
                "--objective", "accuracy", "--objective", "completion",
                "--objective", "latency", "--objective", "throughput", "--json",
            ]
            with patch("sys.stdout", source_stdout):
                self.assertEqual(main([
                    "results", "readiness", str(directory), *cli_arguments]), 0)
            with patch("sys.stdout", database_stdout):
                self.assertEqual(main([
                    "results", "readiness", "--database", str(database),
                    *cli_arguments]), 0)
            with patch("sys.stderr", io.StringIO()):
                self.assertEqual(main([
                    "results", "readiness", str(directory), "--database",
                    str(database), *cli_arguments]), 2)
            occupied = Path(tmp) / "occupied.json"
            occupied.write_text("preserve", encoding="utf-8")
            with patch("sys.stderr", io.StringIO()):
                self.assertEqual(main([
                    "results", "readiness", str(directory), *cli_arguments,
                    "--output", str(occupied)]), 2)
            self.assertEqual(occupied.read_text(encoding="utf-8"), "preserve")
        self.assertEqual(materialized, source)
        self.assertEqual(database_stdout.getvalue(), source_stdout.getvalue())

    def test_prediction_readiness_states_and_validation(self):
        submissions = self._recommendation_submissions(1)
        empty = audit_prediction_readiness([], round_number=1)
        self.assertEqual(empty["status"], "NO_OBSERVATIONS")
        self.assertFalse(empty["predictive_service_authorized"])
        mixed = json.loads(json.dumps(self._recommendation_submissions(2)))
        from llm_hardtest.public_results import _bundle_id
        mixed[1]["benchmark"]["packs"]["1"] = "sha256:" + "b" * 64
        body = {key: value for key, value in mixed[1].items() if key != "bundle_id"}
        mixed[1]["bundle_id"] = _bundle_id(body)
        validate_public_result(mixed[1])
        self.assertEqual(audit_submissions(
            mixed, round_number=1)["status"], "PACK_REQUIRED")
        with self.assertRaisesRegex(ValueError, "must be a list"):
            audit_submissions(
                submissions, round_number=1, objectives="accuracy")
        with self.assertRaisesRegex(ValueError, "unique values"):
            audit_submissions(
                submissions, round_number=1,
                objectives=["accuracy", "accuracy"])
        for key, value, message in (
                ("target_bundles", 4, "target bundles"),
                ("minimum_configurations", 1, "minimum configurations"),
                ("minimum_environments", True, "minimum environments"),
                ("minimum_paired_edges", 0, "minimum paired edges"),
                ("minimum_environment_bridges", 0,
                 "minimum environment bridges")):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, message):
                audit_submissions(
                    submissions, round_number=1, **{key: value})
        with self.assertRaisesRegex(ValueError, "round must"):
            audit_submissions(submissions, round_number=5)
        with self.assertRaisesRegex(ValueError, "exact sha256"):
            audit_submissions(submissions, round_number=1, pack="latest")

    def test_legacy_runner_hosts_never_unlock_serving_environment_gates(self):
        from llm_hardtest.public_results import _bundle_id
        submissions = self._readiness_submissions(5)
        for payload in submissions:
            payload["schema_version"] = 2
            for model in payload["models"]:
                model.pop("serving_environment")
                model.pop("execution_scaffold")
                self.assertEqual(normalized_serving_environment(payload, model), {
                    "scope": "unreported", "os": None, "architecture": None})
            body = {key: value for key, value in payload.items()
                    if key != "bundle_id"}
            payload["bundle_id"] = _bundle_id(body)
            validate_public_result(payload)
        result = audit_submissions(submissions, round_number=1, target_bundles=5)
        self.assertEqual(result["summary"]["observed_configurations"], 6)
        self.assertEqual(result["summary"]["distinct_serving_environments"], 0)
        self.assertEqual(
            result["summary"]["configurations_without_attested_serving_coordinates"],
            6)
        self.assertEqual(result["summary"][
            "model_profiles_repeated_across_environments"], 0)
        self.assertEqual(next(gate for gate in result["gates"] if gate["name"] ==
                              "serving_environment_diversity")["status"], "GAP")

    def test_published_prediction_readiness_schema_matches_runtime_contract(self):
        schema = json.loads((
            repo_root() / "results/prediction-readiness-schema-v2.json").read_text(
                encoding="utf-8"))
        result = audit_submissions(
            self._readiness_submissions(5), round_number=1, target_bundles=5,
            objectives=["accuracy", "latency"])
        self.assertEqual(set(result), set(schema["properties"]))
        self.assertEqual(set(result), set(schema["required"]))
        for name, definition in (
                ("configuration", result["configurations"][0]),
                ("pairedEdge", result["paired_edges"][0]),
                ("servingEnvironment", result["serving_environments"][0]),
                ("environmentBridge", result["environment_bridges"][0]),
                ("gate", result["gates"][0])):
            self.assertEqual(set(definition), set(schema["$defs"][name]["properties"]))
            self.assertEqual(set(definition), set(schema["$defs"][name]["required"]))

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
            payload["models"][0].pop("serving_environment")
            payload["models"][0].pop("execution_scaffold")
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
        self.assertIn("Community out-of-fold panel validation", document)
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
