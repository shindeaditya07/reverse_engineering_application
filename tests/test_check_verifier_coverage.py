"""The coverage gate for the verifier package (VER-1.5)."""

import json
from pathlib import Path

import pytest

from scripts import check_verifier_coverage as gate


def report(
    covered: int, total: int, name: str = "services/verifier/verify.py"
) -> dict[str, object]:
    return {
        "files": {
            name: {"summary": {"covered_branches": covered, "num_branches": total}},
            "services/other.py": {"summary": {"covered_branches": 0, "num_branches": 100}},
        }
    }


def test_counts_only_branches_in_the_verifier_package() -> None:
    assert gate.branch_percent(report(95, 100)) == (95.0, 1)
    assert gate.branch_percent(report(1, 2, r"services\verifier\x.py")) == (50.0, 1)  # Windows path


def test_no_branches_counts_as_zero() -> None:
    assert gate.branch_percent({"files": {}}) == (0.0, 0)


@pytest.mark.parametrize(("covered", "expected"), [(95, 0), (94, 1), (100, 0)])
def test_main_threshold(
    covered: int, expected: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "coverage.json").write_text(json.dumps(report(covered, 100)))
    monkeypatch.setattr(gate, "COVERAGE", tmp_path / "coverage.json")
    assert gate.main() == expected


def test_main_fails_without_a_report_or_without_verifier_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "COVERAGE", tmp_path / "missing.json")
    assert gate.main() == 1
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"files": {}}))
    monkeypatch.setattr(gate, "COVERAGE", empty)
    assert gate.main() == 1
