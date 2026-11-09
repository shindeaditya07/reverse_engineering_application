"""Code Analysis (FR-3): what each construct yields, what it must not, and the fixture score."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from services.codeanalysis import __main__ as cli
from services.codeanalysis import analyze
from services.codeanalysis.__main__ import analyzer_sha256
from services.codeanalysis.run import KINDS, run_on_fixture
from services.discovery.agent import Finding, to_claim_inputs
from services.evals.results import RESULTS_DIR
from services.evidence import SnapshotReader
from services.ingest.limits import MIB, Limits
from services.ingest.pin import pin_local
from services.verifier import verify_claim

LIMITS = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
APP = b"const express = require('express');\nconst app = express();\n"


def run(tmp_path: Path, files: Mapping[str, bytes | str]):  # type: ignore[no-untyped-def]
    source = tmp_path / "source"
    for rel, data in files.items():
        (source / rel).parent.mkdir(parents=True, exist_ok=True)
        (source / rel).write_bytes(data if isinstance(data, bytes) else data.encode())
    pin = pin_local(source, tmp_path / "store", LIMITS)
    reader = SnapshotReader.from_pinned(pin)
    return analyze(reader, [f.path for f in pin.tree.files]), reader


def found(
    tmp_path: Path, code: str, kind: str | None = None, **extra: bytes | str
) -> list[Finding]:
    result, _ = run(tmp_path, {"app.js": APP + code.encode(), **extra})
    return [f for f in result.findings if kind is None or f.kind == kind]


def routes(tmp_path: Path, code: str, **extra: bytes | str) -> list[Finding]:
    return found(tmp_path, code, "route", **extra)


# ---- routes ----------------------------------------------------------------------------


def test_a_literal_route_is_confirmed_with_its_method_and_path(tmp_path: Path) -> None:
    (route,) = routes(tmp_path, "app.post('/a', (req, res) => res.end());")
    assert route.status == "confirmed" and "POST /a" in route.text
    assert route.evidence == (("app.js", 3, 3),)


@pytest.mark.parametrize(
    "method", ["get", "post", "put", "patch", "delete", "all", "head", "options"]
)
def test_every_http_method_is_a_route(tmp_path: Path, method: str) -> None:
    (route,) = routes(tmp_path, f"app.{method}('/m', h);")
    assert f"{method.upper()} /m" in route.text


def test_a_call_on_something_that_is_not_an_express_object_is_not_a_route(tmp_path: Path) -> None:
    code = "const cache = new Map();\ncache.get('/a');\nconst other = make();\nother.get('/b');\n"
    assert routes(tmp_path, code) == []


def test_use_and_listen_are_not_routes(tmp_path: Path) -> None:
    assert routes(tmp_path, "app.use(mw);\napp.listen(3000);") == []


def test_a_route_registered_in_a_literal_loop_is_expanded(tmp_path: Path) -> None:
    code = "['a', 'b'].forEach((p) => {\n  app.get('/x/' + p, h);\n});\n"
    (route,) = routes(tmp_path, code)
    assert route.status == "confirmed" and "GET /x/a, GET /x/b" in route.text
    assert "in a loop" in route.text


def test_a_template_string_path_is_expanded_too(tmp_path: Path) -> None:
    (route,) = routes(tmp_path, "['a'].forEach(function (p) {\n  app.get(`/t/${p}`, h);\n});\n")
    assert "GET /t/a" in route.text and route.status == "confirmed"


def test_a_loop_over_something_not_literal_is_unknown(tmp_path: Path) -> None:
    (route,) = routes(tmp_path, "list.forEach((p) => {\n  app.get('/x/' + p, h);\n});\n")
    assert route.status == "unknown" and "computed at run time" in route.text


def test_a_for_loop_is_unknown(tmp_path: Path) -> None:
    code = "for (const p of ['a']) {\n  app.get('/x/' + p, h);\n}\n"
    (route,) = routes(tmp_path, code)
    assert route.status == "unknown"


def test_a_computed_path_is_unknown_and_cites_the_registration(tmp_path: Path) -> None:
    (route,) = routes(tmp_path, "app.get(base + '/x', h);")
    assert route.status == "unknown" and route.evidence == (("app.js", 3, 3),)


def test_a_route_with_no_path_argument_is_unknown(tmp_path: Path) -> None:
    (route,) = routes(tmp_path, "app.get();")
    assert route.status == "unknown"


def test_a_route_behind_a_condition_says_so_and_cites_the_condition(tmp_path: Path) -> None:
    code = "if (process.env.X !== '1') {\n  app.get('/d', h);\n} else {\n  app.get('/e', h);\n}\n"
    first, second = routes(tmp_path, code)
    assert "only when process.env.X !== '1'" in first.text
    assert "only when not process.env.X !== '1'" in second.text
    assert ("app.js", 3, 3) in first.evidence


def test_a_route_inside_a_function_names_the_function(tmp_path: Path) -> None:
    (route,) = routes(tmp_path, "function setup() {\n  app.get('/s', h);\n}\n")
    assert "inside setup" in route.text


def test_a_binary_expression_that_is_not_addition_is_not_a_path(tmp_path: Path) -> None:
    (route,) = routes(tmp_path, "app.get('a' - 'b', h);")
    assert route.status == "unknown"


def test_a_router_is_prefixed_by_its_mount_and_cites_it(tmp_path: Path) -> None:
    files = {
        "app.js": APP + b"app.use('/api', require('./r'));\n",
        "r.js": b"const express = require('express');\nconst r = express.Router();\n"
        b"r.get('/', h);\nr.get('/:id', h);\nmodule.exports = r;\n",
    }
    result, _ = run(tmp_path, files)
    top, second = [f for f in result.findings if f.kind == "route"]
    assert top.status == "confirmed" and "GET /api" in top.text and "GET /api/:id" in second.text
    assert ("app.js", 3, 3) in top.evidence


def test_a_router_mounted_through_an_alias_and_a_nested_router(tmp_path: Path) -> None:
    files = {
        "app.js": APP + b"const outer = require('./outer');\napp.use('/o', outer);\n",
        "outer.js": b"const { Router } = require('express');\nconst r = Router();\n"
        b"r.use('/i', require('./inner'));\nmodule.exports = r;\n",
        "inner.js": b"const express = require('express');\nconst r = express.Router();\n"
        b"r.get('/x', h);\n",
    }
    result, _ = run(tmp_path, files)
    (route,) = [f for f in result.findings if f.kind == "route"]
    assert route.status == "confirmed" and "GET /o/i/x" in route.text


def test_a_router_that_is_never_mounted_is_inferred_not_confirmed(tmp_path: Path) -> None:
    files = {"r.js": b"const e = require('express');\nconst r = e.Router();\nr.get('/x', h);\n"}
    result, _ = run(tmp_path, files)
    (route,) = [f for f in result.findings if f.kind == "route"]
    assert route.status == "inferred" and "no mount point" in route.text


def test_a_mount_cycle_does_not_loop_forever(tmp_path: Path) -> None:
    files = {
        "a.js": b"const e = require('express');\nconst r = e.Router();\n"
        b"r.use('/a', require('./b'));\nr.get('/x', h);\n",
        "b.js": b"const e = require('express');\nconst r = e.Router();\n"
        b"r.use('/b', require('./a'));\n",
    }
    result, _ = run(tmp_path, files)
    (route,) = [f for f in result.findings if f.kind == "route"]
    assert route.status == "inferred"


# ---- swallowed errors ------------------------------------------------------------------


def test_an_empty_catch_is_found_even_with_a_comment(tmp_path: Path) -> None:
    (swallowed,) = found(
        tmp_path, "try {\n  f();\n} catch (e) {\n  // ignore\n}\n", "error_handling"
    )
    assert swallowed.status == "confirmed" and swallowed.evidence == (("app.js", 5, 7),)


def test_a_catch_that_does_something_is_not_swallowed(tmp_path: Path) -> None:
    assert found(tmp_path, "try { f(); } catch (e) { log(e); }", "error_handling") == []


@pytest.mark.parametrize("callback", ["() => {}", "function () {}", "(e) => { /* none */ }"])
def test_an_empty_promise_catch_is_found(tmp_path: Path, callback: str) -> None:
    (swallowed,) = found(tmp_path, f"p.catch({callback});", "error_handling")
    assert ".catch callback" in swallowed.text


@pytest.mark.parametrize("code", ["p.catch(handler);", "p.catch((e) => log(e));", "p.catch();"])
def test_a_promise_catch_that_handles_is_not_swallowed(tmp_path: Path, code: str) -> None:
    assert found(tmp_path, code, "error_handling") == []


def test_a_member_call_that_is_not_catch_is_ignored(tmp_path: Path) -> None:
    assert found(tmp_path, "p.then(() => {});\nfoo();", "error_handling") == []


# ---- unresolved ------------------------------------------------------------------------


def test_a_computed_require_is_unknown_and_names_where_it_may_reach(tmp_path: Path) -> None:
    (computed,) = found(tmp_path, "const m = require('./plugins/' + name);", "dependency")
    assert computed.status == "unknown" and "./plugins/" in computed.text


def test_a_fully_computed_require_may_reach_anything(tmp_path: Path) -> None:
    (computed,) = found(tmp_path, "const m = require(name);", "dependency")
    assert "any module may be loaded" in computed.text


def test_a_file_that_does_not_parse_is_listed_and_claimed_unknown(tmp_path: Path) -> None:
    result, _ = run(tmp_path, {"bad.js": "function ( {\n", "ok.js": "const x = 1;\n"})
    assert result.unanalyzed == (
        ("bad.js", "syntax the parser could not read (CommonJS and ES2022 only)"),
    )
    (claim,) = [f for f in result.findings if f.claim_id == "ca:unanalyzed:bad.js"]
    assert claim.status == "unknown" and claim.evidence == ()


def test_typescript_and_undecodable_files_are_stated_not_skipped_silently(tmp_path: Path) -> None:
    result, _ = run(tmp_path, {"t.ts": "const x: number = 1;\n", "b.js": b"\xff\xfe\xfa"})
    reasons = dict(result.unanalyzed)
    assert "only JavaScript" in reasons["t.ts"] and reasons["b.js"].startswith("unreadable")


# ---- dead code -------------------------------------------------------------------------

LIB = "function used() {}\nfunction unused() {}\nmodule.exports = { used, unused };\n"


def dead(tmp_path: Path, files: Mapping[str, bytes | str]) -> list[str]:
    result, _ = run(tmp_path, files)
    return sorted(f.claim_id.rsplit(":", 1)[1] for f in result.findings if f.kind == "dead_code")


def test_an_exported_function_nobody_uses_is_dead_and_a_used_one_is_not(tmp_path: Path) -> None:
    files = {"lib.js": LIB, "app.js": "const lib = require('./lib');\nlib.used();\n"}
    assert dead(tmp_path, files) == ["unused"]


def test_the_dead_code_claim_is_inferred_and_cites_declaration_and_export(tmp_path: Path) -> None:
    result, _ = run(
        tmp_path, {"lib.js": LIB, "app.js": "const lib = require('./lib');\nlib.used();\n"}
    )
    (claim,) = [f for f in result.findings if f.kind == "dead_code"]
    assert claim.status == "inferred" and claim.evidence == (("lib.js", 2, 2), ("lib.js", 3, 3))


@pytest.mark.parametrize(
    "app",
    [
        "const { unused } = require('./lib');\nunused();\n",
        "const { unused: renamed } = require('./lib');\nrenamed();\n",
        "require('./lib').unused();\n",
        "const lib = require('./lib');\nschedule(lib.unused);\n",
        "const lib = require('./lib');\nuse(lib);\n",
        "const lib = require('./lib');\nlib[name]();\n",
        "use(require('./lib'));\n",
    ],
)
def test_any_way_of_reaching_an_export_keeps_it_alive(tmp_path: Path, app: str) -> None:
    files = {"lib.js": "function unused() {}\nmodule.exports = { unused };\n", "app.js": app}
    assert dead(tmp_path, files) == []


def test_a_function_used_inside_its_own_file_is_not_dead(tmp_path: Path) -> None:
    lib = "function a() {}\nfunction b() { a(); }\nmodule.exports = { a };\nb();\n"
    assert dead(tmp_path, {"lib.js": lib}) == []


def test_a_function_that_only_calls_itself_is_dead(tmp_path: Path) -> None:
    lib = "function a() { a(); }\nmodule.exports = { a };\n"
    assert dead(tmp_path, {"lib.js": lib}) == ["a"]


def test_use_from_a_test_file_does_not_keep_code_alive(tmp_path: Path) -> None:
    files = {
        "lib.js": "function a() {}\nmodule.exports = { a };\n",
        "test/lib.test.js": "const lib = require('../lib');\nlib.a();\n",
    }
    assert dead(tmp_path, files) == ["a"]


def test_exports_in_other_shapes(tmp_path: Path) -> None:
    lib = (
        "function a() {}\nfunction b() {}\nconst c = () => 1;\nconst d = 5;\n"
        "exports.a = a;\nmodule.exports.b = b;\nmodule.exports.c = c;\nmodule.exports.d = d;\n"
        "module.exports.e = unknownThing;\n"
    )
    assert dead(tmp_path, {"lib.js": lib}) == ["a", "b", "c"]  # a constant is not a function


def test_an_export_object_with_a_renamed_key(tmp_path: Path) -> None:
    lib = "function impl() {}\nmodule.exports = { api: impl, n: 1, ...rest };\n"
    assert dead(tmp_path, {"lib.js": lib}) == ["api"]


def test_the_entry_point_is_never_called_dead(tmp_path: Path) -> None:
    files = {
        "package.json": '{"main": "index.js"}\n',
        "index.js": "function start() {}\nmodule.exports = { start };\n",
    }
    assert dead(tmp_path, files) == []


def test_a_computed_require_protects_only_the_directory_it_can_reach(tmp_path: Path) -> None:
    files = {
        "app.js": "const m = require('./plugins/' + name);\n",
        "plugins/p.js": "function a() {}\nmodule.exports = { a };\n",
        "other/o.js": "function b() {}\nmodule.exports = { b };\n",
    }
    assert dead(tmp_path, files) == ["b"]


def test_a_fully_computed_require_means_no_dead_code_claims_at_all(tmp_path: Path) -> None:
    files = {
        "app.js": "const m = require(name);\n",
        "o.js": "function b() {}\nmodule.exports = { b };\n",
    }
    assert dead(tmp_path, files) == []


def test_requires_that_do_not_resolve_are_ignored(tmp_path: Path) -> None:
    files = {"app.js": "const x = require('./missing');\nx.a();\nconst y = require('lodash');\n"}
    assert dead(tmp_path, files) == []


def test_an_index_file_and_an_extensionless_require_resolve(tmp_path: Path) -> None:
    files = {
        "app.js": "const d = require('./dir');\nd.used();\n",
        "dir/index.js": "function used() {}\nfunction spare() {}\nmodule.exports = { used, spare };\n",
    }
    assert dead(tmp_path, files) == ["spare"]


# ---- call graph ------------------------------------------------------------------------


def test_the_call_graph_resolves_local_imported_and_destructured_calls(tmp_path: Path) -> None:
    files = {
        "lib.js": "function helper() {}\nfunction outer() { helper(); }\nmodule.exports = { outer, helper };\n",
        "app.js": "const lib = require('./lib');\nconst { helper } = require('./lib');\n"
        "lib.outer();\nconst run = () => helper();\nunknown();\n",
    }
    result, _ = run(tmp_path, files)
    edges = {(e.caller, e.callee) for e in result.calls}
    assert (("lib.js", "outer"), ("lib.js", "helper")) in edges
    assert (("app.js", "<module>"), ("lib.js", "outer")) in edges
    assert (("app.js", "run"), ("lib.js", "helper")) in edges
    assert all(e.callee[1] != "unknown" for e in result.calls)


# ---- evidence and encoding -------------------------------------------------------------


def test_line_numbers_count_after_crlf_normalisation_and_claims_verify(tmp_path: Path) -> None:
    code = (APP + b"app.get('/x', h);\n").replace(b"\n", b"\r\n")
    result, reader = run(tmp_path, {"app.js": code})
    (route,) = [f for f in result.findings if f.kind == "route"]
    assert route.evidence == (("app.js", 3, 3),)
    assert verify_claim(to_claim_inputs(route, reader), reader).passed


def test_a_long_registration_cites_at_most_the_excerpt_limit(tmp_path: Path) -> None:
    body = "\n".join(f"  x{i}();" for i in range(60))
    (route,) = routes(tmp_path, f"app.get('/long', (req, res) => {{\n{body}\n}});\n")
    (_, start, end) = route.evidence[0]
    assert end - start + 1 == 40


# ---- flow ------------------------------------------------------------------------------

CALLBACKS = """
function run(id, cb) {
  db.query('a', [id], (err, rows) => {
    if (err) return cb(err);
    return db.query('b', [rows[0].x], (err2, more) => {
      return cb(null, more);
    });
  });
}
"""


def test_nested_error_first_callbacks_are_one_confirmed_flow_claim(tmp_path: Path) -> None:
    (flow,) = found(tmp_path, CALLBACKS, "flow")
    assert flow.status == "confirmed" and flow.claim_id == "ca:callback-chain:app.js:5"
    assert "run in app.js line 5 nests 2 error-first callbacks: db.query(), db.query()" in flow.text
    assert flow.evidence == (("app.js", 5, 10),)


def test_one_level_of_callback_is_not_a_chain(tmp_path: Path) -> None:
    assert not found(tmp_path, "db.query('a', (err, rows) => { done(err); });", "flow")


def test_callbacks_without_an_error_parameter_are_not_flow(tmp_path: Path) -> None:
    code = "xs.forEach((x) => { ys.forEach((y) => { go(x, y); }); });"
    assert not found(tmp_path, code, "flow")


def test_a_single_function_literal_argument_that_is_not_last_is_ignored(tmp_path: Path) -> None:
    code = "run((err) => { run((err2) => { x(); }); }, 1);"
    assert not found(tmp_path, code, "flow")


def test_a_promise_chain_needs_two_thens(tmp_path: Path) -> None:
    chain = "function f() {\n  return load()\n    .then((a) => a)\n    .then((b) => b)\n    .catch(h);\n}"
    (flow,) = found(tmp_path, chain, "flow")
    assert flow.status == "confirmed" and "f in app.js line 4 runs a promise chain" in flow.text
    assert "starts at load and continues with 3 steps, in order: .then, .then, .catch." in flow.text
    assert not found(tmp_path, "load().then((a) => a).catch(h);", "flow")


def test_an_async_function_lists_its_awaits_in_source_order(tmp_path: Path) -> None:
    code = (
        "async function go() {\n  await a();\n  for (const x of xs) { await b(x); }\n"
        "  await new Promise((r) => setTimeout(r, 1));\n}"
    )
    (flow,) = found(tmp_path, code, "flow")
    assert flow.claim_id == "ca:async-flow:app.js:3"
    assert (
        "go in app.js line 3 is async and awaits 3 steps, in source order: a(), b(), " in flow.text
    )
    assert "<expression>." in flow.text


def test_awaits_in_a_nested_function_belong_to_that_function(tmp_path: Path) -> None:
    code = (
        "async function outer() {\n  await a();\n"
        "  const inner = async () => { await b(); await c(); };\n}"
    )
    (flow,) = found(tmp_path, code, "flow")
    assert "inner in app.js" in flow.text and "awaits 2 steps" in flow.text


def test_a_long_step_list_is_cut_and_counted(tmp_path: Path) -> None:
    awaits = "".join(f"  await s{i}();\n" for i in range(10))
    (flow,) = found(tmp_path, "async function many() {\n" + awaits + "}", "flow")
    assert "awaits 10 steps" in flow.text and "and 2 more" in flow.text


def test_flow_claims_pass_the_verifier(tmp_path: Path) -> None:
    result, reader = run(tmp_path, {"app.js": (APP.decode() + CALLBACKS).encode()})
    flows = [f for f in result.findings if f.kind == "flow"]
    assert flows and all(verify_claim(to_claim_inputs(f, reader), reader).passed for f in flows)


# ---- the fixture -----------------------------------------------------------------------


def test_every_finding_on_the_fixture_passes_the_verifier() -> None:
    result = run_on_fixture()
    assert result.analysis.findings and result.blocked == ()


def test_fixture_score() -> None:
    scores = run_on_fixture().scores
    assert scores.missed_facts == () and scores.overclaims == ()
    assert scores.recall.hits == scores.recall.total == 8
    # The key lists two of the ten routes; the other eight are real and count against precision.
    assert (scores.precision.hits, scores.precision.total) == (8, 17)


def test_the_fixture_states_what_it_could_not_follow() -> None:
    result = run_on_fixture()
    ids = {f.claim_id for f in result.analysis.findings if f.status == "unknown"}
    assert ids == {
        "ca:computed-require:services/orders_service.js:10",
        "ca:unanalyzed:lib/legacy_labels.js",
    }


def test_only_the_built_kinds_are_scored() -> None:
    assert {k.kind for k in run_on_fixture().scores.per_kind} <= KINDS


def test_committed_result_was_run_with_the_current_analyzer() -> None:
    """Change the analyzer and this fails until it is re-run and re-committed."""
    manifests = sorted(RESULTS_DIR.glob("*-codeanalysis-v*/manifest.json"))
    assert manifests, "no committed Code Analysis result under evals/results/"
    assert json.loads(manifests[-1].read_text())["analyzer_sha256"] == analyzer_sha256()


def test_cli_prints_and_records(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--out", str(tmp_path), "--run-id", "t1"]) == 0
    out = capsys.readouterr().out
    assert "Recall on its kinds" in out and "lib/legacy_labels.js" in out
    (folder,) = list(tmp_path.iterdir())
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["kind"] == "codeanalysis" and manifest["model"] is None
    assert manifest["analyzer_sha256"] == analyzer_sha256() and manifest["blocked_by_verifier"] == 0


def test_cli_fails_when_the_verifier_blocks_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = run_on_fixture()
    blocked = type(real)(real.pinned_revision, real.analysis, real.scores, (("x", ("V-2",)),))
    monkeypatch.setattr(cli, "run_on_fixture", lambda: blocked)
    assert cli.main([]) == 1


# ---- a crash in tree-sitter 0.26.0 -----------------------------------------------------

_LARGE_APP = (
    """
const express = require('express');
const router = express.Router();
"""
    + (
        "router.get('/a/:id', restrict, async (req, res) => {\n"
        "  try {\n"
        "    await db.orders.deleteOne({ _id: id });\n"
        "    f().then(() => { if (x) { res.status(200).json({ m: 'ok' }); return; } res.redirect('/a'); });\n"
        "  } catch (ex) { console.log('e', ex); res.redirect('/b'); }\n"
        "});\n"
    )
    * 100
)


def test_a_large_route_file_does_not_crash_the_parser_binding(tmp_path: Path) -> None:
    """tree-sitter 0.26.0 segfaults on `node.end_point.row` in a file this size (found on a real
    Express app). Row is read by index instead. This runs in a child process because the failure
    it guards against kills the interpreter, which would take the whole test run with it."""
    import subprocess
    import sys

    script = (
        "import importlib, sys\n"
        "sys.path.insert(0, sys.argv[2])\n"
        "from pathlib import Path\n"
        "from services.evidence import SnapshotReader\n"
        "from services.ingest.limits import MIB, Limits\n"
        "from services.ingest.pin import pin_local\n"
        "analyze = importlib.import_module('services.codeanalysis.analyze').analyze\n"
        "root = Path(sys.argv[1])\n"
        "pin = pin_local(root / 'source', root / 'store', Limits(10 * MIB, 1000, 30))\n"
        "reader = SnapshotReader.from_pinned(pin)\n"
        "print(len(analyze(reader, [f.path for f in pin.tree.files]).findings))\n"
    )
    repo = Path(__file__).resolve().parents[1]
    source = tmp_path / "source"
    source.mkdir()
    (source / "routes.js").write_text(_LARGE_APP, encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-I", "-c", script, str(tmp_path), str(repo)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr[-400:]
    assert int(done.stdout.strip()) >= 100
