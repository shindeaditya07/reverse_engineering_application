"""The sandbox command (TST-1.2, TST-1.3) and the check that guards it.

The container gets no network, a read-only root, no capabilities, no new privileges, an
unprivileged user, 2 CPUs, 2048 MB with no swap, a process cap, a small scratch tmpfs that cannot
execute, the pinned snapshot mounted read-only, and our own harness mounted read-only. It gets no
environment variables, no host mounts besides those two, and no credentials. The 300 s wall-clock
limit is enforced by the caller, which kills the container by name (part 6b).

`assert_safe` re-reads a finished command and refuses anything that loosens this. It runs inside
`docker_command`, so a bug in building the command cannot reach a container.

Not from rules_constants.yaml (mine, flagged): the process cap and the tmpfs size.
"""

from collections.abc import Sequence

from services.rules_constants import rule_constants

PIDS_LIMIT = 256
TMPFS = "/tmp:rw,noexec,nosuid,nodev,size=64m"
NOBODY = "65534:65534"
APP = "/app"
HARNESS = "/harness/run.js"

# Flags that would loosen the sandbox. Any of them anywhere in the command is refused.
FORBIDDEN = (
    "--privileged", "--cap-add", "--device", "--pid", "--ipc", "--uts", "--userns", "--net",
    "--security-opt=seccomp=unconfined", "--security-opt=apparmor=unconfined", "-v", "--volume",
    "-e", "--env", "--env-file", "-p", "--publish", "-P", "--add-host", "--dns", "--link",
    "--volumes-from", "--mount-propagation",
)  # fmt: skip


def limits() -> dict[str, int]:
    c = rule_constants("TST-1.3")
    return {
        "cpus": int(c["sandbox_cpus"]),
        "memory_mb": int(c["sandbox_memory_mb"]),
        "timeout_seconds": int(c["sandbox_timeout_seconds"]),
    }


def _mount(src: str, dst: str) -> str:
    if any(ch in src for ch in ",=\n\r\0") or not src.startswith("/"):
        raise ValueError("mount source must be an absolute path without , = or control characters")
    return f"type=bind,source={src},target={dst},readonly"


def docker_command(*, image: str, snapshot_dir: str, harness_file: str, name: str) -> list[str]:
    """The `docker run` argv. The job goes in on stdin, so it is never on the command line."""
    if "@sha256:" not in image or image.startswith("-"):
        raise ValueError("the sandbox image must be pinned by digest (name@sha256:...)")
    if not name.replace("-", "").replace("_", "").isalnum():
        raise ValueError("container name must be alphanumeric, - or _")
    lim = limits()
    argv = [
        "docker", "run", "--rm", "-i", "--name", name,
        "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--cpus", str(lim["cpus"]),
        "--memory", f"{lim['memory_mb']}m", "--memory-swap", f"{lim['memory_mb']}m",
        "--pids-limit", str(PIDS_LIMIT),
        "--user", NOBODY,
        "--tmpfs", TMPFS,
        "--mount", _mount(snapshot_dir, APP),
        "--mount", _mount(harness_file, HARNESS),
        "--workdir", APP,
        image, "node", HARNESS,
    ]  # fmt: skip
    assert_safe(argv)
    return argv


def assert_safe(argv: Sequence[str]) -> None:
    """Raise ValueError unless `argv` keeps every sandbox restriction."""
    lim = limits()
    problems = []
    for token in argv:
        head = token.split("=", 1)[0]
        if token in FORBIDDEN or head in FORBIDDEN:
            problems.append(f"forbidden flag {token}")
        if "docker.sock" in token:
            problems.append("the Docker socket must never be mounted")

    def value(flag: str) -> str | None:
        return argv[argv.index(flag) + 1] if flag in argv[:-1] else None

    expected = {
        "--network": "none", "--cap-drop": "ALL", "--security-opt": "no-new-privileges",
        "--cpus": str(lim["cpus"]), "--memory": f"{lim['memory_mb']}m",
        "--memory-swap": f"{lim['memory_mb']}m", "--user": NOBODY,
    }  # fmt: skip
    for flag, want in expected.items():
        if value(flag) != want:
            problems.append(f"{flag} must be {want}")
    for flag in ("--read-only", "--rm"):
        if flag not in argv:
            problems.append(f"{flag} is required")
    pids = value("--pids-limit")
    if pids is None or not pids.isdigit() or int(pids) > PIDS_LIMIT:
        problems.append(f"--pids-limit must be at most {PIDS_LIMIT}")
    tmpfs = [argv[i + 1] for i, t in enumerate(argv[:-1]) if t == "--tmpfs"]
    if not tmpfs or any("noexec" not in t for t in tmpfs):
        problems.append("every tmpfs must be noexec")
    mounts = [argv[i + 1] for i, t in enumerate(argv[:-1]) if t == "--mount"]
    if len(mounts) != 2 or any(not m.endswith(",readonly") or "type=bind" not in m for m in mounts):
        problems.append(
            "exactly two read-only bind mounts are allowed: the snapshot and the harness"
        )
    image = next((t for t in argv if "@sha256:" in t), None)
    if image is None:
        problems.append("the image must be pinned by digest")
    if problems:
        raise ValueError("; ".join(problems))
