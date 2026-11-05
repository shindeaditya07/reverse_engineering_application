"""Fail unless services/verifier/ has enough branch coverage (VER-1.5, AGENTS.md).

Reads coverage.json (written by `make test`) and the threshold from rules_constants.yaml. It
counts branches only, the stricter reading: covered branches over all branches in the package.
"""

import json
import sys
from pathlib import Path
from typing import Any

import yaml

PACKAGE = "services/verifier/"
COVERAGE = Path("coverage.json")
CONSTANTS = Path("rules_constants.yaml")


def branch_percent(data: dict[str, Any], package: str = PACKAGE) -> tuple[float, int]:
    """(percent of branches covered, number of files counted). 0 files is a failure upstream."""
    covered = total = files = 0
    for name, info in data.get("files", {}).items():
        if name.replace("\\", "/").startswith(package):
            summary = info["summary"]
            covered += summary["covered_branches"]
            total += summary["num_branches"]
            files += 1
    return (100.0 * covered / total if total else 0.0), files


def main() -> int:
    threshold = yaml.safe_load(CONSTANTS.read_text(encoding="utf-8"))["VER-1.5"][
        "min_verifier_branch_coverage_percent"
    ]
    if not COVERAGE.exists():
        print(f"{COVERAGE} not found: run the tests with --cov-branch first", file=sys.stderr)
        return 1
    percent, files = branch_percent(json.loads(COVERAGE.read_text(encoding="utf-8")))
    if files == 0:
        print(f"no files under {PACKAGE} in {COVERAGE}", file=sys.stderr)
        return 1
    print(f"verifier branch coverage {percent:.1f}% over {files} files (required {threshold}%)")
    return 0 if percent >= threshold else 1


if __name__ == "__main__":
    sys.exit(main())
