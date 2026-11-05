"""The answer-key drift check must pass on the real key and fail on each kind of drift."""

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts import check_answer_key as ck

ROOT = Path(__file__).resolve().parent.parent
KEY_PATH = ROOT / "fixtures/answer-key/key.yaml"
MAX_LINES = ck.max_excerpt_lines(ROOT / "rules_constants.yaml")


@pytest.fixture
def key() -> dict[str, Any]:
    loaded = yaml.safe_load(KEY_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return copy.deepcopy(loaded)


def problems(key: dict[str, Any]) -> list[str]:
    return ck.check(key, ROOT, MAX_LINES)


def fact(key: dict[str, Any], fact_id: str) -> dict[str, Any]:
    for trap in key["traps"]:
        for item in trap["facts"]:
            if item["id"] == fact_id:
                result: dict[str, Any] = item
                return result
    raise AssertionError(fact_id)


def test_real_key_is_consistent(key: dict[str, Any]) -> None:
    assert problems(key) == []


def test_limit_comes_from_the_constants_file() -> None:
    assert MAX_LINES == 40


def test_key_is_a_draft_until_a_human_reviews_it(key: dict[str, Any]) -> None:
    facts = [f for t in key["traps"] for f in t["facts"]]
    assert key["review"] == "needs_review"
    assert {f["review"] for f in facts} == {"needs_review"}
    assert "NOT fully reviewed" in ck.summarise(key)


def test_all_35_traps_present(key: dict[str, Any]) -> None:
    assert [t["trap"] for t in key["traps"]] == list(range(1, 36))


def test_changed_snippet_is_drift(key: dict[str, Any]) -> None:
    fact(key, "T17-F1")["evidence"][0]["snippet"] = "return Math.round("
    assert any("T17-F1" in p and "not 'return Math.round('" in p for p in problems(key))


def test_moved_line_is_drift(key: dict[str, Any]) -> None:
    fact(key, "T17-F1")["evidence"][0]["start"] += 1
    fact(key, "T17-F1")["evidence"][0]["end"] += 1
    assert any("T17-F1" in p for p in problems(key))


def test_range_past_end_of_file(key: dict[str, Any]) -> None:
    fact(key, "T13-F1")["evidence"][0]["end"] = 9999
    assert any("outside config.js" in p for p in problems(key))


def test_span_over_the_limit(key: dict[str, Any]) -> None:
    item = fact(key, "T21-F1")["evidence"][0]
    item.update({"start": 1, "end": MAX_LINES + 1, "snippet": "'use strict';"})
    assert any("over the limit" in p for p in problems(key))


def test_span_at_the_limit_is_allowed(key: dict[str, Any]) -> None:
    item = fact(key, "T21-F1")["evidence"][0]
    item.update({"start": 1, "end": MAX_LINES, "snippet": "'use strict';"})
    assert problems(key) == []


def test_missing_trap(key: dict[str, Any]) -> None:
    key["traps"].pop()
    assert any("numbered 1 to 35" in p for p in problems(key))


def test_duplicate_trap_number(key: dict[str, Any]) -> None:
    key["traps"][1]["trap"] = 1
    assert any("numbered 1 to 35" in p for p in problems(key))


def test_trap_without_facts(key: dict[str, Any]) -> None:
    key["traps"][0]["facts"] = []
    assert any("trap 1: needs at least one fact" in p for p in problems(key))


def test_duplicate_fact_id(key: dict[str, Any]) -> None:
    fact(key, "T03-F2")["id"] = "T03-F1"
    assert any("used twice" in p for p in problems(key))


def test_fact_id_must_match_its_trap(key: dict[str, Any]) -> None:
    fact(key, "T02-F1")["id"] = "T09-F7"
    assert any("must look like T02-F1" in p for p in problems(key))


def test_bad_status(key: dict[str, Any]) -> None:
    fact(key, "T01-F1")["status"] = "Proven"
    assert any("status must be" in p for p in problems(key))


def test_confirmed_needs_evidence(key: dict[str, Any]) -> None:
    fact(key, "T01-F1")["evidence"] = []
    assert any("Confirmed facts need evidence" in p for p in problems(key))


def test_inferred_needs_evidence(key: dict[str, Any]) -> None:
    fact(key, "T04-F1")["evidence"] = []
    assert any("Inferred facts need evidence" in p for p in problems(key))


def test_unknown_may_have_no_evidence(key: dict[str, Any]) -> None:
    unknown = fact(key, "T18-F2")
    assert unknown["status"] == "Unknown"
    assert unknown["evidence"] == []
    assert problems(key) == []


def test_reviewed_needs_a_reviewer_and_date(key: dict[str, Any]) -> None:
    fact(key, "T01-F1")["review"] = "reviewed"
    assert any("reviewed needs reviewed_by and reviewed_on" in p for p in problems(key))


def test_reviewed_fact_with_reviewer_is_accepted(key: dict[str, Any]) -> None:
    item = fact(key, "T01-F1")
    item.update({"review": "reviewed", "reviewed_by": "aditya", "reviewed_on": "2026-11-06"})
    assert problems(key) == []


def test_top_level_cannot_claim_review_early(key: dict[str, Any]) -> None:
    key["review"] = "reviewed"
    assert any("some facts are still needs_review" in p for p in problems(key))


def test_path_traversal_is_rejected(key: dict[str, Any]) -> None:
    fact(key, "T13-F1")["evidence"][0]["file"] = "../../pyproject.toml"
    assert any("relative path inside the fixture app" in p for p in problems(key))


def test_absolute_path_is_rejected(key: dict[str, Any]) -> None:
    fact(key, "T13-F1")["evidence"][0]["file"] = "/etc/passwd"
    assert any("relative path inside the fixture app" in p for p in problems(key))


def test_missing_file(key: dict[str, Any]) -> None:
    fact(key, "T13-F1")["evidence"][0]["file"] = "nope.js"
    assert any("does not exist" in p for p in problems(key))


def test_invalid_utf8_file_cannot_be_cited_by_line(key: dict[str, Any]) -> None:
    item = fact(key, "T31-F1")["evidence"][0]
    item.pop("bytes")
    item.update({"start": 3, "end": 3, "snippet": "// Labels"})
    assert any("not valid UTF-8" in p for p in problems(key))


def test_byte_range_must_match(key: dict[str, Any]) -> None:
    fact(key, "T31-F1")["evidence"][0]["bytes"]["hex"] = "e8"
    assert any("key says e8" in p for p in problems(key))


def test_byte_range_outside_file(key: dict[str, Any]) -> None:
    span = fact(key, "T31-F1")["evidence"][0]["bytes"]
    span.update({"start": 99999, "end": 100000})
    assert any("outside lib/legacy_labels.js" in p for p in problems(key))


def test_crlf_file_lines_count_after_normalising(key: dict[str, Any]) -> None:
    item = fact(key, "T32-F1")["evidence"][0]
    assert item["file"] == "lib/totals.js"
    assert (ROOT / "fixtures/legacy-app/lib/totals.js").read_bytes().count(b"\r\n") > 0
    assert (item["start"], item["end"]) == (3, 5)
    assert problems(key) == []


def test_missing_app_folder(key: dict[str, Any]) -> None:
    key["app"] = "fixtures/nowhere"
    assert any("does not exist" in p for p in problems(key))


def test_wrong_version(key: dict[str, Any]) -> None:
    key["version"] = 2
    assert "version must be 1" in problems(key)


def test_main_passes_on_real_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(ROOT)
    assert ck.main([]) == 0
    assert "Answer key check passed" in capsys.readouterr().out


def test_main_fails_on_drift(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    key: dict[str, Any],
) -> None:
    fact(key, "T17-F1")["evidence"][0]["snippet"] = "return Math.round("
    broken = tmp_path / "key.yaml"
    broken.write_text(yaml.safe_dump(key), encoding="utf-8")
    monkeypatch.chdir(ROOT)
    assert ck.main(["--key", str(broken)]) == 1
    assert "T17-F1" in capsys.readouterr().out


def test_main_rejects_a_key_that_is_not_a_mapping(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    broken = tmp_path / "key.yaml"
    broken.write_text("- just\n- a list\n", encoding="utf-8")
    monkeypatch.chdir(ROOT)
    assert ck.main(["--key", str(broken)]) == 1
    assert "must hold a mapping" in capsys.readouterr().out
