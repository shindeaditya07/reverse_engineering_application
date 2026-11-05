"""Fetch one revision of a GitHub repository without running anything from it (SEC-1.1, SEC-1.7).

Only https://github.com/<owner>/<repo> is accepted. The token, if any, travels in the
environment of the git process, never on its command line, and is scrubbed from every error.
Hooks, credential helpers, submodules and every protocol except the allowed one are off.
"""

import base64
import os
import re
import subprocess
from pathlib import Path

from services.ingest.errors import IngestError

# Implementation bound, not a rule (see scan.SCAN_MAX_BYTES).
GIT_TIMEOUT_SECONDS = 600
_URL = re.compile(
    r"^https://github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9_.-]{1,100}?)(?:\.git)?/?$"
)
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_PASS_THROUGH = (
    "PATH",
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "NO_PROXY",
    "no_proxy",
    "SSL_CERT_FILE",
    "GIT_SSL_CAINFO",
    "CURL_CA_BUNDLE",
)


def validate_github_url(url: str) -> str:
    """Return the canonical clone URL, or raise. No credentials, ports, queries or other hosts."""
    match = _URL.match(url.strip())
    if match is None or match.group(2).strip(".") == "":
        raise IngestError("bad_url", "expected https://github.com/<owner>/<repo>")
    return f"https://github.com/{match.group(1)}/{match.group(2)}.git"


def validate_ref(ref: str | None) -> str:
    """A branch, tag or commit SHA. Never starts with '-', so it cannot act as a git option."""
    if ref is None:
        return "HEAD"
    if _REF.match(ref) is None or ".." in ref or "//" in ref or ref.endswith(("/", ".lock")):
        raise IngestError("bad_ref", "ref must be a plain branch, tag or commit SHA")
    return ref


def git_env(token: str | None, allow_protocol: str) -> dict[str, str]:
    env = {key: os.environ[key] for key in _PASS_THROUGH if key in os.environ}
    config = {"core.hooksPath": os.devnull, "credential.helper": ""}
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        config["http.https://github.com/.extraheader"] = f"AUTHORIZATION: basic {basic}"
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ALLOW_PROTOCOL": allow_protocol,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "LC_ALL": "C",
            "GIT_CONFIG_COUNT": str(len(config)),
        }
    )
    for index, (key, value) in enumerate(config.items()):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    return env


def _scrub(text: str, token: str | None) -> str:
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        text = text.replace(token, "[token]").replace(basic, "[token]")
    return text.strip()[:500]


def _git(args: list[str], cwd: Path, env: dict[str, str], token: str | None, timeout: int) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as error:
        raise IngestError("git_missing", "git is not installed") from error
    except subprocess.TimeoutExpired as error:
        raise IngestError("git_timeout", f"git {args[0]} took longer than {timeout} s") from error
    if result.returncode != 0:
        raise IngestError("git_failed", f"git {args[0]}: {_scrub(result.stderr, token)}")
    return result.stdout


def fetch_revision(
    remote: str,
    ref: str,
    dest: Path,
    *,
    token: str | None = None,
    allow_protocol: str = "https",
    timeout: int = GIT_TIMEOUT_SECONDS,
) -> str:
    """Fetch a single revision into dest, check it out detached, and return its commit SHA."""
    dest.mkdir(parents=True)
    env = git_env(token, allow_protocol)
    steps = (
        ["init", "-q"],
        ["remote", "add", "origin", remote],
        ["fetch", "-q", "--depth", "1", "--no-tags", "--no-recurse-submodules", "origin", ref],
        ["checkout", "-q", "--detach", "FETCH_HEAD"],
    )
    for step in steps:
        _git(step, dest, env, token, timeout)
    sha = _git(["rev-parse", "HEAD"], dest, env, token, timeout).strip()
    if _SHA.match(sha) is None:
        raise IngestError("git_failed", "git did not return a commit SHA")
    return sha
