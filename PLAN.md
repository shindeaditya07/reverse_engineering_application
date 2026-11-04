# How ReplyDesk was built, and the plan for this project

Source: `shindeaditya07/triage_automation_ecommerce`, read from its git history (188 commits, 99
merged PRs, 2026-10-18 to 2026-10-31). Everything in section 1 is from the commit log and the
files; nothing is from memory. Where I infer a reason, it is marked [Likely].

## 1. What ReplyDesk did, in order

| Day | What landed | Artifacts |
|---|---|---|
| 10-18 | `first commit`: the README alone (a full product description, written before any code) | README.md |
| 10-19 | One docs commit: the foundation | spec.md, policies.md, AGENTS.md, build-plan.md, branching-and-environments.md (+ a stale duplicate, replydesk-agent-guide.md) |
| 10-19 | **Phase 1, 6 PRs in one day**: repo scaffold, staging pipeline, data contract + policy constants + SHA lock, DB schema (first Alembic migration), mock store with 31 edge cases, eval harness (78 labeled tickets, 40 bad drafts) | Makefile, compose, CI, `policy_constants.yaml`, `.policy_lock`, `docs/data-contract.md`, `evals/` |
| 10-20 | Keyword baseline classifier, then **Phase 2 and the start of Phase 3, ~20 PRs**: health endpoints, owner auth, job runner, intake, LLM client, classification, pre/post-lookup escalation, order lookup, policy retrieval, embeddings, drafting, grounding validator G-1..G-10, LLM judge, retry/fallback, owner-edit validation | ADRs 0001-0003 (concurrency, job runner, LLM provider), docs/intake.md, pipeline.md, grounding.md, retrieval.md, auth.md |
| 10-22 | Phase 3 wired into the pipeline; **Phase 4**: ticket API, review actions, mock send, generated API types, queue and ticket screens, audit log, metrics | docs/ticket-api.md, frontend-api.md, metrics.md, evals.md, runbook.md |
| 10-22/23 | **Phase 5**: security headers and accessibility, end-to-end test of all 31 edge cases, README rewrite, runbook, **live eval** against a real model | docs/security-headers-and-a11y.md; first `evals/results/` run |
| 10-23 | The first live eval report **had to be corrected**: the fallback template had been counted as a model draft (1.000 vs the true 0.810) | `CORRECTION.md` beside the report |
| 10-25/26 | Second live eval, ADR-0003 amended to record the provider actually used, license, synthetic check, release workflows, **v1.0.0 on staging only** | README results table, release workflow |
| 10-26/27 | Hold-out set, unlabeled spot-check review, then fixes found by it (sign-off glue, hazard/injury escalation, plain dates, order-store 429 retry) | `evals/review.py`, prompt v4 |
| 10-28 to 10-31 | **Scope kept growing after v1.0.0**: owner reply, retrieval check with real embeddings, retention sweep, customer erasure, public contact page, bulk CSV upload, auto-approve, UI refresh | 200-complaint test set with answer key |

### Patterns worth copying

1. **README first, then one docs commit, then code.** The docs were the contract the code was
   built against (each PR cites a spec section).
2. **Eval harness before the model.** Phase 1 shipped labeled data and a bad-draft corpus before
   any LLM call existed.
3. **Small PRs, one deliverable each, merged in dependency order** (`feature/p<N>-<name>`),
   about 6 to 20 a day.
4. **Behaviour docs written next to the code** (`pipeline.md`, `grounding.md`, `intake.md`), with
   12 edits to pipeline.md as steps were added.
5. **Honest measurement:** live evals recorded in README, a published correction when wrong, and
   an unlabeled hold-out review to check the labeled set was not just memorised.
6. **ADRs amended in place** with the real outcome.

### Where it deviated or slipped (verified)

- `make resilience` is still a stub that prints "not yet implemented", though the spec's Definition
  of Done requires it.
- Non-prod environment was dropped and there is no production deployment; the docs described five
  environments.
- The spec cites `spec-amendments.md`, which is not in the repo. The stale duplicate
  `replydesk-agent-guide.md` still sits next to AGENTS.md.
- ADR-0003's planned provider split (Anthropic drafts, OpenAI judges) was not what ran; the
  measured run used one provider for both.
- On 10-30 a commit titled "approve and send a confident, clean reply without the owner"
  appeared, against invariant 1 ("nothing is sent without owner approval"). I have not read the
  code, so I can't say whether the invariant or the feature was adjusted. [Guessing] The invariant
  was relaxed without an amendment. Worth you checking, because it is the exact failure this
  project's "human approves every output" rule must not repeat.

## 2. The equivalent plan for this project

Same order, translated. Day counts are Replydesk's pace, which was agent-assisted; treat them as a
lower bound, not a promise. [Guessing] Expect 2 to 3x for this project because the parsing and
sandbox work has no Replydesk equivalent.

| Step | ReplyDesk analogue | Here | Output |
|---|---|---|---|
| 0 | README first commit | Replace the repo's one-line README with ours | README.md |
| 1 | The one docs commit | Commit the 15 base docs in `base-docs/` after your review | spec, policies, AGENTS, tech-stack, build-plan, branching, ADR 0000-0005, policy_constants.yaml |
| 2 | Phase 1 (6 PRs, day 1) | scaffold + CI, policy-check + SHA lock, claim-store migration, snapshot ingest, evidence resolver, verifier V-1..V-10, **fixture Node.js app + answer key**, eval harness | Everything needed to score output before any agent runs |
| 3 | Phase 2 (deterministic half) | job runner, Discovery, JavaScript adapter, call graph, Data agent, code metrics | Facts, scored against the fixture answer key |
| 4 | Phase 3 (model layer) | ModelGateway, rule candidates, rule explainer, judge, retry/fallback, review-queue backend | Needs ADR-0004 accepted |
| 5 | Phase 4 (outputs + UI) | diagrams, doc writer, review UI, exports, metrics dashboard | Every artifact in spec §15 on the fixture |
| 6 | Phase 5 (hardening, live eval, release) | sandbox, characterization tests, modernizer, pilot run, accuracy sampling, time-saved measurement | spec §22 Definition of Done |
| 7 | Hold-out review | Run on a second, unseen Node app and sample claims by hand | Checks the fixture was not memorised |

### Adjustments from what went wrong

1. **Write `make resilience`'s equivalent (sandbox escape test, snapshot-unchanged test) in
   Phase 1, not Phase 5.** The safety tests are the product here.
2. **Commit every document the spec references**, and keep exactly one rules file.
3. **Put the human-approval invariant under the same amendment process as everything else.** No
   feature may relax REV-5.1 without a numbered spec amendment.
4. **Freeze scope at the Definition of Done.** Ten features landed after v1.0.0 in Replydesk; here,
   anything after the pilot run goes to a v2 list.
5. **Evaluator tests first**, so there is no corrected report.
6. **Decide ADR-0004 (model hosting) and the pilot app before Phase 3.** Replydesk's open items
   were also deferred, and its ADR-0003 then did not match what shipped.

### Repo state

`reverse_engineering_application` currently holds one commit with a README that is a single
heading, saved in UTF-16 (it will show as garbled text in some tools). Proposed first push: a
branch `docs/base-docs` containing the 15 files, opened as a PR into the default branch, so you
review the docs as a diff, as Replydesk reviewed each PR.
