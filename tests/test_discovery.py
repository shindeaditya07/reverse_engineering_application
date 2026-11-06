"""Discovery (FR-2): what each pattern matches and does not, fail-safe handling, the fixture score."""

import json
from pathlib import Path

import pytest

from services.discovery import __main__ as cli
from services.discovery import discover, to_claim_inputs
from services.discovery.agent import PATTERNS, _package_name, patterns_sha256
from services.discovery.run import KINDS, run_on_fixture
from services.evals.results import RESULTS_DIR
from services.evidence import SnapshotReader
from services.ingest.limits import MIB, Limits
from services.ingest.pin import PinnedSource, pin_local
from services.verifier import verify_claim

LIMITS = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
PACKAGE = b'{\n  "name": "x",\n  "main": "app.js",\n  "dependencies": {\n    "express": "^4"\n  },\n  "devDependencies": {"jest": "1"}\n}\n'


def pinned(tmp_path: Path, files: dict[str, bytes]) -> PinnedSource:
    source = tmp_path / "source"
    for rel, data in files.items():
        (source / rel).parent.mkdir(parents=True, exist_ok=True)
        (source / rel).write_bytes(data)
    return pin_local(source, tmp_path / "store", LIMITS)


def run(tmp_path: Path, files: dict[str, bytes]):  # type: ignore[no-untyped-def]
    pin = pinned(tmp_path, files)
    reader = SnapshotReader.from_pinned(pin)
    return discover(reader, [f.path for f in pin.tree.files]), reader


def kinds(tmp_path: Path, code: str, extra: dict[str, bytes] | None = None) -> list[str]:
    files = {"package.json": PACKAGE, "a.js": code.encode(), **(extra or {})}
    found, _ = run(tmp_path, files)
    return sorted(f.claim_id.split(":")[1] for f in found.findings)


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("express", "express"),
        ("lodash/fp", "lodash"),
        ("@scope/pkg/deep", "@scope/pkg"),
        ("./local", None),
        ("../up", None),
        ("/abs", None),
        ("node:fs", None),
        ("fs", None),
        ("https", None),
    ],
)
def test_package_names(spec: str, expected: str | None) -> None:
    assert _package_name(spec) == expected


def test_an_undeclared_package_is_found_and_a_declared_one_is_not(tmp_path: Path) -> None:
    assert kinds(tmp_path, "const _ = require('lodash');") == ["undeclared"]
    assert kinds(tmp_path / "b", "const e = require('express');") == []
    assert kinds(tmp_path / "c", "const j = require('jest');") == []  # a dev dependency counts
    assert kinds(tmp_path / "d", "const f = require('fs'); require('./x');") == []


def test_the_undeclared_claim_cites_the_require_and_the_dependencies_block(tmp_path: Path) -> None:
    found, _ = run(tmp_path, {"package.json": PACKAGE, "a.js": b"x\nrequire('lodash');\n"})
    (finding,) = found.findings
    assert finding.evidence == (("a.js", 2, 2), ("package.json", 4, 6))
    assert "lodash" in finding.text and finding.status == "inferred"


def test_without_a_package_json_nothing_is_called_undeclared(tmp_path: Path) -> None:
    found, _ = run(tmp_path, {"a.js": b"require('lodash');\n"})
    assert found.findings == () and found.inventory.main is None


def test_a_package_json_without_a_dependencies_object_gives_no_undeclared_claim(
    tmp_path: Path,
) -> None:
    found, _ = run(tmp_path, {"package.json": b'{"name": "x"}\n', "a.js": b"require('lodash');\n"})
    assert found.findings == ()


def test_an_unreadable_package_json_is_noted_not_fatal(tmp_path: Path) -> None:
    found, _ = run(tmp_path, {"package.json": b"{not json", "a.js": b"require('x');\n"})
    assert found.inventory.notes == ("package.json not read: JSONDecodeError",)
    assert found.inventory.declared == {}


def test_a_non_object_package_json_gives_an_empty_inventory(tmp_path: Path) -> None:
    found, _ = run(tmp_path, {"package.json": b"[1, 2]\n"})
    assert found.inventory.declared == {} and found.inventory.scripts == {}


@pytest.mark.parametrize(
    "line",
    [
        "const m = require('./x/' + name);",
        "const m = require(name);",
        "const m = require(`./${name}`);",
    ],
)
def test_a_computed_require_is_left_to_code_analysis(tmp_path: Path, line: str) -> None:
    assert kinds(tmp_path, line) == []


def test_a_literal_require_is_not_dynamic(tmp_path: Path) -> None:
    assert kinds(tmp_path, "const m = require('express');") == []


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("setInterval(job, 1000);", ["timer"]),
        ("cron.schedule('* * * * *', job);", ["timer"]),
        ("setTimeout(job, 1000);", []),
        ("https.request(opts, cb);", ["http"]),
        ("http.get(url, cb);", ["http"]),
        ("axios.post(url, body);", ["http"]),
        ("fetch(url);", ["http"]),
        ("net.connect({ port: 1 });", ["socket"]),
        ("net.createConnection(1);", ["socket"]),
        ("const prefetch = 1;", []),
    ],
)
def test_line_patterns(tmp_path: Path, line: str, expected: list[str]) -> None:
    assert kinds(tmp_path, line) == expected


def test_generated_and_vendored_files_are_classified_and_never_scanned(tmp_path: Path) -> None:
    files = {
        "generated/c.js": b"// AUTO-GENERATED. DO NOT EDIT.\nsetInterval(a, 1);\n",
        "vendor/v.js": b"/*! v1 | vendored copy */\nsetInterval(a, 1);\n",
    }
    found, _ = run(tmp_path, {"package.json": PACKAGE, **files})
    assert sorted(f.claim_id for f in found.findings) == [
        "disc:generated:generated/c.js",
        "disc:vendored:vendor/v.js",
    ]
    assert found.inventory.first_party_sources == ()


def test_provenance_cites_the_marker_line_or_line_one(tmp_path: Path) -> None:
    files = {
        "generated/c.js": b"'use strict';\n/** AUTO-GENERATED */\n",
        "vendor/plain.js": b"a;\nb;\n",
    }
    found, _ = run(tmp_path, files)
    cited = {f.claim_id: f.evidence[0] for f in found.findings}
    assert cited["disc:generated:generated/c.js"] == ("generated/c.js", 2, 2)
    assert cited["disc:vendored:vendor/plain.js"] == ("vendor/plain.js", 1, 1)


def test_a_file_that_is_not_utf8_gets_an_exact_byte_claim_and_is_listed(tmp_path: Path) -> None:
    found, reader = run(tmp_path, {"a.js": b"var x = '\xe9';\n"})
    (finding,) = found.findings
    assert finding.kind == "encoding" and finding.status == "confirmed"
    assert finding.byte_evidence == (("a.js", 9, 10),)
    assert found.unscanned == (("a.js", "undecodable"),)
    assert verify_claim(to_claim_inputs(finding, reader), reader).passed


def test_crlf_is_reported_with_normalised_line_numbers(tmp_path: Path) -> None:
    found, reader = run(tmp_path, {"a.js": b"a;\r\nb;\r\nc;\r\n"})
    (finding,) = found.findings
    assert finding.claim_id == "disc:crlf:a.js" and finding.status == "confirmed"
    assert finding.evidence == (("a.js", 1, 3),)
    assert verify_claim(to_claim_inputs(finding, reader), reader).passed


def test_a_lone_carriage_return_is_not_crlf(tmp_path: Path) -> None:
    assert kinds(tmp_path, "a;\rb;\n") == []


def test_crlf_evidence_stops_at_the_excerpt_limit(tmp_path: Path) -> None:
    body = b"x;\r\n" * 100
    found, reader = run(tmp_path, {"a.js": body})
    (finding,) = found.findings
    _, first, last = finding.evidence[0]
    assert (first, last) == (1, 40)  # EVD-1.4
    assert verify_claim(to_claim_inputs(finding, reader), reader).passed


def test_the_inventory_counts_languages_and_reads_the_manifest(tmp_path: Path) -> None:
    pkg = b'{"main": "app.js", "scripts": {"start": "node app.js"}, "dependencies": {"a": "1"}}'
    found, _ = run(tmp_path, {"package.json": pkg, "a.js": b"x;\n", "s.sql": b"x;\n", "n": b"x\n"})
    inv = found.inventory
    assert inv.languages == {"JSON": 1, "JavaScript": 1, "SQL": 1, "other": 1}
    assert (inv.main, inv.scripts, inv.declared) == ("app.js", {"start": "node app.js"}, {"a": "1"})


def test_a_package_json_main_that_is_not_a_string_is_ignored(tmp_path: Path) -> None:
    found, _ = run(tmp_path, {"package.json": b'{"main": 3, "scripts": [1]}\n'})
    assert found.inventory.main is None and found.inventory.scripts == {}


# ---- on the fixture ---------------------------------------------------------------------------


def test_every_finding_on_the_fixture_passes_the_verifier() -> None:
    result = run_on_fixture()
    assert result.discovery.findings and result.blocked == ()


def test_fixture_score_facts_found_and_missed() -> None:
    scores = run_on_fixture().scores
    assert set(scores.missed_facts) == {"T03-F2", "T24-F2"}  # defaults need meaning, not a pattern
    assert scores.precision.hits == scores.precision.total
    assert scores.overclaims == ()


def test_discovery_only_scores_the_kinds_it_looks_for() -> None:
    assert {k.kind for k in run_on_fixture().scores.per_kind} <= KINDS


def test_the_patterns_are_fingerprinted() -> None:
    assert len(patterns_sha256()) == 64 and len(PATTERNS) == 4


def test_committed_result_was_run_with_the_current_patterns() -> None:
    """Change a pattern and this fails until Discovery is re-run and re-committed."""
    manifests = sorted(RESULTS_DIR.glob("*-discovery-v*/manifest.json"))
    assert manifests, "no committed Discovery result under evals/results/"
    assert json.loads(manifests[-1].read_text())["patterns_sha256"] == patterns_sha256()


def test_cli_prints_and_records(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--out", str(tmp_path), "--run-id", "t1"]) == 0
    out = capsys.readouterr().out
    assert "Recall on Discovery's kinds" in out and "lib/legacy_labels.js" in out
    (folder,) = list(tmp_path.iterdir())
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["kind"] == "discovery" and manifest["model"] is None
    assert manifest["patterns_sha256"] == patterns_sha256() and manifest["blocked_by_verifier"] == 0


def test_cli_fails_when_the_verifier_blocks_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = run_on_fixture()
    blocked = type(real)(real.pinned_revision, real.discovery, real.scores, (("x", ("V-2",)),))
    monkeypatch.setattr(cli, "run_on_fixture", lambda: blocked)
    assert cli.main([]) == 1
