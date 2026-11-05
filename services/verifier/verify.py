"""Checks V-1 to V-10 (spec section 11). Each failure names its claim and its check ID.

Fail closed (VER-1.3): a check that raises is a failed check, never a pass. A model may only
demote a claim, and V-10 is the only heuristic here; nothing in this module promotes a claim.
"""

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from services.evidence import (
    EvidenceRef,
    Resolution,
    SnapshotReader,
    check_hash,
    parse_ref,
    resolve,
)
from services.evidence.refs import max_excerpt_lines
from services.ingest.scan import scan_text
from services.rules_constants import rule_constants
from services.verifier.flags import FileFlags, detect_flags
from services.verifier.models import (
    DEMOTING_CHECKS,
    PRODUCER_KINDS,
    STATUSES,
    CheckResult,
    ClaimInput,
    DocSentence,
    EvidenceInput,
    SentenceResult,
    Verdict,
)
from services.verifier.tokens import overlap

DETERMINISTIC = ("deterministic", "test")
_MARKER = re.compile(r"\[REDACTED:[a-z_:]+\]")
_ALL = ("V-1", "V-2", "V-3", "V-4", "V-5", "V-6", "V-7", "V-9", "V-10")


@dataclass(frozen=True)
class _Item:
    """One cited reference after parsing, resolving and re-hashing."""

    ref: EvidenceRef | None
    stored_hash: str | None
    problem: str | None  # why it could not be parsed or resolved
    owner: str  # the check that reports `problem`: "V-2" or "V-4"
    resolution: Resolution | None
    checked: Resolution | None  # the same reference compared with its stored hash


def _too_long(raw: Mapping[str, Any]) -> bool:
    start, end = raw.get("start_line"), raw.get("end_line")
    return (
        raw.get("kind") == "file_range"
        and isinstance(start, int)
        and isinstance(end, int)
        and end - start + 1 > max_excerpt_lines()
    )


def _parse(entry: EvidenceInput) -> tuple[EvidenceRef | None, str | None, str]:
    """(reference, problem, owning check). A reference that does not parse has no span."""
    ref = entry.ref
    if not isinstance(ref, Mapping):
        return ref, None, "V-2"
    try:
        return parse_ref(dict(ref)), None, "V-2"
    except (ValidationError, TypeError, ValueError) as error:
        if _too_long(ref):
            return None, f"span over the line limit: {type(error).__name__}", "V-4"
        return None, f"invalid reference: {type(error).__name__}", "V-2"


def _item(entry: EvidenceInput, reader: SnapshotReader) -> _Item:
    ref, problem, owner = _parse(entry)
    if ref is None:
        return _Item(None, entry.content_hash, problem, owner, None, None)
    try:
        found = resolve(ref, reader)
        checked = None
        if found.status == "resolved" and entry.content_hash is not None:
            checked = check_hash(ref, entry.content_hash, reader)
    except Exception as error:  # fail closed: any crash is an unresolved reference
        return _Item(ref, entry.content_hash, f"error: {type(error).__name__}", "V-2", None, None)
    if found.status == "unresolved":
        reason = found.reason or "unresolved"
        owner = "V-4" if reason.startswith("span_too_long") else "V-2"
        return _Item(ref, entry.content_hash, reason, owner, None, None)
    return _Item(ref, entry.content_hash, None, "V-2", found, checked)


def _result(check_id: str, problems: list[str], ok: str | None = None) -> CheckResult:
    if problems:
        return CheckResult(check_id, False, "; ".join(problems))
    return CheckResult(check_id, True, ok)


def _v1(claim: ClaimInput, items: list[_Item]) -> CheckResult:
    # EVD-1.1: a claim with no evidence is Unknown, and Unknown needs none. Anything else does.
    missing = not claim.evidence and claim.status != "unknown"
    return _result("V-1", ["the claim cites no evidence (EVD-1.1)"] if missing else [])


def _v2(claim: ClaimInput, items: list[_Item]) -> CheckResult:
    problems = [
        f"ref {n}: {i.problem}" for n, i in enumerate(items, 1) if i.owner == "V-2" and i.problem
    ]
    return _result("V-2", problems)


def _v3(claim: ClaimInput, items: list[_Item]) -> CheckResult:
    problems = []
    for n, item in enumerate(items, 1):
        if item.resolution is None:
            continue
        if item.stored_hash is None:
            problems.append(f"ref {n}: no content hash stored (EVD-1.3)")
        elif item.checked is not None and item.checked.status == "stale":
            problems.append(f"ref {n}: the cited bytes changed since the claim was made")
    return _result("V-3", problems)


def _v4(claim: ClaimInput, items: list[_Item]) -> CheckResult:
    limit = max_excerpt_lines()
    problems = [
        f"ref {n}: {i.problem} (limit {limit} lines)"
        for n, i in enumerate(items, 1)
        if i.owner == "V-4" and i.problem
    ]
    return _result("V-4", problems)


def _v5(claim: ClaimInput, items: list[_Item]) -> CheckResult:
    problems = []
    if claim.status not in STATUSES:
        problems.append(f"status {claim.status!r} is not confirmed, inferred or unknown")
    if claim.producer_kind not in PRODUCER_KINDS:
        problems.append(f"producer {claim.producer_kind!r} is not a known kind")
    elif claim.status == "confirmed" and claim.producer_kind not in DETERMINISTIC:
        problems.append(
            f"confirmed needs a deterministic analysis or test, not {claim.producer_kind}"
        )
    elif claim.status == "inferred" and claim.producer_kind == "test":
        problems.append("a test confirms or says nothing; it does not produce an inference")
    return _result("V-5", problems)


def _v6(claim: ClaimInput, items: list[_Item]) -> CheckResult:
    bad = claim.status == "confirmed" and claim.producer_kind == "model"
    return _result(
        "V-6", ["a model alone cannot produce a Confirmed claim (CLM-1.2)"] if bad else []
    )


def _v9(claim: ClaimInput, items: list[_Item]) -> CheckResult:
    texts = {"claim text": claim.text, "explanation": claim.explanation or ""}
    texts.update(
        {f"excerpt {n}": i.resolution.excerpt for n, i in enumerate(items, 1) if i.resolution}
    )
    problems = []
    for where, text in texts.items():
        # A redaction marker is not a value; without this, `password = "[REDACTED:...]"` would
        # match the credential pattern again. Only the exact marker form is removed.
        kinds = sorted({f.kind for f in scan_text("claim", _MARKER.sub("", text), numbered=False)})
        if kinds:
            problems.append(f"{where} holds {', '.join(kinds)} (SEC-1.3, SEC-1.5)")
    return _result("V-9", problems)


def _v10(claim: ClaimInput, items: list[_Item]) -> CheckResult:
    explanation = (claim.explanation or "").strip()
    found = [i for i in items if i.resolution is not None and i.ref is not None]
    if not explanation or not found:
        return CheckResult("V-10", True, "nothing to compare")
    evidence = " ".join(
        f"{i.resolution.excerpt} {i.ref.path}" for i in found if i.resolution and i.ref
    )
    score = overlap(explanation, evidence)
    floor = float(rule_constants("VER-1.7")["v10_demote_overlap_below"])
    detail = f"overlap {score:.2f}, floor {floor}"
    if score < floor:
        return CheckResult("V-10", False, f"explanation does not match the cited code: {detail}")
    return CheckResult("V-10", True, detail)


def _v7(
    claim: ClaimInput,
    items: list[_Item],
    reader: SnapshotReader,
    recorded: Mapping[str, FileFlags] | None,
) -> CheckResult:
    paths = {i.ref.path for i in items if i.resolution is not None and i.ref is not None}
    problems = []
    for path in sorted(paths):
        flag = detect_flags(path, reader, recorded)
        if (flag.generated or flag.vendored) and path not in claim.subject_paths:
            kind = "generated" if flag.generated else "vendored"
            problems.append(f"{path} is {kind} and the claim is not about it (EVD-1.6)")
    return _result("V-7", problems)


def _guard(check_id: str, run: Callable[[], CheckResult]) -> CheckResult:
    try:
        return run()
    except Exception as error:  # VER-1.3: an error is a block, never a pass
        return CheckResult(check_id, False, f"error: {type(error).__name__}")


def _run(
    check_id: str,
    check: Callable[[ClaimInput, list[_Item]], CheckResult],
    claim: ClaimInput,
    items: list[_Item],
) -> CheckResult:
    return _guard(check_id, lambda: check(claim, items))


def _verdict(claim: ClaimInput, results: tuple[CheckResult, ...], stale: bool) -> Verdict:
    failed = {r.check_id for r in results if not r.passed}
    demoted = bool(failed & DEMOTING_CHECKS) or claim.status not in STATUSES
    status = "unknown" if demoted else claim.status
    return Verdict(claim.claim_id, claim.status, status, results, stale)


def verify_claim(
    claim: ClaimInput,
    reader: SnapshotReader,
    *,
    recorded_flags: Mapping[str, FileFlags] | None = None,
) -> Verdict:
    """Run every claim-level check. V-8 is document-level: see verify_document."""
    try:
        items = [_item(entry, reader) for entry in claim.evidence]
    except Exception as error:  # a crash while resolving blocks every check
        failed = tuple(CheckResult(c, False, f"error: {type(error).__name__}") for c in _ALL)
        return _verdict(claim, failed, stale=False)
    plain: dict[str, Callable[[ClaimInput, list[_Item]], CheckResult]] = {
        "V-1": _v1,
        "V-2": _v2,
        "V-3": _v3,
        "V-4": _v4,
        "V-5": _v5,
        "V-6": _v6,
        "V-9": _v9,
        "V-10": _v10,
    }
    results = {cid: _run(cid, fn, claim, items) for cid, fn in plain.items()}
    results["V-7"] = _guard("V-7", lambda: _v7(claim, items, reader, recorded_flags))
    stale = any(i.checked is not None and i.checked.status == "stale" for i in items)
    return _verdict(claim, tuple(results[c] for c in _ALL), stale)


def verify_claims(
    claims: Iterable[ClaimInput],
    reader: SnapshotReader,
    *,
    recorded_flags: Mapping[str, FileFlags] | None = None,
) -> dict[str, Verdict]:
    return {c.claim_id: verify_claim(c, reader, recorded_flags=recorded_flags) for c in claims}


def _sentence_problem(sentence: DocSentence, verdicts: Mapping[str, Verdict]) -> str | None:
    if not sentence.claim_ids:
        return "sentence cites no claim"
    for claim_id in sentence.claim_ids:
        verdict = verdicts.get(claim_id)
        if verdict is None:
            return f"cites {claim_id}, which is not a stored claim"
        if not verdict.passed:
            return f"cites {claim_id}, which failed verification"
        if verdict.final_status == "unknown":
            return f"cites {claim_id}, which is Unknown and cannot be stated as fact"
    return None


def verify_document(
    sentences: Iterable[DocSentence], verdicts: Mapping[str, Verdict]
) -> list[SentenceResult]:
    """V-8 (CLM-1.6): a sentence stands only if every claim it cites exists, passed
    verification, and is not Unknown. It does not check that the sentence says what the claim
    says; see docs/verifier.md."""
    results = []
    for index, sentence in enumerate(sentences):
        try:
            reason = _sentence_problem(sentence, verdicts)
        except Exception as error:  # VER-1.3
            reason = f"error: {type(error).__name__}"
        results.append(SentenceResult(index, reason is None, reason))
    return results
