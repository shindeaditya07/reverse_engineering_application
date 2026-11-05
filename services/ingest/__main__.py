"""Pin a source and print a summary: python -m services.ingest <github-url-or-path> [--ref REF].

Prints counts and finding kinds only, never a matched value. The GitHub token, if needed for a
private repository, comes from GITHUB_TOKEN through Settings and stays on this machine.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from services.api.settings import get_settings
from services.ingest.errors import IngestError
from services.ingest.pin import PinnedSource, pin_github, pin_local


def _summary(pinned: PinnedSource) -> dict[str, object]:
    return {
        "kind": pinned.kind,
        "origin": pinned.origin,
        "revision": pinned.revision,
        "pinned_copy": str(pinned.root),
        "files": len(pinned.tree.files),
        "bytes": pinned.tree.total_bytes,
        "skipped": [{"path": s.path, "reason": s.reason} for s in pinned.tree.skipped],
        "excluded": list(pinned.tree.excluded),
        "unscanned": [{"path": p, "reason": r} for p, r in pinned.report.unscanned],
        "findings": dict(Counter(f.kind for f in pinned.report.findings)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="GitHub repository URL or local directory")
    parser.add_argument("--ref", help="branch, tag or commit SHA (GitHub URLs only)")
    args = parser.parse_args(argv)
    settings = get_settings()
    store = Path(settings.snapshot_dir)
    try:
        if args.source.startswith(("http://", "https://", "git@", "ssh://", "git://")):
            token = settings.github_token.get_secret_value() if settings.github_token else None
            pinned = pin_github(args.source, store, ref=args.ref, token=token)
        else:
            if args.ref:
                raise IngestError("bad_ref", "--ref only applies to GitHub URLs")
            pinned = pin_local(args.source, store)
    except IngestError as error:
        print(f"Rejected: {error}", file=sys.stderr)
        return 1
    print(json.dumps(_summary(pinned), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
