"""The eval harness: scoring, run validity, results folder, and the smoke eval itself."""

import datetime as dt
import json
from pathlib import Path

import pytest

from services.evals import __main__ as smoke_cli
from services.evals.key import KeyFact, Span, load_key
from services.evals.results import render_report, write_results
from services.evals.runner import MAX_CONSECUTIVE_FAILURES, run_analyzer
from services.evals.score import Produced, Rate, score
from services.evals.verifier_eval import VerifierEval, evaluate_verifier


def fact(fid: str, kind: str, status: str, *spans: Span, trap: int = 1) -> KeyFact:
    return KeyFact(fid, trap, kind, status, spans)


def claim(cid: str, kind: str, status: str, *spans: Span) -> Produced:
    return Produced(cid, kind, status, spans)


A = Span("a.js", 10, 20)


# ---- the key ---------------------------------------------------------------------------------


def test_key_loads_all_facts() -> None:
    facts = load_key()
    assert len(facts) == 42 and len({f.fact_id for f in facts}) == 42
    assert [f.fact_id for f in facts if not f.spans] == ["T18-F2"]
    assert any(s.unit == "byte" for f in facts for s in f.spans)


def test_span_overlap() -> None:
    assert Span("a", 1, 5).overlap(Span("a", 5, 9)) == 1
    assert Span("a", 1, 5).overlap(Span("a", 6, 9)) == 0
    assert Span("a", 1, 5).overlap(Span("b", 1, 5)) == 0
    assert Span("a", 73, 74, "byte").overlap(Span("a", 73, 74, "byte")) == 1
    assert Span("a", 73, 74, "byte").overlap(Span("a", 74, 75, "byte")) == 0
    assert Span("a", 1, 5, "byte").overlap(Span("a", 1, 5)) == 0  # bytes never match lines


# ---- scoring ---------------------------------------------------------------------------------


def test_exact_match_scores_everything() -> None:
    result = score([claim("p1", "route", "confirmed", A)], [fact("F1", "route", "confirmed", A)])
    assert (result.precision.value, result.recall.value) == (1.0, 1.0)
    assert result.overclaims == () and result.missed_facts == () and result.unmatched_claims == ()
    assert result.traps_fully_found == Rate(1, 1)


def test_kind_and_place_must_both_match() -> None:
    facts = [fact("F1", "route", "confirmed", A)]
    wrong_kind = score([claim("p", "rule", "confirmed", A)], facts)
    wrong_place = score([claim("p", "route", "confirmed", Span("a.js", 30, 40))], facts)
    wrong_file = score([claim("p", "route", "confirmed", Span("b.js", 10, 20))], facts)
    for result in (wrong_kind, wrong_place, wrong_file):
        assert result.recall.hits == 0 and result.precision.hits == 0
        assert result.missed_facts == ("F1",) and result.unmatched_claims == ("p",)


def test_overlap_not_equality_is_enough() -> None:
    result = score(
        [claim("p", "route", "confirmed", Span("a.js", 18, 30))],
        [fact("F", "route", "confirmed", A)],
    )
    assert result.recall.hits == 1


def test_one_to_one_matching_and_largest_overlap_wins() -> None:
    facts = [
        fact("F1", "route", "confirmed", Span("a.js", 1, 10)),
        fact("F2", "route", "confirmed", Span("a.js", 8, 30)),
    ]
    claims = [
        claim("p1", "route", "confirmed", Span("a.js", 5, 30)),
        claim("p2", "route", "confirmed", Span("a.js", 1, 3)),
    ]
    result = score(claims, facts)
    assert result.recall.hits == 2 and result.precision.hits == 2
    twice = score(
        [claim("p1", "route", "confirmed", A), claim("p2", "route", "confirmed", A)],
        [fact("F", "route", "confirmed", A)],
    )
    assert twice.precision == Rate(1, 2) and twice.unmatched_claims == ("p2",)


def test_overclaims_are_counted_and_underclaims_are_not() -> None:
    facts = [fact("F1", "rule", "inferred", A), fact("F2", "rule", "confirmed", Span("b.js", 1, 2))]
    claims = [
        claim("p1", "rule", "confirmed", A),
        claim("p2", "rule", "inferred", Span("b.js", 1, 2)),
    ]
    assert score(claims, facts).overclaims == (("p1", "confirmed", "inferred"),)


def test_facts_without_evidence_are_not_scorable_and_not_counted() -> None:
    result = score([], [fact("U", "rule", "unknown"), fact("F", "rule", "confirmed", A)])
    assert result.not_scorable == ("U",) and result.recall == Rate(0, 1)


def test_trap_counts_only_when_every_scorable_fact_is_found() -> None:
    facts = [
        fact("F1", "route", "confirmed", A, trap=1),
        fact("F2", "route", "confirmed", Span("b.js", 1, 2), trap=1),
    ]
    result = score([claim("p", "route", "confirmed", A)], facts)
    assert result.traps_fully_found == Rate(0, 1) and result.recall == Rate(1, 2)


def test_per_kind_rows_include_kinds_only_one_side_has() -> None:
    result = score([claim("p", "sql_read", "confirmed", A)], [fact("F", "route", "confirmed", A)])
    kinds = {k.kind: k for k in result.per_kind}
    assert set(kinds) == {"route", "sql_read"}
    assert kinds["sql_read"].precision == Rate(0, 1) and kinds["route"].recall == Rate(0, 1)
    assert kinds["route"].precision == Rate(0, 0)


def test_rate_shows_interval_and_handles_zero() -> None:
    assert Rate(0, 0).value is None and Rate(0, 0).show() == "n/a (0 of 0)"
    assert "95% interval" in Rate(9, 10).show()
    low, high = Rate(1, 1).interval
    assert round(low, 2) == 0.21 and high == 1.0  # one hit proves very little


def test_a_run_that_copies_the_key_scores_100_and_empty_scores_0() -> None:
    facts = load_key()
    copy = [Produced(f.fact_id, f.kind, f.status, f.spans) for f in facts if f.spans]
    perfect = score(copy, facts)
    assert perfect.recall == Rate(41, 41) and perfect.precision == Rate(41, 41)
    assert score([], facts).recall.hits == 0


# ---- runs ------------------------------------------------------------------------------------


def ok(unit: str) -> list[Produced]:
    return [claim(f"c-{unit}", "route", "inferred", A)]


def test_a_clean_run_is_valid() -> None:
    run = run_analyzer(["a", "b"], ok)
    assert run.valid and run.status == "valid" and len(run.claims) == 2 and not run.failures


def test_a_failed_unit_makes_the_run_invalid_and_is_counted_separately() -> None:
    def analyze(unit: str) -> list[Produced]:
        if unit == "bad":
            raise TimeoutError("provider said: secret detail")
        return ok(unit)

    run = run_analyzer(["a", "bad", "b"], analyze)
    assert not run.valid and run.units_run == 3 and len(run.claims) == 2
    assert [(f.unit, f.error) for f in run.failures] == [("bad", "TimeoutError")]
    assert "secret detail" not in repr(run.failures)  # the exception type only
    assert run.status.startswith("INVALID") and "1 failed of 3" in run.status


def test_three_failures_in_a_row_stop_the_run() -> None:
    def analyze(unit: str) -> list[Produced]:
        raise RuntimeError

    run = run_analyzer(list("abcdef"), analyze)
    assert MAX_CONSECUTIVE_FAILURES == 3
    assert run.stopped_early and run.units_run == 3 and not run.valid
    assert "consecutive" in run.status


def test_a_success_resets_the_consecutive_count() -> None:
    def analyze(unit: str) -> list[Produced]:
        if unit in "bcef":
            raise RuntimeError
        return ok(unit)

    run = run_analyzer(list("abcdefg"), analyze)
    assert not run.stopped_early and run.units_run == 7 and len(run.failures) == 4
    assert not run.valid


def test_an_empty_run_is_valid_but_empty() -> None:
    run = run_analyzer([], ok)
    assert run.valid and run.claims == ()


# ---- results ---------------------------------------------------------------------------------


def test_write_results_makes_a_dated_folder_and_never_overwrites(tmp_path: Path) -> None:
    folder = write_results("run1", "# r", {"model": None}, tmp_path, dt.date(2026, 11, 5))
    assert folder.name == "2026-11-05-run1"
    assert (folder / "report.md").read_text() == "# r"
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["model"] is None and "commit" in manifest
    with pytest.raises(FileExistsError):
        write_results("run1", "# again", {}, tmp_path, dt.date(2026, 11, 5))


@pytest.mark.parametrize("bad", ["", "../x", "a/b", "a\\b", ".hidden"])
def test_run_id_must_be_a_plain_name(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        write_results(bad, "x", {}, tmp_path)


def test_write_results_defaults_to_today(tmp_path: Path) -> None:
    folder = write_results("today", "x", {}, tmp_path)
    assert folder.name.endswith("-today") and folder.name[:4].isdigit()


def test_git_sha_falls_back_when_git_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_git(*_: object, **__: object) -> None:
        raise FileNotFoundError

    monkeypatch.setattr("services.evals.results.subprocess.run", no_git)
    folder = write_results("nogit", "x", {}, tmp_path)
    assert json.loads((folder / "manifest.json").read_text())["commit"] == "unknown"


def test_report_shows_intervals_failures_and_gaps() -> None:
    facts = load_key()
    scores = score([], facts)
    run = run_analyzer(["u"], lambda unit: (_ for _ in ()).throw(TimeoutError()))
    text = render_report("T", scores, evaluate_verifier(), run)
    assert "INVALID" in text and "`u`: TimeoutError" in text
    assert "95% interval" in text and "T18-F2" in text and "Missed facts" in text
    assert "falsely blocked" in text


def test_report_can_omit_sections() -> None:
    assert render_report("Only", None, None, None).strip() == "# Only"


# ---- verifier eval and the smoke command ------------------------------------------------------


def test_verifier_eval_measures_both_corpora() -> None:
    result = evaluate_verifier()
    assert result.caught == Rate(50, 50) and result.missed == ()
    assert result.v10_caught == Rate(7, 7)
    assert result.falsely_blocked.total == 50
    assert len(result.blocked_ids) == result.falsely_blocked.hits  # bad numbers are reported


def test_smoke_passes_today(capsys: pytest.CaptureFixture[str]) -> None:
    assert smoke_cli.main(["smoke"]) == 0
    assert "Seeded bad claims caught: 100%" in capsys.readouterr().out


def test_smoke_can_write_a_results_folder(tmp_path: Path) -> None:
    assert smoke_cli.main(["smoke", "--out", str(tmp_path)]) == 0
    (folder,) = list(tmp_path.iterdir())
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["kind"] == "smoke" and manifest["model"] is None
    assert len(manifest["answer_key_sha256"]) == 64 and manifest["problems"] == []


def test_smoke_fails_when_the_verifier_misses_a_bad_claim(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real = evaluate_verifier()
    broken = VerifierEval(
        Rate(49, 50), real.v10_caught, real.falsely_blocked, real.v10_demotions,
        real.blocked_ids, ("V-3: a missed claim",),
    )  # fmt: skip
    monkeypatch.setattr(smoke_cli, "evaluate_verifier", lambda: broken)
    assert smoke_cli.main(["smoke"]) == 1
    err = capsys.readouterr().err
    assert "caught 98%" in err and "missed V-3: a missed claim" in err


def test_smoke_fails_when_scoring_is_broken(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smoke_cli, "oracle_run", lambda: [])
    assert smoke_cli.main(["smoke"]) == 1


def test_smoke_fails_when_an_empty_run_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    real_score = score
    calls: list[int] = []

    def fake(produced: list[Produced], facts: list[KeyFact]):  # type: ignore[no-untyped-def]
        calls.append(1)
        if len(calls) == 2:  # the empty-run call
            return real_score([Produced("x", "route", "confirmed", (A,))], facts)
        return real_score(produced, facts)

    monkeypatch.setattr(smoke_cli, "score", fake)
    assert smoke_cli.main(["smoke"]) == 1
