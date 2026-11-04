from pathlib import Path

from scripts import policy_check as pc

RULES = """# Rules

- **EVD-1.4** A range MUST NOT span more than 40 lines.
- **OPS-1.1** A job MUST retry at most 3 times; see EVD-1.4 and V-10.
  A model call MUST time out after 120 seconds.
- **CLM-1.1** Every claim MUST have exactly one status, counted from 1.
"""

CONSTANTS = {
    "version": 1,
    "EVD-1.4": {"max_excerpt_lines": 40},
    "OPS-1.1": {"max_job_retries": 3, "model_call_timeout_seconds": 120},
}


def test_parse_joins_wrapped_lines_and_ignores_headings() -> None:
    rules = pc.parse_rules(RULES)
    assert set(rules) == {"EVD-1.4", "OPS-1.1", "CLM-1.1"}
    assert "120 seconds" in rules["OPS-1.1"]


def test_matching_constants_pass() -> None:
    rules = pc.parse_rules(RULES)
    assert pc.check_constants(rules, CONSTANTS) == []
    assert pc.check_unconstrained_numbers(rules, CONSTANTS) == []


def test_wrong_value_is_caught() -> None:
    rules = pc.parse_rules(RULES)
    bad = {**CONSTANTS, "EVD-1.4": {"max_excerpt_lines": 50}}
    errors = pc.check_constants(rules, bad)
    assert errors == ["EVD-1.4.max_excerpt_lines: value 50 not found in the rule text"]


def test_unknown_rule_id_is_caught() -> None:
    rules = pc.parse_rules(RULES)
    errors = pc.check_constants(rules, {"EVD-9.9": {"x": 1}})
    assert errors == ["EVD-9.9: no such rule in rules.md"]


def test_number_in_rule_but_not_in_constants_is_caught() -> None:
    rules = pc.parse_rules(RULES)
    errors = pc.check_unconstrained_numbers(rules, {"EVD-1.4": {"max_excerpt_lines": 40}})
    assert any(e.startswith("OPS-1.1: number 3 ") for e in errors)
    assert any(e.startswith("OPS-1.1: number 120 ") for e in errors)


def test_rule_ids_and_trivial_numbers_are_not_flagged() -> None:
    rules = pc.parse_rules(RULES)
    assert pc.numbers_in(rules["CLM-1.1"]) == {1.0}
    assert pc.numbers_in("see EVD-1.4, V-10, UTF-8 and Apache-2.0") == set()


def test_lock_detects_changes_and_missing_lock(tmp_path: Path) -> None:
    rules_file = tmp_path / "rules.md"
    rules_file.write_text(RULES)
    lock = tmp_path / "lock.json"
    assert "missing" in pc.check_lock(lock, [rules_file])[0]
    pc.write_lock(lock, [rules_file])
    assert pc.check_lock(lock, [rules_file]) == []
    rules_file.write_text(RULES + "- **CLM-1.2** Changed.\n")
    errors = pc.check_lock(lock, [rules_file])
    assert len(errors) == 1
    assert "changed since the lock" in errors[0]


def test_repository_files_pass_the_check() -> None:
    assert pc.run(pc.RULES, pc.CONSTANTS, pc.LOCK) == []
