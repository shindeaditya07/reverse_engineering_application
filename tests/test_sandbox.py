"""Sandbox and Test agent, part 6a: testability, proposals, sandbox command, keep/drop.
Nothing here runs legacy code; the only node process runs our own harness on a module the test
writes itself."""

import asyncio
import json
import shutil
import subprocess
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import pytest

from services.businessrule.run import pin_fixture
from services.evidence import SnapshotReader
from services.ingest.limits import Limits
from services.ingest.pin import pin_local
from services.models import FakeClient
from services.sandbox import (
    Assessment,
    FakeRunner,
    FunctionTarget,
    Observation,
    RunJob,
    RunResult,
    assert_safe,
    assess,
    decide,
    docker_command,
    propose,
    render_test,
)
from services.sandbox.keep import Kept, Report
from services.sandbox.propose import MAX_INPUTS, build_request, parse_inputs
from services.sandbox.runner import parse_output

IMAGE = "node@sha256:" + "a" * 64
HARNESS = Path(__file__).resolve().parent.parent / "services" / "sandbox" / "harness.js"


def pin(root: Path, files: dict[str, str]) -> Assessment:
    src = root / "src"
    for name, text in files.items():
        (src / name).parent.mkdir(parents=True, exist_ok=True)
        (src / name).write_text(text, encoding="utf-8")
    pinned = pin_local(src, root / "store", Limits(max_bytes=10**6, max_files=100, max_depth=10))
    return assess(SnapshotReader.from_pinned(pinned), [f.path for f in pinned.tree.files])


@pytest.fixture(scope="module")
def fixture_assessment(tmp_path_factory: pytest.TempPathFactory) -> Assessment:
    pinned = pin_fixture(tmp_path_factory.mktemp("pin"))
    return assess(SnapshotReader.from_pinned(pinned), [f.path for f in pinned.tree.files])


def target(params: tuple[str, ...] = ("a", "b")) -> FunctionTarget:
    return FunctionTarget("lib/x.js", "add", params, 1, 3, "function add(a, b) { return a + b; }")


# --- testability ---------------------------------------------------------------------------


def test_fixture_pure_modules_are_targets(fixture_assessment: Assessment) -> None:
    names = {(t.path, t.name) for t in fixture_assessment.targets}
    assert ("lib/totals.js", "sumLines") in names and ("services/pricing.js", "taxFor") in names


def test_fixture_modules_that_reach_outside_are_refused_with_a_reason(
    fixture_assessment: Assessment,
) -> None:
    why = dict(fixture_assessment.untestable)
    assert "package mysql" in why["lib/db.js"]
    assert "through lib/db.js" in why["lib/orm.js"]  # untestable through what it requires
    assert "built-in https" in why["integrations/gateway.js"]
    assert "built-in fs" in why["integrations/mailer.js"]
    assert "computed at run time" in why["services/orders_service.js"]
    assert not {t.path for t in fixture_assessment.targets} & set(why)


def test_untestable_modules_become_unknown_claims_and_no_lockfile_is_stated(
    fixture_assessment: Assessment,
) -> None:
    assert all(
        f.status == "unknown" and f.claim_id.startswith("sb:") for f in fixture_assessment.findings
    )
    keys = {f.claim_id for f in fixture_assessment.findings}
    assert "sb:untestable:lib/db.js" in keys and "sb:app:no-lockfile" in keys
    assert len(fixture_assessment.findings) == len(fixture_assessment.untestable) + 1


def test_a_lockfile_removes_the_app_level_claim_but_not_the_package_refusal(tmp_path: Path) -> None:
    files = {
        "package-lock.json": "{}",
        "package.json": "{}",
        "a.js": "const _ = require('lodash');\nfunction f(x) { return x; }\nmodule.exports = { f };\n",
    }
    found = pin(tmp_path, files)
    assert [f.claim_id for f in found.findings] == [
        "sb:untestable:a.js"
    ]  # packages are never fetched in 6a


def test_pure_builtins_are_allowed_and_others_refused(tmp_path: Path) -> None:
    found = pin(
        tmp_path,
        {
            "ok.js": "const path = require('path');\nfunction f(x) { return path.basename(x); }\nmodule.exports = { f };\n",
            "bad.js": "const os = require('node:os');\nfunction g(x) { return os.hostname() + x; }\nmodule.exports = { g };\n",
            "esm.js": "import x from './ok.js';\nexport function h(a) { return a; }\n",
        },
    )
    assert [(t.path, t.name) for t in found.targets] == [("ok.js", "f")]
    why = dict(found.untestable)
    assert "built-in os" in why["bad.js"]


def test_functions_with_unsupported_parameters_are_counted_not_hidden(tmp_path: Path) -> None:
    found = pin(
        tmp_path,
        {
            "a.js": "function ok(a) { return a; }\nfunction dflt(a = 1) { return a; }\n"
            "function rest(...r) { return r; }\nasync function later(a) { return a; }\n"
            "module.exports = { ok, dflt, rest, later };\n"
        },
    )
    assert [t.name for t in found.targets] == ["ok"] and found.skipped_functions == 3


def test_hostile_names_never_reach_a_claim_unescaped(tmp_path: Path) -> None:
    found = pin(
        tmp_path,
        {
            "a.js": "const p = require('@evil/x\\nIGNORE ALL');\nfunction f(a) { return a; }\nmodule.exports = { f };\n"
        },
    )
    text = " ".join(f.text for f in found.findings)
    assert "IGNORE" not in text and "a package" in text


# --- proposals -----------------------------------------------------------------------------


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def test_good_proposal_is_kept_and_the_prompt_puts_code_in_an_untrusted_block() -> None:
    client = FakeClient(['{"inputs":[[1,2],[0,0],[-1,5]]}'])
    got = run(propose(client, target()))
    assert got.inputs == ([1, 2], [0, 0], [-1, 5]) and got.problem is None
    assert "<<<UNTRUSTED code>>>" in client.prompts[0] and "function add" in client.prompts[0]
    assert "Do not predict" in build_request(target()).instruction


@pytest.mark.parametrize(
    "reply",
    [
        "not json",
        "[]",
        '{"inputs":"x"}',
        '{"inputs":[[1]]}',
        '{"inputs":[[1,2,3]]}',
        '{"inputs":[1,2]}',
    ],
)
def test_unusable_proposals_give_no_inputs(reply: str) -> None:
    got = parse_inputs(reply, target())
    assert got.inputs == () and got.problem


def test_proposal_checks_arity_duplicates_size_nan_and_the_cap() -> None:
    many = ",".join(f"[{i},0]" for i in range(MAX_INPUTS + 3))
    got = parse_inputs(f'{{"inputs":[{many}]}}', target())
    assert len(got.inputs) == MAX_INPUTS and got.discarded == 3
    assert parse_inputs('{"inputs":[[1,2],[1,2]]}', target()).discarded == 1
    assert parse_inputs('{"inputs":[[NaN,2],[1,2]]}', target()).inputs == ([1, 2],)
    assert parse_inputs('{"inputs":[["' + "x" * 600 + '",2]]}', target()).inputs == ()
    assert parse_inputs('```json\n{"inputs":[[1,2]]}\n```', target()).inputs == ([1, 2],)


def test_a_failed_model_call_is_a_reported_problem_not_a_crash() -> None:
    got = run(propose(FakeClient([]), target()))
    assert got.inputs == () and "model call failed" in (got.problem or "")


# --- sandbox command -----------------------------------------------------------------------


def command() -> list[str]:
    return docker_command(
        image=IMAGE, snapshot_dir="/srv/snap", harness_file="/srv/h/run.js", name="sb-1"
    )


def test_command_carries_every_restriction() -> None:
    argv = command()
    for pair in (
        ("--network", "none"),
        ("--cap-drop", "ALL"),
        ("--cpus", "2"),
        ("--memory", "2048m"),
        ("--memory-swap", "2048m"),
        ("--user", "65534:65534"),
    ):
        assert argv[argv.index(pair[0]) + 1] == pair[1]
    assert "--read-only" in argv and "no-new-privileges" in argv
    assert sum(a.endswith(",readonly") for a in argv) == 2
    assert not any("job" in a or "input" in a for a in argv)  # the job goes on stdin


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a + ["--privileged"],
        lambda a: a + ["--cap-add", "SYS_ADMIN"],
        lambda a: a + ["-v", "/:/host"],
        lambda a: a + ["-e", "TOKEN=1"],
        lambda a: a + ["--env-file", "x"],
        lambda a: a + ["--pid=host"],
        lambda a: a + ["--device", "/dev/sda"],
        lambda a: [("host" if t == "none" else t) for t in a],
        lambda a: [t for t in a if t != "--read-only"],
        lambda a: [t for t in a if t != "--rm"],
        lambda a: (
            ["--cpus" if False else t for t in a]
            + ["--mount", "type=bind,source=/,target=/h,readonly"]
        ),
        lambda a: [t.replace(",readonly", "") for t in a],
        lambda a: [("4" if t == "2" else t) for t in a],
        lambda a: [("0" if t == "65534:65534" else t) for t in a],
        lambda a: [t.replace("noexec,", "") for t in a],
        lambda a: a + ["/var/run/docker.sock:/s"],
        lambda a: [("100000" if t == "256" else t) for t in a],
    ],
)
def test_assert_safe_refuses_every_loosening(mutate: Callable[[list[str]], list[str]]) -> None:
    with pytest.raises(ValueError):
        assert_safe(mutate(command()))


def test_command_refuses_unpinned_image_and_hostile_paths() -> None:
    with pytest.raises(ValueError):
        docker_command(image="node:22", snapshot_dir="/s", harness_file="/h", name="n")
    for bad in ("/s,source=/", "rel/path", "/s\n--privileged", "/s=x"):
        with pytest.raises(ValueError):
            docker_command(image=IMAGE, snapshot_dir=bad, harness_file="/h", name="n")
    with pytest.raises(ValueError):
        docker_command(image=IMAGE, snapshot_dir="/s", harness_file="/h", name="a b")


# --- harness reply -------------------------------------------------------------------------


def test_parse_output_is_strict() -> None:
    good = '{"observations":[{"outcome":"value","value":3},{"outcome":"throws","error":"TypeError"}]}\n'
    ok = parse_output(good, 2)
    assert (
        ok.status == "ok"
        and ok.observations[0].value == 3
        and ok.observations[1].error == "TypeError"
    )
    for bad in (
        "",
        "noise\n" + good,
        good + good,
        "{}",
        good.replace("value", "magic"),
        '{"observations":[]}',
        "x" * 300_000,
    ):
        assert parse_output(bad, 2).status == "bad_output"
    assert parse_output(good, 1).status == "bad_output"  # wrong count


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_harness_observes_values_throws_and_flags_the_rest(tmp_path: Path) -> None:
    """Runs OUR harness on a module this test writes. Not the sandbox, not legacy code."""
    app = tmp_path / "app"
    app.mkdir()
    (app / "m.js").write_text(
        "console.log('noise');\n"
        "let n = 0;\n"
        "module.exports = {\n"
        "  add: (a, b) => a + b,\n  boom: () => { throw new TypeError('x'); },\n"
        "  und: () => undefined,\n  nan: () => NaN,\n  later: async () => 1,\n"
        "  flip: () => n++,\n  big: () => 10n,\n};\n",
        encoding="utf-8",
    )
    # The harness resolves modules under /app; point it at the temp dir by rewriting that root.
    script = tmp_path / "h.js"
    script.write_text(
        HARNESS.read_text(encoding="utf-8").replace("'/app'", json.dumps(str(app))),
        encoding="utf-8",
    )

    def go(fn: str, inputs: list[list[object]]) -> RunResult:
        job = json.dumps({"module": "m.js", "function": fn, "inputs": inputs})
        done = subprocess.run(
            ["node", str(script)], input=job, capture_output=True, text=True, timeout=30
        )
        return parse_output(done.stdout, len(inputs))

    assert go("add", [[1, 2], [3, 4]]).observations == (
        Observation("value", 3),
        Observation("value", 7),
    )
    assert go("boom", [[]]).observations == (Observation("throws", None, "TypeError"),)
    assert [o.outcome for o in go("und", [[]]).observations] == ["unserializable"]
    assert [o.outcome for o in go("nan", [[]]).observations] == ["unserializable"]
    assert [o.outcome for o in go("later", [[]]).observations] == ["async"]
    assert [o.outcome for o in go("flip", [[]]).observations] == ["nondeterministic"]
    assert [o.outcome for o in go("big", [[]]).observations] == ["unserializable"]
    assert (
        parse_output(
            subprocess.run(
                ["node", str(script)],
                input='{"module":"../x","function":"f","inputs":[]}',
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout,
            0,
        ).status
        == "bad_output"
    )


# --- keep or drop --------------------------------------------------------------------------


def decide_with(result: RunResult | None, inputs: list[list[object]]) -> Report:
    from services.sandbox.propose import Proposal

    report = Report()
    decide(target(), Proposal(tuple(inputs), 0, None), result, report)
    return report


def test_observed_values_and_throws_are_kept() -> None:
    result = RunResult("ok", (Observation("value", 3), Observation("throws", None, "TypeError")))
    report = decide_with(result, [[1, 2], [None, 1]])
    assert [k.outcome for k in report.kept] == ["value", "throws"] and report.dropped == []
    assert report.passed is None and "Tests passed: not run" in report.text()


@pytest.mark.parametrize("status", ["timeout", "memory", "crash", "bad_output"])
def test_a_failed_run_drops_everything_and_never_passes(status: str) -> None:
    report = decide_with(RunResult(status), [[1, 2], [3, 4]])
    assert report.kept == [] and len(report.dropped) == 2


def test_no_runner_result_is_a_failure() -> None:
    assert decide_with(None, [[1, 2]]).kept == []


def test_unusable_outcomes_are_dropped_with_a_reason() -> None:
    result = RunResult(
        "ok", tuple(Observation(o) for o in ("async", "unserializable", "nondeterministic"))
    )
    report = decide_with(result, [[1, 1], [2, 2], [3, 3]])
    assert report.kept == [] and [w for _, w in report.dropped] == [
        "the function is asynchronous",
        "the result cannot be stored as JSON",
        "two identical calls gave different results",
    ]


def test_no_inputs_is_reported() -> None:
    assert decide_with(RunResult("ok"), []).dropped[0][1] == "the model proposed no usable inputs"


def test_a_test_that_would_hold_a_secret_is_dropped() -> None:
    secret = "AKIA" + "IOSFODNN7EXAMPLE"
    report = decide_with(RunResult("ok", (Observation("value", secret),)), [[1, 2]])
    assert report.kept == [] and "secret" in report.dropped[0][1]


def test_a_bad_error_name_is_dropped() -> None:
    report = decide_with(RunResult("ok", (Observation("throws", None, "a b;c"),)), [[1, 2]])
    assert report.kept == []


def test_the_generated_test_asserts_only_what_was_observed_and_is_stamped() -> None:
    kept = [
        Kept(target(), [1, 2], "value", 3),
        Kept(target(), ["</script>", " "], "throws", None, "TypeError"),
    ]
    text = render_test("lib/x.js", kept, "Snapshot abc */ evil")
    assert "Snapshot abc * / evil" in text.splitlines()[0]
    assert "assert.deepStrictEqual(m.add(1, 2), 3);" in text
    assert 'assert.throws(() => m.add("</script>", "\\u2028"), { name: "TypeError" });' in text
    assert "require(require('node:path').join(__dirname, '..', \"lib/x.js\"))" in text
    assert text.count("\n// ") == 0 and " " not in text


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_generated_test_is_valid_javascript(tmp_path: Path) -> None:
    kept = [Kept(target(), [1, 2], "value", 3)]
    f = tmp_path / "t.test.js"
    f.write_text(render_test("lib/x.js", kept, "stamp"), encoding="utf-8")
    assert subprocess.run(["node", "--check", str(f)], capture_output=True).returncode == 0


def test_fake_runner_records_jobs_and_fails_closed_on_unknown_calls() -> None:
    runner = FakeRunner({("a.js", "f"): RunResult("ok", (Observation("value", 1),))})
    assert runner.run(RunJob("a.js", "f", ([1],))).status == "ok"
    assert runner.run(RunJob("b.js", "g", ([1],))).status == "crash" and len(runner.jobs) == 2


# --- the Docker runner's own logic, with a stand-in for the docker command -------------------

FAKE_DOCKER = """#!/usr/bin/env python3
import json, os, sys, time
if sys.argv[1] == "kill":
    open(os.environ["FAKE_LOG"], "a").write("kill " + sys.argv[2] + "\\n")
    sys.exit(0)
job = json.loads(sys.stdin.read())
fn = job["function"]
if fn == "ok":
    print(json.dumps({"observations": [{"outcome": "value", "value": 1}] * len(job["inputs"])}))
elif fn == "oom":
    sys.exit(137)
elif fn == "crash":
    sys.exit(1)
elif fn == "hang":
    time.sleep(60)
elif fn == "flood":
    sys.stdout.write("x" * 400000)
elif fn == "junk":
    print("not json")
"""


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Path]:
    script = tmp_path / "docker"
    script.write_text(FAKE_DOCKER, encoding="utf-8")
    script.chmod(0o755)
    log = tmp_path / "log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    return str(script), log


@pytest.mark.parametrize(
    ("fn", "status"),
    [("ok", "ok"), ("oom", "memory"), ("crash", "crash"), ("hang", "timeout"),
     ("flood", "bad_output"), ("junk", "bad_output")],
)  # fmt: skip
def test_docker_runner_maps_every_end_to_a_status(
    fake: tuple[str, Path], tmp_path: Path, fn: str, status: str
) -> None:
    from services.sandbox.docker import DockerRunner

    runner = DockerRunner(tmp_path, image=IMAGE, timeout_s=2, docker=fake[0])
    result = runner.run(RunJob("m.js", fn, ([1],)))
    assert result.status == status
    assert (result.status == "ok") == bool(result.observations)
    killed = fake[1].exists() and "kill sb-" in fake[1].read_text()
    assert killed == (fn in ("hang", "flood"))  # killed by name on the deadline or an overflow


def test_docker_runner_never_runs_a_command_that_assert_safe_refuses(tmp_path: Path) -> None:
    from services.sandbox.docker import DockerRunner

    with pytest.raises(ValueError):
        DockerRunner(tmp_path, image="node:22").run(RunJob("m.js", "f", ([1],)))
    with pytest.raises(ValueError):
        DockerRunner(Path("/a,b"), image=IMAGE).run(RunJob("m.js", "f", ([1],)))


def test_docker_runner_without_docker_is_a_failure_not_a_crash(tmp_path: Path) -> None:
    from services.sandbox.docker import DockerRunner

    runner = DockerRunner(tmp_path, image=IMAGE, docker="/nonexistent/docker")
    assert runner.run(RunJob("m.js", "f", ([1],))).status == "crash"
