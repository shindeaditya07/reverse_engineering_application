"""Write a run's results under evals/results/YYYY-MM-DD-<run-id>/ (spec section 19).

Real runs are committed there with the model and prompt hashes. Smoke runs print to the
terminal and are not committed.
"""

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

from services.evals.runner import RunResult
from services.evals.score import Scores
from services.evals.verifier_eval import VerifierEval

RESULTS_DIR = Path(__file__).resolve().parents[2] / "evals/results"


def render_report(
    title: str, scores: Scores | None, verifier: VerifierEval | None, run: RunResult | None
) -> str:
    out = [f"# {title}", ""]
    if run is not None:
        out += [f"Run status: **{run.status}**", ""]
        if run.failures:
            out += ["Failures (counted on their own, never treated as empty results):", ""]
            out += [f"- `{f.unit}`: {f.error}" for f in run.failures] + [""]
    if scores is not None:
        out += [
            "## Against the answer key",
            "",
            f"- Recall: {scores.recall.show()}",
            f"- Precision (a floor, see docs/evals.md): {scores.precision.show()}",
            f"- Traps with every scorable fact found: {scores.traps_fully_found.show()}",
            f"- Overclaims (stronger status than the key): {len(scores.overclaims)}",
            "",
            "| Kind | Precision | Recall |",
            "|---|---|---|",
        ]
        out += [f"| {k.kind} | {k.precision.show()} | {k.recall.show()} |" for k in scores.per_kind]
        out += ["", f"Missed facts: {', '.join(scores.missed_facts) or 'none'}"]
        out += [f"Not scorable (no evidence): {', '.join(scores.not_scorable) or 'none'}", ""]
    if verifier is not None:
        out += [
            "## Verifier",
            "",
            f"- Seeded bad claims caught: {verifier.caught.show()}",
            f"- V-10 alone (heuristic): {verifier.v10_caught.show()}",
            f"- Good claims falsely blocked: {verifier.falsely_blocked.show()}",
            f"- V-10 demotions of good Inferred claims with an explanation: "
            f"{verifier.v10_demotions.show()}",
            f"- Blocked good claims: {', '.join(verifier.blocked_ids) or 'none'}",
            "",
        ]
    return "\n".join(out)


def _git_sha() -> str:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return done.stdout.strip()


def write_results(
    run_id: str,
    report: str,
    manifest: dict[str, Any],
    root: Path = RESULTS_DIR,
    today: dt.date | None = None,
) -> Path:
    """Create <root>/<date>-<run_id>/ with report.md and manifest.json. Never overwrites."""
    if not run_id or any(ch in run_id for ch in "/\\") or run_id.startswith("."):
        raise ValueError("run id must be a plain name")
    folder = root / f"{(today or dt.datetime.now(dt.UTC).date()).isoformat()}-{run_id}"
    folder.mkdir(parents=True)  # FileExistsError if the run id was already used
    (folder / "report.md").write_text(report, encoding="utf-8")
    full = {"commit": _git_sha(), **manifest}
    (folder / "manifest.json").write_text(json.dumps(full, indent=2, sort_keys=True), "utf-8")
    return folder
