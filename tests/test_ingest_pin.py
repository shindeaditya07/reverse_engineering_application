"""Pinning a local path: read-only copy, content-hash revision, source never modified."""

import json
import os
import stat
from pathlib import Path

import pytest

from services.ingest.__main__ import main
from services.ingest.errors import IngestError
from services.ingest.limits import MIB, Limits
from services.ingest.pin import pin_local, verify

LIMITS = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
ROOT = Path(__file__).resolve().parent.parent


def make_source(root: Path) -> Path:
    for rel, content in {
        "app.js": b"one\n",
        "lib/util.js": b"two\r\n",
        ".git/HEAD": b"ref",
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root


def snapshot_of(root: Path) -> dict[str, tuple[bytes, int, int]]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            info = path.stat()
            result[str(path.relative_to(root))] = (
                path.read_bytes(),
                info.st_mtime_ns,
                info.st_mode,
            )
    return result


def rejected(*args: object, **kwargs: object) -> str:
    with pytest.raises(IngestError) as caught:
        pin_local(*args, **kwargs)  # type: ignore[arg-type]
    return caught.value.code


def test_pins_a_copy_named_by_its_content_hash(tmp_path: Path) -> None:
    source = make_source(tmp_path / "src")
    pinned = pin_local(source, tmp_path / "store", LIMITS)
    assert pinned.kind == "local_path"
    assert pinned.origin == str(source.resolve())
    assert pinned.revision == pinned.tree.tree_hash
    assert pinned.root == (tmp_path / "store").resolve() / pinned.revision
    assert (pinned.root / "lib/util.js").read_bytes() == b"two\r\n"
    assert not (pinned.root / ".git").exists()
    assert pinned.tree.excluded == (".git",)


def test_the_source_is_not_modified(tmp_path: Path) -> None:
    source = make_source(tmp_path / "src")
    before = snapshot_of(source)
    pin_local(source, tmp_path / "store", LIMITS)
    assert snapshot_of(source) == before
    assert sorted(os.listdir(source)) == [".git", "app.js", "lib"]


def test_the_pinned_copy_is_read_only(tmp_path: Path) -> None:
    pinned = pin_local(make_source(tmp_path / "src"), tmp_path / "store", LIMITS)
    for path in pinned.root.rglob("*"):
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == (0o555 if path.is_dir() else 0o444), path
    assert stat.S_IMODE(pinned.root.stat().st_mode) == 0o555


def test_same_content_gives_the_same_revision_and_reuses_the_copy(tmp_path: Path) -> None:
    store = tmp_path / "store"
    first = pin_local(make_source(tmp_path / "a"), store, LIMITS)
    second = pin_local(make_source(tmp_path / "b"), store, LIMITS)
    assert first.revision == second.revision
    assert first.root == second.root
    assert [p.name for p in store.iterdir()] == [first.revision]


def test_different_content_gives_a_different_revision(tmp_path: Path) -> None:
    source = make_source(tmp_path / "src")
    first = pin_local(source, tmp_path / "store", LIMITS)
    (source / "app.js").write_bytes(b"changed\n")
    second = pin_local(source, tmp_path / "store", LIMITS)
    assert first.revision != second.revision
    assert (first.root / "app.js").read_bytes() == b"one\n"


def test_uncommitted_changes_are_part_of_the_revision(tmp_path: Path) -> None:
    source = make_source(tmp_path / "src")
    clean = pin_local(source, tmp_path / "store", LIMITS)
    (source / "new_file.js").write_bytes(b"not committed anywhere")
    dirty = pin_local(source, tmp_path / "store", LIMITS)
    assert clean.revision != dirty.revision
    assert "new_file.js" in [f.path for f in dirty.tree.files]


def test_findings_and_skips_are_reported(tmp_path: Path) -> None:
    source = make_source(tmp_path / "src")
    (source / "conf.js").write_bytes(b"password = 'correct-horse-battery'\n")
    (source / "alias.js").symlink_to("app.js")
    pinned = pin_local(source, tmp_path / "store", LIMITS)
    assert [(f.path, f.line, f.kind) for f in pinned.report.findings] == [
        ("conf.js", 1, "secret:credential")
    ]
    assert [(s.path, s.reason) for s in pinned.tree.skipped] == [("alias.js", "symlink")]
    assert not (pinned.root / "alias.js").exists()


def test_verify_proves_the_source_unchanged(tmp_path: Path) -> None:
    source = make_source(tmp_path / "src")
    pinned = pin_local(source, tmp_path / "store", LIMITS)
    result = verify(pinned, LIMITS)
    assert (result.pinned_copy_intact, result.source_unchanged) == (True, True)


def test_verify_reports_a_source_that_changed_during_the_run(tmp_path: Path) -> None:
    source = make_source(tmp_path / "src")
    pinned = pin_local(source, tmp_path / "store", LIMITS)
    (source / "app.js").write_bytes(b"edited while the run was going\n")
    result = verify(pinned, LIMITS)
    assert (result.pinned_copy_intact, result.source_unchanged) == (True, False)
    assert (pinned.root / "app.js").read_bytes() == b"one\n"


def test_verify_detects_a_tampered_pinned_copy(tmp_path: Path) -> None:
    pinned = pin_local(make_source(tmp_path / "src"), tmp_path / "store", LIMITS)
    target = pinned.root / "app.js"
    target.chmod(0o644)
    target.write_bytes(b"tampered")
    assert verify(pinned, LIMITS).pinned_copy_intact is False


def test_a_corrupted_store_entry_is_not_reused(tmp_path: Path) -> None:
    source = make_source(tmp_path / "src")
    first = pin_local(source, tmp_path / "store", LIMITS)
    target = first.root / "app.js"
    target.chmod(0o644)
    target.write_bytes(b"tampered")
    assert rejected(source, tmp_path / "store", LIMITS) == "store_corrupt"


def test_rejected_source_leaves_nothing_behind(tmp_path: Path) -> None:
    source = make_source(tmp_path / "src")
    (tmp_path / "secret.txt").write_text("outside")
    (source / "link").symlink_to(tmp_path / "secret.txt")
    assert rejected(source, tmp_path / "store", LIMITS) == "path_escape"
    assert list((tmp_path / "store").iterdir()) == []


def test_limits_apply_to_the_source(tmp_path: Path) -> None:
    source = make_source(tmp_path / "src")
    tight = Limits(max_bytes=MIB, max_files=1, max_depth=30)
    assert rejected(source, tmp_path / "store", tight) == "too_many_files"
    assert list((tmp_path / "store").iterdir()) == []


def test_missing_path_and_file_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "f").write_text("x")
    assert rejected(tmp_path / "nope", tmp_path / "store", LIMITS) == "not_found"
    assert rejected(tmp_path / "f", tmp_path / "store", LIMITS) == "not_a_directory"


def test_store_inside_the_source_is_rejected(tmp_path: Path) -> None:
    source = make_source(tmp_path / "src")
    assert rejected(source, source / ".snapshots", LIMITS) == "store_overlap"
    assert rejected(source, source, LIMITS) == "store_overlap"
    assert rejected(source, tmp_path, LIMITS) == "store_overlap"


def test_pins_the_fixture_app(tmp_path: Path) -> None:
    pinned = pin_local(ROOT / "fixtures/legacy-app", tmp_path / "store", LIMITS)
    paths = {f.path for f in pinned.tree.files}
    assert {"lib/totals.js", "lib/legacy_labels.js", "app.js"} <= paths
    assert (pinned.root / "lib/totals.js").read_bytes().count(b"\r\n") == 7
    assert (pinned.root / "lib/legacy_labels.js").read_bytes().count(b"\xe9") == 1


def test_cli_prints_a_summary_without_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = make_source(tmp_path / "src")
    (source / "conf.js").write_bytes(b"password = 'correct-horse-battery'\n")
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "store"))
    from services.api.settings import get_settings

    get_settings.cache_clear()
    assert main([str(source)]) == 0
    out = capsys.readouterr().out
    summary = json.loads(out)
    assert summary["findings"] == {"secret:credential": 1}
    assert summary["files"] == 3
    assert "correct-horse-battery" not in out
    get_settings.cache_clear()


def test_cli_rejects_with_a_message_and_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "store"))
    from services.api.settings import get_settings

    get_settings.cache_clear()
    assert main([str(tmp_path / "missing")]) == 1
    assert "Rejected: not_found" in capsys.readouterr().err
    assert main([str(tmp_path), "--ref", "main"]) == 1
    assert "Rejected: bad_ref" in capsys.readouterr().err
    assert main(["git@github.com:o/r.git"]) == 1
    assert "Rejected: bad_url" in capsys.readouterr().err
    get_settings.cache_clear()
