"""Resolve a source to a pinned, read-only revision (FR-1, SEC-1.1, SEC-1.6).

A local path pins to a content hash of its working tree (uncommitted changes included). A
GitHub URL pins to a commit SHA. Either way the files are copied (or checked out) into the
snapshot store, made read-only, and every later read uses that copy, so a line number cited
now still points at the same code later even if the source moves on.
"""

import os
import shutil
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from services.ingest.errors import IngestError
from services.ingest.gitfetch import fetch_revision, validate_github_url, validate_ref
from services.ingest.limits import Limits, load_limits
from services.ingest.scan import ScanReport, scan_files
from services.ingest.tree import TreeScan, open_regular, scan_tree

_CHUNK = 1024 * 1024
_FILE_MODE = 0o444
_DIR_MODE = 0o555


@dataclass(frozen=True)
class PinnedSource:
    kind: str
    origin: str
    requested_ref: str | None
    revision: str
    root: Path
    tree: TreeScan
    report: ScanReport


@dataclass(frozen=True)
class Verification:
    """pinned_copy_intact: the stored copy still hashes the same.
    source_unchanged: the original still hashes the same; None when there is no local original."""

    pinned_copy_intact: bool
    source_unchanged: bool | None


def _copy_file(source: str, dest: Path, shown: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(open_regular(source, shown), "rb") as reader, dest.open("wb") as writer:
        shutil.copyfileobj(reader, writer, _CHUNK)


def _make_read_only(root: Path) -> None:
    for directory, _, names in os.walk(root, topdown=False):
        for name in names:
            Path(directory, name).chmod(_FILE_MODE)
        Path(directory).chmod(_DIR_MODE)


def _make_writable(root: Path) -> None:
    for directory, _, names in os.walk(root):
        Path(directory).chmod(0o755)
        for name in names:
            Path(directory, name).chmod(0o644)


def _place(tmp: Path, store: Path, revision: str, tree: TreeScan, limits: Limits) -> Path:
    """Move the finished copy to store/<revision>, or reuse an identical one already there."""
    final = store / revision
    if final.exists():
        if scan_tree(final, limits).tree_hash != tree.tree_hash:
            raise IngestError("store_corrupt", f"{revision} is in the store but its files differ")
        return final
    tmp.rename(final)
    _make_read_only(final)
    return final


def _finish(
    tmp: Path, store: Path, revision: str, tree: TreeScan, limits: Limits
) -> tuple[Path, ScanReport]:
    root = _place(tmp, store, revision, tree, limits)
    return root, scan_files(root, tree.files)


def _prepare_store(store: Path) -> Path:
    store = Path(store).resolve()
    store.mkdir(parents=True, exist_ok=True)
    return store


def pin_local(path: Path | str, store: Path, limits: Limits | None = None) -> PinnedSource:
    limits = limits or load_limits()
    source = Path(path).expanduser()
    if not source.exists():
        raise IngestError("not_found", f"{source} does not exist")
    real = Path(os.path.realpath(source))
    if not real.is_dir():
        raise IngestError("not_a_directory", f"{source} is not a directory")
    store = _prepare_store(store)
    if store == real or real in store.parents or store in real.parents:
        raise IngestError("store_overlap", "the snapshot store must be outside the source")

    first = scan_tree(real, limits)
    tmp = store / f".tmp-{uuid.uuid4().hex}"
    try:
        for entry in first.files:
            _copy_file(str(real / entry.path), tmp / entry.path, entry.path)
        copied = scan_tree(tmp, limits)
        tree = replace(copied, skipped=first.skipped, excluded=first.excluded)
        root, report = _finish(tmp, store, copied.tree_hash, tree, limits)
    finally:
        if tmp.exists():
            _make_writable(tmp)
            shutil.rmtree(tmp)
    return PinnedSource("local_path", str(real), None, copied.tree_hash, root, tree, report)


def _pin_git(
    remote: str,
    origin: str,
    ref: str | None,
    store: Path,
    limits: Limits,
    token: str | None,
    allow_protocol: str,
) -> PinnedSource:
    checked_ref = validate_ref(ref)
    store = _prepare_store(store)
    tmp = store / f".tmp-{uuid.uuid4().hex}"
    try:
        sha = fetch_revision(remote, checked_ref, tmp, token=token, allow_protocol=allow_protocol)
        shutil.rmtree(tmp / ".git")
        tree = scan_tree(tmp, limits)
        root, report = _finish(tmp, store, sha, tree, limits)
    finally:
        if tmp.exists():
            _make_writable(tmp)
            shutil.rmtree(tmp)
    return PinnedSource("github", origin, ref, sha, root, tree, report)


def pin_github(
    url: str,
    store: Path,
    *,
    ref: str | None = None,
    token: str | None = None,
    limits: Limits | None = None,
) -> PinnedSource:
    canonical = validate_github_url(url)
    return _pin_git(canonical, canonical, ref, store, limits or load_limits(), token, "https")


def verify(pinned: PinnedSource, limits: Limits | None = None) -> Verification:
    """Prove the source unchanged (SEC-1.1). A changed original is reported, never followed."""
    limits = limits or load_limits()
    intact = scan_tree(pinned.root, limits).tree_hash == pinned.tree.tree_hash
    unchanged: bool | None = None
    if pinned.kind == "local_path":
        unchanged = scan_tree(Path(pinned.origin), limits).tree_hash == pinned.tree.tree_hash
    return Verification(intact, unchanged)
