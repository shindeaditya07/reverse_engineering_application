"""Read files from a pinned snapshot, and only those (SEC-1.1, SEC-1.6, EVD-1.5).

A path is readable only if it is in the snapshot's recorded file list, so `..`, absolute paths
and symlinks never resolve. Each file is hashed on read and compared with the recorded hash,
so a snapshot that was edited after pinning resolves nothing.
"""

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path

from services.evidence.errors import Unresolved
from services.ingest.errors import IngestError
from services.ingest.pin import PinnedSource
from services.ingest.scan import normalise
from services.ingest.tree import open_regular

__all__ = ["SnapshotReader", "Unresolved"]


class SnapshotReader:
    def __init__(self, root: Path | str, hashes: Mapping[str, str]) -> None:
        self._root = Path(root)
        self._hashes = dict(hashes)
        self._raw: dict[str, bytes] = {}
        self._lines: dict[str, list[str] | None] = {}

    @classmethod
    def from_pinned(cls, pinned: PinnedSource) -> "SnapshotReader":
        return cls(pinned.root, {f.path: f.sha256 for f in pinned.tree.files})

    def raw(self, path: str) -> bytes:
        if path in self._raw:
            return self._raw[path]
        expected = self._hashes.get(path)
        if expected is None:
            raise Unresolved("not_in_snapshot", f"{path!r} is not a file of this snapshot")
        try:
            with os.fdopen(open_regular(str(self._root / path), path), "rb") as handle:
                data = handle.read()
        except IngestError as error:
            raise Unresolved("unreadable", str(error)) from error
        if hashlib.sha256(data).hexdigest() != expected:
            raise Unresolved("snapshot_modified", f"{path!r} differs from its pinned hash")
        self._raw[path] = data
        return data

    def lines(self, path: str) -> list[str]:
        """The file as decoded UTF-8 with LF line ends, split on LF only (EVD-1.5)."""
        if path not in self._lines:
            data = self.raw(path)
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                self._lines[path] = None
            else:
                parts = normalise(text).split("\n")
                if parts and parts[-1] == "":
                    parts.pop()
                self._lines[path] = parts
        cached = self._lines[path]
        if cached is None:
            raise Unresolved("undecodable", f"{path!r} is not UTF-8; cite a byte range instead")
        return cached
