# Source ingest

FR-1, SEC-1.1, SEC-1.3 to SEC-1.7. Code: `services/ingest/`. Build-plan step 6.

## What it does
A GitHub URL (optional branch, tag or commit) or a local directory becomes a **pinned revision** and a **read-only copy** in the snapshot store (`SNAPSHOT_DIR`, default `.snapshots/`, git-ignored). Every later read uses the copy, so a cited line number cannot move.

| Source | Revision | Copy |
|---|---|---|
| GitHub URL | 40-character commit SHA | one shallow fetch, checked out, `.git` removed |
| Local path | SHA-256 of every analysed file's path and content, uncommitted changes included | files copied, never linked |

Run it by hand (prints counts and finding kinds, never a matched value):

```bash
uv run python -m services.ingest fixtures/legacy-app
uv run python -m services.ingest https://github.com/OWNER/REPO --ref main
```

`store_snapshot(session, pinned)` records the snapshot, its files and one audit row per finding. Ingesting the same revision twice writes nothing the second time.

## What is enforced
| Rule | How | Test file |
|---|---|---|
| SEC-1.4 limits (500 MB, 20000 files, depth 30) | numbers read from `rules_constants.yaml`; the whole source is rejected, nothing is stored | `test_ingest_tree.py`, `test_ingest_pin.py` |
| SEC-1.4 nothing outside the root | any symlink resolving outside is rejected, including one named `node_modules`; symlinks inside are skipped, never followed | `test_ingest_tree.py` |
| Hostile files | files open with `O_NOFOLLOW` and must be regular, so a FIFO is skipped and a file swapped for one is refused; non-UTF-8 file names are skipped | `test_ingest_tree.py`, `test_ingest_scan.py` |
| SEC-1.1 source unchanged | the source is only read; `verify()` re-hashes it and the copy, and reports a change instead of following it (SEC-1.6) | `test_ingest_pin.py` |
| SEC-1.7 token | only in the git process environment, never on a command line; scrubbed from every error | `test_ingest_git.py` |
| GitHub input only | `https://github.com/<owner>/<repo>`; refs that could act as git options are rejected; hooks, credential helpers, submodules and other protocols are off | `test_ingest_git.py` |
| SEC-1.3 findings | findings hold path, line and kind, never the value; `redact()` masks values | `test_ingest_scan.py` |

## What it does not do
- **The scan is regex only.** It finds keys, tokens, credentials in assignments, e-mails, phone and card numbers, and fields named like phone or address. Personal names and free-text addresses outside such a field are **not** found; the reviewer must catch them. Binary files and files over 10 MiB are listed as unscanned, never skipped silently.
- The fixture's hard-coded token (trap 29) is caught by the generic "name says token, value is long" rule, not by a pattern written for it.
- A GitHub fetch downloads one shallow revision before the limits are checked, so a huge repository costs the download before it is rejected.
- The private-repository token path is tested for header handling only. It has not been run against a real private repository.

## Choices to confirm
1. `node_modules` is excluded like `.git` (recorded in `excluded`), so a working copy with installed dependencies does not hit the 20000-file limit. Dependencies are for the two-stage fetch later (amendment A2).
2. "500 MB" is read as 500 MiB.
3. Two implementation bounds are not in the rules and live in code as proposed constants: the 10 MiB scan size and the 600 s git timeout.
4. The staging image does not include `rules_constants.yaml`. Ingest runs on the laptop, not on Render, so this is fine until something on Render needs it.
