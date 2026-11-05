"""Hostile-source tests for the tree walk (SEC-1.1, SEC-1.4, SEC-1.6)."""

import os
from pathlib import Path

import pytest

from services.ingest.errors import IngestError
from services.ingest.limits import MIB, Limits, load_limits
from services.ingest.tree import EXCLUDED_DIRS, scan_tree
from services.rules_constants import rule_constants

BIG = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)


def write(root: Path, rel: str, content: bytes = b"x") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def rejected(root: Path, limits: Limits = BIG) -> str:
    with pytest.raises(IngestError) as caught:
        scan_tree(root, limits)
    return caught.value.code


def test_limits_come_from_the_constants_file() -> None:
    constants = rule_constants("SEC-1.4")
    limits = load_limits()
    assert limits.max_bytes == constants["max_archive_unpacked_mb"] * MIB
    assert limits.max_files == constants["max_archive_files"]
    assert limits.max_depth == constants["max_directory_depth"]


def test_lists_and_hashes_files(tmp_path: Path) -> None:
    write(tmp_path, "b.js", b"bb")
    write(tmp_path, "a/c.js", b"c")
    scan = scan_tree(tmp_path, BIG)
    assert [f.path for f in scan.files] == ["a/c.js", "b.js"]
    assert scan.total_bytes == 3
    assert len(scan.tree_hash) == 64


def test_hash_is_stable_and_ignores_creation_order(tmp_path: Path) -> None:
    one, two = tmp_path / "one", tmp_path / "two"
    for name in ("a", "b", "c"):
        write(one, name, name.encode())
    for name in ("c", "a", "b"):
        write(two, name, name.encode())
    assert scan_tree(one, BIG).tree_hash == scan_tree(two, BIG).tree_hash


def test_hash_changes_with_content_name_and_extra_file(tmp_path: Path) -> None:
    write(tmp_path, "a", b"1")
    base = scan_tree(tmp_path, BIG).tree_hash
    write(tmp_path, "a", b"2")
    changed = scan_tree(tmp_path, BIG).tree_hash
    (tmp_path / "a").rename(tmp_path / "b")
    renamed = scan_tree(tmp_path, BIG).tree_hash
    write(tmp_path, "c", b"")
    added = scan_tree(tmp_path, BIG).tree_hash
    assert len({base, changed, renamed, added}) == 4


def test_crlf_and_lf_files_hash_differently(tmp_path: Path) -> None:
    one, two = tmp_path / "one", tmp_path / "two"
    write(one, "f", b"a\r\nb\r\n")
    write(two, "f", b"a\nb\n")
    assert scan_tree(one, BIG).tree_hash != scan_tree(two, BIG).tree_hash


def test_git_and_node_modules_are_excluded_and_reported(tmp_path: Path) -> None:
    write(tmp_path, "app.js")
    write(tmp_path, ".git/config")
    write(tmp_path, "node_modules/dep/index.js")
    write(tmp_path, "sub/node_modules/dep/index.js")
    scan = scan_tree(tmp_path, BIG)
    assert [f.path for f in scan.files] == ["app.js"]
    assert scan.excluded == (".git", "node_modules", "sub/node_modules")
    assert EXCLUDED_DIRS == {".git", "node_modules"}


def test_excluded_dirs_do_not_count_toward_limits(tmp_path: Path) -> None:
    write(tmp_path, "app.js")
    for index in range(50):
        write(tmp_path, f"node_modules/m{index}.js")
    assert len(scan_tree(tmp_path, Limits(MIB, max_files=1, max_depth=30)).files) == 1


def test_too_many_files(tmp_path: Path) -> None:
    for index in range(4):
        write(tmp_path, f"f{index}")
    assert rejected(tmp_path, Limits(MIB, max_files=3, max_depth=30)) == "too_many_files"


def test_exactly_at_the_file_limit_is_allowed(tmp_path: Path) -> None:
    for index in range(3):
        write(tmp_path, f"f{index}")
    assert len(scan_tree(tmp_path, Limits(MIB, max_files=3, max_depth=30)).files) == 3


def test_too_large_in_total(tmp_path: Path) -> None:
    write(tmp_path, "a", b"x" * 60)
    write(tmp_path, "b", b"x" * 60)
    assert rejected(tmp_path, Limits(max_bytes=100, max_files=10, max_depth=30)) == "too_large"


def test_exactly_at_the_size_limit_is_allowed(tmp_path: Path) -> None:
    write(tmp_path, "a", b"x" * 100)
    assert scan_tree(tmp_path, Limits(100, 10, 30)).total_bytes == 100


def test_too_deep(tmp_path: Path) -> None:
    write(tmp_path, "/".join(["d"] * 4) + "/f")
    assert rejected(tmp_path, Limits(MIB, 10, max_depth=3)) == "too_deep"


def test_exactly_at_the_depth_limit_is_allowed(tmp_path: Path) -> None:
    write(tmp_path, "/".join(["d"] * 3) + "/f")
    assert len(scan_tree(tmp_path, Limits(MIB, 10, max_depth=3)).files) == 1


def test_symlink_to_a_file_outside_is_rejected(tmp_path: Path) -> None:
    outside = write(tmp_path, "outside/secret.txt")
    root = tmp_path / "src"
    write(root, "ok.js")
    (root / "link").symlink_to(outside)
    assert rejected(root) == "path_escape"


def test_symlink_to_a_directory_outside_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "outside").mkdir()
    root = tmp_path / "src"
    write(root, "ok.js")
    (root / "link").symlink_to(tmp_path / "outside", target_is_directory=True)
    assert rejected(root) == "path_escape"


def test_relative_symlink_climbing_out_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, "outside.txt")
    root = tmp_path / "src"
    write(root, "sub/ok.js")
    (root / "sub" / "link").symlink_to("../../outside.txt")
    assert rejected(root) == "path_escape"


def test_excluded_dir_name_does_not_hide_an_escaping_symlink(tmp_path: Path) -> None:
    (tmp_path / "outside").mkdir()
    root = tmp_path / "src"
    root.mkdir()
    (root / "node_modules").symlink_to(tmp_path / "outside", target_is_directory=True)
    assert rejected(root) == "path_escape"


def test_symlinks_inside_the_root_are_skipped_not_followed(tmp_path: Path) -> None:
    write(tmp_path, "real.js", b"r")
    (tmp_path / "alias.js").symlink_to("real.js")
    (tmp_path / "dangling").symlink_to("missing")
    (tmp_path / "loop").symlink_to(".", target_is_directory=True)
    scan = scan_tree(tmp_path, BIG)
    assert [f.path for f in scan.files] == ["real.js"]
    assert {(s.path, s.reason) for s in scan.skipped} == {
        ("alias.js", "symlink"),
        ("dangling", "symlink"),
        ("loop", "symlink"),
    }


def test_root_given_as_a_symlink_is_resolved(tmp_path: Path) -> None:
    write(tmp_path, "real/a.js")
    (tmp_path / "alias").symlink_to(tmp_path / "real", target_is_directory=True)
    assert [f.path for f in scan_tree(tmp_path / "alias", BIG).files] == ["a.js"]


def test_fifo_is_skipped_and_never_opened(tmp_path: Path) -> None:
    write(tmp_path, "ok.js")
    os.mkfifo(tmp_path / "pipe")
    scan = scan_tree(tmp_path, BIG)
    assert [f.path for f in scan.files] == ["ok.js"]
    assert [(s.path, s.reason) for s in scan.skipped] == [("pipe", "special_file")]


def test_non_utf8_file_name_is_skipped_and_printable(tmp_path: Path) -> None:
    write(tmp_path, "ok.js")
    (tmp_path / os.fsdecode(b"bad-\xff-name")).write_bytes(b"x")
    scan = scan_tree(tmp_path, BIG)
    assert [f.path for f in scan.files] == ["ok.js"]
    assert scan.skipped[0].reason == "undecodable_name"
    assert scan.skipped[0].path == "bad-\\udcff-name"


def test_newline_in_a_file_name_is_hashed_unambiguously(tmp_path: Path) -> None:
    one, two = tmp_path / "one", tmp_path / "two"
    write(one, "a\nb", b"x")
    write(two, "a", b"x")
    write(two, "b", b"x")
    assert scan_tree(one, BIG).tree_hash != scan_tree(two, BIG).tree_hash


def test_not_a_directory(tmp_path: Path) -> None:
    file = write(tmp_path, "f")
    assert rejected(file) == "not_a_directory"
    assert rejected(tmp_path / "missing") == "not_a_directory"


def test_scan_does_not_touch_the_source(tmp_path: Path) -> None:
    path = write(tmp_path, "a.js", b"data")
    before = (path.stat().st_mtime_ns, path.stat().st_mode, sorted(os.listdir(tmp_path)))
    scan_tree(tmp_path, BIG)
    assert before == (path.stat().st_mtime_ns, path.stat().st_mode, sorted(os.listdir(tmp_path)))
