"""Send saved prompts to a LOCAL model and write a recording. Standalone: stdlib only.

  python -m services.businessrule prompts --out prompts.json      (on a machine with the platform)
  python scripts/record_replies.py --prompts prompts.json --model <name> --out recording.json

Works on plain Windows. The recording is {"model": ..., "calls": {prompt hash: reply}} and is
replayed by `python -m services.businessrule run --recording recording.json`. The prompts hold
the synthetic fixture's code only; do not use this on code you may not share.
"""

import argparse
import hashlib
import ipaddress
import json
import sys
import time
import urllib.request
from urllib.parse import urlsplit


def check_local(endpoint: str) -> None:
    host = urlsplit(endpoint).hostname or ""
    if host == "localhost":
        return
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        sys.exit(f"Refusing {endpoint}: not a local address.")
    if not (ip.is_loopback or ip.is_private):
        sys.exit(f"Refusing {endpoint}: not a local address.")


def ask(endpoint: str, model: str, prompt: str, timeout: float) -> dict[str, object]:
    body = json.dumps(
        {
            "model": model,
            "temperature": 0,
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/chat/completions", body, {"Content-Type": "application/json"}
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        data: dict[str, object] = json.load(resp)
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", default="recording.json")
    ap.add_argument("--endpoint", default="http://127.0.0.1:11434/v1")
    ap.add_argument("--timeout", type=float, default=120.0)
    a = ap.parse_args()
    check_local(a.endpoint)
    with open(a.prompts, encoding="utf-8") as f:
        prompts: dict[str, str] = json.load(f)
    calls: dict[str, dict[str, object]] = {}
    failed = 0
    for n, (digest, prompt) in enumerate(sorted(prompts.items()), 1):
        if hashlib.sha256(prompt.encode("utf-8")).hexdigest() != digest:
            sys.exit("prompts.json was edited: a hash does not match its prompt.")
        start = time.monotonic()
        try:
            data = ask(a.endpoint, a.model, prompt, a.timeout)
            text = data["choices"][0]["message"]["content"]  # type: ignore[index]
            usage: dict[str, int] = data.get("usage") or {}  # type: ignore[assignment]
        except Exception as exc:  # noqa: BLE001 - keep going, report at the end
            failed += 1
            print(f"{n}/{len(prompts)} FAILED {type(exc).__name__}: {exc}")
            continue
        calls[digest] = {
            "text": text,
            "tokens_in": int(usage.get("prompt_tokens") or max(1, len(prompt) // 4)),
            "tokens_out": int(usage.get("completion_tokens") or max(1, len(text) // 4)),
        }
        print(f"{n}/{len(prompts)} ok in {time.monotonic() - start:.1f}s")
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"model": a.model, "calls": calls}, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"Wrote {a.out}: {len(calls)} replies, {failed} failed.")


if __name__ == "__main__":
    main()
