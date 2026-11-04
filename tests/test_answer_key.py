"""The fixture's answer key must stay in step with the fixture app."""

import subprocess
import sys
from pathlib import Path

KEY_CHECK = Path(__file__).resolve().parents[1] / "fixtures" / "answer-key" / "check_key.py"


def test_answer_key_resolves_against_the_fixture() -> None:
    result = subprocess.run(
        [sys.executable, str(KEY_CHECK)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "33 traps" in result.stdout
