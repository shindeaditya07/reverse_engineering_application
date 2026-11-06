# Discovery agent

`services/discovery/` is FR-2: deterministic, no model, no parser. `python -m services.discovery [--out evals/results]` runs it on the fixture, verifies every finding and scores it against the reviewed key ([evals.md](evals.md)).

## What it produces

**Inventory** (not claims): languages by file count, generated and vendored files, first-party sources, and from `package.json` the `main`, `scripts` and declared dependencies. It is shown to the reviewer before any claim.

**Findings** (claims, each cites lines or bytes that resolve in the snapshot):

| Kind | Finding | Status |
|---|---|---|
| `dependency` | a `require` of a package `package.json` does not declare | Inferred |
| `job` | `setInterval`, `cron.schedule` | Inferred |
| `integration` | `http(s).request/get`, `axios.*`, `fetch`, `net.connect` | Inferred |
| `provenance` | generated or vendored, by folder or header (cites the matched header line) | Inferred |
| `encoding` | file is not UTF-8 (exact byte range) | Confirmed |
| `encoding` | file uses CRLF (first lines with CR, at most 40) | Confirmed |

Only the two read straight from bytes are Confirmed. A line pattern is a heuristic, so it is Inferred (CLM-1.2, CLM-1.3).

## What it does not do

- **A `require` with a computed path.** Discovery used to report it as Inferred; it is now Code Analysis's, as an Unknown claim ([codeanalysis.md](codeanalysis.md)), so a reviewer sees one item for it, not two.
- **Routes, call graphs, data flow, config and SQL** are Code Analysis (FR-3) and the Data agent. A route in a loop or behind a condition needs a parser, which is why the grep baseline cannot find them either.
- **Meaning.** The two key facts it misses, T03-F2 (the default payment provider) and T24-F2 (no time of day is set), need a default read in context.
- **Generated and vendored files are never scanned for findings** (EVD-1.6). They get one provenance claim each.
- **Storing** goes through the claim writer: `services/discovery/store.py` verifies each finding and stores it ([claims.md](claims.md)). The worker queues it as the `discovery` job ([worker.md](worker.md)).

## Reading the score

- Recall and precision are over the five kinds it looks for (10 key facts: the 11th, T03-F1, is the computed `require`, which Code Analysis owns), so every interval is very wide. The first recorded run, `discovery-v1`, still reports 9/11 because it predates that change; `discovery-v2` is the current one.
- **The patterns were written after the fixture was read**, so the score is optimistic. It shows the approach can find these things, not how it does on another app. The pilot is the real test.
- A first run scored 73%: the generated-file claim cited line 1, and the marker is on line 2. A claim must cite the line that carries its evidence, so it was fixed to cite the matched header line. That is a citation bug, not tuning of a pattern.
- Patterns are fingerprinted (`patterns_sha256`) and a test fails if they change without a re-run committed under `evals/results/`.
