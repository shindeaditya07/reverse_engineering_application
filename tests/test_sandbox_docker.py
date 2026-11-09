"""The Docker runner against a real container, with a hostile snapshot (TST-1.2, TST-1.3).

Each probe is a function in a module that does something a sandbox must stop. The runner is
called directly, so these hold even if the testability check were bypassed. Skipped when Docker
or the pinned image is missing, unless REQUIRE_DOCKER=1 (the Sandbox Safety CI job), where
absence is a failure.
"""

import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from services.sandbox.docker import DockerRunner
from services.sandbox.runner import Observation, RunJob, RunResult
from services.sandbox.spec import DEFAULT_IMAGE

REQUIRE = os.environ.get("REQUIRE_DOCKER") == "1"


def _docker_ready() -> str | None:
    """None when usable, else the reason it is not."""
    try:
        info = subprocess.run(["docker", "info"], capture_output=True, timeout=30)
        if info.returncode != 0:
            return "the Docker daemon is not running"
        have = subprocess.run(
            ["docker", "image", "inspect", DEFAULT_IMAGE], capture_output=True, timeout=30
        )
        return None if have.returncode == 0 else f"{DEFAULT_IMAGE} is not pulled"
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"docker is unavailable ({type(error).__name__})"


_REASON = _docker_ready()
if _REASON and REQUIRE:
    pytest.fail(f"REQUIRE_DOCKER=1 but {_REASON}", pytrace=False)
pytestmark = pytest.mark.skipif(_REASON is not None, reason=_REASON or "")

HOSTILE = r"""
const fs = require('fs');
const cp = require('child_process');
const status = () => fs.readFileSync('/proc/self/status', 'utf8');
module.exports = {
  ident: () => ({ uid: process.getuid(), gid: process.getgid() }),
  env: () => Object.keys(process.env).sort(),
  secret: () => process.env.SANDBOX_CANARY || null,
  caps: () => /CapEff:\s*(\w+)/.exec(status())[1],
  nonewprivs: () => /NoNewPrivs:\s*(\d)/.exec(status())[1],
  net: () => cp.spawnSync(process.execPath, ['-e',
    "const s=require('net').connect(53,'1.1.1.1');s.on('connect',()=>process.exit(0));" +
    "s.on('error',()=>process.exit(1));setTimeout(()=>process.exit(2),4000)"]).status,
  loopback: () => cp.spawnSync(process.execPath, ['-e',
    "const s=require('net').connect(5432,'127.0.0.1');s.on('connect',()=>process.exit(0));" +
    "s.on('error',()=>process.exit(1));setTimeout(()=>process.exit(2),4000)"]).status,
  writeApp: () => { try { fs.writeFileSync('/app/pwn', 'x'); return 'wrote'; } catch (e) { return e.code; } },
  writeRoot: () => { try { fs.writeFileSync('/pwn', 'x'); return 'wrote'; } catch (e) { return e.code; } },
  writeHarness: () => { try { fs.appendFileSync('/harness/run.js', '//'); return 'wrote'; } catch (e) { return e.code; } },
  execTmp: () => {
    fs.writeFileSync('/tmp/x.sh', '#!/bin/sh\necho hi\n', { mode: 0o755 });
    const r = cp.spawnSync('/tmp/x.sh');
    return r.error ? r.error.code : r.status;
  },
  sock: () => fs.existsSync('/var/run/docker.sock') || fs.existsSync('/run/docker.sock'),
  mounts: () => fs.readFileSync('/proc/self/mountinfo', 'utf8').split('\n')
    .map((l) => l.split(' ')[4]).filter((p) => p && !p.startsWith('/proc') && !p.startsWith('/sys') && !p.startsWith('/dev')).sort(),
  forks: () => { let n = 0; const kids = [];
    for (let i = 0; i < 1000; i++) { const c = cp.spawn('sleep', ['20']); if (!c.pid) break; kids.push(c); n++; }
    kids.forEach((c) => c.kill()); return n; },
  hog: () => { const keep = []; for (let i = 0; i < 40; i++) { keep.push(Buffer.alloc(100 * 1024 * 1024, 1)); } return keep.length; },
  spin: () => { while (true) {} },
  flood: () => 'x'.repeat(400000),
  noisy: () => { console.log('NOISE'); return 7; },
};
"""


@pytest.fixture(scope="module")
def runner(tmp_path_factory: pytest.TempPathFactory) -> DockerRunner:
    snap = tmp_path_factory.mktemp("hostile")
    (snap / "m.js").write_text(HOSTILE, encoding="utf-8")
    snap.chmod(0o755)
    (snap / "m.js").chmod(0o644)
    return DockerRunner(snap, timeout_s=20)


def call(runner: DockerRunner, fn: str) -> RunResult:
    return runner.run(RunJob("m.js", fn, ([],)))


def value(runner: DockerRunner, fn: str) -> Any:
    result = call(runner, fn)
    assert result.status == "ok", (fn, result.status)
    assert result.observations[0].outcome == "value", (fn, result.observations)
    return result.observations[0].value


def test_the_harness_works_in_a_real_container(runner: DockerRunner) -> None:
    assert value(runner, "noisy") == 7  # legacy console.log did not break the reply


def test_runs_as_nobody_with_no_capabilities_and_no_new_privileges(runner: DockerRunner) -> None:
    assert value(runner, "ident") == {"uid": 65534, "gid": 65534}
    assert int(str(value(runner, "caps")), 16) == 0
    assert value(runner, "nonewprivs") == "1"


def test_no_environment_leaks_in(runner: DockerRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANDBOX_CANARY", "host-secret")
    assert value(runner, "secret") is None
    names = set(value(runner, "env"))
    assert not names & {
        "SANDBOX_CANARY",
        "DATABASE_URL",
        "GITHUB_TOKEN",
        "HTTPS_PROXY",
        "HTTP_PROXY",
    }


def test_no_network_not_even_loopback_to_the_host(runner: DockerRunner) -> None:
    assert value(runner, "net") == 1  # connect failed fast; 0 would be connected, 2 a hang
    assert value(runner, "loopback") == 1


def test_the_snapshot_the_harness_and_the_root_are_read_only(runner: DockerRunner) -> None:
    assert value(runner, "writeApp") == "EROFS"
    assert value(runner, "writeRoot") == "EROFS"
    assert value(runner, "writeHarness") in ("EROFS", "EACCES")  # a file we own as root


def test_scratch_space_cannot_execute_files(runner: DockerRunner) -> None:
    assert value(runner, "execTmp") == "EACCES"


def test_the_docker_socket_is_absent_and_only_expected_mounts_exist(runner: DockerRunner) -> None:
    assert value(runner, "sock") is False
    assert set(value(runner, "mounts")) <= {
        "/",
        "/app",
        "/harness/run.js",
        "/tmp",
        "/etc/hosts",
        "/etc/hostname",
        "/etc/resolv.conf",
    }


def test_a_fork_bomb_is_capped_by_the_process_limit(runner: DockerRunner) -> None:
    result = call(runner, "forks")
    assert result.status in ("ok", "crash", "timeout")
    if result.status == "ok":
        assert result.observations[0].value < 300


def test_a_memory_hog_is_killed_and_reported_as_a_failure(runner: DockerRunner) -> None:
    result = call(runner, "hog")  # asks for 4 GB against a 2 GB limit
    assert result.status == "memory" and result.observations == ()


def test_an_endless_loop_is_killed_at_the_deadline_and_leaves_no_container(
    tmp_path: Path, runner: DockerRunner
) -> None:
    quick = DockerRunner(Path(runner._snapshot), timeout_s=4)
    start = time.monotonic()
    result = call(quick, "spin")
    assert result.status == "timeout" and time.monotonic() - start < 30
    left = subprocess.run(
        ["docker", "ps", "-aq", "--filter", "name=sb-"], capture_output=True, text=True
    )
    assert left.stdout.strip() == ""


def test_oversized_output_is_a_failure(runner: DockerRunner) -> None:
    assert call(runner, "flood").status == "bad_output"


def test_a_path_outside_the_snapshot_is_refused(runner: DockerRunner) -> None:
    result = runner.run(RunJob("../harness/run.js", "x", ([],)))
    assert result.status == "bad_output" and result.observations == ()


def test_the_real_observations_have_the_expected_shape(runner: DockerRunner) -> None:
    assert call(runner, "ident").observations == (
        Observation("value", {"uid": 65534, "gid": 65534}),
    )
