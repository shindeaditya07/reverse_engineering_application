"""GitHub source: URL and ref validation, token handling, and a real fetch from a local repo."""

import base64
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from services.ingest.errors import IngestError
from services.ingest.gitfetch import fetch_revision, git_env, validate_github_url, validate_ref
from services.ingest.limits import MIB, Limits
from services.ingest.pin import _pin_git, pin_github, verify

LIMITS = Limits(max_bytes=10 * MIB, max_files=1000, max_depth=30)
TOKEN = "tok_s3cr3t_value_1234567890"
IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@example.com"]


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *IDENTITY, *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def make_repo(root: Path, files: dict[str, bytes]) -> tuple[Path, str]:
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root, git(root, "rev-parse", "HEAD")


def pin_from(repo: Path, store: Path, ref: str | None = None, token: str | None = None) -> Any:
    return _pin_git(repo.as_uri(), "origin-label", ref, store, LIMITS, token, "file")


@pytest.mark.parametrize(
    ("url", "canonical"),
    [
        ("https://github.com/octo/repo", "https://github.com/octo/repo.git"),
        ("https://github.com/octo/repo.git", "https://github.com/octo/repo.git"),
        ("https://github.com/octo/repo/", "https://github.com/octo/repo.git"),
        ("  https://github.com/Octo-Cat/my.repo_1  ", "https://github.com/Octo-Cat/my.repo_1.git"),
    ],
)
def test_accepts_github_urls(url: str, canonical: str) -> None:
    assert validate_github_url(url) == canonical


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/octo/repo",
        "git@github.com:octo/repo.git",
        "ssh://git@github.com/octo/repo",
        "git://github.com/octo/repo",
        "file:///etc",
        "/local/path",
        "https://gitlab.com/octo/repo",
        "https://github.com.evil.example/octo/repo",
        "https://user:pass@github.com/octo/repo",
        "https://github.com:8443/octo/repo",
        "https://github.com/octo/repo?x=1",
        "https://github.com/octo/repo#frag",
        "https://github.com/octo/repo/tree/main",
        "https://github.com/octo",
        "https://github.com/octo/..",
        "https://github.com/-octo/repo",
        "https://github.com/octo/re po",
        "",
    ],
)
def test_rejects_other_urls(url: str) -> None:
    with pytest.raises(IngestError) as caught:
        validate_github_url(url)
    assert caught.value.code == "bad_url"


@pytest.mark.parametrize("ref", ["main", "v1.2.3", "feature/x-y_z", "a" * 40, "release/2026.11"])
def test_accepts_refs(ref: str) -> None:
    assert validate_ref(ref) == ref


def test_no_ref_means_head() -> None:
    assert validate_ref(None) == "HEAD"


@pytest.mark.parametrize(
    "ref",
    [
        "--upload-pack=evil",
        "-x",
        "",
        "a..b",
        "a b",
        "a//b",
        "main/",
        "x.lock",
        "a;rm",
        "$(id)",
        "a" * 201,
    ],
)
def test_rejects_refs_that_could_act_as_options_or_paths(ref: str) -> None:
    with pytest.raises(IngestError) as caught:
        validate_ref(ref)
    assert caught.value.code == "bad_ref"


def test_token_goes_in_the_environment_never_on_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs["env"]))
        return subprocess.CompletedProcess(args, 0, stdout="a" * 40 + "\n", stderr="")

    monkeypatch.setattr("services.ingest.gitfetch.subprocess.run", fake_run)
    sha = fetch_revision("https://github.com/o/r.git", "main", tmp_path / "d", token=TOKEN)
    assert sha == "a" * 40
    basic = base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()
    for args, env in calls:
        assert TOKEN not in " ".join(args)
        assert basic not in " ".join(args)
        assert basic in " ".join(env.values())
        assert TOKEN not in " ".join(env.values())


def test_git_environment_is_locked_down() -> None:
    env = git_env(None, "https")
    assert env["GIT_ALLOW_PROTOCOL"] == "https"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    config = {
        env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
        for i in range(int(env["GIT_CONFIG_COUNT"]))
    }
    assert config == {"core.hooksPath": "/dev/null", "credential.helper": ""}


def test_failed_fetch_never_leaks_the_token(tmp_path: Path) -> None:
    with pytest.raises(IngestError) as caught:
        pin_from(tmp_path / "does-not-exist", tmp_path / "store", token=TOKEN)
    message = str(caught.value)
    assert caught.value.code == "git_failed"
    assert TOKEN not in message
    assert base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode() not in message
    assert list((tmp_path / "store").iterdir()) == []


def test_timeout_and_missing_git_become_ingest_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired("git", 1)

    monkeypatch.setattr("services.ingest.gitfetch.subprocess.run", timeout)
    with pytest.raises(IngestError) as caught:
        fetch_revision("https://github.com/o/r.git", "main", tmp_path / "a")
    assert caught.value.code == "git_timeout"

    def missing(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError

    monkeypatch.setattr("services.ingest.gitfetch.subprocess.run", missing)
    with pytest.raises(IngestError) as caught:
        fetch_revision("https://github.com/o/r.git", "main", tmp_path / "b")
    assert caught.value.code == "git_missing"


def test_bad_output_from_git_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout="not-a-sha\n", stderr="")

    monkeypatch.setattr("services.ingest.gitfetch.subprocess.run", fake_run)
    with pytest.raises(IngestError) as caught:
        fetch_revision("https://github.com/o/r.git", "main", tmp_path / "d")
    assert caught.value.code == "git_failed"


def test_pin_github_rejects_a_bad_url_before_touching_the_network(tmp_path: Path) -> None:
    with pytest.raises(IngestError) as caught:
        pin_github("https://evil.example/o/r", tmp_path / "store")
    assert caught.value.code == "bad_url"
    assert not (tmp_path / "store").exists()


def test_pins_a_commit_from_a_repository(tmp_path: Path) -> None:
    repo, sha = make_repo(tmp_path / "origin", {"app.js": b"one\n", "lib/b.js": b"two\n"})
    pinned = pin_from(repo, tmp_path / "store")
    assert pinned.kind == "github"
    assert pinned.revision == sha
    assert pinned.root == (tmp_path / "store").resolve() / sha
    assert [f.path for f in pinned.tree.files] == ["app.js", "lib/b.js"]
    assert not (pinned.root / ".git").exists()
    assert verify(pinned, LIMITS).pinned_copy_intact is True
    assert verify(pinned, LIMITS).source_unchanged is None


def test_pins_the_requested_branch_tag_and_sha(tmp_path: Path) -> None:
    repo, first = make_repo(tmp_path / "origin", {"app.js": b"one\n"})
    git(repo, "tag", "v1")
    (repo / "app.js").write_bytes(b"two\n")
    git(repo, "commit", "-q", "-am", "second")
    second = git(repo, "rev-parse", "HEAD")
    store = tmp_path / "store"
    assert pin_from(repo, store).revision == second
    assert pin_from(repo, store, "v1").revision == first
    assert pin_from(repo, store, "main").revision == second
    by_sha = pin_from(repo, store, first)
    assert by_sha.revision == first
    assert by_sha.requested_ref == first
    assert (by_sha.root / "app.js").read_bytes() == b"one\n"


def test_unknown_ref_is_a_clean_error(tmp_path: Path) -> None:
    repo, _ = make_repo(tmp_path / "origin", {"a": b"x"})
    with pytest.raises(IngestError) as caught:
        pin_from(repo, tmp_path / "store", "no-such-branch")
    assert caught.value.code == "git_failed"
    assert list((tmp_path / "store").iterdir()) == []


def test_repo_with_an_escaping_symlink_is_rejected_and_cleaned_up(tmp_path: Path) -> None:
    repo, _ = make_repo(tmp_path / "origin", {"ok.js": b"x"})
    (repo / "evil").symlink_to("/etc/passwd")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "evil")
    with pytest.raises(IngestError) as caught:
        pin_from(repo, tmp_path / "store")
    assert caught.value.code == "path_escape"
    assert list((tmp_path / "store").iterdir()) == []


def test_repo_limits_are_enforced_after_checkout(tmp_path: Path) -> None:
    repo, _ = make_repo(tmp_path / "origin", {"a": b"x", "b": b"x", "c": b"x"})
    tight = Limits(MIB, max_files=2, max_depth=30)
    with pytest.raises(IngestError) as caught:
        _pin_git(repo.as_uri(), "o", None, tmp_path / "store", tight, None, "file")
    assert caught.value.code == "too_many_files"
    assert list((tmp_path / "store").iterdir()) == []


def test_https_only_by_default_blocks_a_file_remote(tmp_path: Path) -> None:
    repo, _ = make_repo(tmp_path / "origin", {"a": b"x"})
    with pytest.raises(IngestError) as caught:
        _pin_git(repo.as_uri(), "o", None, tmp_path / "store", LIMITS, None, "https")
    assert caught.value.code == "git_failed"


def test_repository_hooks_and_filters_do_not_run(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    repo, _ = make_repo(
        tmp_path / "origin",
        {".gitattributes": b"* filter=evil\n", "a.js": b"x"},
    )
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / "post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    git(repo, "config", "filter.evil.smudge", f"touch {marker}; cat")
    pinned = pin_from(repo, tmp_path / "store")
    assert not marker.exists()
    assert "a.js" in [f.path for f in pinned.tree.files]


def test_cleanup_never_changes_permissions_through_a_symlink(tmp_path: Path) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("outside the source")
    victim.chmod(0o600)
    repo, _ = make_repo(tmp_path / "origin", {"ok.js": b"x"})
    (repo / "evil").symlink_to(victim)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "evil")
    with pytest.raises(IngestError):
        pin_from(repo, tmp_path / "store")
    assert stat.S_IMODE(victim.stat().st_mode) == 0o600


def test_symlinks_inside_a_repository_are_skipped_and_do_not_break_pinning(tmp_path: Path) -> None:
    repo, _ = make_repo(tmp_path / "origin", {"real.js": b"x"})
    (repo / "alias.js").symlink_to("real.js")
    (repo / "dangling").symlink_to("missing")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "links")
    pinned = pin_from(repo, tmp_path / "store")
    assert [f.path for f in pinned.tree.files] == ["real.js"]
    assert {s.path for s in pinned.tree.skipped} == {"alias.js", "dangling"}
    assert stat.S_IMODE((pinned.root / "real.js").stat().st_mode) == 0o444
    assert verify(pinned, LIMITS).pinned_copy_intact is True
