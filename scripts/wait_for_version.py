"""Wait until a deployed /healthz reports the expected commit.

Health alone is not enough: Render can roll back to an older image while the old
instance keeps answering /healthz (docs/branching-and-environments.md, staging deploy).
Exit 0 only when the reported version equals the expected one; exit 1 on timeout.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable


def fetch_version(url: str) -> str | None:
    """Return the version reported by /healthz, or None if unreachable or not ready."""
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            body = json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    version = body.get("version") if isinstance(body, dict) else None
    return version if isinstance(version, str) else None


def wait_for_version(
    expected: str,
    fetch: Callable[[], str | None],
    timeout_seconds: float,
    interval_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> bool:
    deadline = monotonic() + timeout_seconds
    while True:
        if fetch() == expected:
            return True
        if monotonic() >= deadline:
            return False
        sleep(interval_seconds)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--interval", type=float, default=10)
    args = parser.parse_args()
    url = args.base_url.rstrip("/") + "/healthz"
    if wait_for_version(args.expected, lambda: fetch_version(url), args.timeout, args.interval):
        print(f"{url} reports {args.expected}")
        return 0
    print(f"timed out: {url} never reported {args.expected}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
