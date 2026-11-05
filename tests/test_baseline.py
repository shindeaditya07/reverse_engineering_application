"""The grep baseline: what its patterns do and do not match, run validity, frozen patterns."""

import json
from pathlib import Path

import pytest

from services.baseline import __main__ as cli
from services.baseline import run as run_module
from services.baseline.finder import PATTERNS, find_in_file, patterns_sha256, source_files
from services.baseline.run import run_baseline
from services.evals.results import RESULTS_DIR
from services.evidence import SnapshotReader, Unresolved
from services.ingest.limits import MIB, Limits
from services.ingest.pin import PinnedSource, pin_local

LIMITS = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)


def pinned(tmp_path: Path, files: dict[str, bytes]) -> PinnedSource:
    source = tmp_path / "source"
    for rel, data in files.items():
        (source / rel).parent.mkdir(parents=True, exist_ok=True)
        (source / rel).write_bytes(data)
    return pin_local(source, tmp_path / "store", LIMITS)


def kinds(tmp_path: Path, code: str) -> list[str]:
    reader = SnapshotReader.from_pinned(pinned(tmp_path, {"a.js": code.encode()}))
    return [c.kind for c in find_in_file(reader, "a.js")]


@pytest.mark.parametrize(
    "line",
    [
        "app.get('/orders', handler);",
        'router.post("/orders/:id", h);',
        "app.delete(`/x`, h);",
        "server.put('/y', h)",
        "  app.patch( '/z', h);",
    ],
)
def test_route_pattern_matches_common_express_calls(tmp_path: Path, line: str) -> None:
    assert kinds(tmp_path, line) == ["route"]


@pytest.mark.parametrize(
    "line",
    [
        "app.get(path, handler);",  # not a literal path: the baseline cannot see it
        "app.use('/api', router);",
        "// app.get without a call",
        "const app = express();",
        "cache.get('/x')",
    ],
)
def test_route_pattern_does_not_over_reach(tmp_path: Path, line: str) -> None:
    assert kinds(tmp_path, line) == []


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("db.query('SELECT id FROM orders WHERE id = ?', [id]);", ["sql_read"]),
        ("const q = 'select * from t';", ["sql_read"]),
        ("db.query('INSERT INTO t (a) VALUES (?)');", ["sql_write"]),
        ("db.query('UPDATE t SET a = 1');", ["sql_write"]),
        ("db.query('delete from t');", ["sql_write"]),
        ("const q = 'SELECT 1';", []),  # no FROM on the line: a one-line regex cannot know
        ("// we select the best from the list", ["sql_read"]),  # a known false positive
    ],
)
def test_sql_patterns(tmp_path: Path, line: str, expected: list[str]) -> None:
    assert kinds(tmp_path, line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "return res.status(400).json({ error: 'bad' });",
        "res.sendStatus(422);",
        "throw new ValidationError('bad');",
        "throw new InvalidInputError('x')",
    ],
)
def test_validation_patterns(tmp_path: Path, line: str) -> None:
    assert kinds(tmp_path, line) == ["validation"]


def test_other_status_codes_are_not_validation(tmp_path: Path) -> None:
    assert kinds(tmp_path, "res.status(500).end(); res.status(404).end();") == []


def test_each_claim_is_inferred_cites_its_own_line_and_has_a_stable_id(tmp_path: Path) -> None:
    reader = SnapshotReader.from_pinned(pinned(tmp_path, {"a.js": b"x\napp.get('/a', h);\n"}))
    (claim,) = find_in_file(reader, "a.js")
    assert claim.claim_id == "grep:a.js:2:route" and claim.status == "inferred"
    assert [(s.file, s.start, s.end) for s in claim.spans] == [("a.js", 2, 2)]


def test_a_line_matching_two_kinds_gives_two_claims(tmp_path: Path) -> None:
    code = "db.query('SELECT a FROM t'); db.query('DELETE FROM t');"
    assert sorted(kinds(tmp_path, code)) == ["sql_read", "sql_write"]


def test_no_claim_is_ever_confirmed(tmp_path: Path) -> None:
    code = "app.get('/a', h);\ndb.query('SELECT a FROM t');\nres.status(400);\n"
    reader = SnapshotReader.from_pinned(pinned(tmp_path, {"a.js": code.encode()}))
    assert {c.status for c in find_in_file(reader, "a.js")} == {"inferred"}


def test_source_files_filters_by_suffix() -> None:
    assert source_files(["b.js", "a.ts", "c.json", "d.md", "e.mjs"]) == ["a.ts", "b.js", "e.mjs"]


# ---- runs ------------------------------------------------------------------------------------


def test_an_undecodable_file_is_stated_as_not_analysed_not_a_failure(tmp_path: Path) -> None:
    snap = pinned(tmp_path, {"ok.js": b"app.get('/a', h);\n", "bad.js": b"\xff\xfe app.get('/b')"})
    result = run_baseline(snap, [])
    assert result.run.valid and result.unscanned == (("bad.js", "undecodable"),)
    assert len(result.run.claims) == 1


def test_an_unreadable_file_is_a_failure_and_invalidates_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = pinned(tmp_path, {"a.js": b"x\n"})

    def boom(reader: SnapshotReader, path: str) -> list[object]:
        raise Unresolved("snapshot_modified", "edited")

    monkeypatch.setattr(run_module, "find_in_file", boom)
    result = run_baseline(snap, [])
    assert not result.run.valid and [f.error for f in result.run.failures] == ["Unresolved"]
    assert result.unscanned == ()


def test_baseline_run_scores_against_the_key(tmp_path: Path) -> None:
    result = run_module.run_on_fixture(tmp_path)
    assert result.run.valid and result.scores.recall.total == 41
    assert result.scores.overclaims == ()  # it only ever says Inferred
    assert result.unscanned == (("lib/legacy_labels.js", "undecodable"),)


# ---- never tuned -------------------------------------------------------------------------------


def test_patterns_are_fingerprinted() -> None:
    assert len(patterns_sha256()) == 64 and len(PATTERNS) == 5


def test_committed_baseline_was_run_with_the_current_patterns() -> None:
    """Change a pattern and this fails until the baseline is re-run and re-committed, so a
    change to the baseline is always visible in review (build-plan step 10: recorded, not tuned)."""
    manifests = sorted(RESULTS_DIR.glob("*-baseline-grep/manifest.json"))
    assert manifests, "no committed baseline result under evals/results/"
    recorded = json.loads(manifests[-1].read_text())
    assert recorded["patterns_sha256"] == patterns_sha256()


# ---- command line ------------------------------------------------------------------------------


def test_cli_prints_and_records(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--out", str(tmp_path), "--run-id", "t1"]) == 0
    out = capsys.readouterr().out
    assert "Recall on those kinds alone" in out and "lib/legacy_labels.js" in out
    (folder,) = list(tmp_path.iterdir())
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["kind"] == "baseline" and manifest["model"] is None
    assert manifest["patterns_sha256"] == patterns_sha256() and manifest["run_valid"] is True
    assert manifest["unscanned"] == [{"path": "lib/legacy_labels.js", "reason": "undecodable"}]


def test_cli_without_out_writes_nothing_and_exits_1_on_an_invalid_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(reader: SnapshotReader, path: str) -> list[object]:
        raise RuntimeError

    monkeypatch.setattr(run_module, "find_in_file", boom)
    assert cli.main([]) == 1
