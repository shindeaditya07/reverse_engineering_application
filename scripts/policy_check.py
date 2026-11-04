"""Keep docs/policies.md, policy_constants.yaml and .policy_lock in step (AGENTS.md section 1).

Checks:
  1. Every constant in the YAML is named, in backticks, in the passage it is keyed to.
  2. No constant is named in a passage it is not keyed to.
  3. The "Notes for the Development Team" list matches the YAML (name, value, policy ID).
  4. The policy version in the header equals ``policy_version`` in the YAML.
  5. The SHA-256 of policies.md (line endings normalised to LF) equals the lock file, and the
     lock's version equals the header version. A changed file with an unchanged version is the
     error this check exists to catch.

Usage:
  python -m scripts.policy_check          check, exit 1 on any problem
  python -m scripts.policy_check --lock   rewrite .policy_lock (do this only after a version bump)
"""

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]

_VERSION = re.compile(r"Policy version \*\*(\d+\.\d+)")
_PASSAGE = re.compile(r"^\*\*([A-Z]{3}-\d+\.\d+) [^\n]*\*\*\s*$", re.MULTILINE)
_NOTE = re.compile(r"^\s*-\s*`([a-z_]+) = ([0-9.]+)`\s*\(([A-Z]{3}-\d+\.\d+)\)\s*$", re.MULTILINE)
_NOTES_HEADING = "## Notes for the Development Team"


def normalised_text(path: Path) -> str:
    """Read a file with CRLF/CR folded to LF so a Windows checkout hashes the same."""
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def sha256_of(path: Path) -> str:
    """SHA-256 of the file's LF-normalised text."""
    return hashlib.sha256(normalised_text(path).encode("utf-8")).hexdigest()


def header_version(text: str) -> str | None:
    """The policy version declared in the file header, or None."""
    match = _VERSION.search(text)
    return match.group(1) if match else None


def passages(text: str) -> dict[str, str]:
    """Map each policy ID to its passage text (up to the next passage or ## heading)."""
    body = text.split(_NOTES_HEADING)[0]
    marks = list(_PASSAGE.finditer(body))
    out: dict[str, str] = {}
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        chunk = body[mark.end() : end]
        out[mark.group(1)] = chunk.split("\n## ")[0].split("\n---")[0]
    return out


def notes(text: str) -> dict[str, tuple[float, str]]:
    """Constants listed in the developer notes: name -> (value, policy ID)."""
    if _NOTES_HEADING not in text:
        return {}
    section = text.split(_NOTES_HEADING)[1]
    return {m.group(1): (float(m.group(2)), m.group(3)) for m in _NOTE.finditer(section)}


def load_constants(path: Path) -> tuple[str, dict[str, tuple[float, str]]]:
    """Return (policy_version, {constant: (value, policy ID)}) from the YAML."""
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    version = str(data.pop("policy_version"))
    constants: dict[str, tuple[float, str]] = {}
    for policy_id, block in data.items():
        for name, value in block.items():
            constants[name] = (float(value), policy_id)
    return version, constants


def check(root: Path = ROOT) -> list[str]:
    """Run every check and return the problems found (empty means all good)."""
    policies = root / "docs" / "policies.md"
    text = normalised_text(policies)
    errors: list[str] = []
    yaml_version, constants = load_constants(root / "policy_constants.yaml")
    version = header_version(text)
    if version is None:
        errors.append("policies.md has no 'Policy version **X.Y' header")
    elif version != yaml_version:
        errors.append(f"policy_version {yaml_version} in the YAML != {version} in policies.md")

    by_id = passages(text)
    for name, (_, policy_id) in constants.items():
        if policy_id not in by_id:
            errors.append(f"{name}: keyed to {policy_id}, which is not a passage in policies.md")
        elif f"`{name}`" not in by_id[policy_id]:
            errors.append(f"{name}: not named in {policy_id}")
    for policy_id, passage in by_id.items():
        for name, (_, owner) in constants.items():
            if f"`{name}`" in passage and owner != policy_id:
                errors.append(f"{name}: named in {policy_id} but keyed to {owner}")

    listed = notes(text)
    for name, (value, policy_id) in constants.items():
        if name not in listed:
            errors.append(f"{name}: missing from the developer notes list")
        elif listed[name] != (value, policy_id):
            errors.append(f"{name}: notes say {listed[name]}, YAML says {(value, policy_id)}")
    for name in listed.keys() - constants.keys():
        errors.append(f"{name}: in the developer notes but not in policy_constants.yaml")

    lock_path = root / ".policy_lock"
    if not lock_path.is_file():
        errors.append(".policy_lock is missing (run: python -m scripts.policy_check --lock)")
    else:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        if sha256_of(policies) != lock["sha256"]:
            if version == lock["version"]:
                errors.append(f"policies.md changed but the version is still {version}: bump it")
            else:
                errors.append(f"version is {version}, lock is {lock['version']}: rerun with --lock")
        elif version != lock["version"]:
            errors.append(f"lock version {lock['version']} != policies.md version {version}")
    return errors


def write_lock(root: Path = ROOT) -> None:
    """Record the current version and hash. Run only after a deliberate version bump."""
    policies = root / "docs" / "policies.md"
    version = header_version(normalised_text(policies))
    lock = {"version": version, "sha256": sha256_of(policies)}
    (root / ".policy_lock").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    """CLI entry point."""
    if "--lock" in argv:
        write_lock()
        print("wrote .policy_lock")
        return 0
    errors = check()
    if errors:
        print("\n".join(errors))
        return 1
    print("policy check OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
