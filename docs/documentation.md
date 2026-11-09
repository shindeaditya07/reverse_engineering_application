# Documentation agent (FR-7, CLM-1.6, OUT-1.2)

Status: built for Phase 3 item 5. No model is called.

## How it works
`python -m services.documentation RUN_ID [--accepted-only] --out DIR` reads a run's claims from the
claim store and writes:

| File | Holds |
|---|---|
| `api-reference.md` | routes |
| `data-reference.md` | tables, relations, reads, writes, column write sources, unused columns, personal data |
| `business-rules.md` | rules and validation (model-drafted ones are Inferred) |
| `runbook.md` | outbound calls, scheduled work, dependencies, error handling, step order, unused code, generated or vendored code, file encoding |
| `glossary.md` | table names, each with its defining claim |
| `open-questions.md` | Unknown claims and claims waiting in the review queue |
| `index.md`, `map.json` | what is covered, and the claim keys behind each document |

Every bullet is `- **Status** <claim text> (claim `key`)`, with the text copied word for word.
The only other text is fixed wording that says how to read the page. A document with nothing in
it is not written. Kinds with no document yet are counted in `index.md`, never dropped.

## The CLM-1.6 check
`check()` re-reads each rendered document and fails on any bullet that is not a stored claim,
verbatim, with its stored status. `build()` runs it before anything is written, so a bug here
stops the run instead of producing an unbacked sentence.

## Choices
- **No connecting prose.** The spec allows a model to write connecting sentences that the verifier
  checks. Not built: V-10 is a token-overlap heuristic and demoted 4 of the true sentences in the
  business-rule audit, so a verified prose layer would mostly be rejected or would need a weaker
  check. Revisit once there are more claims.
- Unknown claims appear only under open questions.
- `--accepted-only` limits the documents to claims a human accepted. Open questions still lists
  Unknown and queued claims.
- Every document carries the snapshot, run ID, date and scope (OUT-1.2).
- The glossary holds table names only; other terms would need a claim that defines them.
