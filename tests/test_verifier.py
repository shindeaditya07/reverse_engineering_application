"""The verifier: each check V-1 to V-10, fail-closed behaviour, and what it must never do."""

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from services.evidence import FileRange, SnapshotReader
from services.ingest.limits import MIB, Limits
from services.ingest.pin import pin_local
from services.stats import wilson_interval
from services.verifier import (
    ClaimInput,
    DocSentence,
    EvidenceInput,
    FileFlags,
    detect_flags,
    result_rows,
    verify_claim,
    verify_claims,
    verify_document,
)
from services.verifier import verify as verify_module
from services.verifier.models import CheckResult, Verdict
from services.verifier.tokens import content_tokens, overlap
from tests.verifier_corpus import APP, lines, sha, stored

LIMITS = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
SECRET = "AKIA" + "IOSFODNN7EXAMPLE"


@pytest.fixture(scope="module")
def reader(tmp_path_factory: pytest.TempPathFactory) -> SnapshotReader:
    return SnapshotReader.from_pinned(pin_local(APP, tmp_path_factory.mktemp("snap"), LIMITS))


def make_reader(tmp_path: Path, files: dict[str, bytes]) -> SnapshotReader:
    source = tmp_path / "source"
    for rel, data in files.items():
        (source / rel).parent.mkdir(parents=True, exist_ok=True)
        (source / rel).write_bytes(data)
    return SnapshotReader.from_pinned(pin_local(source, tmp_path / "store", LIMITS))


def claim(reader: SnapshotReader, **changes: Any) -> ClaimInput:
    fields: dict[str, Any] = {
        "claim_id": "C1",
        "text": "Three report routes are registered in one loop.",
        "status": "confirmed",
        "producer_kind": "deterministic",
        "evidence": (stored(reader, lines("app.js", 24, 28)),),
    }
    fields.update(changes)
    return ClaimInput(**fields)


def failed(verdict: Verdict) -> set[str]:
    return {r.check_id for r in verdict.failures}


def test_valid_confirmed_claim_passes_every_check(reader: SnapshotReader) -> None:
    verdict = verify_claim(claim(reader), reader)
    assert verdict.passed and verdict.final_status == "confirmed"
    assert [r.check_id for r in verdict.results] == [
        "V-1", "V-2", "V-3", "V-4", "V-5", "V-6", "V-7", "V-9", "V-10",
    ]  # fmt: skip
    assert verdict.queue_reason is None


# ---- V-1 and unknown claims ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "kind"), [("confirmed", "deterministic"), ("inferred", "model")]
)
def test_v1_confirmed_or_inferred_without_evidence_is_demoted(
    reader: SnapshotReader, status: str, kind: str
) -> None:
    verdict = verify_claim(claim(reader, status=status, producer_kind=kind, evidence=()), reader)
    assert failed(verdict) == {"V-1"}
    assert verdict.final_status == "unknown"
    assert verdict.queue_reason == "verifier_failure"


def test_unknown_claim_needs_no_evidence(reader: SnapshotReader) -> None:
    verdict = verify_claim(
        claim(reader, status="unknown", producer_kind="model", evidence=()), reader
    )
    assert verdict.passed and verdict.final_status == "unknown"
    assert verdict.queue_reason == "unknown"


# ---- V-2, V-3, V-4: evidence -----------------------------------------------------------------


def test_v2_names_the_reference_that_failed(reader: SnapshotReader) -> None:
    good = stored(reader, lines("app.js", 24, 28))
    bad = EvidenceInput(lines("gone.js", 1, 1), "0" * 64)
    verdict = verify_claim(claim(reader, evidence=(good, bad)), reader)
    assert failed(verdict) == {"V-2"}
    detail = next(r.detail for r in verdict.failures)
    assert detail is not None and detail.startswith("ref 2: not_in_snapshot")
    assert verdict.final_status == "unknown"


def test_v2_unparseable_reference_is_unresolved_not_a_crash(reader: SnapshotReader) -> None:
    for raw in [{"kind": "screenshot"}, {"kind": "file_range", "path": "app.js"}, {}]:
        verdict = verify_claim(claim(reader, evidence=(EvidenceInput(raw, "h"),)), reader)
        assert "V-2" in failed(verdict)


def test_reference_object_is_accepted_as_well_as_a_dict(reader: SnapshotReader) -> None:
    ref = FileRange(path="app.js", start_line=24, end_line=28)
    good = stored(reader, lines("app.js", 24, 28))
    verdict = verify_claim(claim(reader, evidence=(EvidenceInput(ref, good.content_hash),)), reader)
    assert verdict.passed


def test_v3_changed_bytes_mark_the_claim_stale_without_demoting_it(reader: SnapshotReader) -> None:
    ref = lines("app.js", 24, 28)
    verdict = verify_claim(claim(reader, evidence=(EvidenceInput(ref, sha("old")),)), reader)
    assert failed(verdict) == {"V-3"}
    assert verdict.stale and not verdict.passed
    assert verdict.final_status == "confirmed"
    assert verdict.queue_reason == "verifier_failure"


def test_v3_missing_hash_fails(reader: SnapshotReader) -> None:
    verdict = verify_claim(
        claim(reader, evidence=(EvidenceInput(lines("app.js", 24, 28), None),)), reader
    )
    assert failed(verdict) == {"V-3"} and not verdict.stale


def test_v4_span_over_the_limit_from_a_raw_reference(reader: SnapshotReader) -> None:
    verdict = verify_claim(
        claim(reader, evidence=(EvidenceInput(lines("app.js", 1, 41), "h"),)), reader
    )
    assert failed(verdict) == {"V-4"}
    assert verdict.final_status == "confirmed"  # blocked, but what it says is unchanged


def test_v4_forty_lines_is_allowed(tmp_path: Path) -> None:
    rdr = make_reader(tmp_path, {"long.js": b"x\n" * 45})
    ev = (stored(rdr, lines("long.js", 1, 40)),)
    assert verify_claim(ClaimInput("C", "t", "confirmed", "deterministic", ev), rdr).passed


def test_v4_located_object_that_spans_too_many_lines(tmp_path: Path) -> None:
    body = ",\n".join(f"  c{i} INT" for i in range(60))
    rdr = make_reader(tmp_path, {"s.sql": f"CREATE TABLE wide (\n{body}\n);\n".encode()})
    ref = {"kind": "schema_object", "path": "s.sql", "object_name": "table:wide"}
    verdict = verify_claim(
        ClaimInput("C", "wide table", "confirmed", "deterministic", (EvidenceInput(ref, "h"),)), rdr
    )
    assert failed(verdict) == {"V-4"}


# ---- V-5, V-6: status ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "kind", "expected"),
    [
        ("maybe", "model", {"V-5"}),
        ("confirmed", "oracle", {"V-5"}),
        ("confirmed", "human", {"V-5"}),
        ("inferred", "test", {"V-5"}),
        ("confirmed", "model", {"V-5", "V-6"}),
    ],
)
def test_v5_and_v6(reader: SnapshotReader, status: str, kind: str, expected: set[str]) -> None:
    verdict = verify_claim(claim(reader, status=status, producer_kind=kind), reader)
    assert failed(verdict) == expected
    assert verdict.final_status == "unknown"


@pytest.mark.parametrize(
    ("status", "kind"),
    [("confirmed", "deterministic"), ("confirmed", "test"), ("inferred", "model"),
     ("inferred", "deterministic"), ("inferred", "human"), ("unknown", "model")],
)  # fmt: skip
def test_v5_accepts_every_legitimate_pairing(
    reader: SnapshotReader, status: str, kind: str
) -> None:
    assert verify_claim(claim(reader, status=status, producer_kind=kind), reader).passed


def test_a_verdict_never_raises_a_status(reader: SnapshotReader) -> None:
    order = {"unknown": 0, "inferred": 1, "confirmed": 2}
    for status in ("confirmed", "inferred", "unknown"):
        for kind in ("deterministic", "test", "model", "human"):
            verdict = verify_claim(claim(reader, status=status, producer_kind=kind), reader)
            assert order[verdict.final_status] <= order[status]


# ---- V-7: generated and vendored -------------------------------------------------------------


def test_v7_generated_and_vendored_are_refused_unless_the_claim_is_about_them(
    reader: SnapshotReader,
) -> None:
    for path in ("generated/api_client.js", "vendor/tinyid.js"):
        ev = (stored(reader, lines(path, 1, 3)),)
        assert failed(verify_claim(claim(reader, evidence=ev), reader)) == {"V-7"}
        about = claim(reader, evidence=ev, subject_paths=frozenset({path}))
        assert verify_claim(about, reader).passed


def test_v7_recorded_flag_marks_a_file_the_heuristic_misses(reader: SnapshotReader) -> None:
    ordinary = claim(reader)
    assert verify_claim(ordinary, reader).passed
    flags = {"app.js": FileFlags(generated=True)}
    assert failed(verify_claim(ordinary, reader, recorded_flags=flags)) == {"V-7"}


def test_detect_flags(tmp_path: Path) -> None:
    rdr = make_reader(
        tmp_path,
        {
            "a.js": b"// @generated by tool\nx\n",
            "b.js": b"/* vendored copy */\nx\n",
            "node_modules/c.js": b"x\n",
            "gen/__generated__/d.js": b"x\n",
            "plain.js": b"const a = 1;\n",
            "bin.dat": b"\xff\xfe\x00bad",
        },
    )
    assert detect_flags("a.js", rdr).generated
    assert detect_flags("b.js", rdr).vendored
    assert detect_flags("node_modules/c.js", rdr).vendored
    assert detect_flags("gen/__generated__/d.js", rdr).generated
    assert detect_flags("plain.js", rdr) == FileFlags()
    assert detect_flags("bin.dat", rdr) == FileFlags()  # not UTF-8: no header to read
    assert detect_flags("plain.js", rdr, {"plain.js": FileFlags(vendored=True)}).vendored


# ---- V-9: secrets and personal data ----------------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"text": f"The key is {SECRET}."},
        {"text": "Mail goes to jane.doe@example.com."},
        {"explanation": f"Signed with {SECRET}."},
    ],
)
def test_v9_secret_or_pii_in_claim_text_or_explanation(
    reader: SnapshotReader, changes: dict[str, str]
) -> None:
    verdict = verify_claim(
        claim(reader, status="inferred", producer_kind="model", **changes), reader
    )
    assert "V-9" in failed(verdict)
    detail = next(r.detail for r in verdict.failures if r.check_id == "V-9") or ""
    assert SECRET not in detail and "jane.doe" not in detail  # kinds only, never the value


def test_v9_redacted_excerpts_do_not_trip_it_again(tmp_path: Path) -> None:
    data = f'const password = "{SECRET}1234";\n'.encode()
    rdr = make_reader(tmp_path, {"c.js": data})
    ev = (stored(rdr, lines("c.js", 1, 1)),)
    verdict = verify_claim(
        ClaimInput("C", "A password is set.", "confirmed", "deterministic", ev), rdr
    )
    assert verdict.passed


def test_v9_a_fake_marker_cannot_hide_a_secret(reader: SnapshotReader) -> None:
    text = f"[REDACTED:{SECRET}] leaked"
    assert "V-9" in failed(verify_claim(claim(reader, text=text), reader))


# ---- V-10: heuristic, demote only --------------------------------------------------------------


def test_v10_unrelated_explanation_demotes_to_unknown(reader: SnapshotReader) -> None:
    c = claim(
        reader,
        status="inferred",
        producer_kind="model",
        explanation="Customers get a refund email.",
    )
    verdict = verify_claim(c, reader)
    assert failed(verdict) == {"V-10"} and verdict.final_status == "unknown"


def test_v10_matching_explanation_changes_nothing_and_never_promotes(
    reader: SnapshotReader,
) -> None:
    c = claim(
        reader, status="inferred", producer_kind="model",
        explanation="The forEach over daily, weekly and monthly registers the report routes.",
    )  # fmt: skip
    verdict = verify_claim(c, reader)
    assert verdict.passed and verdict.final_status == "inferred"


def test_v10_is_skipped_without_an_explanation_or_without_resolved_evidence(
    reader: SnapshotReader,
) -> None:
    no_text = verify_claim(claim(reader), reader)
    assert next(r.detail for r in no_text.results if r.check_id == "V-10") == "nothing to compare"
    c = claim(
        reader, status="inferred", producer_kind="model", evidence=(), explanation="Anything."
    )
    assert "V-10" not in failed(verify_claim(c, reader))


def test_tokens() -> None:
    assert content_tokens("registerRoutes loops over the Daily reports") == {
        "register", "route", "loop", "daily", "report",
    }  # fmt: skip
    assert content_tokens("tax 75 is a bus entries class") >= {"tax", "75", "entry", "class", "bus"}
    assert overlap("the of and", "anything") == 1.0
    assert overlap("alpha beta", "alpha gamma") == 0.5


# ---- fail closed (VER-1.3) ---------------------------------------------------------------------


def boom(*_: Any, **__: Any) -> Any:
    raise RuntimeError("secret detail must not leak")


@pytest.mark.parametrize(
    ("target", "check"),
    [
        ("resolve", "V-2"),
        ("scan_text", "V-9"),
        ("rule_constants", "V-10"),
        ("detect_flags", "V-7"),
        ("max_excerpt_lines", "V-4"),
    ],
)
def test_an_error_inside_a_check_is_a_block(
    reader: SnapshotReader, monkeypatch: pytest.MonkeyPatch, target: str, check: str
) -> None:
    c = claim(
        reader, status="inferred", producer_kind="model", explanation="routes registered in a loop"
    )
    monkeypatch.setattr(verify_module, target, boom)
    verdict = verify_claim(c, reader)
    assert check in failed(verdict) and not verdict.passed
    assert all("secret detail" not in (r.detail or "") for r in verdict.results)
    assert all("error: " in (r.detail or "") for r in verdict.failures if r.check_id == check)


def test_a_crash_while_resolving_blocks_every_check(
    reader: SnapshotReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verify_module, "_item", boom)
    verdict = verify_claim(claim(reader), reader)
    assert len(verdict.failures) == 9 and verdict.final_status == "unknown"


def test_a_snapshot_that_was_edited_resolves_nothing(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.js").write_bytes(b"one\n")
    pinned = pin_local(source, tmp_path / "store", LIMITS)
    rdr = SnapshotReader.from_pinned(pinned)
    ev = (stored(rdr, lines("a.js", 1, 1)),)
    (pinned.root / "a.js").chmod(0o644)
    (pinned.root / "a.js").write_bytes(b"two\n")
    fresh = SnapshotReader.from_pinned(pinned)
    verdict = verify_claim(ClaimInput("C", "t", "confirmed", "deterministic", ev), fresh)
    assert "V-2" in failed(verdict)


# ---- batches, queue reasons, rows --------------------------------------------------------------


def test_verify_claims_keys_by_claim_id(reader: SnapshotReader) -> None:
    verdicts = verify_claims(
        [claim(reader, claim_id="A"), claim(reader, claim_id="B", status="x")], reader
    )
    assert verdicts["A"].passed and not verdicts["B"].passed


@pytest.mark.parametrize(
    ("verdict", "reason"),
    [
        (
            Verdict("c", "confirmed", "confirmed", (CheckResult("V-1", False, "x"),), False),
            "verifier_failure",
        ),
        (Verdict("c", "confirmed", "confirmed", (), True), "stale"),
        (Verdict("c", "inferred", "inferred", (), False), "inferred"),
        (Verdict("c", "unknown", "unknown", (), False), "unknown"),
        (Verdict("c", "confirmed", "confirmed", (), False), None),
    ],
)
def test_queue_reason(verdict: Verdict, reason: str | None) -> None:
    assert verdict.queue_reason == reason


def test_result_rows_are_one_per_check(reader: SnapshotReader) -> None:
    verdict = verify_claim(claim(reader, status="maybe"), reader)
    version = uuid.uuid4()
    rows = result_rows(verdict, version)
    assert len(rows) == len(verdict.results) == 9
    assert {r["claim_version_id"] for r in rows} == {version}
    assert {r["check_id"] for r in rows if not r["passed"]} == {"V-5"}


# ---- V-8: documents ----------------------------------------------------------------------------


def test_v8(reader: SnapshotReader) -> None:
    verdicts = verify_claims(
        [
            claim(reader, claim_id="OK"),
            claim(reader, claim_id="BAD", status="x"),
            claim(reader, claim_id="UNK", status="unknown", producer_kind="model", evidence=()),
        ],
        reader,
    )
    sentences = [
        DocSentence("backed", ("OK",)),
        DocSentence("uncited", ()),
        DocSentence("ghost", ("NOPE",)),
        DocSentence("failed", ("BAD",)),
        DocSentence("unknown as fact", ("UNK",)),
        DocSentence("one good one missing", ("OK", "NOPE")),
    ]
    results = verify_document(sentences, verdicts)
    assert [r.passed for r in results] == [True, False, False, False, False, False]
    assert [r.index for r in results] == list(range(6))
    reasons = [r.reason or "" for r in results[1:]]
    assert "no claim" in reasons[0] and "NOPE" in reasons[1] and "BAD" in reasons[2]
    assert "UNK" in reasons[3] and "NOPE" in reasons[4]


def test_v8_an_error_is_a_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify_module, "_sentence_problem", boom)
    (result,) = verify_document([DocSentence("x", ("A",))], {})
    assert not result.passed and result.reason == "error: RuntimeError"


# ---- statistics --------------------------------------------------------------------------------


def test_wilson_interval() -> None:
    low, high = wilson_interval(50, 50)
    assert round(low, 3) == 0.929 and high == 1.0
    low, high = wilson_interval(0, 50)
    assert round(low, 12) == 0.0 and round(high, 3) == 0.071
    assert wilson_interval(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError):
        wilson_interval(5, 4)


_UNUSED: Callable[..., Any] = boom
