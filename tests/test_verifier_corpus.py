"""VER-1.4: the verifier catches every seeded bad claim and its false-block rate is measured."""

from collections import Counter

import pytest

from services.evidence import SnapshotReader
from services.ingest.limits import MIB, Limits
from services.ingest.pin import pin_local
from services.rules_constants import rule_constants
from services.verifier import verify_claim, verify_claims, verify_document
from tests.verifier_corpus import APP, bad_claims, good_claims, sentences


@pytest.fixture(scope="module")
def reader(tmp_path_factory: pytest.TempPathFactory) -> SnapshotReader:
    limits = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
    return SnapshotReader.from_pinned(pin_local(APP, tmp_path_factory.mktemp("snap"), limits))


def test_corpus_sizes(reader: SnapshotReader) -> None:
    assert len(good_claims(reader)) == 50
    assert len(bad_claims(reader)) == 50
    assert len({c.claim_id for c in good_claims(reader)}) == 50


def test_every_check_has_seeded_bad_claims(reader: SnapshotReader) -> None:
    counts = Counter(check for _, check in bad_claims(reader))
    assert set(counts) == {"V-1", "V-2", "V-3", "V-4", "V-5", "V-6", "V-7", "V-9", "V-10"}
    assert min(counts.values()) >= 5


def test_the_verifier_catches_every_seeded_bad_claim(reader: SnapshotReader) -> None:
    target = rule_constants("VER-1.4")["seeded_bad_claims_caught_percent"]
    bad = bad_claims(reader)
    missed = [
        (claim.text, check)
        for claim, check in bad
        if check not in {r.check_id for r in verify_claim(claim, reader).failures}
    ]
    caught_percent = 100 * (len(bad) - len(missed)) / len(bad)
    assert caught_percent >= target, f"missed: {missed}"


def test_a_bad_claim_is_never_left_able_to_stand(reader: SnapshotReader) -> None:
    for claim, check in bad_claims(reader):
        verdict = verify_claim(claim, reader)
        assert not verdict.passed, (check, claim.text)
        assert verdict.queue_reason is not None


def test_deterministic_checks_never_block_a_good_claim(reader: SnapshotReader) -> None:
    """V-10 is a heuristic and may demote a good claim; nothing else may touch one."""
    for claim in good_claims(reader):
        verdict = verify_claim(claim, reader)
        assert {r.check_id for r in verdict.failures} <= {"V-10"}, claim.claim_id
        if not verdict.failures:
            assert verdict.final_status == claim.status


def test_v10_only_ever_blocks_inferred_claims_with_an_explanation(reader: SnapshotReader) -> None:
    for claim in good_claims(reader):
        if any(r.check_id == "V-10" for r in verify_claim(claim, reader).failures):
            assert claim.status == "inferred" and claim.explanation


def test_v8_corpus(reader: SnapshotReader) -> None:
    good = good_claims(reader)
    bad = bad_claims(reader)[0][0]
    verdicts = verify_claims([*good, bad], reader)
    standing, rejected = sentences(
        [c.claim_id for c in good if c.status == "confirmed"], bad.claim_id
    )
    assert all(r.passed for r in verify_document(standing, verdicts))
    assert not any(r.passed for r in verify_document(rejected, verdicts))
