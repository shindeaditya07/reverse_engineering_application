#!/usr/bin/env python3
"""Resolve every anchor in answer-key.yaml to a line number and fail if the key has drifted.

Usage: python3 fixtures/answer-key/check_key.py [--print]
Checks: file exists, anchor occurs exactly once, min_lines holds, every fixture file is either in
`modules`, `not_app_code`, or a known non-code file, and all 33 traps T01..T33 are present.
"""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
APP = ROOT.parent / "legacy-app"
KEY = yaml.safe_load((ROOT / "answer-key.yaml").read_text(encoding="utf-8"))
errors: list[str] = []
resolved: list[tuple[str, str, int]] = []


def resolve(item_id: str, file: str, anchor: str) -> None:
    path = APP / file
    if not path.is_file():
        errors.append(f"{item_id}: missing file {file}")
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    hits = [i + 1 for i, line in enumerate(lines) if anchor in line]
    if len(hits) != 1:
        errors.append(f"{item_id}: anchor {anchor!r} matches {len(hits)} lines in {file}")
        return
    resolved.append((item_id, file, hits[0]))


def walk(section: str) -> None:
    for item in KEY.get(section, []):
        if "anchor" in item:
            resolve(item.get("id") or item.get("name", section), item["file"], item["anchor"])
        for extra in item.get("also", []):
            resolve(f"{item['id']}+", extra["file"], extra["anchor"])
        if "min_lines" in item:
            n = len((APP / item["file"]).read_text(encoding="utf-8").splitlines())
            if n < item["min_lines"]:
                errors.append(
                    f"{item['id']}: {item['file']} has {n} lines, expected >= {item['min_lines']}"
                )


for sec in (
    "entry_points",
    "integrations",
    "call_edges_confirmed",
    "call_edges_inferred",
    "business_rules",
    "traps",
):
    walk(sec)
for r in KEY["schema"]["routines"]:
    resolve(r["name"], r["file"], r["anchor"])

known_files = {m["file"] for m in KEY["modules"]} | {m["file"] for m in KEY["not_app_code"]}
non_code = {
    "package.json",
    "config/default.json",
    "schema.sql",
    "README.old.md",
    "Gruntfile.js",
    "docs/TICKET-4821.txt",
    "lib/mailer.dev.js",
    "lib/mailer.prod.js",
}
for f in sorted(p.relative_to(APP).as_posix() for p in APP.rglob("*") if p.is_file()):
    if f not in known_files | non_code:
        errors.append(f"file not listed in the key: {f}")
for m in known_files:
    if not (APP / m).is_file():
        errors.append(f"key lists a file that does not exist: {m}")

trap_ids = {t["id"] for t in KEY["traps"]}
want = {f"T{i:02d}" for i in range(1, 34)}
if trap_ids != want:
    missing, extra = sorted(want - trap_ids), sorted(trap_ids - want)
    errors.append(f"trap ids differ: missing {missing}, extra {extra}")

if "--print" in sys.argv:
    for item_id, file, line in resolved:
        print(f"{item_id:8} {file}:{line}")
if errors:
    print("\n".join(errors))
    sys.exit(1)
print(f"answer key OK: {len(resolved)} anchors resolved, {len(trap_ids)} traps")
