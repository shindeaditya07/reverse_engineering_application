# Verifier

`services/verifier/` decides which claims may stand. It is deterministic code (VER-1.1): it
reads a claim and a pinned snapshot and returns a `Verdict`. It never calls a model, never
reaches the network, and nothing in it can promote a claim. Errors are blocks (VER-1.3).

## Checks

| ID | Check | Rule | If it fails |
|---|---|---|---|
| V-1 | A Confirmed or Inferred claim cites at least one reference. Unknown needs none. | EVD-1.1 | demoted to Unknown |
| V-2 | Every reference parses and resolves to bytes in the snapshot | EVD-1.2 | demoted to Unknown |
| V-3 | The stored excerpt hash still matches. A missing hash fails too. | EVD-1.3 | marked stale, status kept |
| V-4 | No file range over 40 lines (also for a located object whose span is longer) | EVD-1.4 | blocked, status kept |
| V-5 | Status is one of three and matches how it was produced | CLM-1.1 to 1.3 | demoted to Unknown |
| V-6 | No Confirmed claim produced by a model alone | CLM-1.2 | demoted to Unknown |
| V-7 | No cited file is generated or vendored unless the claim is about it | EVD-1.6 | blocked, status kept |
| V-8 | A document sentence cites claims that exist, passed, and are not Unknown | CLM-1.6 | sentence rejected |
| V-9 | No secret or personal data in the claim, its explanation or its excerpts | SEC-1.3, 1.5 | blocked, status kept |
| V-10 | Explanation overlaps the cited code (heuristic, below) | VER-1.6, VER-1.7 | demoted to Unknown |

**The demote-or-block split is my proposal.** Rules say V-1, V-2 and V-10 lead to Unknown
(EVD-1.1, CLM-1.4, VER-1.7) and that a stale claim returns to the queue (EVD-1.3). For the rest
I chose: a status that is wrong or impossible (V-5, V-6) becomes Unknown, and a claim that is
true but badly cited or unsafe to show (V-4, V-7, V-9) is blocked with its status unchanged.
Either way every failure puts the claim in the review queue with reason `verifier_failure`.

`Verdict.final_status` is never above the input status. `Verdict.queue_reason` is
`verifier_failure`, `stale`, `unknown`, `inferred` or none, matching `review_items.reason`.
`result_rows` gives one `verification_results` row per check.

## Rules about the checks themselves

- **V-5 pairings.** Confirmed needs `deterministic` or `test`. Inferred may come from `model`,
  `deterministic` or `human`, not `test`. Unknown may come from anyone. A human cannot make a
  claim Confirmed.
- **CLM-1.8 is not checked here.** That a test's assertion names the same input and output as
  the claim needs the test runner and the reviewer; a Confirmed-by-test claim is only checked
  for status and evidence.
- **V-7 uses a heuristic.** A path segment such as `vendor`, `node_modules`, `generated`, or a
  header in the first 15 lines saying generated, `@generated`, `do not edit` or `vendored`. A
  flag recorded in `snapshot_files` also counts. A generated file with an ordinary path and no
  marker is not caught. The claim names what it is about in `subject_paths`.
- **V-9 uses the ingest scanner**, so it finds only what that regex scanner finds (keys,
  tokens, credentials in assignments, e-mail, phone, card, SSN, fields named like personal
  data). Names and free-text addresses are not found. A redaction marker `[REDACTED:kind]` is
  ignored; anything else, including a fake marker around a value, is scanned. The failure
  detail names kinds and places, never the value.
- **V-8 checks the link, not the wording.** It proves a sentence points at a good claim. It
  does not prove the sentence says what the claim says. A model could attach the wrong claim ID
  to a sentence and V-8 would accept it. Closing that needs a sentence-to-claim comparison I
  have not built.

## V-10 is a heuristic (VER-1.7)

It takes the content words of the explanation (camelCase and snake_case split, a crude plural
strip, small stop-word list) and asks what share appear in the cited excerpts or their paths.
Below the floor, `v10_demote_overlap_below: 0.1`, the claim becomes
Unknown. It runs only when a claim has an explanation and at least one resolved reference, and
it can only demote. A Confirmed claim never depends on it.

It cannot tell a false explanation that reuses the code's words from a true one, and it
penalises a true explanation written in other words. Both are known limits, reported below.

## Measured quality (VER-1.4)

`make eval-smoke` runs both corpora in `services/evals/corpus.py` and prints these rates:

- **Good corpus, 50 claims:** the 42 facts of the reviewed fixture answer key plus 8
  hand-written ones, all with real references and stored hashes. A Confirmed fact is a
  deterministic claim; an Inferred fact is a model claim whose explanation is the fact's own
  statement, a stand-in until real model explanations exist.
- **Bad corpus, 50 claims:** each a good claim broken in one named way, between 5 and 7 per
  check (V-1 to V-7, V-9, V-10). V-8 has its own five rejected sentences.

Result at the time of writing:

- Seeded bad claims caught: 50 of 50, 95% interval 93% to 100%. The test requires the
  `VER-1.4` constant (100%).
- V-10 on its own: 7 of 7 caught, interval 65% to 100%.
- Good claims falsely blocked: 0 of 50 (0%, interval 0% to 7%). V-10 demotions of Inferred
  claims that carry an explanation: 0 of 7 (interval 0% to 35%).

**The floor was changed after seeing these numbers.** At 0.5 it demoted 5 of those 7 good
claims. The first real model run (2026-11-11, expressCart slice, qwen2.5-coder:7b) then
demoted all 4 of its Inferred claims that carried an explanation, and all 4 were true on
reading the source (scores 0.29, 0.40, 0.40, 0.43). The 7 seeded bad explanations score 0.00;
the 7 good ones score 0.14 to 0.75. The floor is now 0.1 (VER-1.7, rules v1.3), which sits
between those groups. That is a choice made with the data in view, from 11 true claims, so do
not read the 0% above as measured accuracy. The seeded bad explanations are all off-topic.
V-10 still cannot catch a wrong explanation that reuses the code's words, at any floor. At 0.1
it also lets through a short off-topic sentence that shares one common word with the code:
"Customers get a refund email." scores 0.25 because `get` appears in `app.get`. No floor fixes
that without demoting at least 3 of the 11 true claims (a floor of 0.3 would). A test pins this.
Re-measure when there are more real explanations.

## Coverage gate (VER-1.5)

`make test` writes `coverage.json` with branch coverage and then runs
`scripts/check_verifier_coverage.py`, which fails if branches covered in `services/verifier/`
fall below `min_verifier_branch_coverage_percent`. It counts branches only, the stricter
reading.
