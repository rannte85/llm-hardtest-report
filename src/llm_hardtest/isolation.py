from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


class IsolationError(RuntimeError):
    """A requested execution boundary is unavailable or failed closed."""


def _seatbelt_literal(value: str) -> str:
    return json.dumps(value)


class NoIsolation:
    mode = "none"
    command_prefix: list[str] = []
    env: dict[str, str] = {}

    def preflight(self, workdir: Path) -> dict:
        return {"status": "not_requested", "mandatory_checks_passed": True}

    def audit(self, transcript: str) -> dict:
        return {"status": "not_requested", "boundary_violation": False}

    @property
    def provenance(self) -> dict:
        return {
            "mode": self.mode,
            "fail_closed": False,
            "policy_hash": None,
            "network": "unrestricted",
        }


class MacOSSeatbeltIsolation:
    """Fail-closed macOS defense-in-depth boundary for one agent attempt."""

    mode = "macos_seatbelt"

    def __init__(self, config: dict, state_dir: Path,
                 protected_paths: dict[str, list[Path]] | list[Path],
                 allowed_write_paths: list[Path], base_url: str):
        if platform.system() != "Darwin":
            raise IsolationError("macos_seatbelt is unavailable on this platform")
        executable = shutil.which("sandbox-exec")
        if not executable:
            raise IsolationError("macos_seatbelt requested but sandbox-exec is unavailable")
        self.executable = executable
        self.config = config
        self.state_dir = state_dir.resolve()
        if isinstance(protected_paths, dict):
            categorized = protected_paths
        else:
            categorized = {"protected_material": protected_paths}
        self.protected_by_category = {
            name: sorted({path.resolve() for path in paths if path.exists()})
            for name, paths in categorized.items()
        }
        self.protected_paths = sorted({
            path for paths in self.protected_by_category.values() for path in paths})
        self.allowed_write_paths = sorted(
            {path.resolve() for path in allowed_write_paths})
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or not parsed.port:
            raise IsolationError(
                "model_endpoint_only requires an explicit http(s) endpoint port")
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise IsolationError("model_endpoint_only requires a loopback model endpoint")
        self.endpoint_host = parsed.hostname
        self.endpoint_port = parsed.port
        self.canary_dir = self.state_dir.parent / (self.state_dir.name + "-deny-canary")
        self.canary_dir.mkdir(parents=True, exist_ok=False)
        self.canary_token = hashlib.sha256(os.urandom(32)).hexdigest()
        for category in self.protected_by_category:
            category_dir = self.canary_dir / category
            category_dir.mkdir(parents=True)
            (category_dir / "secret.txt").write_text(
                self.canary_token + category, encoding="utf-8")
        self.protected_paths.append(self.canary_dir.resolve())
        self.protected_targets = {}
        for category, paths in self.protected_by_category.items():
            targets = [self.canary_dir / category / "secret.txt"]
            for path in paths:
                if path.is_file():
                    targets.append(path)
                    continue
                target = next((candidate for candidate in path.rglob("*")
                               if candidate.is_file()), None)
                if target is not None:
                    targets.append(target)
            self.protected_targets[category] = targets
        self._profile = ""
        self.command_prefix = []
        self.env = {}
        self._canary_result: dict | None = None

    def _build_profile(self, workdir: Path) -> str:
        write_paths = [workdir.resolve(), self.state_dir, *self.allowed_write_paths]
        lines = [
            "(version 1)",
            "(deny default)",
            "(allow process*)",
            "(allow sysctl-read)",
            "(allow mach-lookup)",
            "(allow file-read*)",
        ]
        for path in self.protected_paths:
            lines.append(
                f"(deny file-read* (subpath {_seatbelt_literal(str(path))}))")
        for path in write_paths:
            lines.append(
                f"(allow file-write* (subpath {_seatbelt_literal(str(path))}))")
        lines.extend([
            '(allow file-write-data (literal "/dev/null"))',
            '(allow file-write-data (literal "/dev/dtracehelper"))',
            f'(allow network-outbound (remote tcp "localhost:{self.endpoint_port}"))',
        ])
        return "\n".join(lines) + "\n"

    def preflight(self, workdir: Path) -> dict:
        self._profile = self._build_profile(workdir)
        policy_hash = "sha256:" + hashlib.sha256(
            self._profile.encode("utf-8")).hexdigest()
        tmp = self.state_dir / "tmp"
        home = self.state_dir / "home"
        for path in (tmp, home):
            path.mkdir(parents=True, exist_ok=True)
        self.env = {
            "HOME": str(home),
            "TMPDIR": str(tmp),
            "XDG_CONFIG_HOME": str(self.state_dir / "xdg-config"),
            "XDG_DATA_HOME": str(self.state_dir / "xdg-data"),
            "XDG_CACHE_HOME": str(self.state_dir / "xdg-cache"),
        }
        script = r'''
import json, pathlib, socket, sys
work = pathlib.Path(sys.argv[1])
protected = {name: [pathlib.Path(value) for value in values]
             for name, values in json.loads(sys.argv[2]).items()}
checks = {}
try:
    checks["work_read"] = (work / ".llm-hardtest-read-canary").read_text(encoding="utf-8") == "ok"
    (work / ".llm-hardtest-write-canary").write_text("ok", encoding="utf-8")
    checks["work_write"] = True
    (work / ".llm-hardtest-write-canary").unlink()
except OSError:
    checks["work_write"] = checks["work_read"] = False
for name, paths in protected.items():
    blocked = []
    for path in paths:
        try:
            path.read_bytes()
            blocked.append(False)
        except OSError:
            blocked.append(True)
    checks["blocked_" + name] = bool(blocked) and all(blocked)
endpoint = socket.socket()
endpoint.settimeout(2)
try:
    endpoint.connect((sys.argv[3], int(sys.argv[4])))
    checks["model_endpoint_reachable"] = True
except OSError:
    checks["model_endpoint_reachable"] = False
finally:
    endpoint.close()
external = socket.socket()
external.settimeout(1)
try:
    external.connect(("1.1.1.1", 53))
    checks["external_network_blocked"] = False
except PermissionError:
    checks["external_network_blocked"] = True
except OSError:
    checks["external_network_blocked"] = False
finally:
    external.close()
print(json.dumps(checks, sort_keys=True))
raise SystemExit(0 if all(checks.values()) else 3)
'''
        command = [
            self.executable, "-p", self._profile, sys.executable, "-c", script,
            str(workdir.resolve()),
            json.dumps({name: [str(path) for path in paths]
                        for name, paths in self.protected_targets.items()}),
            self.endpoint_host, str(self.endpoint_port),
        ]
        env = dict(os.environ)
        env.update(self.env)
        read_canary = workdir / ".llm-hardtest-read-canary"
        if read_canary.exists():
            raise IsolationError("Seatbelt work canary path already exists")
        read_canary.write_text("ok", encoding="utf-8")
        try:
            probe = subprocess.run(
                command, text=True, capture_output=True, env=env, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise IsolationError(f"Seatbelt canary could not run: {exc}") from exc
        finally:
            read_canary.unlink(missing_ok=True)
        try:
            checks = json.loads((probe.stdout or "").splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise IsolationError(
                "Seatbelt canary returned malformed evidence") from exc
        mandatory = {"work_write", "work_read", "model_endpoint_reachable",
                     "external_network_blocked"}
        mandatory.update("blocked_" + name for name in self.protected_targets)
        passed = (probe.returncode == 0 and mandatory.issubset(checks)
                  and all(checks[name] is True for name in mandatory))
        self._canary_result = {
            "status": "pass" if passed else "fail",
            "mandatory_checks_passed": passed,
            "checks": {name: bool(checks.get(name)) for name in sorted(mandatory)},
        }
        if not passed:
            raise IsolationError("Seatbelt mandatory canary failed closed")
        self.command_prefix = [self.executable, "-p", self._profile]
        self._policy_hash = policy_hash
        return self._canary_result

    def audit(self, transcript: str) -> dict:
        violation = self.canary_token in (transcript or "")
        return {
            "status": "fail" if violation else "pass",
            "boundary_violation": violation,
            "canary_disclosure": violation,
        }

    @property
    def provenance(self) -> dict:
        return {
            "mode": self.mode,
            "fail_closed": True,
            "policy_hash": getattr(self, "_policy_hash", None),
            "network": "model_endpoint_only",
            "canary": self._canary_result,
        }


def make_isolation(config: dict | None, state_dir: Path,
                   protected_paths: dict[str, list[Path]] | list[Path],
                   allowed_write_paths: list[Path],
                   base_url: str):
    if not config or config.get("mode", "none") == "none":
        return NoIsolation()
    if config.get("mode") == "macos_seatbelt":
        return MacOSSeatbeltIsolation(
            config, state_dir, protected_paths, allowed_write_paths, base_url)
    raise IsolationError(f"unknown Round 4 isolation mode {config.get('mode')!r}")
