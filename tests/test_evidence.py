"""Evidence resolution: every kind resolves to bytes, and every failure says why."""

import hashlib
import uuid
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from services.evidence import (
    BuildStep,
    ConfigKey,
    FileRange,
    LogLine,
    SchemaObject,
    SnapshotReader,
    Ticket,
    check_hash,
    evidence_row_fields,
    parse_ref,
    resolve,
    split_range,
)
from services.evidence.refs import MAX_EXCERPT_BYTES
from services.ingest.limits import MIB, Limits
from services.ingest.pin import pin_local

ROOT = Path(__file__).resolve().parent.parent
LIMITS = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
SECRET = "AKIA" + "IOSFODNN7EXAMPLE"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_reader(tmp_path: Path, files: dict[str, bytes]) -> SnapshotReader:
    source = tmp_path / "source"
    for rel, data in files.items():
        path = source / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return SnapshotReader.from_pinned(pin_local(source, tmp_path / "store", LIMITS))


@pytest.fixture(scope="module")
def fixture_reader(tmp_path_factory: pytest.TempPathFactory) -> SnapshotReader:
    tmp = tmp_path_factory.mktemp("fixture")
    return SnapshotReader.from_pinned(pin_local(ROOT / "fixtures/legacy-app", tmp, LIMITS))


# ---- every kind resolves against the fixture app -------------------------------------------


def test_file_range_resolves_lines(fixture_reader: SnapshotReader) -> None:
    found = resolve(FileRange(path="lib/totals.js", start_line=3, end_line=5), fixture_reader)
    assert found.status == "resolved"
    assert found.excerpt.splitlines()[0] == "function sumLines(items) {"
    assert (found.start_line, found.end_line) == (3, 5)
    assert found.content_hash == sha(found.excerpt.encode())


def test_crlf_file_is_numbered_as_lf(fixture_reader: SnapshotReader) -> None:
    """EVD-1.5: totals.js is CRLF on disk; line 7 is still line 7 and holds no CR."""
    found = resolve(FileRange(path="lib/totals.js", start_line=7, end_line=7), fixture_reader)
    assert found.excerpt == "module.exports = { sumLines };"
    assert "\r" not in found.excerpt


def test_undecodable_file_is_cited_by_bytes(fixture_reader: SnapshotReader) -> None:
    ref = FileRange(path="lib/legacy_labels.js", start_byte=73, end_byte=74)
    found = resolve(ref, fixture_reader)
    assert found.status == "resolved"
    assert found.content_hash == sha(b"\xe9")
    assert (found.start_byte, found.end_byte) == (73, 74)


def test_undecodable_file_cannot_be_cited_by_line(fixture_reader: SnapshotReader) -> None:
    found = resolve(
        FileRange(path="lib/legacy_labels.js", start_line=1, end_line=1), fixture_reader
    )
    assert found.status == "unresolved"
    assert found.reason is not None and found.reason.startswith("undecodable")


def test_schema_table_column_and_index(fixture_reader: SnapshotReader) -> None:
    table = resolve(
        SchemaObject(path="db/schema.sql", object_name="table:customers"), fixture_reader
    )
    assert (table.start_line, table.end_line) == (1, 7)
    column = resolve(
        SchemaObject(path="db/schema.sql", object_name="column:orders.ship_by"), fixture_reader
    )
    assert column.excerpt == "  ship_by DATETIME,"
    assert column.start_line == column.end_line


def test_config_key(fixture_reader: SnapshotReader) -> None:
    found = resolve(ConfigKey(path="config.js", object_name="taxRate"), fixture_reader)
    assert found.excerpt.strip() == "taxRate: 0.0825,"


def test_nested_config_key_uses_last_segment(fixture_reader: SnapshotReader) -> None:
    found = resolve(
        ConfigKey(path="config.js", object_name="features.bulkDiscount"), fixture_reader
    )
    assert "FEATURE_BULK_DISCOUNT" in found.excerpt


def test_build_step_npm(fixture_reader: SnapshotReader) -> None:
    found = resolve(BuildStep(path="package.json", object_name="npm:test"), fixture_reader)
    assert found.excerpt.strip() == '"test": "node --test test/"'


def test_log_line(fixture_reader: SnapshotReader) -> None:
    found = resolve(LogLine(path="app.js", line=1), fixture_reader)
    assert found.status == "resolved" and found.start_line == found.end_line == 1


def test_ticket(tmp_path: Path) -> None:
    reader = make_reader(
        tmp_path, {"CHANGES.md": b"x\n- fix rounding (ORD-123)\n- ORD-1234 other\n"}
    )
    found = resolve(Ticket(path="CHANGES.md", object_name="ORD-123"), reader)
    assert found.start_line == 2  # ORD-1234 on line 3 is a different ticket


# ---- schema locator details ----------------------------------------------------------------

DDL = b"""-- CREATE TABLE ghost (id INT);
/* CREATE TABLE ghost2 (
   id INT) */
CREATE TABLE IF NOT EXISTS `Shop`.`Items` (
  id INT PRIMARY KEY,
  price DECIMAL(10, 2) NOT NULL, -- cents? no
  note VARCHAR(5) DEFAULT 'a,b)',
  CONSTRAINT fk_owner FOREIGN KEY (id) REFERENCES owners (id),
  KEY idx_price (price)
);
CREATE UNIQUE INDEX ux_note ON items (note);
ALTER TABLE items ADD CONSTRAINT chk_price CHECK (price > 0);
"""


@pytest.mark.parametrize(
    ("name", "lines"),
    [
        ("table:items", (4, 10)),
        ("table:ITEMS", (4, 10)),
        ("column:items.price", (6, 6)),
        ("column:items.note", (7, 7)),
        ("constraint:items.fk_owner", (8, 8)),
        ("constraint:items.chk_price", (12, 12)),
        ("index:idx_price", (9, 9)),
        ("index:ux_note", (11, 11)),
    ],
)
def test_ddl_locator(tmp_path: Path, name: str, lines: tuple[int, int]) -> None:
    reader = make_reader(tmp_path, {"s.sql": DDL})
    found = resolve(SchemaObject(path="s.sql", object_name=name), reader)
    assert found.status == "resolved", found.reason
    assert (found.start_line, found.end_line) == lines


@pytest.mark.parametrize(
    "name",
    [
        "table:ghost",
        "table:ghost2",
        "column:items.missing",
        "column:items.fk_owner",
        "column:nope.id",
        "index:nothing",
        "constraint:items.nothing",
    ],
)
def test_ddl_locator_does_not_invent_objects(tmp_path: Path, name: str) -> None:
    reader = make_reader(tmp_path, {"s.sql": DDL})
    found = resolve(SchemaObject(path="s.sql", object_name=name), reader)
    assert found.status == "unresolved" and (found.reason or "").startswith("not_found")


@pytest.mark.parametrize("name", ["items", "table:", "column:items", "view:items", ":x"])
def test_bad_schema_names(tmp_path: Path, name: str) -> None:
    reader = make_reader(tmp_path, {"s.sql": DDL})
    found = resolve(SchemaObject(path="s.sql", object_name=name), reader)
    assert (found.reason or "").startswith("bad_object_name")


def test_duplicate_table_is_ambiguous(tmp_path: Path) -> None:
    reader = make_reader(tmp_path, {"s.sql": b"CREATE TABLE t (a INT);\nCREATE TABLE t (b INT);\n"})
    found = resolve(SchemaObject(path="s.sql", object_name="table:t"), reader)
    assert (found.reason or "").startswith("ambiguous")


def test_long_table_is_too_long_but_its_columns_are_citable(tmp_path: Path) -> None:
    body = ",\n".join(f"  c{i} INT" for i in range(60))
    reader = make_reader(tmp_path, {"s.sql": f"CREATE TABLE wide (\n{body}\n);\n".encode()})
    table = resolve(SchemaObject(path="s.sql", object_name="table:wide"), reader)
    assert (table.reason or "").startswith("span_too_long")
    assert (
        resolve(SchemaObject(path="s.sql", object_name="column:wide.c59"), reader).status
        == "resolved"
    )


# ---- ambiguity and hints for line-matched kinds --------------------------------------------


def test_repeated_key_needs_a_line_hint(tmp_path: Path) -> None:
    reader = make_reader(tmp_path, {"c.js": b"a = { port: 1 };\nb = { port: 2 };\n"})
    ambiguous = resolve(ConfigKey(path="c.js", object_name="port"), reader)
    assert (ambiguous.reason or "").startswith("ambiguous")
    hinted = resolve(ConfigKey(path="c.js", object_name="port", line=2), reader)
    assert hinted.status == "resolved" and hinted.start_line == 2
    wrong = resolve(ConfigKey(path="c.js", object_name="port", line=1 + 2), reader)
    assert wrong.status == "unresolved"


@pytest.mark.parametrize(
    ("name", "content", "line"),
    [
        ("make:build", b"CC=gcc\nbuild: main.o\n\tgcc\n", 2),
        ("docker:FROM", b"# base\nFROM node:20\nRUN npm ci\n", 2),
        ("docker:run", b"FROM node:20\nrun npm ci\n", 2),
        ("step:npm ci", b"steps:\n  - run: npm ci\n", 2),
    ],
)
def test_build_step_kinds(tmp_path: Path, name: str, content: bytes, line: int) -> None:
    reader = make_reader(tmp_path, {"f": content})
    found = resolve(BuildStep(path="f", object_name=name), reader)
    assert found.status == "resolved" and found.start_line == line


@pytest.mark.parametrize("name", ["npm:", "weird:x", "plain"])
def test_bad_build_step_names(tmp_path: Path, name: str) -> None:
    reader = make_reader(tmp_path, {"f": b"x\n"})
    assert (resolve(BuildStep(path="f", object_name=name), reader).reason or "").startswith(
        "bad_object_name"
    )


def test_make_variable_assignment_is_not_a_target(tmp_path: Path) -> None:
    reader = make_reader(tmp_path, {"Makefile": b"build := x\n"})
    assert (
        resolve(BuildStep(path="Makefile", object_name="make:build"), reader).status == "unresolved"
    )


# ---- limits, ranges, encodings -------------------------------------------------------------


def test_forty_lines_ok_forty_one_rejected() -> None:
    FileRange(path="a", start_line=1, end_line=40)
    with pytest.raises(ValidationError):
        FileRange(path="a", start_line=1, end_line=41)


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"start_line": 1},
        {"start_line": 0, "end_line": 1},
        {"start_line": 3, "end_line": 2},
        {"start_line": 1, "end_line": 2, "start_byte": 0, "end_byte": 1},
        {"start_byte": 4, "end_byte": 4},
        {"start_byte": -1, "end_byte": 4},
        {"start_byte": 0, "end_byte": MAX_EXCERPT_BYTES + 1},
        {"start_byte": 1},
    ],
)
def test_invalid_file_ranges(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        FileRange(path="a", **kwargs)


def test_split_range_cuts_at_the_limit() -> None:
    parts = split_range("a.js", 5, 100)
    assert [(p.start_line, p.end_line) for p in parts] == [(5, 44), (45, 84), (85, 100)]
    assert split_range("a.js", 3, 3) == [FileRange(path="a.js", start_line=3, end_line=3)]
    with pytest.raises(ValueError):
        split_range("a.js", 0, 3)
    with pytest.raises(ValueError):
        split_range("a.js", 4, 3)


def test_range_past_end_of_file_is_unresolved(tmp_path: Path) -> None:
    reader = make_reader(tmp_path, {"a.txt": b"one\ntwo\n"})
    assert resolve(FileRange(path="a.txt", start_line=2, end_line=2), reader).status == "resolved"
    past = resolve(FileRange(path="a.txt", start_line=2, end_line=3), reader)
    assert (past.reason or "").startswith("out_of_range")
    bytes_past = resolve(FileRange(path="a.txt", start_byte=0, end_byte=99), reader)
    assert (bytes_past.reason or "").startswith("out_of_range")


def test_trailing_newline_does_not_add_a_line(tmp_path: Path) -> None:
    reader = make_reader(tmp_path, {"a.txt": b"one\ntwo", "b.txt": b"one\ntwo\n", "c.txt": b""})
    for name in ("a.txt", "b.txt"):
        assert len(reader.lines(name)) == 2
    assert resolve(LogLine(path="c.txt", line=1), reader).status == "unresolved"


def test_unicode_line_separators_do_not_split_lines(tmp_path: Path) -> None:
    """EVD-1.5 counts LF only; U+2028, form feed and VT are ordinary characters."""
    data = "a b\x0c\x0bc\nsecond\n".encode()
    reader = make_reader(tmp_path, {"u.txt": data})
    assert reader.lines("u.txt") == ["a b\x0c\x0bc", "second"]


def test_bom_is_not_part_of_line_one(tmp_path: Path) -> None:
    reader = make_reader(tmp_path, {"b.txt": b"\xef\xbb\xbfhello\n"})
    assert resolve(LogLine(path="b.txt", line=1), reader).excerpt == "hello"


def test_lone_cr_counts_as_a_line_end(tmp_path: Path) -> None:
    reader = make_reader(tmp_path, {"m.txt": b"one\rtwo\r\nthree\n"})
    assert reader.lines("m.txt") == ["one", "two", "three"]


def test_byte_range_is_exact_not_normalised(tmp_path: Path) -> None:
    reader = make_reader(tmp_path, {"c.txt": b"ab\r\ncd\n"})
    found = resolve(FileRange(path="c.txt", start_byte=1, end_byte=4), reader)
    assert found.content_hash == sha(b"b\r\n")


# ---- reading is confined to the snapshot ---------------------------------------------------


@pytest.mark.parametrize(
    "path", ["../x", "/etc/passwd", "lib/../a.txt", "missing.txt", "a.txt/", "./a.txt", ""]
)
def test_paths_outside_the_file_list_never_resolve(tmp_path: Path, path: str) -> None:
    reader = make_reader(tmp_path, {"a.txt": b"hi\n"})
    if path == "":
        with pytest.raises(ValidationError):
            LogLine(path=path, line=1)
        return
    assert resolve(LogLine(path=path, line=1), reader).status == "unresolved"


def test_symlink_in_source_is_not_readable(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_bytes(b"hi\n")
    (source / "link").symlink_to("a.txt")
    reader = SnapshotReader.from_pinned(pin_local(source, tmp_path / "store", LIMITS))
    found = resolve(LogLine(path="link", line=1), reader)
    assert (found.reason or "").startswith("not_in_snapshot")


def test_edited_snapshot_resolves_nothing(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_bytes(b"hi\n")
    pinned = pin_local(source, tmp_path / "store", LIMITS)
    target = pinned.root / "a.txt"
    target.chmod(0o644)
    target.write_bytes(b"HI\n")
    found = resolve(LogLine(path="a.txt", line=1), SnapshotReader.from_pinned(pinned))
    assert (found.reason or "").startswith("snapshot_modified")


def test_deleted_snapshot_file_is_unresolved(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_bytes(b"hi\n")
    pinned = pin_local(source, tmp_path / "store", LIMITS)
    pinned.root.chmod(0o755)  # the pinned copy is read-only; a hostile edit would lift that
    (pinned.root / "a.txt").unlink()
    found = resolve(LogLine(path="a.txt", line=1), SnapshotReader.from_pinned(pinned))
    assert (found.reason or "").startswith("unreadable")


# ---- staleness and redaction ---------------------------------------------------------------


def test_same_bytes_are_fresh_and_changed_bytes_are_stale(tmp_path: Path) -> None:
    ref = FileRange(path="a.js", start_line=1, end_line=1)
    old = resolve(ref, make_reader(tmp_path / "one", {"a.js": b"rate = 1;\n"}))
    assert old.content_hash is not None
    same = check_hash(
        ref, old.content_hash, make_reader(tmp_path / "two", {"a.js": b"rate = 1;\n"})
    )
    assert same.status == "resolved"
    new = check_hash(
        ref, old.content_hash, make_reader(tmp_path / "three", {"a.js": b"rate = 2;\n"})
    )
    assert new.status == "stale" and new.reason == "content_changed"
    assert new.excerpt == "rate = 2;"


def test_moved_code_is_stale_not_fresh(tmp_path: Path) -> None:
    ref = FileRange(path="a.js", start_line=1, end_line=1)
    old = resolve(ref, make_reader(tmp_path / "one", {"a.js": b"rate = 1;\n"}))
    assert old.content_hash is not None
    moved = make_reader(tmp_path / "two", {"a.js": b"// new header\nrate = 1;\n"})
    assert check_hash(ref, old.content_hash, moved).status == "stale"


def test_unresolved_stays_unresolved_in_check(tmp_path: Path) -> None:
    reader = make_reader(tmp_path, {"a.js": b"x\n"})
    result = check_hash(LogLine(path="gone.js", line=1), "0" * 64, reader)
    assert result.status == "unresolved"


def test_excerpt_is_redacted_but_hash_covers_the_real_bytes(tmp_path: Path) -> None:
    ref = FileRange(path="a.js", start_line=1, end_line=1)
    one = resolve(ref, make_reader(tmp_path / "one", {"a.js": f'const k = "{SECRET}";\n'.encode()}))
    other = SECRET[:-1] + "Z"
    two = resolve(ref, make_reader(tmp_path / "two", {"a.js": f'const k = "{other}";\n'.encode()}))
    assert SECRET not in one.excerpt and "[REDACTED" in one.excerpt
    assert one.excerpt == two.excerpt
    assert one.content_hash != two.content_hash
    assert one.content_hash == sha(f'const k = "{SECRET}";'.encode())


def test_byte_range_excerpt_is_redacted_and_printable(tmp_path: Path) -> None:
    data = b"\xe9 key=" + SECRET.encode() + b"\n"
    reader = make_reader(tmp_path, {"a.bin": data})
    found = resolve(FileRange(path="a.bin", start_byte=0, end_byte=len(data)), reader)
    assert SECRET not in found.excerpt
    assert "\\xe9" in found.excerpt


# ---- references, rows ----------------------------------------------------------------------


def test_parse_ref_picks_the_type_by_kind() -> None:
    assert parse_ref({"kind": "ticket", "path": "a", "object_name": "X-1"}) == Ticket(
        path="a", object_name="X-1"
    )
    with pytest.raises(ValidationError):
        parse_ref({"kind": "screenshot", "path": "a"})
    with pytest.raises(ValidationError):
        parse_ref({"kind": "log_line", "path": "a", "line": 1, "extra": 1})


def test_row_fields_refuse_unresolved_and_stale(tmp_path: Path) -> None:
    reader = make_reader(tmp_path, {"a.js": b"x\n"})
    ref = LogLine(path="nope.js", line=1)
    with pytest.raises(ValueError):
        evidence_row_fields(ref, resolve(ref, reader), uuid.uuid4(), uuid.uuid4())
    ok = LogLine(path="a.js", line=1)
    stale = check_hash(ok, "0" * 64, reader)
    with pytest.raises(ValueError):
        evidence_row_fields(ok, stale, uuid.uuid4(), uuid.uuid4())
