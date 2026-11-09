"""The Docker runner: the only place legacy code is executed, and only inside the sandbox.

One container per job, built by `docker_command` and re-checked by `assert_safe`. The job goes in
on stdin. stdout is read up to a cap; stderr is discarded, so nothing the legacy code prints is
ever stored (SEC-1.3, NFR-6). The wall-clock limit is enforced here: on expiry the container is
killed by name (TST-1.3). Anything but a clean, well-formed reply is a failure status, never a pass.
"""

import json
import subprocess
import threading
import uuid
from pathlib import Path

from services.sandbox.runner import MAX_OUTPUT_BYTES, RunJob, RunResult, parse_output
from services.sandbox.spec import DEFAULT_IMAGE, docker_command, limits

HARNESS_FILE = Path(__file__).resolve().parent / "harness.js"
_SIGKILL_EXIT = 137  # killed from outside the process: the memory limit, as we did not kill it


class DockerRunner:
    def __init__(
        self,
        snapshot_dir: Path,
        *,
        image: str = DEFAULT_IMAGE,
        timeout_s: float | None = None,
        docker: str = "docker",
    ) -> None:
        self._snapshot = str(Path(snapshot_dir).resolve())
        self._image = image
        self._timeout = float(timeout_s if timeout_s is not None else limits()["timeout_seconds"])
        self._docker = docker

    def run(self, job: RunJob) -> RunResult:
        name = f"sb-{uuid.uuid4().hex[:16]}"
        argv = docker_command(
            image=self._image,
            snapshot_dir=self._snapshot,
            harness_file=str(HARNESS_FILE),
            name=name,
        )
        argv[0] = self._docker
        payload = json.dumps(
            {"module": job.module, "function": job.function, "inputs": list(job.inputs)}
        )
        try:
            proc = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
        except OSError:
            return RunResult("crash")
        chunks: list[bytes] = []
        overflow = threading.Event()

        def drain() -> None:
            assert proc.stdout is not None
            size = 0
            while block := proc.stdout.read(65536):
                size += len(block)
                if overflow.is_set():
                    continue  # keep reading and discarding, or the client blocks on a full pipe
                if size > MAX_OUTPUT_BYTES:
                    overflow.set()
                    chunks.clear()
                    self._kill(name)
                    continue
                chunks.append(block)

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        try:
            assert proc.stdin is not None
            proc.stdin.write(payload.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass  # the container may already be gone; the exit status decides
        try:
            code = proc.wait(timeout=self._timeout)
        except subprocess.TimeoutExpired:
            self._kill(name)
            self._reap(proc)
            reader.join(5)
            return RunResult("timeout")
        reader.join(5)
        if overflow.is_set():
            self._reap(proc)
            return RunResult("bad_output")
        if code == _SIGKILL_EXIT:
            return RunResult("memory")
        if code != 0:
            return RunResult("crash")
        return parse_output(b"".join(chunks).decode("utf-8", "replace"), len(job.inputs))

    @staticmethod
    def _reap(proc: "subprocess.Popen[bytes]") -> None:
        """Stop the docker client too: it can outlive its container. Never wait without a bound."""
        proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass  # a zombie client holds nothing: the container is already gone

    def _kill(self, name: str) -> None:
        subprocess.run(
            [self._docker, "kill", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
