from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from .backends import BackendError, CodexBackend, OpenAICompatBackend
from .common import load_json, repo_root, save_json, slug
from .orchestrator import _model_rounds, run, validate_config
from .report import generate
from .results import output_limited
from .inspection import inspect_run, render_inspection
from .replay import make_replay_config
from .packs import validate_pack
from .public_results import export_public_bundle
from .github_submit import (
    DEFAULT_REPOSITORY, open_submission_pr, preview_pilot_submission,
    preview_submission,
)
from .community_results import (
    build_index, build_pilot_index, load_pilot_submission_directory,
    load_submission_directory, recommend_configurations, render_recommendation,
)
from .calibration import write_analysis
from .round5 import run_pilot
from .pilot_analysis import write_pilot_analysis
from .public_pilots import export_public_pilot_bundle


SELFTEST_EXCLUDED_ROOTS = {
    ".git", ".venv", "build", "dist", "runs", "__pycache__",
}


def _selftest_source_paths(root: Path):
    """Yield repository source files, excluding local/generated evidence trees."""
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if (not path.is_file() or path.suffix == ".zip"
                or any(part in SELFTEST_EXCLUDED_ROOTS for part in relative.parts)
                or any(part.endswith(".egg-info") for part in relative.parts)):
            continue
        yield path


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(prompt + suffix + ": ").strip()
    return value or (default or "")


SERVER_PRESETS = {
    "custom": "http://127.0.0.1:8000/v1",
    "ollama": "http://127.0.0.1:11434/v1",
    "lmstudio": "http://127.0.0.1:1234/v1",
    "llamacpp": "http://127.0.0.1:8080/v1",
    "vllm": "http://127.0.0.1:8000/v1",
    "mlxlm": "http://127.0.0.1:8080/v1",
}


def _api_headers(api_key_env: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key_env and os.environ.get(api_key_env):
        headers["Authorization"] = "Bearer " + os.environ[api_key_env]
    return headers


def discover_models(base_url: str, api_key_env: str | None = None,
                    timeout: int = 10) -> list[str]:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/models", headers=_api_headers(api_key_env)
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        raise ValueError("/models response does not contain a data list")
    return [str(item["id"]) for item in models
            if isinstance(item, dict) and item.get("id")]


def _probe_codex(model: dict, timeout: int) -> None:
    probe = dict(model)
    probe["transport"] = "codex_cli"
    probe.setdefault("codex_provider", "custom")
    with tempfile.TemporaryDirectory(prefix="llm-hardtest-doctor-") as tmp:
        result = CodexBackend(probe, Path(tmp)).complete(
            [{"role": "user", "content": "Reply with OK."}], timeout)
        if not result["content"].strip():
            raise BackendError("Codex returned no text")


def doctor_config(config: dict, timeout: int = 30) -> int:
    """Probe model discovery and the APIs needed by each selected model."""
    validate_config(config)
    campaign_rounds = [int(value) for value in config["rounds"]]
    failures = []
    for model in config["models"]:
        key = model["key"]
        selected = _model_rounds(model, campaign_rounds)
        if model.get("codex_provider") == "openai":
            proc = subprocess.run(["codex", "login", "status"], text=True,
                                  capture_output=True, timeout=timeout)
            if proc.returncode:
                failures.append(f"{key}: Codex is not signed in")
            else:
                try:
                    _probe_codex(model, timeout)
                    print(f"PASS {key}: signed-in Codex returned text from {model['model']}")
                except Exception as exc:
                    failures.append(f"{key}: {exc}")
            continue
        try:
            served = discover_models(model.get("base_url", "http://127.0.0.1:8000/v1"),
                                     model.get("api_key_env"), timeout)
            if model["model"] not in served:
                raise ValueError(f'model {model["model"]!r} not found; served: {served}')
            print(f"PASS {key}: /models lists {model['model']}")
            if any(number in (1, 2, 3) for number in selected):
                if model.get("transport") == "openai_compat":
                    result = OpenAICompatBackend(model, Path(".")).complete(
                        [{"role": "user", "content": "Reply with OK."}], timeout)
                    if output_limited(result.get("finish_reason")):
                        raise BackendError(
                            "Chat Completions reached its output limit during a short probe"
                            + (" and returned no final text"
                               if not result["content"].strip() else ""))
                    if not result["content"].strip():
                        raise BackendError("Chat Completions returned no text")
                    print(f"PASS {key}: /chat/completions returned text")
            if model.get("transport") == "codex_cli" or 4 in selected:
                _probe_codex(model, timeout)
                purpose = "repository-agent rounds" if 4 in selected else "configured transport"
                print(f"PASS {key}: Codex completed through /responses for {purpose}")
        except Exception as exc:
            failures.append(f"{key}: {exc}")
    if failures:
        print("DOCTOR FAILED", file=sys.stderr)
        for failure in failures:
            print("- " + failure, file=sys.stderr)
        return 1
    print("DOCTOR PASSED")
    return 0


def init_config(path: Path) -> None:
    count = int(_ask("How many model configurations", "2"))
    repetitions = int(_ask("Independent repetitions per task", "5"))
    rounds = [int(x) for x in _ask("Campaign rounds (comma-separated)", "1,2,3").split(",")]
    models = []
    for index in range(1, count + 1):
        print(f"\nModel {index}/{count}")
        preset = _ask(
            "Server preset: custom, ollama, lmstudio, llamacpp, vllm, mlxlm, openai",
            "custom").lower()
        if preset not in {*SERVER_PRESETS, "openai"}:
            raise ValueError(f"unknown server preset {preset!r}")
        if preset == "openai":
            model_id = _ask("Codex model ID")
            transport, base_url, api_key_env = "codex_cli", None, None
        else:
            base_url = _ask("OpenAI-compatible /v1 base URL", SERVER_PRESETS[preset])
            api_key_env = _ask("API-key environment variable", "LLM_HARDTEST_API_KEY")
            try:
                available = discover_models(base_url, api_key_env)
                print("Available models: " + (", ".join(available) or "(none)"))
            except Exception as exc:
                available = []
                print(f"Could not discover models yet: {exc}")
            model_id = _ask("Model ID", available[0] if available else None)
            transport = _ask("Transport: openai_compat or codex_cli", "openai_compat")
        key = slug(_ask("Short key", model_id))
        model_rounds = [int(x) for x in _ask(
            "Rounds for this model (comma-separated)",
            ",".join(map(str, rounds))).split(",")]
        model = {"key": key, "label": _ask("Display label", model_id),
                 "model": model_id, "transport": transport,
                 "rounds": model_rounds,
                 "reasoning_effort": _ask("Reasoning effort (blank if unsupported)", "") or None,
                 "context_window": int(_ask("Context window", "131072")),
                 "max_tokens": int(_ask("Maximum output tokens", "16000"))}
        if preset != "openai":
            model["base_url"] = base_url
            model["api_key_env"] = api_key_env
            if transport == "codex_cli":
                model["codex_provider"] = "custom"
        else:
            model["codex_provider"] = "openai"
        models.append(model)
    config = {"name": _ask("Campaign name", "llm-hardtest"), "repetitions": repetitions,
              "rounds": rounds, "timeout_seconds": int(_ask("Timeout per model call", "3600")),
              "round4_tasks": ["q26_hidden_tests", "q27_race", "q28_false_hypothesis",
                               "q29_multiturn", "q30v2_policy_conflict", "q31_approval_followup"],
              "models": models}
    validate_config(config, check_runtime=False)
    save_json(path, config)
    print(f"Saved {path}")


def selftest() -> int:
    root = repo_root()
    failures = []
    for rel in ("rounds/round1/questions.json", "rounds/round2/questions.json",
                "rounds/round3/problems_v3.json"):
        try:
            load_json(root / rel)
        except Exception as exc:
            failures.append(f"{rel}: {exc}")
    for number in (1, 2, 3, 4, 5):
        try:
            validate_pack(root / "rounds" / f"round{number}")
        except Exception as exc:
            failures.append(f"round {number} pack: {exc}")
    cmd = [sys.executable, str(root / "rounds/round4/_harness_selftest/selftest.py")]
    proc = subprocess.run(cmd, cwd=root / "rounds/round4", text=True,
                          capture_output=True, timeout=300)
    if proc.returncode:
        failures.append("round-4 selftest failed:\n" + proc.stdout[-1000:] + proc.stderr[-1000:])
    pilot = subprocess.run(
        [sys.executable, str(root / "rounds/round5/verify_pilot.py")],
        cwd=root / "rounds/round5", text=True, capture_output=True, timeout=60)
    if pilot.returncode:
        failures.append(
            "round-5 pilot controls failed:\n" + pilot.stdout[-1000:] + pilot.stderr[-1000:])
    korean_hits = []
    for path in _selftest_source_paths(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any("\uac00" <= char <= "\ud7a3" for char in text):
            korean_hits.append(str(path.relative_to(root)))
    if korean_hits:
        failures.append("Korean text remains in: " + ", ".join(korean_hits[:50]))
    if failures:
        print("SELFTEST FAILED")
        print("\n\n".join(failures))
        return 1
    print("SELFTEST PASSED: datasets parse, packs and controls validate, harness is healthy")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog=Path(sys.argv[0]).name,
        description="Run LLM Hardtest and validate its reusable benchmark packs",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init", help="interactively create a campaign config")
    p_init.add_argument("--output", default="benchmark.json")
    p_run = sub.add_parser("run", help="run or resume a campaign")
    p_run.add_argument("--config", required=True)
    p_run.add_argument("--runs-dir", default="runs")
    p_run.add_argument("--resume")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument(
        "--progress", choices=("auto", "dashboard", "plain"), default="auto",
        help="progress display: live dashboard on a TTY, force dashboard, or plain logs",
    )
    p_report = sub.add_parser("report", help="regenerate a completed campaign report")
    p_report.add_argument("run_dir")
    p_analyze = sub.add_parser(
        "analyze",
        help="measure robust item discrimination, repeat stability, and configuration evidence")
    p_analyze.add_argument("run_dirs", nargs="+")
    p_analyze.add_argument("--output", default="HARDTEST_ANALYSIS.md")
    p_analyze.add_argument(
        "--panel-max-items", type=int,
        help="cap the discriminative panel and report any uncovered directions")
    p_inspect = sub.add_parser("inspect", help="show unresolved campaign items")
    p_inspect.add_argument("run_dir")
    p_inspect.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_replay = sub.add_parser("replay", help="rerun unresolved items as a new campaign")
    p_replay.add_argument("run_dir")
    p_replay.add_argument("--runs-dir", default="runs")
    p_replay.add_argument("--include-review", action="store_true")
    p_replay.add_argument("--dry-run", action="store_true")
    p_replay.add_argument(
        "--progress", choices=("auto", "dashboard", "plain"), default="auto")
    p_validate = sub.add_parser("validate", help="validate config syntax and local executables")
    p_validate.add_argument("--config", required=True)
    p_doctor = sub.add_parser("doctor", help="probe configured servers, models, and APIs")
    p_doctor.add_argument("--config", required=True)
    p_doctor.add_argument("--timeout", type=int, default=30)
    p_discover = sub.add_parser("discover", help="list model IDs exposed by a server")
    p_discover.add_argument("--base-url", required=True)
    p_discover.add_argument("--api-key-env")
    p_pack = sub.add_parser("pack", help="validate and inspect reusable benchmark packs")
    pack_commands = p_pack.add_subparsers(dest="pack_command", required=True)
    p_pack_validate = pack_commands.add_parser("validate", help="validate a pack manifest")
    p_pack_validate.add_argument("path")
    p_pack_validate.add_argument("--json", action="store_true")
    p_export = sub.add_parser("export", help="create an explicitly public result bundle")
    p_export.add_argument("run_dir")
    p_export.add_argument("--public", action="store_true",
                          help="confirm that the sanitized bundle is intended for review")
    p_export.add_argument("--output", default="llm-hardtest-public-result.zip")
    p_submit = sub.add_parser("submit", help="preview or voluntarily submit a public bundle")
    p_submit.add_argument("bundle")
    submit_mode = p_submit.add_mutually_exclusive_group(required=True)
    submit_mode.add_argument("--preview", action="store_true")
    submit_mode.add_argument("--open-pr", action="store_true")
    p_submit.add_argument("--yes", action="store_true",
                          help="confirm the external GitHub branch, file, and PR writes")
    p_submit.add_argument("--repo", default=DEFAULT_REPOSITORY)
    p_results = sub.add_parser("results", help="validate and aggregate public submissions")
    results_commands = p_results.add_subparsers(dest="results_command", required=True)
    p_results_validate = results_commands.add_parser(
        "validate", help="validate canonical submission files")
    p_results_validate.add_argument("directory", nargs="?", default="results/submissions")
    p_results_build = results_commands.add_parser(
        "build", help="rebuild the community result index")
    p_results_build.add_argument("directory", nargs="?", default="results/submissions")
    p_results_build.add_argument("--output", default="results/INDEX.md")
    p_results_build.add_argument("--check", action="store_true")
    p_results_recommend = results_commands.add_parser(
        "recommend", help="query gated Pareto candidates from public observations")
    p_results_recommend.add_argument(
        "directory", nargs="?", default="results/submissions")
    p_results_recommend.add_argument("--round", type=int, required=True)
    p_results_recommend.add_argument(
        "--pack", help="exact sha256 pack fingerprint; required when multiple exist")
    p_results_recommend.add_argument(
        "--objective", action="append",
        choices=("accuracy", "completion", "latency", "throughput"),
        help="Pareto objective; repeat for multiple axes (default: accuracy)")
    p_results_recommend.add_argument("--accuracy-floor", type=float)
    p_results_recommend.add_argument("--os")
    p_results_recommend.add_argument("--architecture")
    p_results_recommend.add_argument(
        "--transport", choices=("openai_compat", "codex_cli"))
    p_results_recommend.add_argument("--accelerator")
    p_results_recommend.add_argument("--server")
    p_results_recommend.add_argument("--quantization")
    p_results_recommend.add_argument("--model-format")
    p_results_recommend.add_argument("--max-memory-gb", type=float)
    p_results_recommend.add_argument("--max-system-memory-gb", type=float)
    p_results_recommend.add_argument("--max-parameter-count-b", type=float)
    p_results_recommend.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON")
    p_results_recommend.add_argument(
        "--output", help="write the report to this path instead of stdout")
    p_results_pilots = results_commands.add_parser(
        "pilots", help="validate or aggregate voluntary Round 5 pilot summaries")
    pilot_result_commands = p_results_pilots.add_subparsers(
        dest="pilot_results_command", required=True)
    p_results_pilots_validate = pilot_result_commands.add_parser(
        "validate", help="validate public pilot submission files")
    p_results_pilots_validate.add_argument(
        "directory", nargs="?", default="results/pilots")
    p_results_pilots_build = pilot_result_commands.add_parser(
        "build", help="rebuild the community Round 5 pilot index")
    p_results_pilots_build.add_argument(
        "directory", nargs="?", default="results/pilots")
    p_results_pilots_build.add_argument("--output", default="results/PILOTS.md")
    p_results_pilots_build.add_argument("--check", action="store_true")
    p_pilot = sub.add_parser("pilot", help="run non-canonical research pilots")
    pilot_commands = p_pilot.add_subparsers(dest="pilot_command", required=True)
    p_pilot_r5 = pilot_commands.add_parser(
        "round5", help="collect three-turn Round 5 research evidence")
    p_pilot_r5.add_argument("--config", required=True)
    p_pilot_r5.add_argument("--model", action="append", dest="models",
                            help="configured model key; repeat to select multiple")
    p_pilot_r5.add_argument("--attempts", type=int, default=1)
    p_pilot_r5.add_argument("--timeout", type=int)
    p_pilot_r5.add_argument("--runs-dir", default="runs")
    p_pilot_r5.add_argument("--resume")
    p_pilot_analyze = pilot_commands.add_parser(
        "analyze", help="compare Round 5 evidence across models and repeated pilots")
    p_pilot_analyze.add_argument("run_dirs", nargs="+")
    p_pilot_analyze.add_argument("--output", default="ROUND5_ANALYSIS.md")
    p_pilot_analyze.add_argument(
        "--include-model-labels", action="store_true",
        help="copy configured model labels into the local analysis report")
    p_pilot_export = pilot_commands.add_parser(
        "export", help="create an explicitly public sanitized Round 5 summary")
    p_pilot_export.add_argument("run_dir")
    p_pilot_export.add_argument("--public", action="store_true",
                                help="confirm the sanitized bundle is intended for review")
    p_pilot_export.add_argument("--output", default="llm-hardtest-public-pilot.zip")
    p_pilot_submit = pilot_commands.add_parser(
        "submit", help="preview or voluntarily submit a public Round 5 bundle")
    p_pilot_submit.add_argument("bundle")
    pilot_submit_mode = p_pilot_submit.add_mutually_exclusive_group(required=True)
    pilot_submit_mode.add_argument("--preview", action="store_true")
    pilot_submit_mode.add_argument("--open-pr", action="store_true")
    p_pilot_submit.add_argument("--yes", action="store_true",
                                help="confirm the external GitHub branch, file, and PR writes")
    p_pilot_submit.add_argument("--repo", default=DEFAULT_REPOSITORY)
    sub.add_parser("selftest", help="validate datasets and graders without calling a model")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            init_config(Path(args.output)); return 0
        if args.command == "run":
            config = load_json(Path(args.config))
            run_dir = run(config, Path(args.runs_dir), Path(args.resume) if args.resume else None,
                          args.dry_run, args.progress)
            print(f"Campaign directory: {run_dir}")
            if not args.dry_run:
                print(f"Report: {run_dir / 'REPORT.md'}")
            return 0
        if args.command == "report":
            md, js = generate(Path(args.run_dir)); print(md); print(js); return 0
        if args.command == "analyze":
            md, js, analysis = write_analysis(
                [Path(value) for value in args.run_dirs], Path(args.output),
                args.panel_max_items)
            print(f"Analysis: {md}")
            print(f"Machine-readable analysis: {js}")
            print(f"Comparable pack groups: {len(analysis['groups'])}")
            return 0
        if args.command == "inspect":
            summary = inspect_run(Path(args.run_dir))
            print(json.dumps(summary, indent=2) if args.json else render_inspection(summary))
            return 0
        if args.command == "replay":
            source = Path(args.run_dir)
            config = make_replay_config(source, args.include_review)
            if config is None:
                print(f"{source.name}: no matching unresolved items to replay")
                return 0
            run_dir = run(config, Path(args.runs_dir), dry_run=args.dry_run,
                          progress_mode=args.progress)
            print(f"Replay campaign directory: {run_dir}")
            if not args.dry_run:
                print(f"Report: {run_dir / 'REPORT.md'}")
            return 0
        if args.command == "validate":
            validate_config(load_json(Path(args.config)))
            print(f"VALID: {args.config} (run doctor for live API checks)")
            return 0
        if args.command == "doctor":
            return doctor_config(load_json(Path(args.config)), args.timeout)
        if args.command == "discover":
            for model_id in discover_models(args.base_url, args.api_key_env):
                print(model_id)
            return 0
        if args.command == "pack":
            metadata = validate_pack(Path(args.path))
            print(json.dumps(metadata, indent=2) if args.json else
                  f'{metadata["id"]}: VALID {metadata["fingerprint"]}')
            return 0
        if args.command == "export":
            if not args.public:
                raise ValueError("public export requires the explicit --public flag")
            path, payload, warnings = export_public_bundle(
                Path(args.run_dir), Path(args.output))
            print(f"Public bundle: {path}")
            print(f'Bundle ID: {payload["bundle_id"]}')
            for warning in warnings:
                print("WARNING: " + warning)
            print(f"Preview before submission: llm-hardtest submit {path} --preview")
            return 0
        if args.command == "submit":
            payload, relative, document = preview_submission(Path(args.bundle))
            print(document, end="")
            print(f"Proposed repository path: {relative}")
            if args.preview:
                print("PREVIEW ONLY: no network request or GitHub write was made")
                return 0
            if not args.yes:
                raise ValueError("opening a GitHub pull request requires --open-pr --yes")
            url = open_submission_pr(payload, args.repo)
            print(f"Pull request: {url}")
            return 0
        if args.command == "results":
            if args.results_command == "pilots":
                directory = Path(args.directory)
                if args.pilot_results_command == "validate":
                    submissions = load_pilot_submission_directory(directory)
                    print(f"VALID: {len(submissions)} public pilot bundle(s)")
                    return 0
                bundles, groups = build_pilot_index(
                    directory, Path(args.output), check=args.check)
                action = "VALID" if args.check else "BUILT"
                print(f"{action}: {args.output} ({bundles} bundle(s), {groups} group(s))")
                return 0
            directory = Path(args.directory)
            if args.results_command == "validate":
                submissions = load_submission_directory(directory)
                print(f"VALID: {len(submissions)} public result bundle(s)")
                return 0
            if args.results_command == "recommend":
                submissions = load_submission_directory(directory)
                constraints = {
                    key: value for key, value in {
                        "os": args.os,
                        "architecture": args.architecture,
                        "transport": args.transport,
                        "accelerator": args.accelerator,
                        "server": args.server,
                        "quantization": args.quantization,
                        "model_format": args.model_format,
                        "max_memory_gb": args.max_memory_gb,
                        "max_system_memory_gb": args.max_system_memory_gb,
                        "max_parameter_count_b": args.max_parameter_count_b,
                    }.items() if value is not None
                }
                result = recommend_configurations(
                    submissions, round_number=args.round, pack=args.pack,
                    constraints=constraints, objectives=args.objective,
                    accuracy_floor=args.accuracy_floor)
                document = (json.dumps(result, indent=2, sort_keys=True,
                                       ensure_ascii=False) + "\n"
                            if args.json else render_recommendation(result))
                if args.output:
                    output = Path(args.output)
                    if output.exists() or output.is_symlink():
                        raise ValueError(
                            f"refusing to overwrite existing recommendation: {output}")
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text(document, encoding="utf-8")
                    print(f"Recommendation: {output}")
                else:
                    print(document, end="")
                return 0
            bundles, groups = build_index(
                directory, Path(args.output), check=args.check)
            action = "VALID" if args.check else "BUILT"
            print(f"{action}: {args.output} ({bundles} bundle(s), {groups} group(s))")
            return 0
        if args.command == "pilot":
            if args.pilot_command == "analyze":
                md, machine, analysis = write_pilot_analysis(
                    [Path(value) for value in args.run_dirs], Path(args.output),
                    args.include_model_labels)
                print(f"Round 5 analysis: {md}")
                print(f"Machine-readable analysis: {machine}")
                print(f"Comparable pilot groups: {len(analysis['groups'])}")
                return 0
            if args.pilot_command == "export":
                if not args.public:
                    raise ValueError("public pilot export requires the explicit --public flag")
                path, payload, warnings = export_public_pilot_bundle(
                    Path(args.run_dir), Path(args.output))
                print(f"Public pilot bundle: {path}")
                print(f'Bundle ID: {payload["bundle_id"]}')
                for warning in warnings:
                    print("WARNING: " + warning)
                print(f"Preview before submission: llm-hardtest pilot submit {path} --preview")
                return 0
            if args.pilot_command == "submit":
                payload, relative, document = preview_pilot_submission(Path(args.bundle))
                print(document, end="")
                print(f"Proposed repository path: {relative}")
                if args.preview:
                    print("PREVIEW ONLY: no network request or GitHub write was made")
                    return 0
                if not args.yes:
                    raise ValueError("opening a GitHub pull request requires --open-pr --yes")
                url = open_submission_pr(payload, args.repo)
                print(f"Pull request: {url}")
                return 0
            config = load_json(Path(args.config))
            run_dir = run_pilot(
                config, Path(args.runs_dir), args.models, args.attempts,
                timeout=args.timeout,
                resume=Path(args.resume) if args.resume else None)
            print(f"Round 5 research evidence: {run_dir}")
            print(f"Pilot report: {run_dir / 'PILOT_REPORT.md'}")
            return 0
        return selftest()
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError,
            subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
