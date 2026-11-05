"""The dependency and interface inventory (FR-2). Not claims: facts read straight from the tree
and from package.json, listed so a reviewer can see the shape of the app before any claim."""

import json
from collections import Counter
from dataclasses import dataclass, field

from services.evidence import SnapshotReader, Unresolved
from services.verifier.flags import detect_flags

LANGUAGES = {
    ".js": "JavaScript",
    ".cjs": "JavaScript",
    ".mjs": "JavaScript",
    ".ts": "TypeScript",
    ".json": "JSON",
    ".sql": "SQL",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".md": "Markdown",
}
SOURCE_SUFFIXES = (".js", ".cjs", ".mjs", ".ts")


@dataclass(frozen=True)
class Inventory:
    languages: dict[str, int]  # language -> file count
    generated: tuple[str, ...]
    vendored: tuple[str, ...]
    first_party_sources: tuple[str, ...]
    main: str | None  # package.json "main"
    scripts: dict[str, str]  # package.json "scripts"
    declared: dict[str, str]  # package.json "dependencies"
    declared_dev: dict[str, str]  # package.json "devDependencies"
    notes: tuple[str, ...] = field(default_factory=tuple)  # what could not be read, stated


def _suffix(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name[name.rfind(".") :] if "." in name else ""


def _string_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items()}


def build_inventory(reader: SnapshotReader, paths: list[str]) -> Inventory:
    languages: Counter[str] = Counter()
    generated: list[str] = []
    vendored: list[str] = []
    first_party: list[str] = []
    notes: list[str] = []
    for path in sorted(paths):
        suffix = _suffix(path)
        languages[LANGUAGES.get(suffix, "other")] += 1
        flags = detect_flags(path, reader)
        if flags.generated:
            generated.append(path)
        if flags.vendored:
            vendored.append(path)
        if suffix in SOURCE_SUFFIXES and not (flags.generated or flags.vendored):
            first_party.append(path)
    manifest: dict[str, object] = {}
    if "package.json" in paths:
        try:
            loaded = json.loads("\n".join(reader.lines("package.json")))
            manifest = loaded if isinstance(loaded, dict) else {}
        except (Unresolved, ValueError) as error:
            notes.append(f"package.json not read: {type(error).__name__}")
    main = manifest.get("main")
    return Inventory(
        dict(sorted(languages.items())),
        tuple(generated),
        tuple(vendored),
        tuple(first_party),
        main if isinstance(main, str) else None,
        _string_map(manifest.get("scripts")),
        _string_map(manifest.get("dependencies")),
        _string_map(manifest.get("devDependencies")),
        tuple(notes),
    )
