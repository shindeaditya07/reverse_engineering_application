"""Load the fixture answer key as scorable facts (spec section 17)."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

KEY_PATH = Path(__file__).resolve().parents[2] / "fixtures/answer-key/key.yaml"
STRENGTH = {"unknown": 0, "inferred": 1, "confirmed": 2}


@dataclass(frozen=True)
class Span:
    """A cited place. `unit` is "line" (1-based, inclusive) or "byte" (start, end exclusive)."""

    file: str
    start: int
    end: int
    unit: str = "line"

    def overlap(self, other: "Span") -> int:
        if self.file != other.file or self.unit != other.unit:
            return 0
        last_a = self.end if self.unit == "line" else self.end - 1
        last_b = other.end if other.unit == "line" else other.end - 1
        return max(0, min(last_a, last_b) - max(self.start, other.start) + 1)


@dataclass(frozen=True)
class KeyFact:
    fact_id: str
    trap: int
    kind: str
    status: str
    spans: tuple[Span, ...]


def _span(entry: dict[str, Any]) -> Span:
    if "bytes" in entry:
        return Span(entry["file"], entry["bytes"]["start"], entry["bytes"]["end"], "byte")
    return Span(entry["file"], entry["start"], entry["end"])


def load_key(path: Path = KEY_PATH) -> list[KeyFact]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        KeyFact(
            f["id"],
            trap["trap"],
            f["kind"],
            f["status"].lower(),
            tuple(_span(e) for e in f["evidence"]),
        )
        for trap in data["traps"]
        for f in trap["facts"]
    ]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
