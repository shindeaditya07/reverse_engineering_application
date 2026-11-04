import shutil
from pathlib import Path

import pytest

from scripts import policy_check

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    shutil.copy(ROOT / "docs" / "policies.md", tmp_path / "docs" / "policies.md")
    shutil.copy(ROOT / "policy_constants.yaml", tmp_path / "policy_constants.yaml")
    shutil.copy(ROOT / ".policy_lock", tmp_path / ".policy_lock")
    return tmp_path


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_real_repo_passes() -> None:
    assert policy_check.check(ROOT) == []


def test_changed_policy_without_version_bump_fails(repo: Path) -> None:
    edit(repo / "docs" / "policies.md", "Every claim cites evidence.", "Every claim cites proof.")
    assert any("still 0.1: bump it" in e for e in policy_check.check(repo))


def test_version_bump_without_relock_fails(repo: Path) -> None:
    edit(repo / "docs" / "policies.md", "Policy version **0.1", "Policy version **0.2")
    errors = policy_check.check(repo)
    assert any("rerun with --lock" in e for e in errors)
    assert any("policy_version 0.1 in the YAML != 0.2" in e for e in errors)


def test_value_drift_between_yaml_and_notes_fails(repo: Path) -> None:
    edit(repo / "policy_constants.yaml", "accuracy_target: 0.90", "accuracy_target: 0.95")
    assert any("accuracy_target" in e and "notes say" in e for e in policy_check.check(repo))


def test_constant_keyed_to_the_wrong_passage_fails(repo: Path) -> None:
    edit(repo / "policy_constants.yaml", "TST-7.4:", "TST-7.5:")
    errors = policy_check.check(repo)
    assert any("char_test_stability_runs: not named in TST-7.5" in e for e in errors)
    assert any("named in TST-7.4 but keyed to TST-7.5" in e for e in errors)


def test_constant_missing_from_notes_fails(repo: Path) -> None:
    edit(repo / "docs" / "policies.md", "  - `char_test_stability_runs = 3` (TST-7.4)\n", "")
    assert any("missing from the developer notes" in e for e in policy_check.check(repo))


def test_crlf_checkout_hashes_the_same(repo: Path) -> None:
    policies = repo / "docs" / "policies.md"
    policies.write_bytes(policies.read_bytes().replace(b"\n", b"\r\n"))
    assert policy_check.check(repo) == []


def test_missing_lock_fails(repo: Path) -> None:
    (repo / ".policy_lock").unlink()
    assert any(".policy_lock is missing" in e for e in policy_check.check(repo))
