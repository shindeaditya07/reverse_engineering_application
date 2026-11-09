"""Data agent (FR-4): schema, ER data, SQL statements and lineage; what each yields, what it
must not, and the fixture score."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from services.data import __main__ as cli
from services.data import analyze
from services.data.__main__ import analyzer_sha256
from services.data.run import KINDS, run_on_fixture
from services.data.sql import SqlUnreadable, analyze_sql
from services.discovery.agent import Finding, to_claim_inputs
from services.evals.results import RESULTS_DIR
from services.evidence import SnapshotReader
from services.ingest.limits import MIB, Limits
from services.ingest.pin import pin_local
from services.verifier import verify_claim

LIMITS = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
SCHEMA = (
    "CREATE TABLE customers (\n  id INT PRIMARY KEY AUTO_INCREMENT,\n  name VARCHAR(80) NOT NULL,\n"
    "  tier VARCHAR(10) NOT NULL DEFAULT 'none',\n  fax VARCHAR(20)\n);\n\n"
    "CREATE TABLE orders (\n  id INT PRIMARY KEY,\n  customer_id INT NOT NULL,\n"
    "  status VARCHAR(12) NOT NULL DEFAULT 'open'\n);\n"
)
DB = "const mysql = require('mysql');\nconst pool = mysql.createPool({});\nfunction query(sql, p, cb) { pool.query(sql, p, cb); }\nfunction queryAsync(sql, p) { return pool.query(sql, p); }\nmodule.exports = { query, queryAsync };\n"


def run(tmp_path: Path, files: Mapping[str, bytes | str]):  # type: ignore[no-untyped-def]
    source = tmp_path / "source"
    for rel, data in files.items():
        (source / rel).parent.mkdir(parents=True, exist_ok=True)
        (source / rel).write_bytes(data if isinstance(data, bytes) else data.encode())
    pin = pin_local(source, tmp_path / "store", LIMITS)
    reader = SnapshotReader.from_pinned(pin)
    return analyze(reader, [f.path for f in pin.tree.files]), reader


def app(tmp_path: Path, code: str, schema: str = SCHEMA, **extra: str) -> list[Finding]:
    files = {
        "db/schema.sql": schema,
        "lib/db.js": DB,
        "app.js": "const db = require('./lib/db');\n" + code,
    }
    result, _ = run(tmp_path, {**files, **extra})
    return list(result.findings)


def by_kind(findings: list[Finding], kind: str) -> list[Finding]:
    return [f for f in findings if f.kind == kind]


# ---- schema ----------------------------------------------------------------------------


def test_tables_columns_keys_defaults_and_lines(tmp_path: Path) -> None:
    result, _ = run(tmp_path, {"s.sql": SCHEMA})
    customers, orders = result.er.tables
    assert (customers.name, customers.start, customers.end) == ("customers", 1, 6)
    assert (orders.start, orders.end) == (8, 12)
    id_, name, tier, fax = customers.columns
    assert id_.primary_key and id_.auto_increment and not id_.nullable and id_.line == 2
    assert not name.nullable and name.type == "VARCHAR(80)"
    assert tier.default == "'none'" and tier.line == 4
    assert fax.nullable and fax.default is None


def test_the_table_claim_is_confirmed_and_cites_the_create_statement(tmp_path: Path) -> None:
    claim = by_kind(app(tmp_path, ""), "table")[0]
    assert claim.status == "confirmed" and claim.evidence == (("db/schema.sql", 1, 6),)
    assert "id, name, tier, fax" in claim.text and "primary key id" in claim.text


def test_a_table_without_a_primary_key_says_so(tmp_path: Path) -> None:
    (claim,) = by_kind(app(tmp_path, "", "CREATE TABLE t (a INT);\n"), "table")
    assert "no primary key" in claim.text


def test_a_name_that_implies_a_reference_is_inferred_not_declared(tmp_path: Path) -> None:
    (relation,) = by_kind(app(tmp_path, ""), "relation")
    assert relation.status == "inferred" and "no foreign key is declared" in relation.text
    assert relation.evidence == (("db/schema.sql", 10, 10),)


def test_declared_foreign_keys_are_confirmed_inline_and_at_table_level(tmp_path: Path) -> None:
    schema = (
        "CREATE TABLE a (id INT PRIMARY KEY);\n"
        "CREATE TABLE b (id INT PRIMARY KEY, a_id INT REFERENCES a (id));\n"
        "CREATE TABLE c (id INT PRIMARY KEY, a_id INT, FOREIGN KEY (a_id) REFERENCES a (id));\n"
    )
    result, _ = run(tmp_path, {"s.sql": schema})
    assert [(r.table, r.ref_table, r.declared) for r in result.er.relations] == [
        ("b", "a", True),
        ("c", "a", True),
    ]  # a declared key is not also reported as inferred


@pytest.mark.parametrize(
    "schema",
    [
        "CREATE TABLE a (id INT PRIMARY KEY, z_id INT);\n",  # no table z
        "CREATE TABLE zs (code INT);\nCREATE TABLE a (id INT, zs_id INT);\n",  # target has no id
        "CREATE TABLE a (id INT PRIMARY KEY, a_id INT);\n",  # a table is not its own parent
    ],
)
def test_no_relation_is_inferred_without_a_target(tmp_path: Path, schema: str) -> None:
    result, _ = run(tmp_path, {"s.sql": schema})
    assert result.er.relations == ()


def test_a_singular_target_table_is_found_too(tmp_path: Path) -> None:
    schema = "CREATE TABLE customer (id INT);\nCREATE TABLE o (id INT, customer_id INT);\n"
    result, _ = run(tmp_path, {"s.sql": schema})
    assert [(r.table, r.ref_table) for r in result.er.relations] == [("o", "customer")]


def test_other_statements_in_a_schema_file_are_ignored(tmp_path: Path) -> None:
    schema = "INSERT INTO t VALUES (1);\nDROP TABLE x;\nCREATE VIEW v AS SELECT 1;\nCREATE TABLE t (a INT);\n"
    result, _ = run(tmp_path, {"s.sql": schema})
    assert [t.name for t in result.er.tables] == ["t"]


def test_a_schema_file_that_does_not_parse_is_listed_and_claimed_unknown(tmp_path: Path) -> None:
    result, _ = run(tmp_path, {"bad.sql": "CREATE TABLE ((((;\n"})
    assert result.unread == (("bad.sql", "SQL the parser could not read"),)
    (claim,) = [f for f in result.findings if f.claim_id == "data:unread:bad.sql"]
    assert claim.status == "unknown" and claim.evidence == ()


def test_the_er_model_is_plain_json_data(tmp_path: Path) -> None:
    result, _ = run(tmp_path, {"s.sql": SCHEMA})
    data = result.er.as_dict()
    assert json.loads(json.dumps(data)) == data
    assert data["tables"][0]["columns"][0] == {
        "name": "id", "type": "INT", "nullable": False, "primary_key": True,
        "unique": False, "default": None, "line": 2,
    }  # fmt: skip
    assert data["relations"] == [
        {"from": "orders", "columns": ["customer_id"], "to": "customers",
         "to_columns": ["id"], "declared": False, "line": 10}
    ]  # fmt: skip


def test_generated_schema_files_are_not_read(tmp_path: Path) -> None:
    result, _ = run(
        tmp_path, {"generated/g.sql": "-- AUTO-GENERATED. DO NOT EDIT.\nCREATE TABLE g (a INT);\n"}
    )
    assert result.er.tables == ()


# ---- one statement ---------------------------------------------------------------------


def test_select_reads_its_columns_and_attributes_a_join_by_alias() -> None:
    s = analyze_sql(
        "SELECT o.id, c.email FROM orders o JOIN customers c ON c.id = o.customer_id WHERE total > 1"
    )
    assert s.verb == "select" and s.tables == ("customers", "orders")
    assert ("customers", "email") in s.reads and ("orders", "customer_id") in s.reads
    assert s.ambiguous == ("total",)  # unqualified in a join: not guessed


def test_stars_read_every_column_but_count_star_reads_none() -> None:
    assert analyze_sql("SELECT * FROM t").reads == (("t", "*"),)
    assert analyze_sql("SELECT t.* FROM t JOIN u ON 1 = 1").reads == (("t", "*"),)
    assert analyze_sql("SELECT COUNT(*) FROM t").reads == ()


def test_update_writes_its_set_targets_and_reads_the_rest() -> None:
    s = analyze_sql("UPDATE t SET a = a + ?, b = NOW() WHERE id = ?")
    assert s.writes == (("t", "a"), ("t", "b")) and s.reads == (("t", "a"), ("t", "id"))


def test_insert_writes_its_column_list_or_whole_rows() -> None:
    assert analyze_sql("INSERT INTO t (a, b) VALUES (?, ?)").writes == (("t", "a"), ("t", "b"))
    assert analyze_sql("INSERT INTO t VALUES (1)").writes == (("t", "*"),)
    s = analyze_sql("INSERT INTO a SELECT x FROM b")
    assert s.writes == (("a", "*"),) and s.reads == (("b", "x"),) and s.tables == ("a", "b")


def test_delete_writes_a_whole_row() -> None:
    s = analyze_sql("DELETE FROM t WHERE id = ?")
    assert s.verb == "delete" and s.writes == (("t", "*"),) and s.reads == (("t", "id"),)


def test_a_dynamic_token_in_a_value_is_ignored_and_in_the_table_is_flagged() -> None:
    assert not analyze_sql("SELECT a FROM t WHERE b = '__dyn1__'").dynamic_table
    assert analyze_sql("SELECT * FROM __dyn1__").dynamic_table
    assert analyze_sql("SELECT * FROM t WHERE __dyn1__").reads == (("t", "*"),)


@pytest.mark.parametrize("text", ["CREATE TABLE t (a INT)", "SELECT FROM WHERE (", ""])
def test_statements_it_cannot_read_raise(text: str) -> None:
    with pytest.raises(SqlUnreadable):
        analyze_sql(text)


# ---- statements in code ----------------------------------------------------------------


def test_a_literal_statement_is_confirmed_and_cites_its_line(tmp_path: Path) -> None:
    (read,) = by_kind(
        app(tmp_path, "db.query('SELECT id FROM orders WHERE id = ?', [1], cb);"), "sql_read"
    )
    assert read.status == "confirmed" and read.evidence == (("app.js", 2, 2),)
    assert "app.js line 2 reads orders.id from orders" in read.text


def test_template_and_constant_statements_resolve(tmp_path: Path) -> None:
    code = "const q = 'SELECT id FROM orders';\ndb.query(q, [], cb);\ndb.query(`SELECT name FROM ${'customers'}`, [], cb);\n"
    reads = by_kind(app(tmp_path, code), "sql_read")
    assert [r.text.split(" reads ")[1].split(" from")[0] for r in reads] == [
        "orders.id",
        "customers.name",
    ]
    assert reads[0].evidence == (("app.js", 3, 3), ("app.js", 2, 2))  # the call, then the constant


def test_a_value_concatenated_into_the_text_is_said_not_hidden(tmp_path: Path) -> None:
    (read,) = by_kind(
        app(
            tmp_path, 'db.query("SELECT id FROM orders WHERE status = \'" + req.q + "\'", [], cb);'
        ),
        "sql_read",
    )
    assert read.status == "confirmed" and "computed at run time and concatenated in" in read.text


def test_a_table_name_passed_in_is_followed_one_step_and_marked_inferred(tmp_path: Path) -> None:
    files = {
        "lib/orm.js": "const db = require('./db');\nfunction table(name) {\n  return { all() { return db.queryAsync('SELECT * FROM ' + name, []); } };\n}\nmodule.exports = { table };\n",
        "models/m.js": "const orm = require('../lib/orm');\nconst m = orm.table('orders');\n",
    }
    reads = by_kind(app(tmp_path, "", **files), "sql_read")
    (read,) = [r for r in reads if r.claim_id.startswith("data:sql:lib/orm.js")]
    assert read.status == "inferred" and "passed in from models/m.js line 2" in read.text
    assert ("models/m.js", 2, 2) in read.evidence


def test_two_call_sites_with_different_tables_give_two_claims(tmp_path: Path) -> None:
    files = {
        "lib/orm.js": "const db = require('./db');\nfunction table(name) { return db.queryAsync('SELECT * FROM ' + name, []); }\nmodule.exports = { table };\n",
        "models/m.js": "const orm = require('../lib/orm');\norm.table('orders');\norm.table('customers');\n",
    }
    ids = [
        f.claim_id
        for f in app(tmp_path, "", **files)
        if f.claim_id.startswith("data:sql:lib/orm.js")
    ]
    assert ids == ["data:sql:lib/orm.js:2", "data:sql:lib/orm.js:2:1"]


@pytest.mark.parametrize(
    "caller",
    ["orm.table(name);\n", "orm.table();\n", ""],  # computed argument, missing argument, no caller
)
def test_a_table_that_cannot_be_followed_is_unknown(tmp_path: Path, caller: str) -> None:
    files = {
        "lib/orm.js": "const db = require('./db');\nfunction table(name) { return db.queryAsync('SELECT * FROM ' + name, []); }\nmodule.exports = { table };\n",
        "models/m.js": "const orm = require('../lib/orm');\n" + caller,
    }
    unknown = [f for f in app(tmp_path, "", **files) if f.kind == "unresolved"]
    assert [f.status for f in unknown] == ["unknown"] and "table name is computed" in unknown[
        0
    ].text


def test_a_wrapper_call_with_fully_computed_sql_is_unknown(tmp_path: Path) -> None:
    (unknown,) = by_kind(app(tmp_path, "db.query(build(), [], cb);"), "unresolved")
    assert unknown.status == "unknown" and "computed at run time" in unknown.text


def test_sql_the_analyzer_cannot_read_is_unknown_not_skipped(tmp_path: Path) -> None:
    findings = app(
        tmp_path,
        "db.query('SELECT FROM WHERE (', [], cb);\ndb.query('CREATE TABLE x (a INT)', [], cb);",
    )
    unknown = by_kind(findings, "unresolved")
    assert len(unknown) == 2 and all("cannot read" in f.text for f in unknown)


def test_calls_that_are_not_sql_are_ignored(tmp_path: Path) -> None:
    code = "const cache = require('./lib/cache');\ncache.query('hello');\nclient.query('hello');\nother.run('SELECT 1');\n"
    assert (
        by_kind(app(tmp_path, code, **{"lib/cache.js": "module.exports = {};\n"}), "unresolved")
        == []
    )


def test_a_driver_call_whose_sql_is_a_parameter_is_listed_not_claimed(tmp_path: Path) -> None:
    result, _ = run(tmp_path, {"lib/db.js": DB})
    assert result.plumbing == (("lib/db.js", 3, 3), ("lib/db.js", 4, 4)) and result.sites == ()
    assert not [f for f in result.findings if f.kind == "unresolved"]


def test_a_direct_driver_call_with_literal_sql_is_a_statement(tmp_path: Path) -> None:
    code = (
        "const pool = require('mysql').createPool({});\npool.query('SELECT id FROM orders', cb);\n"
    )
    result, _ = run(tmp_path, {"db/schema.sql": SCHEMA, "x.js": code})
    assert [s.statement.verb for s in result.sites] == ["select"]


def test_generated_and_vendored_code_is_not_scanned(tmp_path: Path) -> None:
    code = "const db = require('../lib/db');\ndb.query('SELECT id FROM orders', [], cb);\n"
    findings = app(tmp_path, "", **{"vendor/v.js": "/*! v1 | vendored copy */\n" + code})
    assert by_kind(findings, "sql_read") == []


# ---- lineage ---------------------------------------------------------------------------


def test_a_column_written_twice_is_one_lineage_claim_citing_both(tmp_path: Path) -> None:
    code = "db.query('UPDATE orders SET status = ?', [1], cb);\ndb.query('UPDATE orders SET status = ? WHERE id = 1', [1], cb);\n"
    (lineage,) = [
        f
        for f in by_kind(app(tmp_path, code), "sql_write")
        if f.claim_id.startswith("data:lineage")
    ]
    assert lineage.claim_id == "data:lineage:orders.status" and lineage.status == "inferred"
    assert lineage.evidence == (("app.js", 2, 2), ("app.js", 3, 3)) and "2 places" in lineage.text


def test_a_column_default_counts_when_an_insert_leaves_the_column_out(tmp_path: Path) -> None:
    code = "db.query('UPDATE orders SET status = ?', [1], cb);\ndb.query('INSERT INTO orders (customer_id) VALUES (?)', [1], cb);\n"
    (lineage,) = [f for f in app(tmp_path, code) if f.claim_id == "data:lineage:orders.status"]
    assert "3 places" not in lineage.text and "2 places" in lineage.text
    assert "column default 'open' at db/schema.sql line 11" in lineage.text
    assert ("db/schema.sql", 11, 11) in lineage.evidence


def test_a_single_writer_or_a_default_that_nothing_overrides_is_not_lineage(tmp_path: Path) -> None:
    code = "db.query('UPDATE orders SET status = ?', [1], cb);\ndb.query('INSERT INTO orders (status) VALUES (1)', [], cb);\n"
    ids = [f.claim_id for f in app(tmp_path, code) if f.claim_id.startswith("data:lineage")]
    assert ids == ["data:lineage:orders.status"]  # two statements; no default writer
    assert [
        f
        for f in app(tmp_path / "b", "db.query('UPDATE orders SET status = ?', [1], cb);")
        if f.claim_id.startswith("data:lineage")
    ] == []


def test_deletes_and_bare_inserts_are_not_column_writers(tmp_path: Path) -> None:
    code = "db.query('DELETE FROM orders WHERE id = 1', [], cb);\ndb.query('INSERT INTO orders VALUES (1)', [], cb);\n"
    assert [f for f in app(tmp_path, code) if f.claim_id.startswith("data:lineage")] == []


# ---- unused columns --------------------------------------------------------------------

USES = "db.query('SELECT id, name FROM customers', [], cb);\n"


def unused(findings: list[Finding]) -> list[str]:
    return sorted(f.claim_id.split(":")[2] for f in findings if f.kind == "column")


def test_a_column_no_statement_refers_to_is_inferred_unused(tmp_path: Path) -> None:
    findings = app(tmp_path, USES)
    assert unused(findings) == ["customers.fax", "customers.tier"]
    claim = next(f for f in findings if f.claim_id == "data:unused:customers.fax")
    assert claim.status == "inferred" and claim.evidence == (("db/schema.sql", 5, 5),)


def test_select_star_uses_every_column_of_its_table(tmp_path: Path) -> None:
    assert unused(app(tmp_path, "db.query('SELECT * FROM customers', [], cb);")) == []


def test_an_unqualified_column_in_a_join_counts_for_each_table_in_it(tmp_path: Path) -> None:
    code = "db.query('SELECT o.id FROM orders o JOIN customers c ON c.id = o.customer_id WHERE fax = 1', [], cb);\n"
    assert "customers.fax" not in unused(app(tmp_path, code))


def test_any_unresolved_statement_turns_the_unused_claims_off(tmp_path: Path) -> None:
    assert unused(app(tmp_path, USES + "db.query(build(), [], cb);\n")) == []


def test_a_table_no_statement_touches_gets_no_unused_claims(tmp_path: Path) -> None:
    assert not [c for c in unused(app(tmp_path, USES)) if c.startswith("orders")]


# ---- evidence --------------------------------------------------------------------------


def test_crlf_files_cite_normalised_lines_and_verify(tmp_path: Path) -> None:
    files = {
        "db/schema.sql": SCHEMA.replace("\n", "\r\n"),
        "lib/db.js": DB,
        "app.js": "const db = require('./lib/db');\r\ndb.query('SELECT id FROM orders', [], cb);\r\n",
    }
    result, reader = run(tmp_path, files)
    assert result.findings
    for finding in result.findings:
        assert verify_claim(to_claim_inputs(finding, reader), reader).passed, finding.claim_id
    assert ("app.js", 2, 2) in [f.evidence[0] for f in result.findings if f.kind == "sql_read"]


# ---- personal data ---------------------------------------------------------------------

PEOPLE = (
    '[\n  {\n    "name": "A Person",\n    "email": "a.person@example.com",\n'
    '    "phone": "555-0100",\n    "city": "Somewhere"\n  }\n]\n'
)


def pii(tmp_path: Path, files: Mapping[str, str]) -> list[Finding]:
    result, _ = run(tmp_path, files)
    return by_kind(list(result.findings), "pii")


def test_a_data_file_with_personal_data_gets_one_inferred_claim_without_the_values(
    tmp_path: Path,
) -> None:
    (claim,) = pii(tmp_path, {"data/people.json": PEOPLE})
    assert claim.claim_id == "data:pii:data/people.json" and claim.status == "inferred"
    assert "e-mail addresses on line 4" in claim.text and "on line 5" in claim.text
    for value in ("a.person", "example.com", "555-0100", "A Person", "Somewhere"):
        assert value not in claim.text  # SEC-1.5: never repeated


def test_the_claim_cites_a_line_that_matches_nothing(tmp_path: Path) -> None:
    result, reader = run(tmp_path, {"data/people.json": PEOPLE})
    (claim,) = by_kind(list(result.findings), "pii")
    assert claim.evidence == (("data/people.json", 3, 3),)
    assert verify_claim(to_claim_inputs(claim, reader), reader).passed


def test_a_file_where_every_line_matches_has_no_evidence_and_fails_closed(
    tmp_path: Path,
) -> None:
    result, reader = run(tmp_path, {"data/mail.txt": "a.b@example.com\nc.d@example.com\n"})
    (claim,) = by_kind(list(result.findings), "pii")
    assert claim.evidence == ()
    verdict = verify_claim(to_claim_inputs(claim, reader), reader)
    assert not verdict.passed and verdict.final_status == "unknown"


def test_many_lines_are_cut_and_counted(tmp_path: Path) -> None:
    rows = "".join(f"x,x{i}@example.com\n" for i in range(9))
    (claim,) = pii(tmp_path, {"data/many.csv": "id,email\n" + rows})
    assert "and 3 more" in claim.text


def test_code_files_and_clean_data_files_are_not_scanned(tmp_path: Path) -> None:
    found = pii(
        tmp_path,
        {
            "app.js": "const a = 'a.b@example.com';\n",
            "data/none.json": '{"count": 3}\n',
            "vendor/people.json": PEOPLE,
            "generated/people.json": PEOPLE,
        },
    )
    assert found == []


def test_a_data_file_that_is_not_utf8_is_skipped(tmp_path: Path) -> None:
    assert pii(tmp_path, {"data/latin.csv": b"caf\xe9,a.b@example.com\n"}) == []  # type: ignore[dict-item]


# ---- the fixture -----------------------------------------------------------------------


def test_every_finding_on_the_fixture_passes_the_verifier() -> None:
    result = run_on_fixture()
    assert result.analysis.findings and result.blocked == ()


def test_fixture_score() -> None:
    scores = run_on_fixture().scores
    assert scores.missed_facts == () and scores.overclaims == ()
    assert scores.recall.hits == scores.recall.total == 7
    # The key lists 6 of the fixture's data facts; the other statements and columns are real.
    assert (scores.precision.hits, scores.precision.total) == (7, 24)


def test_the_fixture_model_has_three_tables_and_one_inferred_relation() -> None:
    er = run_on_fixture().analysis.er
    assert [t.name for t in er.tables] == ["customers", "products", "orders"]
    assert [(r.table, r.ref_table, r.declared) for r in er.relations] == [
        ("orders", "customers", False)
    ]


def test_the_fixture_states_what_it_did_not_follow() -> None:
    result = run_on_fixture().analysis
    assert [p for p, _ in result.unread] == ["lib/legacy_labels.js"]
    assert [(f, a) for f, a, _ in result.plumbing] == [("lib/db.js", 9), ("lib/db.js", 14)]


def test_only_the_built_kinds_are_scored() -> None:
    assert {k.kind for k in run_on_fixture().scores.per_kind} <= KINDS


def test_committed_result_was_run_with_the_current_analyzer() -> None:
    """Change the analyzer and this fails until it is re-run and re-committed."""
    manifests = sorted(RESULTS_DIR.glob("*-data-v*/manifest.json"))
    assert manifests, "no committed Data agent result under evals/results/"
    assert json.loads(manifests[-1].read_text())["analyzer_sha256"] == analyzer_sha256()


def test_cli_prints_and_records(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--out", str(tmp_path), "--run-id", "t1"]) == 0
    out = capsys.readouterr().out
    assert "Recall on its kinds" in out and "lib/db.js" in out
    (folder,) = list(tmp_path.iterdir())
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["kind"] == "data" and manifest["model"] is None
    assert manifest["analyzer_sha256"] == analyzer_sha256() and manifest["blocked_by_verifier"] == 0


def test_cli_fails_when_the_verifier_blocks_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = run_on_fixture()
    blocked = type(real)(real.pinned_revision, real.analysis, real.scores, (("x", ("V-2",)),))
    monkeypatch.setattr(cli, "run_on_fixture", lambda: blocked)
    assert cli.main([]) == 1
