"""The verifier's test corpora (VER-1.4): 50 known-good and 50 seeded known-bad claims.

Good claims come from the reviewed fixture answer key plus eight hand-written ones, so they are
real statements about real fixture code, not shapes built to pass. Bad claims are made by
breaking a good claim in one named way and say which check must catch it.
"""

import hashlib
from pathlib import Path
from typing import Any

import yaml

from services.evidence import FileRange, SnapshotReader, parse_ref, resolve
from services.verifier import ClaimInput, DocSentence, EvidenceInput

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "fixtures/legacy-app"
KEY = ROOT / "fixtures/answer-key/key.yaml"


def sha(data: str | bytes) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def stored(reader: SnapshotReader, ref: dict[str, Any]) -> EvidenceInput:
    """Evidence as the pipeline stores it at claim time: the reference and its excerpt hash."""
    found = resolve(parse_ref(ref), reader)
    assert found.status == "resolved", (ref, found.reason)
    return EvidenceInput(ref, found.content_hash)


def lines(path: str, start: int, end: int) -> dict[str, Any]:
    return {"kind": "file_range", "path": path, "start_line": start, "end_line": end}


def _key_ref(entry: dict[str, Any]) -> dict[str, Any]:
    if "bytes" in entry:
        b = entry["bytes"]
        return {
            "kind": "file_range",
            "path": entry["file"],
            "start_byte": b["start"],
            "end_byte": b["end"],
        }
    return lines(entry["file"], entry["start"], entry["end"])


def _from_fact(reader: SnapshotReader, fact: dict[str, Any]) -> ClaimInput:
    status = fact["status"].lower()
    paths = frozenset(
        e["file"] for e in fact["evidence"] if e["file"].startswith(("generated/", "vendor/"))
    )
    return ClaimInput(
        claim_id=fact["id"],
        text=fact["statement"],
        status=status,
        producer_kind="deterministic" if status == "confirmed" else "model",
        evidence=tuple(stored(reader, _key_ref(e)) for e in fact["evidence"]),
        explanation=fact["statement"] if status == "inferred" else None,
        subject_paths=paths,
    )


def extra_good(reader: SnapshotReader) -> list[ClaimInput]:
    def claim(
        n: int, text: str, status: str, kind: str, refs: list[dict[str, Any]], **kw: Any
    ) -> ClaimInput:
        return ClaimInput(
            f"X{n:02d}", text, status, kind, tuple(stored(reader, r) for r in refs), **kw
        )

    return [
        claim(1, "The package.json start script runs node app.js.", "confirmed", "deterministic",
              [{"kind": "build_step", "path": "package.json", "object_name": "npm:start"}]),
        claim(2, "The orders table has a status column.", "confirmed", "deterministic",
              [{"kind": "schema_object", "path": "db/schema.sql", "object_name": "column:orders.status"}]),
        claim(3, "The default tax rate is 0.0825.", "confirmed", "deterministic",
              [{"kind": "config_key", "path": "config.js", "object_name": "taxRate"}]),
        claim(4, "The customers table exists.", "confirmed", "deterministic",
              [{"kind": "schema_object", "path": "db/schema.sql", "object_name": "table:customers"}]),
        claim(5, "A sum of order lines multiplies price by quantity.", "inferred", "model",
              [lines("lib/totals.js", 3, 5)],
              explanation="sumLines adds up the price in cents times the quantity of each item."),
        claim(6, "Nothing is known about how refunds are issued.", "unknown", "model", []),
        claim(7, "The label file contains one byte outside UTF-8.", "confirmed", "deterministic",
              [{"kind": "file_range", "path": "lib/legacy_labels.js", "start_byte": 73, "end_byte": 74}]),
        claim(8, "The generated API client states its own version.", "confirmed", "deterministic",
              [lines("generated/api_client.js", 7, 7)], subject_paths=frozenset({"generated/api_client.js"})),
    ]  # fmt: skip


def good_claims(reader: SnapshotReader) -> list[ClaimInput]:
    key = yaml.safe_load(KEY.read_text(encoding="utf-8"))
    claims = [_from_fact(reader, f) for t in key["traps"] for f in t["facts"]]
    return claims + extra_good(reader)


def _base(reader: SnapshotReader, **changes: Any) -> ClaimInput:
    """A valid inferred claim about app.js that each bad claim then breaks in one way."""
    evidence = (stored(reader, lines("app.js", 24, 28)),)
    fields: dict[str, Any] = {
        "claim_id": "B",
        "text": "Three report routes are registered in one loop.",
        "status": "inferred",
        "producer_kind": "model",
        "evidence": evidence,
        "explanation": "The forEach over daily, weekly and monthly registers the report routes.",
    }
    fields.update(changes)
    return ClaimInput(**fields)


def bad_claims(reader: SnapshotReader) -> list[tuple[ClaimInput, str]]:
    good = stored(reader, lines("app.js", 24, 28))
    wrong_hashes = [sha("x"), "0" * 64, "", sha("app.js"), sha("['daily'].forEach(")]
    secret = "AKIA" + "IOSFODNN7EXAMPLE"
    out: list[tuple[ClaimInput, str]] = []

    def add(check: str, claim: ClaimInput) -> None:
        out.append((claim, check))

    # V-1: no evidence at all.
    for status, kind in [("confirmed", "deterministic"), ("inferred", "model"), ("confirmed", "test"),
                         ("inferred", "deterministic"), ("inferred", "human")]:  # fmt: skip
        add("V-1", _base(reader, status=status, producer_kind=kind, evidence=(), explanation=None))
    # V-2: a reference that does not resolve.
    unresolved: list[dict[str, Any]] = [
        lines("no/such/file.js", 1, 2),
        lines("../outside.js", 1, 1),
        lines("app.js", 900, 905),
        {"kind": "schema_object", "path": "db/schema.sql", "object_name": "table:ghosts"},
        {"kind": "config_key", "path": "config.js", "object_name": "noSuchKey"},
        {"kind": "file_range", "path": "app.js", "start_byte": 0, "end_byte": 99999},
    ]
    for ref in unresolved:
        add("V-2", _base(reader, evidence=(EvidenceInput(ref, "0" * 64),)))
    # V-3: stored hash no longer matches the cited bytes.
    for bad_hash in wrong_hashes:
        add("V-3", _base(reader, evidence=(EvidenceInput(good.ref, bad_hash),)))
    # V-4: a file range over the line limit.
    for start, end in [(1, 41), (5, 100), (1, 500), (3, 43), (100, 141)]:
        add("V-4", _base(reader, evidence=(EvidenceInput(lines("app.js", start, end), "0" * 64),)))
    # V-5: a status that is not one of three, or does not match how it was produced.
    for status, kind in [("maybe", "model"), ("accepted", "model"), ("", "deterministic"),
                         ("confirmed", "oracle"), ("confirmed", "human"), ("inferred", "test")]:  # fmt: skip
        add("V-5", _base(reader, status=status, producer_kind=kind))
    # V-6: a model alone produced Confirmed.
    for text in [
        "Reports exist.",
        "Three routes.",
        "Loop registers routes.",
        "Daily route.",
        "Monthly route.",
    ]:
        add("V-6", _base(reader, text=text, status="confirmed", producer_kind="model"))
    # V-7: authored behaviour cited to a generated or vendored file.
    for ref in [lines("generated/api_client.js", 1, 3), lines("generated/api_client.js", 8, 10),
                lines("vendor/tinyid.js", 1, 1), lines("vendor/tinyid.js", 4, 6)]:  # fmt: skip
        add("V-7", _base(reader, evidence=(stored(reader, ref),), explanation=None))
    add(
        "V-7",
        _base(
            reader,
            evidence=(good, stored(reader, lines("vendor/tinyid.js", 4, 6))),
            explanation=None,
        ),
    )
    # V-9: a secret or personal data in the claim text or the explanation.
    for field, text in [
        ("text", f"The mailer uses the key {secret} to sign requests."),
        ("text", "Receipts are sent to jane.doe@example.com."),
        ("text", "The support line is 415-555-0134."),
        ("text", "The test customer has SSN 123-45-6789."),
        ("explanation", f"The loop registers routes, using {secret}."),
        ("text", "The database is at postgres://admin:hunter2pass@db.internal/shop."),
    ]:
        add("V-9", _base(reader, **{field: text}))
    # V-10: an explanation that has nothing to do with the cited code.
    for explanation in [
        "Customers receive a confirmation email once their parcel has shipped.",
        "Loyalty tiers grant a ten percent discount on large purchases.",
        "The nightly job archives old orders into cold storage.",
        "Payment is captured by the gateway before stock is reserved.",
        "Passwords are hashed with bcrypt before they are saved.",
        "Inventory levels are reconciled against the warehouse feed hourly.",
        "Tax is calculated per region using a lookup table.",
    ]:
        add("V-10", _base(reader, explanation=explanation))
    return out


def sentences(good_ids: list[str], bad_id: str) -> tuple[list[DocSentence], list[DocSentence]]:
    """(sentences that should stand, sentences V-8 must reject)."""
    standing = [DocSentence(f"Statement {i}.", (cid,)) for i, cid in enumerate(good_ids[:5])]
    rejected = [
        DocSentence("Uncited statement.", ()),
        DocSentence("Cites a claim that does not exist.", ("NOPE",)),
        DocSentence("Cites a claim that failed.", (bad_id,)),
        DocSentence("Cites one good and one missing claim.", (good_ids[0], "NOPE")),
        DocSentence("Cites an Unknown claim as fact.", ("T18-F2",)),
    ]
    return standing, rejected


__all__ = ["FileRange", "bad_claims", "good_claims", "sentences", "sha", "stored"]
