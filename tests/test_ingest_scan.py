"""Secret and personal-data scan: finds structured values, never reports or keeps them."""

from pathlib import Path

import pytest

from services.ingest.limits import MIB, Limits
from services.ingest.scan import SCAN_MAX_BYTES, redact, scan_files, scan_text
from services.ingest.tree import scan_tree

ROOT = Path(__file__).resolve().parent.parent
# Built at runtime so this file itself carries nothing a scanner would match.
AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
GITHUB = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
SLACK = "xoxb-" + "123456789012-abcdefghij"
JWT = ".".join(
    ["eyJhbGciOiJIUzI1NiJ9", "eyJzdWIiOiIxMjM0NTY3ODkwIn0", "c2lnbmF0dXJlLXZhbHVlLWhlcmU"]
)
KEY_HEADER = "-----BEGIN " + "RSA PRIVATE KEY-----"
LIMITS = Limits(max_bytes=100 * MIB, max_files=100, max_depth=30)


def kinds(text: str) -> list[str]:
    return [f.kind for f in scan_text("f", text)]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (KEY_HEADER, "secret:private_key"),
        (f"id = {AWS}", "secret:aws_access_key"),
        (f"t = {GITHUB}", "secret:github_token"),
        (f"t = {SLACK}", "secret:slack_token"),
        (f"Authorization: {JWT}", "secret:jwt"),
        ("postgres://app:hunter2pass@db.internal/shop", "secret:url_credentials"),
        ("const password = 'correct-horse-battery'", "secret:credential"),
        ('{"apiKey": "abcd1234efgh5678"}', "secret:credential"),
        ("gatewayToken: 'fxlive_0f1e2d3c4b5a69788796',", "secret:credential"),
        ("contact: jane.example@example.com", "pii:email"),
        ("ssn 123-45-6789 on file", "pii:ssn"),
        ("call 555-123-4567 now", "pii:phone"),
        ("call +1 555 123 4567 now", "pii:phone"),
        ("card 4111 1111 1111 1111 expired", "pii:card"),
        ('"phone": "555-0100"', "pii:field"),
        ("address = '100 Placeholder Street, Sampletown'", "pii:field"),
    ],
)
def test_each_kind_is_found(text: str, kind: str) -> None:
    assert kinds(text) == [kind]


@pytest.mark.parametrize(
    "text",
    [
        "const token = require('x')",
        "password: process.env.DB_PASSWORD",
        "tokenLabel: 'Enter your token here'",
        "card 4111 1111 1111 1112 is not a valid number",
        "order 1234567890123456",
        "hash 6607060659998f00afdea0d1234567890abc",
        "version 1.2.3",
        "see 555-0100 for details",
    ],
)
def test_ordinary_text_is_not_flagged(text: str) -> None:
    assert kinds(text) == []


def test_unicode_digits_are_not_treated_as_digits() -> None:
    arabic = "".join(chr(0x0660 + int(d)) for d in "123456789")
    assert kinds(f"ssn {arabic[:3]}-{arabic[3:5]}-{arabic[5:]}") == []
    assert kinds("card " + "".join(chr(0x0660 + int(d)) for d in "4111111111111111")) == []


def test_finding_never_holds_the_value() -> None:
    secret = "correct-horse-battery"
    findings = scan_text("f.js", f"const password = '{secret}'")
    assert findings and secret not in repr(findings)


def test_line_numbers_count_after_crlf_normalisation() -> None:
    text = "a\r\nb\r\npassword = 'correct-horse-battery'\r\n"
    assert [f.line for f in scan_text("f", text)] == [3]


def test_redact_removes_values_and_keeps_the_rest() -> None:
    text = f"user = 'jane.example@example.com'\nid = {AWS}\nplain line\n"
    out = redact(text)
    assert "jane.example@example.com" not in out
    assert AWS not in out
    assert "plain line" in out
    assert "[REDACTED:pii:email]" in out
    assert "[REDACTED:secret:aws_access_key]" in out


def test_redact_masks_only_the_value_of_a_credential() -> None:
    out = redact("password = 'correct-horse-battery'")
    assert out == "password = '[REDACTED:secret:credential]'"


def test_redact_is_idempotent() -> None:
    once = redact(f"x = {GITHUB}\nmail a@example.com")
    assert redact(once) == once


def test_overlapping_matches_are_masked_once() -> None:
    out = redact("token = 'user@example.com-with-more'")
    assert out.count("[REDACTED") == 1
    assert "example.com" not in out


def test_fixture_secret_and_personal_data_are_found() -> None:
    root = ROOT / "fixtures/legacy-app"
    report = scan_files(root, scan_tree(root, LIMITS).files)
    by_file = {(f.path, f.kind) for f in report.findings}
    assert ("lib/credentials.js", "secret:credential") in by_file
    assert ("data/sample_customers.json", "pii:email") in by_file
    assert ("data/sample_customers.json", "pii:field") in by_file
    assert report.unscanned == ()
    assert "fxlive_0f1e2d3c4b5a69788796" not in repr(report)


def test_fixture_code_has_no_other_secret_findings() -> None:
    root = ROOT / "fixtures/legacy-app"
    report = scan_files(root, scan_tree(root, LIMITS).files)
    assert {f.path for f in report.findings if f.kind.startswith("secret:")} == {
        "lib/credentials.js"
    }


def test_undecodable_file_is_scanned_without_line_numbers(tmp_path: Path) -> None:
    (tmp_path / "latin.txt").write_bytes(b"caf\xe9 password = 'correct-horse-battery'\n")
    report = scan_files(tmp_path, scan_tree(tmp_path, LIMITS).files)
    assert [(f.kind, f.line) for f in report.findings] == [("secret:credential", None)]


def test_binary_file_is_listed_as_unscanned(tmp_path: Path) -> None:
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\0\0" + b"password = 'correct-horse-battery'")
    report = scan_files(tmp_path, scan_tree(tmp_path, LIMITS).files)
    assert report.findings == ()
    assert report.unscanned == (("logo.png", "binary"),)


def test_oversized_file_is_listed_as_unscanned(tmp_path: Path) -> None:
    (tmp_path / "big.log").write_bytes(b"a" * (SCAN_MAX_BYTES + 1))
    report = scan_files(tmp_path, scan_tree(tmp_path, LIMITS).files)
    assert report.unscanned == (("big.log", "too_large_to_scan"),)


def test_scan_never_reads_a_replaced_special_file(tmp_path: Path) -> None:
    import os

    (tmp_path / "f").write_bytes(b"x")
    entries = scan_tree(tmp_path, LIMITS).files
    (tmp_path / "f").unlink()
    os.mkfifo(tmp_path / "f")
    from services.ingest.errors import IngestError

    with pytest.raises(IngestError) as caught:
        scan_files(tmp_path, entries)
    assert caught.value.code == "special_file"
