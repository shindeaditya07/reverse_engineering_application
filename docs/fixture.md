# Fixture app and answer key

Spec section 17 and build-plan step 9. The fixture is a small synthetic Node/Express order service (`fixtures/legacy-app/`, CommonJS only for v1) built to hold 35 traps, plus a hand-reviewed answer key (`fixtures/answer-key/key.yaml`) that lists the true facts for each trap. Analyzers are scored against the key before any model is involved.

**Status of the key: reviewed.** Claude drafted it; on 2026-11-05 Aditya said in the project thread that he is okay with all 42 facts, and every fact now carries `review: reviewed` with `reviewed_by` and `reviewed_on`. If a later look finds a wrong fact, set it back to `needs_review` and the drift check will say so.

## What is checked automatically
`make answer-key` (CI job `Fixture Answer Key`) runs `scripts/check_answer_key.py`. It checks that the key is well formed and still points at the right place in the fixture, so neither can drift on its own:

- traps 1 to 35 each appear once, with at least one fact;
- fact ids are unique and match their trap; status is Confirmed, Inferred or Unknown; Confirmed and Inferred facts cite evidence, Unknown may have none;
- every evidence item lies inside the fixture folder, is at most 40 lines (EVD-1.4, read from `rules_constants.yaml`), and its `snippet` starts the text of its first line;
- lines are counted after CRLF is normalised to LF (EVD-1.5, trap 32); a file that is not valid UTF-8 is cited by byte range (trap 31);
- `reviewed` needs `reviewed_by` and `reviewed_on`, and the top-level `review` cannot say `reviewed` while any fact is `needs_review`.

The same job runs `node --check` on every fixture JS file, so the fixture stays real code. Passing means the key is consistent, **not** that it is true or reviewed.

## What is not checked
Whether a statement is correct. Only the reviewer can say that. The 7 facts below are judgement calls that deserve extra attention:

- Facts marked **Inferred** (T03-F2, T04-F1, T10-F1, T13-F1, T18-F1, T24-F2) are claims of absence or of runtime behavior, which static evidence cannot prove.
- T18-F2 is **Unknown** on purpose: nothing in the repository sets the server time zone.

## Choices to confirm
- **CommonJS only** for the fixture (spec section 22, open item 3). ES modules are not covered; add a second small fixture later if the pilot app uses them.
- The key records **traps only**. A full inventory of routes, tables and columns (needed for precision and recall) is not in it yet and belongs with the eval harness.
- Special files are kept byte-exact by `.gitattributes` (`-text`): `lib/totals.js` (CRLF) and `lib/legacy_labels.js` (one Latin-1 byte).
- The hard-coded "secret" (trap 29) is the fake `fxlive_...` token. Its prefix and the sample data (trap 30) use `example.com`, `.invalid` hosts and 555-01xx numbers, so nothing real is present.

## How to review (Aditya)
Open `fixtures/answer-key/key.yaml` next to the file it cites. For each fact, check that the statement is true of the code at the cited lines, that the status is right, and that nothing important in the trap is missing. Then tell me which facts are reviewed (or all of them) and I set `review: reviewed`, `reviewed_by` and `reviewed_on`. A merged PR is not a review.

## Traps
| # | Trap | Facts | Where |
|---|---|---|---|
| 1 | route registered in a loop | 1 | `app.js` |
| 2 | route behind a conditional | 1 | `app.js` |
| 3 | dynamic require | 2 | `services/orders_service.js`, `config.js` |
| 4 | dead code that looks live | 1 | `lib/legacy_utils.js` |
| 5 | function named opposite to its behavior | 2 | `lib/legacy_utils.js`, `routes/orders.js` |
| 6 | comment that contradicts the code | 2 | `lib/legacy_utils.js`, `services/orders_service.js` |
| 7 | string-built SQL | 1 | `routes/orders.js` |
| 8 | parameterized SQL | 1 | `routes/orders.js` |
| 9 | ORM query plus raw query on one table | 2 | `models/product.js`, `lib/orm.js`, `routes/products.js` |
| 10 | column never read | 1 | `db/schema.sql` |
| 11 | column written by two paths | 1 | `routes/orders.js`, `jobs/nightly.js`, `db/schema.sql` |
| 12 | config key overridden by environment | 1 | `config.js` |
| 13 | config key never used | 1 | `config.js` |
| 14 | feature flag changing a rule | 1 | `services/pricing.js`, `config.js` |
| 15 | validation in middleware | 1 | `middleware/validate.js`, `routes/orders.js` |
| 16 | validation duplicated with different limits | 1 | `middleware/validate.js`, `routes/customers.js`, `db/schema.sql` |
| 17 | rounding rule | 1 | `services/pricing.js`, `config.js` |
| 18 | date or timezone rule | 2 | `services/pricing.js` |
| 19 | callback chain | 1 | `services/notify.js` |
| 20 | promise chain | 1 | `services/reports.js` |
| 21 | async/await | 1 | `services/orders_service.js` |
| 22 | error swallowed silently | 1 | `services/orders_service.js` |
| 23 | retry with backoff | 1 | `services/orders_service.js` |
| 24 | scheduled job | 2 | `app.js`, `lib/scheduler.js`, `jobs/nightly.js` |
| 25 | external HTTP call | 1 | `integrations/gateway.js` |
| 26 | message queue producer | 1 | `integrations/queue.js`, `services/orders_service.js` |
| 27 | generated code file | 1 | `generated/api_client.js` |
| 28 | vendored library | 1 | `vendor/tinyid.js` |
| 29 | hard-coded secret | 1 | `lib/credentials.js` |
| 30 | personal data in sample data | 1 | `data/sample_customers.json` |
| 31 | file with invalid encoding | 1 | `lib/legacy_labels.js` |
| 32 | CRLF line endings | 1 | `lib/totals.js` |
| 33 | prompt-injection comment | 2 | `lib/formatting.js` |
| 34 | undeclared dependency | 1 | `services/reports.js`, `package.json` |
| 35 | test documents behavior the code no longer has | 1 | `test/orders.test.js`, `services/pricing.js`, `config.js` |
