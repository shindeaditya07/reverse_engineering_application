"""Report the verifier's measured quality (VER-1.4, VER-1.7): catch rate on the seeded bad
corpus and false-block rate on the good corpus, with Wilson 95% intervals. V-10 is reported
on its own because it is a heuristic.

    uv run python scripts/verifier_report.py
"""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.evidence import SnapshotReader  # noqa: E402
from services.ingest.limits import MIB, Limits  # noqa: E402
from services.ingest.pin import pin_local  # noqa: E402
from services.stats import wilson_interval  # noqa: E402
from services.verifier import verify_claim  # noqa: E402
from tests.verifier_corpus import APP, bad_claims, good_claims  # noqa: E402


def rate(label: str, hits: int, total: int) -> str:
    low, high = wilson_interval(hits, total)
    share = f"{100 * hits / total:.0f}%"
    return f"{label}: {hits}/{total} = {share} (95% interval {100 * low:.0f}% to {100 * high:.0f}%)"


def main() -> int:
    limits = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
    with tempfile.TemporaryDirectory() as store:
        reader = SnapshotReader.from_pinned(pin_local(APP, Path(store), limits))
        bad = bad_claims(reader)
        good = good_claims(reader)
        verdicts = [(c, check, verify_claim(c, reader)) for c, check in bad]
        good_verdicts = [(c, verify_claim(c, reader)) for c in good]
    caught = sum(check in {r.check_id for r in v.failures} for _, check, v in verdicts)
    v10 = [(check, v) for _, check, v in verdicts if check == "V-10"]
    v10_caught = sum("V-10" in {r.check_id for r in v.failures} for _, v in v10)
    blocked = [c.claim_id for c, v in good_verdicts if not v.passed]
    v10_only = [c for c, v in good_verdicts if {r.check_id for r in v.failures} == {"V-10"}]
    inferred = [c for c, _ in good_verdicts if c.status == "inferred" and c.explanation]
    print(rate("Seeded bad claims caught", caught, len(bad)))
    print(rate("  of which V-10 (heuristic)", v10_caught, len(v10)))
    print(rate("Good claims falsely blocked", len(blocked), len(good)))
    print(
        rate("  of which V-10 demotions", len(v10_only), len(inferred))
        + " of inferred claims with an explanation"
    )
    print("Blocked good claims:", ", ".join(blocked) or "none")
    return 0 if caught == len(bad) else 1


if __name__ == "__main__":
    sys.exit(main())
