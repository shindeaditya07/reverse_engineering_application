# Grep baseline

`services/baseline/` is a one-line-at-a-time regex finder for routes, SQL and validation. It
is the bar the real analyzers must beat (spec section 19, item 2), so it is meant to be
poor. `python -m services.baseline [--out evals/results]` runs it on the fixture and scores it
against the reviewed answer key with the eval harness ([evals.md](evals.md)).

## What it looks for

| Kind | Pattern, in words |
|---|---|
| `route` | `app.`, `router.` or `server.` then get, post, put, patch, delete, head, options or all, then a string path starting with `/` |
| `sql_read` | `SELECT` and later `FROM` on one line |
| `sql_write` | `INSERT INTO`, `UPDATE <t> SET` or `DELETE FROM` |
| `validation` | `res.status(400)`, `res.status(422)`, `res.sendStatus(400 or 422)`, or `throw new <...Validation|Invalid...>(` |

Every claim is **Inferred**: a regex hit is a heuristic, not a parse. It reads `.js`, `.cjs`,
`.mjs` and `.ts` files, does not skip generated, vendored or test files, and states files it
cannot decode as not analysed (today `lib/legacy_labels.js`, trap 31) instead of failing.

## Recorded, not tuned

The patterns come from common Express and MySQL idioms and were written before the first
score. I had already read parts of the fixture while building it, so the baseline is not
blind to it; the guard is the process, not ignorance. `patterns_sha256` fingerprints the
patterns and is stored in the committed result under `evals/results/`. A test fails if the
patterns change without a new committed result, so any change is visible in review. A change
needs a stated reason that is not "the score was low".

## How to read the score

- **Headline recall counts every kind in the key**, and the baseline looks for four of the
  nineteen. The report therefore also gives recall on only the kinds it targets.
- **Precision is low by construction.** It makes one claim per matching line, so a block that
  holds several matching lines gives one hit and several unmatched claims, and a comment that
  says "select the best from the list" is a `sql_read`.
- **It cannot see** a route registered in a loop with a computed path, anything behind a
  condition, SQL built from parts, validation in a middleware, or anything about meaning. Those
  are the traps the real agents have to get.
- The key has 41 scorable facts, so every interval is wide. See [evals.md](evals.md).
