#!/usr/bin/env python3
"""Execute q40's positive and adversarial SSRF control matrix."""

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


CORRECT = '''"""Fail-closed outbound HTTPS client with per-hop DNS pinning."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping
from urllib.parse import urljoin, urlsplit, urlunsplit


class FetchError(RuntimeError):
    pass


_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_REDIRECTS = {301, 302, 303, 307, 308}


def _bounded_integer(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _normalize_url(value):
    if not isinstance(value, str):
        raise FetchError("URL must be text")
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() != "https" or not parsed.netloc or not parsed.hostname:
            raise FetchError("absolute HTTPS URL required")
        if parsed.username is not None or parsed.password is not None or parsed.fragment:
            raise FetchError("credentials and fragments are forbidden")
        port = parsed.port or 443
    except (TypeError, ValueError, UnicodeError) as exc:
        if isinstance(exc, FetchError):
            raise
        raise FetchError("invalid URL authority") from exc
    raw_host = parsed.hostname
    if "%" in raw_host:
        raise FetchError("zone identifiers are forbidden")
    if raw_host.endswith("."):
        raw_host = raw_host[:-1]
        if not raw_host or raw_host.endswith("."):
            raise FetchError("invalid trailing dot")
    try:
        literal = ipaddress.ip_address(raw_host)
    except ValueError:
        try:
            host = raw_host.encode("idna").decode("ascii").lower()
        except (UnicodeError, ValueError) as exc:
            raise FetchError("invalid DNS hostname") from exc
        if not host or len(host) > 253 or any(not label or len(label) > 63
                                               for label in host.split(".")):
            raise FetchError("invalid DNS hostname")
        url_host = host
    else:
        host = literal.compressed
        url_host = f"[{host}]" if literal.version == 6 else host
    if not 1 <= port <= 65535:
        raise FetchError("invalid port")
    path = parsed.path or "/"
    target = path + (("?" + parsed.query) if parsed.query else "")
    netloc = url_host if port == 443 else f"{url_host}:{port}"
    canonical = urlunsplit(("https", netloc, path, parsed.query, ""))
    return canonical, host, port, target, (host, port), (host, port, target)


def _validate_header(name, value):
    if not isinstance(name, str) or not name.isascii() or not _TOKEN.fullmatch(name):
        raise FetchError("invalid header name")
    if not isinstance(value, str) or "\\r" in value or "\\n" in value:
        raise FetchError("invalid header value")


def _request_headers(headers):
    if headers is None:
        return {}
    if not isinstance(headers, Mapping):
        raise FetchError("headers must be a mapping")
    output = {}
    for name, value in headers.items():
        _validate_header(name, value)
        if name.lower() == "host":
            raise FetchError("Host is owned by the client")
        output[name] = value
    return output


def _response_headers(value):
    try:
        pairs = list(value)
    except (TypeError, ValueError) as exc:
        raise FetchError("response headers must be pairs") from exc
    output = []
    for pair in pairs:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise FetchError("response headers must be pairs")
        name, header_value = pair
        _validate_header(name, header_value)
        output.append((name, header_value))
    lengths = [item for name, item in output if name.lower() == "content-length"]
    if lengths:
        if any(not re.fullmatch(r"[0-9]+", item) for item in lengths):
            raise FetchError("invalid Content-Length")
        if len(set(lengths)) != 1:
            raise FetchError("conflicting Content-Length")
    return output, lengths


def _drop_credentials(headers):
    return {name: value for name, value in headers.items()
            if name.lower() not in {"authorization", "cookie"}}


class SafeHttpClient:
    def __init__(self, resolver, transport, max_redirects=5,
                 max_body_bytes=1_048_576):
        if not callable(resolver) or not callable(transport):
            raise ValueError("resolver and transport must be callable")
        self.resolver = resolver
        self.transport = transport
        self.max_redirects = _bounded_integer(max_redirects, "max_redirects")
        self.max_body_bytes = _bounded_integer(max_body_bytes, "max_body_bytes")

    def _resolve(self, host, port):
        try:
            addresses = list(self.resolver(host, port))
        except Exception as exc:
            raise FetchError("DNS resolution failed") from exc
        if not addresses:
            raise FetchError("hostname did not resolve")
        approved = []
        for address in addresses:
            if not isinstance(address, str) or "%" in address:
                raise FetchError("invalid DNS address")
            try:
                parsed_ip = ipaddress.ip_address(address)
            except ValueError as exc:
                raise FetchError("invalid DNS address") from exc
            mapped = getattr(parsed_ip, "ipv4_mapped", None)
            policy = mapped or parsed_ip
            if not policy.is_global:
                raise FetchError("non-global DNS address")
            approved.append(parsed_ip.compressed)
        return approved[0]

    def get(self, url, headers=None):
        request_headers = _request_headers(headers)
        current, host, port, target, origin, key = _normalize_url(url)
        seen = {key}
        redirects = 0
        while True:
            ip = self._resolve(host, port)
            outgoing = dict(request_headers)
            try:
                host_value = f"[{host}]" if ipaddress.ip_address(host).version == 6 else host
            except ValueError:
                host_value = host
            outgoing["Host"] = host_value if port == 443 else f"{host_value}:{port}"
            try:
                response = self.transport(ip, port, host, target, outgoing)
            except Exception as exc:
                raise FetchError("HTTPS transport failed") from exc
            if not isinstance(response, Mapping):
                raise FetchError("invalid response")
            status = response.get("status")
            if isinstance(status, bool) or not isinstance(status, int):
                raise FetchError("invalid response status")
            response_headers, lengths = _response_headers(response.get("headers", []))
            if status in _REDIRECTS:
                locations = [value for name, value in response_headers
                             if name.lower() == "location"]
                if len(locations) != 1 or not locations[0]:
                    raise FetchError("redirect requires exactly one Location")
                if redirects >= self.max_redirects:
                    raise FetchError("too many redirects")
                try:
                    next_url = urljoin(current, locations[0])
                except (TypeError, ValueError) as exc:
                    raise FetchError("invalid redirect") from exc
                normalized = _normalize_url(next_url)
                if normalized[5] in seen:
                    raise FetchError("redirect loop")
                if normalized[4] != origin:
                    request_headers = _drop_credentials(request_headers)
                current, host, port, target, origin, key = normalized
                seen.add(key)
                redirects += 1
                continue
            if not 200 <= status < 300:
                raise FetchError("unexpected status")
            if lengths and int(lengths[0]) > self.max_body_bytes:
                raise FetchError("response body is too large")
            body = response.get("body", [])
            try:
                iterator = iter(body)
            except TypeError as exc:
                raise FetchError("response body is not iterable") from exc
            chunks = []
            total = 0
            try:
                for chunk in iterator:
                    if not isinstance(chunk, bytes):
                        raise FetchError("response chunks must be bytes")
                    total += len(chunk)
                    if total > self.max_body_bytes:
                        raise FetchError("response body is too large")
                    chunks.append(chunk)
            except FetchError:
                raise
            except Exception as exc:
                raise FetchError("response body failed") from exc
            return b"".join(chunks)
'''


def _implementation(state: str) -> str:
    source = CORRECT
    if state == "first_address_only":
        source = source.replace("for address in addresses:",
                                "for address in addresses[:1]:")
    elif state == "mapped_allowed":
        source = source.replace(
            "if not policy.is_global:\n                raise FetchError(\"non-global DNS address\")",
            "if mapped is None and not policy.is_global:\n"
            "                raise FetchError(\"non-global DNS address\")")
    elif state == "zone_allowed":
        source = source.replace(
            'if not isinstance(address, str) or "%" in address:',
            'if not isinstance(address, str):')
    elif state == "no_idna":
        source = source.replace(
            'host = raw_host.encode("idna").decode("ascii").lower()',
            'host = raw_host.lower()')
    elif state == "drops_query":
        source = source.replace(
            'target = path + (("?" + parsed.query) if parsed.query else "")',
            'target = path')
    elif state == "double_resolve":
        source = source.replace(
            "ip = self._resolve(host, port)\n            outgoing = dict(request_headers)",
            "ip = self._resolve(host, port)\n"
            "            self.resolver(host, port)\n"
            "            outgoing = dict(request_headers)")
    elif state == "redirect_body_read":
        source = source.replace(
            "if status in _REDIRECTS:\n                locations =",
            "if status in _REDIRECTS:\n"
            "                list(response.get(\"body\", []))\n"
            "                locations =")
    elif state == "no_loop_detection":
        source = source.replace(
            'if normalized[5] in seen:\n                    raise FetchError("redirect loop")',
            'if False:\n                    raise FetchError("redirect loop")')
    elif state == "credential_forwarding":
        source = source.replace(
            "request_headers = _drop_credentials(request_headers)",
            "request_headers = dict(request_headers)")
    elif state == "weak_header_grammar":
        source = source.replace(
            'if name.lower() == "host":\n            raise FetchError("Host is owned by the client")',
            'if False:\n            raise FetchError("Host is owned by the client")')
    elif state == "last_content_length":
        source = source.replace(
            'if len(set(lengths)) != 1:\n            raise FetchError("conflicting Content-Length")',
            'if False:\n            raise FetchError("conflicting Content-Length")')
    elif state == "no_length_preflight":
        source = source.replace(
            'if lengths and int(lengths[0]) > self.max_body_bytes:',
            'if False:')
    elif state == "limit_off_by_one":
        source = source.replace(
            "> self.max_body_bytes", "> self.max_body_bytes + 1")
    elif state == "boolean_status":
        source = source.replace(
            "if isinstance(status, bool) or not isinstance(status, int):\n"
            "                raise FetchError(\"invalid response status\")",
            "if isinstance(status, bool):\n"
            "                status = 200\n"
            "            elif not isinstance(status, int):\n"
            "                raise FetchError(\"invalid response status\")")
    return source


def _apply(state: str, repo: Path) -> None:
    if state == "baseline":
        return
    valid = {
        "correct", "first_address_only", "mapped_allowed", "zone_allowed",
        "no_idna", "drops_query", "double_resolve", "redirect_body_read",
        "no_loop_detection", "credential_forwarding", "weak_header_grammar",
        "last_content_length", "no_length_preflight", "limit_off_by_one",
        "boolean_status", "tamper",
    }
    if state not in valid:
        raise ValueError(state)
    implementation = "correct" if state == "tamper" else state
    (repo / "safe_http.py").write_text(
        _implementation(implementation), encoding="utf-8")
    if state == "tamper":
        with (repo / "run_tests.py").open("a", encoding="utf-8") as handle:
            handle.write("\n# candidate changed protected public-test authority\n")


def _run(command: list[str], cwd: Path) -> tuple[int, int, str]:
    proc = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=30)
    output = proc.stdout + proc.stderr
    match = re.search(r"(?:PUBLIC|HIDDEN): (\d+)/(\d+)", output)
    if not match:
        raise RuntimeError(f"control command produced no score: {output[-1500:]}")
    return int(match.group(1)), int(match.group(2)), output


def main() -> int:
    states = (
        "baseline", "correct", "first_address_only", "mapped_allowed",
        "zone_allowed", "no_idna", "drops_query", "double_resolve",
        "redirect_body_read", "no_loop_detection", "credential_forwarding",
        "weak_header_grammar", "last_content_length", "no_length_preflight",
        "limit_off_by_one", "boolean_status", "tamper",
    )
    results = {}
    with tempfile.TemporaryDirectory(prefix="llm-hardtest-r5-q40-") as tmp:
        for state in states:
            repo = Path(tmp) / state
            shutil.copytree(SOURCE, repo)
            _apply(state, repo)
            public = _run([sys.executable, "run_tests.py"], repo)
            hidden = _run([sys.executable, str(HIDDEN), str(repo)], repo)
            results[state] = (public[:2], hidden[:2])
            print(f"{state:24} public {public[0]}/{public[1]} "
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
