#!/usr/bin/env python3
"""Execute q38's positive and adversarial webhook control matrix."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "repo"
HIDDEN = HERE / "hidden" / "hidden_tests.py"


CORRECT = '''"""Authenticated, concurrent replay-safe webhook processing."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading


class WebhookError(ValueError):
    pass


_KID = re.compile(r"[A-Za-z0-9._-]+")
_TIMESTAMP = re.compile(r"0|[1-9][0-9]*")
_SIGNATURE = re.compile(r"[0-9a-f]{64}")


def _header(value):
    fields = {"t": [], "kid": [], "v1": []}
    if not isinstance(value, str) or not value:
        raise WebhookError("malformed signature header")
    for part in value.split(","):
        if part.count("=") != 1:
            raise WebhookError("malformed signature header")
        name, item = part.split("=", 1)
        if name not in fields or not item:
            raise WebhookError("malformed signature header")
        fields[name].append(item)
    if len(fields["t"]) != 1 or len(fields["kid"]) != 1 or not fields["v1"]:
        raise WebhookError("malformed signature header")
    timestamp, kid = fields["t"][0], fields["kid"][0]
    if (not _TIMESTAMP.fullmatch(timestamp) or not _KID.fullmatch(kid)
            or any(not _SIGNATURE.fullmatch(item) for item in fields["v1"])):
        raise WebhookError("malformed signature header")
    return int(timestamp), kid, fields["v1"]


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WebhookError("duplicate JSON key")
        result[key] = value
    return result


class WebhookProcessor:
    def __init__(self, keys, handler, clock, tolerance_seconds=300):
        if (isinstance(tolerance_seconds, bool)
                or not isinstance(tolerance_seconds, int)
                or tolerance_seconds < 0):
            raise ValueError("tolerance_seconds must be a non-negative integer")
        normalized = {}
        for kid, value in dict(keys).items():
            secrets = value if isinstance(value, (tuple, list)) else (value,)
            if (not secrets or any(not isinstance(secret, bytes) or not secret
                                   for secret in secrets)):
                raise ValueError("webhook secrets must be non-empty bytes")
            normalized[kid] = tuple(secrets)
        self._keys = normalized
        self._handler = handler
        self._clock = clock
        self._tolerance = tolerance_seconds
        self._lock = threading.Lock()
        self._pending = set()
        self._done = set()

    def process(self, body, signature_header):
        if not isinstance(body, bytes):
            raise WebhookError("body must be bytes")
        timestamp, kid, signatures = _header(signature_header)
        now = self._clock()
        if (isinstance(now, bool) or not isinstance(now, (int, float))
                or abs(now - timestamp) > self._tolerance):
            raise WebhookError("timestamp outside tolerance")
        secrets = self._keys.get(kid)
        if not secrets:
            raise WebhookError("unknown key")
        candidate_body = body
        signed = str(timestamp).encode("ascii") + b"." + candidate_body
        expected = [hmac.new(secret, signed, hashlib.sha256).hexdigest()
                    for secret in secrets]
        authenticated = any(
            hmac.compare_digest(candidate, supplied)
            for candidate in expected for supplied in signatures)
        if not authenticated:
            raise WebhookError("invalid signature")
        try:
            payload = json.loads(body, object_pairs_hook=_object)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebhookError("invalid JSON") from exc
        if not isinstance(payload, dict):
            raise WebhookError("webhook JSON must be an object")
        token = (kid, timestamp, hashlib.sha256(signed).digest())
        with self._lock:
            if token in self._pending or token in self._done:
                raise WebhookError("replayed webhook")
            self._pending.add(token)
        try:
            result = self._handler(payload)
        except BaseException:
            with self._lock:
                self._pending.discard(token)
            raise
        with self._lock:
            self._pending.discard(token)
            self._done.add(token)
        return result
'''


def _implementation(state: str) -> str:
    source = CORRECT
    if state == "canonical_body":
        source = source.replace(
            "        candidate_body = body",
            "        candidate_body = json.dumps(json.loads(body), separators=(\",\", \":\")).encode()")
    elif state == "first_signature":
        source = source.replace(
            "for candidate in expected for supplied in signatures)",
            "for candidate in expected for supplied in signatures[:1])")
    elif state == "current_secret_only":
        source = source.replace("for secret in secrets]", "for secret in secrets[:1]]")
    elif state == "open_timestamp_boundary":
        source = source.replace(
            "or abs(now - timestamp) > self._tolerance):",
            "or abs(now - timestamp) >= self._tolerance):")
    elif state == "past_only_window":
        source = source.replace(
            "or abs(now - timestamp) > self._tolerance):",
            "or now - timestamp > self._tolerance):")
    elif state == "late_reservation":
        source = source.replace(
            "            if token in self._pending or token in self._done:\n"
            "                raise WebhookError(\"replayed webhook\")\n"
            "            self._pending.add(token)",
            "            if token in self._done:\n"
            "                raise WebhookError(\"replayed webhook\")")
    elif state == "stuck_failure":
        source = source.replace(
            "            with self._lock:\n"
            "                self._pending.discard(token)\n"
            "            raise",
            "            raise")
    elif state == "global_handler_lock":
        source = source.replace(
            "            result = self._handler(payload)",
            "            with self._lock:\n"
            "                result = self._handler(payload)")
    elif state == "body_only_replay":
        source = source.replace(
            "token = (kid, timestamp, hashlib.sha256(signed).digest())",
            "token = hashlib.sha256(body).digest()")
    elif state == "duplicate_json":
        source = source.replace(
            "        if key in result:\n"
            "            raise WebhookError(\"duplicate JSON key\")\n",
            "")
    elif state == "scalar_json":
        source = source.replace(
            "        if not isinstance(payload, dict):\n"
            "            raise WebhookError(\"webhook JSON must be an object\")\n",
            "")
    return source


def _apply(state: str, repo: Path) -> None:
    if state == "baseline":
        return
    valid = {
        "correct", "canonical_body", "first_signature", "current_secret_only",
        "open_timestamp_boundary", "past_only_window", "late_reservation",
        "stuck_failure", "global_handler_lock", "body_only_replay",
        "duplicate_json", "scalar_json", "tamper",
    }
    if state not in valid:
        raise ValueError(state)
    implementation = "correct" if state == "tamper" else state
    (repo / "webhook.py").write_text(
        _implementation(implementation), encoding="utf-8")
    if state == "tamper":
        with (repo / "run_tests.py").open("a", encoding="utf-8") as handle:
            handle.write("\n# candidate changed protected public-test authority\n")


def _run(command: list[str], cwd: Path) -> tuple[int, int, str]:
    proc = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=20)
    output = proc.stdout + proc.stderr
    match = re.search(r"(?:PUBLIC|HIDDEN): (\d+)/(\d+)", output)
    if not match:
        raise RuntimeError(f"control command produced no score: {output[-1000:]}")
    return int(match.group(1)), int(match.group(2)), output


def main() -> int:
    states = (
        "baseline", "correct", "canonical_body", "first_signature",
        "current_secret_only", "open_timestamp_boundary", "past_only_window",
        "late_reservation", "stuck_failure", "global_handler_lock",
        "body_only_replay", "duplicate_json", "scalar_json", "tamper",
    )
    results = {}
    with tempfile.TemporaryDirectory(prefix="llm-hardtest-r5-q38-") as tmp:
        for state in states:
            repo = Path(tmp) / state
            shutil.copytree(SOURCE, repo)
            _apply(state, repo)
            public = _run([sys.executable, "run_tests.py"], repo)
            hidden = _run([sys.executable, str(HIDDEN), str(repo)], repo)
            results[state] = (public[:2], hidden[:2])
            print(f"{state:23} public {public[0]}/{public[1]} "
                  f"hidden {hidden[0]}/{hidden[1]}")
    checks = [
        (results["baseline"][0][0] < results["baseline"][0][1],
         "baseline must fail public tests"),
        (results["correct"][0][0] == results["correct"][0][1],
         "correct control must pass public tests"),
        (results["correct"][1][0] == results["correct"][1][1],
         "correct control must pass hidden tests"),
    ]
    for state in states[2:]:
        public, hidden = results[state]
        checks.append((public[0] == public[1], f"{state} must look public-green"))
        checks.append((hidden[0] < hidden[1], f"{state} must fail held-back checks"))
    failed = [message for ok, message in checks if not ok]
    if failed:
        print("PILOT_CONTROL_MATRIX=False")
        for message in failed:
            print("- " + message)
        return 1
    print("PILOT_CONTROL_MATRIX=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
