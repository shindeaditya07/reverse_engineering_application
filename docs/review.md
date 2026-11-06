# Review CLI

`python -m services.review <command>`. A reviewer works through claims one at a time. Nothing is
accepted by the platform itself (REV-1.1). Reads the database at `DATABASE_URL` and the pinned
copies under `SNAPSHOT_DIR`. Set `REVIEWER` or pass `--reviewer`.

| Command | What it does |
|---|---|
| `queue [--run ID] [--view queue\|undecided\|decided\|all] [--limit N]` | Latest versions. `queue` is REV-2.1 (open review items). `undecided` also lists Confirmed claims, which are never queued. |
| `show ID` | Text, status, producer, failed checks and the cited code. An excerpt is shown only if it resolves and matches no secret pattern. |
| `accept ID...` | One decision per ID. Reason optional. |
| `reject ID... --reason R` | Reason required. |
| `edit ID --text T --reason R [--cite PATH:START-END ...]` | New version, see below. |
| `history [ID]` | Decisions, newest first; with an ID, every version of that claim. |
| `export RUN [--out FILE]` | Markdown of accepted claims. |

IDs are claim-version IDs. A unique prefix of 8 or more characters works.

## Rules this tool enforces

- **Latest version only.** An older version is history and cannot be decided.
- **Unknown cannot be accepted** (CLM-1.4). Edit it with evidence, or reject it.
- **Accept re-verifies** the stored claim against the pinned snapshot (V-1 to V-10) and refuses on any failure or if the cited bytes changed. Claims whose text was withheld (V-9) are never accepted.
- **Edit stores a new version**: producer `review:<name>`, kind `human`, status Inferred (a person's wording is never Confirmed, CLM-1.2). It keeps the old evidence unless `--cite` replaces it. It is verified again (REV-1.3). A failed check stores it Unknown and queued. The edit is not an accept; the new version needs its own.
- **Decisions are append-only** (REV-1.2). A reviewer may decide again; the latest decision on the latest version counts, and every earlier one stays in `history`.
- **A reason or edited text that matches a secret pattern is refused** (SEC-1.3), not stored.
- **Audit entries** (`review.accept|edit|reject`) hold IDs and flags, never text.
- **Batch:** `accept A B C` is three separate decisions; a refusal on one does not undo the others.

## Export (OUT-1.2)

Header: snapshot revision, run ID, date, and `Accepted: N of M claims` with rejected, edited and undecided counts, so the list is never read as the whole picture. Only claims whose latest version was accepted appear. Reviewer names are not exported.

## Not built

REV-3 coverage and accuracy reports and random sampling (REV-3.3), a UI, diagrams. Reasons are optional on accept; REV-1.2 says "reason" but does not say a non-empty one is required for accept.
