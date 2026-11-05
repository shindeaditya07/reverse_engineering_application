"""Walk a source tree safely and hash it (SEC-1.1, SEC-1.4, SEC-1.6).

The walk never follows a symlink, never opens a file that is not a regular file, and rejects
the whole source if anything resolves outside the root or breaks a limit. The tree hash covers
the relative path and SHA-256 of every analysed file, so it changes when any of them changes.
"""

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from services.ingest.errors import IngestError
from services.ingest.limits import Limits

# Never analysed and never copied. Recorded in `excluded` so the omission is visible.
EXCLUDED_DIRS = frozenset({".git", "node_modules"})
_CHUNK = 1024 * 1024
_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)


@dataclass(frozen=True)
class FileEntry:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class Skipped:
    path: str
    reason: str


@dataclass(frozen=True)
class TreeScan:
    files: tuple[FileEntry, ...]
    skipped: tuple[Skipped, ...]
    excluded: tuple[str, ...]
    tree_hash: str
    total_bytes: int


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root + os.sep)


def _printable(path: str) -> str:
    return path.encode("utf-8", "backslashreplace").decode("utf-8")


def _is_utf8(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def open_regular(path: str, shown: str) -> int:
    """Open a file for reading, refusing symlinks and anything that is not a regular file."""
    try:
        fd = os.open(path, _OPEN_FLAGS)
    except OSError as error:
        message = f"cannot open {_printable(shown)}: {error.strerror}"
        raise IngestError("unreadable", message) from error
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise IngestError("special_file", f"{_printable(shown)} is not a regular file")
    return fd


def _hash_file(path: str, shown: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with os.fdopen(open_regular(path, shown), "rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _tree_hash(files: list[FileEntry]) -> str:
    digest = hashlib.sha256()
    for entry in files:
        digest.update(entry.path.encode("utf-8") + b"\0" + entry.sha256.encode("ascii") + b"\n")
    return digest.hexdigest()


def scan_tree(root: Path, limits: Limits) -> TreeScan:
    """List and hash every regular file under root, or raise IngestError."""
    real_root = os.path.realpath(root)
    if not os.path.isdir(real_root):
        raise IngestError("not_a_directory", f"{_printable(str(root))} is not a directory")

    files: list[FileEntry] = []
    skipped: list[Skipped] = []
    excluded: list[str] = []
    total = 0
    stack: list[tuple[str, int]] = [(real_root, 0)]
    while stack:
        directory, depth = stack.pop()
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda e: e.name)
        for entry in entries:
            rel = Path(os.path.relpath(entry.path, real_root)).as_posix()
            if not _is_utf8(rel):
                skipped.append(Skipped(_printable(rel), "undecodable_name"))
            elif entry.is_symlink():
                if not _inside(os.path.realpath(entry.path), real_root):
                    raise IngestError("path_escape", f"{rel} resolves outside the source root")
                skipped.append(Skipped(rel, "symlink"))
            elif entry.is_dir(follow_symlinks=False):
                if entry.name in EXCLUDED_DIRS:
                    excluded.append(rel)
                elif depth + 1 > limits.max_depth:
                    raise IngestError("too_deep", f"{rel} is deeper than {limits.max_depth} levels")
                else:
                    stack.append((entry.path, depth + 1))
            elif entry.is_file(follow_symlinks=False):
                if len(files) + 1 > limits.max_files:
                    raise IngestError("too_many_files", f"more than {limits.max_files} files")
                if total + entry.stat(follow_symlinks=False).st_size > limits.max_bytes:
                    raise IngestError("too_large", f"more than {limits.max_bytes} bytes")
                sha256, size = _hash_file(entry.path, rel)
                total += size
                if total > limits.max_bytes:
                    raise IngestError("too_large", f"more than {limits.max_bytes} bytes")
                files.append(FileEntry(rel, sha256, size))
            else:
                skipped.append(Skipped(rel, "special_file"))

    files.sort(key=lambda f: f.path.encode("utf-8"))
    return TreeScan(
        files=tuple(files),
        skipped=tuple(sorted(skipped, key=lambda s: s.path)),
        excluded=tuple(sorted(excluded)),
        tree_hash=_tree_hash(files),
        total_bytes=total,
    )
