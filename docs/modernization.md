# Modernization agent (FR-11, OUT-1.3 to 1.5)

Status: built for Phase 3 item 7. No model is called.

`python -m services.modernization RUN_ID --out DIR` writes `modernization.md` and
`modernization.map.json` (proposal or boundary id -> claim keys). Every page is stamped with the
snapshot, run ID and date (OUT-1.2) and opens with "PROPOSAL, not a finding".

## What it reads
**Accepted Confirmed and Inferred claims only** (OUT-1.5). Unknown, undecided, rejected and
edited-away claims are never a basis and their text never appears. Their keys, grouped by kind,
are listed under **Unknown dependencies**, so the reader sees what the plan does not cover.
The page states how many claims in the run are accepted.

## What it proposes
- **Candidate boundaries.** Accepted route claims under `/api/<name>` define a boundary. A table
  belongs to it when the names match (plural ignored), and a file when its first name part matches
  or it registers the route. This is a guess from names and is labelled as one. Tables no boundary
  matches are listed apart.
- **A phased tech-debt map.** Each accepted claim of a known kind becomes one proposal with fixed
  wording and the claim quoted word for word as evidence: behaviour to keep and test (rules,
  validation), personal data, file encoding, undeclared dependencies (phase 1); swallowed errors,
  dead code, unused columns (2); foreign keys, column write ownership, outbound calls, scheduled
  work, and writes that cross a boundary (3); callback and promise chains, generated or vendored
  code (4). Phases order the work. They do not measure risk, and no severity is given.
- **Unknown dependencies**, as above.

## Guard rails
- A proposal cannot be built without a claim (`Item` raises). Risks cite claims (OUT-1.3).
- `check()` re-reads the finished page and fails on: an evidence line that is not an accepted claim
  verbatim, a proposal with no evidence, text of a claim that is not accepted, or fixed wording that
  promises safety (safe, guarantee, risk-free, seamless, zero downtime, ...) (OUT-1.4). The CLI
  runs it before writing anything.
- The only sentence containing "safe" is the disclaimer, in a negation.

## Not done, on purpose
- **No model.** The spec allows a model to propose from claims. Not built, for the reason given for
  the Documentation agent: V-10 is too coarse to check free prose, and the rule-based proposals can
  be checked line by line. A model could later reword or add proposals, with each still citing
  claims and passing `check()`.
- **No target technology.** The page says where boundaries and clean-ups could go, not which
  framework to adopt; nothing in the claims supports that choice.
- **No estimate of effort, cost or duration.**
- **Name-based boundaries are weak.** A route group such as `/api/debug` or `/api/reports` becomes a
  boundary though it owns no table. They are shown as they come out.
- On a fresh run nothing is accepted, so the plan is empty until a reviewer has decided.
