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
| `sample RUN [--draw] [--size N] [--seed S] [--below-minimum]` | Draws the accuracy sample once (with `--draw`), or shows its progress and the undecided IDs. |
| `report RUN [--out FILE]` | Coverage and accuracy report (REV-3). |

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

## Coverage and accuracy (REV-3)

`report` computes both from stored decisions. Nothing in it is typed in.

**Coverage (REV-3.1).** Modules = the first-party source files Discovery's inventory lists
(tests included, vendored and generated files not). Endpoints = the `route` claims. A module or
endpoint counts once an **accepted** claim cites it (an evidence range that overlaps the route's
lines, for an endpoint). The denominator is always printed. A module the parser could not read
stays in it, uncovered; its Unknown claim carries the reason.

**Accuracy (REV-3.2 to 3.4).**
- `sample RUN --draw` draws the sample once, at random, and records it with its seed in the audit log. A second draw for the same run is refused, so a bad draw cannot be re-rolled.
- Eligible: the latest version of a claim that is Confirmed or Inferred and has no decision yet. **Draw the sample before reviewing starts.** Every claim you decide first leaves the pool, and people decide the easy ones first.
- Unknown claims are not sampled. They say what is not known; counting a reject of one as an error would punish honesty.
- The default size is the rule's minimum (60). Fewer is refused unless `--below-minimum`, and the report then says so in bold and cannot call the target demonstrated.
- Accept = correct. Reject and edit = not correct (an edit means the claim needed changing).
- Verdict: **demonstrated** only if the Wilson 95% interval's lower bound reaches 90%. A passing point estimate with a lower bound below 90% is reported as not demonstrated and says why. Undecided sampled claims mean **no verdict**.
- The report also prints the pilot size limit (400) and flags a run that exceeds it (REV-3.5).

The fixture run has 52 eligible claims, so it cannot reach the minimum of 60. The report is built for a pilot slice of up to 400 claims.

## Not built

A UI, diagrams. Reasons are optional on accept; REV-1.2 says "reason" but does not say a non-empty one is required for accept.
