"""Precision and recall against the answer key, with Wilson 95% intervals (spec section 18).

A produced claim matches a key fact when it has the same kind and one of its cited spans
overlaps one of the fact's spans. Matching is one to one and greedy in claim-id order, taking
the largest overlap, so the result is deterministic.

What the numbers mean, and do not:
- Recall is exact for the facts in the key. The key lists the true facts for 35 traps; it is
  not every fact in the fixture.
- Precision is the share of produced claims that match a key fact. A true claim the key does
  not list counts against it, so it is a floor, not an estimate of correctness.
- A fact with no evidence (an Unknown) cannot be matched by place and is listed as not
  scorable, never counted.
- An overclaim is a matched claim whose status is stronger than the key's.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from services.evals.key import STRENGTH, KeyFact, Span
from services.stats import wilson_interval


@dataclass(frozen=True)
class Produced:
    claim_id: str
    kind: str
    status: str
    spans: tuple[Span, ...]


@dataclass(frozen=True)
class Rate:
    hits: int
    total: int

    @property
    def value(self) -> float | None:
        return self.hits / self.total if self.total else None

    @property
    def interval(self) -> tuple[float, float]:
        return wilson_interval(self.hits, self.total)

    def show(self) -> str:
        if not self.total:
            return "n/a (0 of 0)"
        low, high = self.interval
        return (
            f"{100 * self.hits / self.total:.0f}% ({self.hits}/{self.total}, "
            f"95% interval {100 * low:.0f}% to {100 * high:.0f}%)"
        )


@dataclass(frozen=True)
class KindScore:
    kind: str
    precision: Rate
    recall: Rate


@dataclass(frozen=True)
class Scores:
    per_kind: tuple[KindScore, ...]
    precision: Rate
    recall: Rate
    traps_fully_found: Rate
    overclaims: tuple[tuple[str, str, str], ...]  # (claim id, produced status, key status)
    unmatched_claims: tuple[str, ...]
    missed_facts: tuple[str, ...]
    not_scorable: tuple[str, ...]


def _best(claim: Produced, facts: Iterable[KeyFact], taken: set[str]) -> KeyFact | None:
    best: tuple[int, KeyFact] | None = None
    for fact in facts:
        if fact.kind != claim.kind or fact.fact_id in taken:
            continue
        size = max((a.overlap(b) for a in claim.spans for b in fact.spans), default=0)
        if size > 0 and (best is None or size > best[0]):
            best = (size, fact)
    return best[1] if best else None


def score(produced: Sequence[Produced], facts: Sequence[KeyFact]) -> Scores:
    scorable = [f for f in facts if f.spans]
    taken: set[str] = set()
    matches: dict[str, KeyFact] = {}
    for claim in sorted(produced, key=lambda c: c.claim_id):
        fact = _best(claim, scorable, taken)
        if fact is not None:
            taken.add(fact.fact_id)
            matches[claim.claim_id] = fact

    kinds = sorted({f.kind for f in scorable} | {c.kind for c in produced})
    per_kind = tuple(
        KindScore(
            kind,
            Rate(
                sum(1 for c in produced if c.kind == kind and c.claim_id in matches),
                sum(1 for c in produced if c.kind == kind),
            ),
            Rate(
                sum(1 for f in scorable if f.kind == kind and f.fact_id in taken),
                sum(1 for f in scorable if f.kind == kind),
            ),
        )
        for kind in kinds
    )
    by_trap: dict[int, list[KeyFact]] = defaultdict(list)
    for fact in scorable:
        by_trap[fact.trap].append(fact)
    complete = sum(all(f.fact_id in taken for f in group) for group in by_trap.values())
    claims = {c.claim_id: c for c in produced}
    return Scores(
        per_kind=per_kind,
        precision=Rate(len(matches), len(produced)),
        recall=Rate(len(taken), len(scorable)),
        traps_fully_found=Rate(complete, len(by_trap)),
        overclaims=tuple(
            (cid, claims[cid].status, fact.status)
            for cid, fact in sorted(matches.items())
            if STRENGTH.get(claims[cid].status, 0) > STRENGTH[fact.status]
        ),
        unmatched_claims=tuple(sorted(c.claim_id for c in produced if c.claim_id not in matches)),
        missed_facts=tuple(f.fact_id for f in scorable if f.fact_id not in taken),
        not_scorable=tuple(f.fact_id for f in facts if not f.spans),
    )
