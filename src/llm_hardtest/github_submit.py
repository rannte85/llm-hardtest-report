from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

from .public_pilots import load_public_pilot_bundle, validate_public_pilot_result
from .public_results import load_public_bundle, validate_public_result


DEFAULT_REPOSITORY = "rannte85/llm-hardtest-report"
REPOSITORY_COMPONENT = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")


def submission_relative_path(payload: dict) -> str:
    digest = payload["bundle_id"].removeprefix("sha256:")
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("submission has an invalid bundle ID")
    directory = "pilots" if "pilot" in payload else "submissions"
    return f"results/{directory}/{digest}.json"


def submission_document(payload: dict) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def preview_submission(path: Path) -> tuple[dict, str, str]:
    payload = load_public_bundle(path)
    return payload, submission_relative_path(payload), submission_document(payload)


def preview_pilot_submission(path: Path) -> tuple[dict, str, str]:
    payload = load_public_pilot_bundle(path)
    return payload, submission_relative_path(payload), submission_document(payload)


class GitHubCLI:
    """Small argument-array wrapper; no shell interpolation or credential logging."""

    def __init__(self):
        if not shutil.which("gh"):
            raise ValueError("GitHub submission requires the gh CLI on PATH")

    def request(self, method: str, endpoint: str, fields: dict | None = None,
                allow_missing: bool = False):
        command = ["gh", "api", endpoint]
        if method != "GET":
            command += ["--method", method]
        for key, value in (fields or {}).items():
            command += ["-f", f"{key}={value}"]
        proc = subprocess.run(command, text=True, capture_output=True)
        if allow_missing and proc.returncode and "HTTP 404" in proc.stderr:
            return None
        if proc.returncode:
            message = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "unknown error"
            raise RuntimeError(f"GitHub API request failed for {endpoint}: {message}")
        return json.loads(proc.stdout) if proc.stdout.strip() else {}


def _repository(value: str) -> tuple[str, str]:
    parts = value.split("/")
    if (len(parts) != 2
            or any(REPOSITORY_COMPONENT.fullmatch(part) is None for part in parts)):
        raise ValueError("repository must use the OWNER/NAME form")
    return parts[0], parts[1]


def open_submission_pr(payload: dict, repository: str = DEFAULT_REPOSITORY,
                       client: GitHubCLI | None = None,
                       wait_seconds: int = 30) -> str:
    """Create one result file and PR after the caller has obtained explicit consent."""
    if "pilot" in payload:
        validate_public_pilot_result(payload)
    else:
        validate_public_result(payload)
    owner, name = _repository(repository)
    relative = submission_relative_path(payload)
    document = submission_document(payload)
    client = client or GitHubCLI()
    user = client.request("GET", "user").get("login")
    if not isinstance(user, str) or REPOSITORY_COMPONENT.fullmatch(user) is None:
        raise RuntimeError("GitHub CLI did not return the signed-in account")
    upstream = client.request("GET", f"repos/{owner}/{name}")
    default_branch = upstream.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        raise RuntimeError("GitHub repository has no default branch")
    if client.request("GET", f"repos/{owner}/{name}/contents/{relative}",
                      allow_missing=True) is not None:
        raise ValueError(f"this bundle is already published at {relative}")

    if user.lower() == owner.lower():
        target = f"{owner}/{name}"
        head = None
    else:
        target = f"{user}/{name}"
        fork = client.request("GET", f"repos/{target}", allow_missing=True)
        if fork is None:
            client.request("POST", f"repos/{owner}/{name}/forks")
            deadline = time.monotonic() + max(1, wait_seconds)
            while time.monotonic() < deadline:
                fork = client.request("GET", f"repos/{target}", allow_missing=True)
                if fork is not None:
                    break
                time.sleep(1)
            if fork is None:
                raise RuntimeError("GitHub fork was not ready; retry the same submit command")
        client.request("POST", f"repos/{target}/merge-upstream",
                       {"branch": default_branch})
        head = f"{user}:"

    encoded_default = quote(default_branch, safe="")
    base_ref = client.request("GET", f"repos/{target}/git/ref/heads/{encoded_default}")
    sha = (base_ref.get("object") or {}).get("sha")
    if not isinstance(sha, str) or not sha:
        raise RuntimeError("GitHub did not return the target default-branch commit")
    digest = payload["bundle_id"].removeprefix("sha256:")
    branch = f"llm-hardtest-result/{digest[:12]}"
    client.request("POST", f"repos/{target}/git/refs",
                   {"ref": f"refs/heads/{branch}", "sha": sha})
    encoded_path = quote(relative, safe="/")
    client.request("PUT", f"repos/{target}/contents/{encoded_path}", {
        "message": f"results: add public bundle {digest[:12]}",
        "content": base64.b64encode(document.encode("utf-8")).decode("ascii"),
        "branch": branch,
    })
    model_names = ", ".join(
        "`" + model["public_name"].replace("`", "'") + "`"
        for model in payload["models"])
    if "pilot" in payload:
        heading = "Voluntary public Round 5 pilot result"
        scope = (f"- Pilot: `{payload['pilot']['id']}`\n"
                 f"- Pack: `{payload['pilot']['pack']}`\n")
    else:
        heading = "Voluntary public result"
        scope = f"- Rounds: {payload['benchmark']['rounds']}\n"
    body = (
        f"## {heading}\n\n"
        f"- Bundle: `{payload['bundle_id']}`\n"
        f"- Models: {model_names}\n"
        f"{scope}\n"
        "I previewed the complete submission JSON and intentionally publish these "
        "allowlisted aggregate fields. No raw run artifacts are included.\n"
    )
    pull = client.request("POST", f"repos/{owner}/{name}/pulls", {
        "title": f"Results: add public bundle {digest[:12]}",
        "head": (head + branch) if head else branch,
        "base": default_branch,
        "body": body,
    })
    url = pull.get("html_url")
    if not isinstance(url, str) or not url.startswith("https://github.com/"):
        raise RuntimeError(
            f"result branch {target}:{branch} was created, but GitHub returned no PR URL")
    return url
