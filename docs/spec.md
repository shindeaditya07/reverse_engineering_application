# Spec: Legacy Reverse-Engineering Platform

Version 1.1 · 2026-11-04 · draft for review · merges amendments A1 to A14 (A3 open)
Sources: `business-case.md` v0.1, `rules.md` v1.1, `rules_constants.yaml` v1.1
Precedence when documents disagree: this spec, then `rules.md`, then `rules_constants.yaml`, then `AGENTS.md`, then `build-plan.md`. Conflicts are flagged with section numbers, never resolved silently. Rules are cited by ID; numbers are never restated here.

## 1. Overview
The platform ingests a frozen snapshot of a legacy application and produces evidence-linked documentation, diagrams, characterization tests and a modernization plan. The unit of output is the **claim**. A deterministic verifier checks every claim; a human reviews every output.

## 2. Problem and goal
As in `business-case.md` §2 and §3. Constraints C-1 to C-5 are implemented by rules EVD, CLM, SEC and REV. Success criteria SC-1 to SC-4 are implemented by REV-3.x, TST-1.x and §19 below.

## 3. Design decision: pipeline first, agents second
The brief names nine agents. This spec makes five of them **deterministic code** and uses a model only where language is the product.

| Agent | Kind | Uses a model? |
|---|---|---|
| 1 Discovery | deterministic | no |
| 2 Code Analysis | deterministic (tree-sitter parse, call graph, data flow) | no |
| 4 Data | deterministic (schema reader, ER, lineage from queries) | no |
| 8 Verification | deterministic (V-1 to V-10); model judge may only demote (VER-1.1) | optional judge |
| 5 Diagram | deterministic render from stored data (OUT-1.1) | no |
| 3 Business Rule | deterministic candidate finder + model explains | yes, output is Inferred (CLM-1.2) |
| 6 Documentation | assembles stored claims; model writes connecting prose that the verifier checks (CLM-1.6) | yes |
| 7 Test | model proposes, sandbox observes, only observed behavior is kept (TST-1.1) | yes |
| 9 Modernization | model proposes from claims, labeled as proposal (OUT-1.3) | yes |

**Why [Likely]:** "every claim verified" is only testable when the thing producing facts is not the thing judging them. ReplyDesk made the same call and it made its validator testable. **Challenge me if you disagree** (a fully LLM-driven agent loop is the alternative; its risk is unverifiable Confirmed claims).

## 4. Scope
In: Node.js/Express (CommonJS and ES modules) as the supported legacy stack for v1; SQL schema or dump input; config, build and deploy scripts; optional logs and tickets; one fixture app and one open-source pilot slice.
Out (v1): automatic code rewrite; mainframe or non-text sources; other languages; connecting to any live system (SEC-1.2); a hosted model for any analysis (SEC-2.1).

## 5. Users
- **Reviewer** (Aditya, 4 hours a week assumed): accepts, edits or rejects claims (REV-1.x). The pilot slice is sized to the review budget (REV-3.5).
- **Operator** (Aditya): ingests snapshots, starts runs, reads reports.
No other roles in v1. Single login, no public registration.

## 6. Core flow
Snapshot ingest → Discovery → Code Analysis and Data (parallel) → Business Rule → Diagram → Documentation → Test → Verification (gates every claim-producing step) → review queue → accepted bundle export → Modernization (reads accepted claims only) → export. Every step writes claims, a run record and an audit entry.

## 7. Functional requirements
- **FR-1 Ingest.** The operator gives **a GitHub repository URL (with optional branch, tag or commit) or a local directory path**, plus optional schema dump, logs, tickets. Uploading an archive is not the primary path. The platform resolves the input to a **pinned revision**: a commit SHA for a Git source, or a content hash of the working tree for a local path (including uncommitted changes). It reads from a read-only clone or read-only mount and keeps an internal pinned copy only so that line citations stay valid (see §16). It scans for secrets and personal data (SEC-1.1, 1.3, 1.4, 1.5, 1.7).
  - **Re-analysis:** the operator can point the same source at a newer revision; claims from the old revision are kept, and claims whose cited excerpt changed become stale (EVD-1.3) instead of being silently overwritten.
  - **GitHub access:** public repos by URL; private repos by a token that stays on the operator's machine and is never stored in the database or logs (SEC-1.7). Private-repo analysis runs locally only (SEC-3.1).
- **FR-2 Discovery.** Inventory languages, modules, entry points (HTTP routes, jobs, CLIs), dependencies, external integrations; classify generated and vendored files (EVD-1.6). Output: claims plus a dependency and interface inventory.
- **FR-3 Code analysis.** Parse into an AST, build call graph and data flow. Dynamic constructs it cannot resolve become Unknown claims (CLM-1.4), not omissions (CLM-1.7).
- **FR-4 Data model.** Reconstruct tables, relations, constraints from schema; derive lineage from queries in code; produce the ER data.
- **FR-5 Business rules.** Find validations and conditionals that enforce domain behavior; each rule is a claim with file and line evidence, status Inferred unless a test confirms it.
- **FR-6 Diagrams.** Architecture, sequence and workflow diagrams in Mermaid, generated from stored data (OUT-1.1).
- **FR-7 Documentation.** Technical docs, API and interface reference, glossary, runbook, open-questions list, assembled from claims (CLM-1.6, OUT-1.2).
- **FR-8 Characterization tests.** Generate tests, run them in the sandbox against the unmodified app, keep what is observed (TST-1.1 to 1.5). Two stages: fetch dependencies from the lockfile with install scripts disabled, then run offline (TST-1.6). A claim is Confirmed by test only under CLM-1.8.
- **FR-9 Verification.** Run V-1 to V-10 on every claim and document sentence; fail closed (VER-1.3).
- **FR-10 Review.** Queue, claim detail with source viewer, accept/edit/reject, audit log, coverage and accuracy reports (REV-1.x to REV-3.x).
- **FR-11 Modernization.** Target architecture, risk and tech-debt map, phased migration plan, all labeled proposals with cited claims, reading accepted claims only (OUT-1.3, OUT-1.4, OUT-1.5).
- **FR-12 Export.** A bundle of documents, diagrams and tests, each stamped (OUT-1.2). Nothing is ever written back to the legacy app (SEC-1.1).

## 8. Non-functional requirements
- **NFR-1 No bypass:** no path marks a claim accepted without a recorded human decision (REV-1.1).
- **NFR-2 Fail closed:** errors block, never pass (VER-1.3, TST-1.3).
- **NFR-3 Privacy:** private or local model only; staging holds fixture data only (SEC-2.1, SEC-3.1).
- **NFR-4 Reproducibility:** same snapshot and same pinned analyzer versions give the same deterministic claims.
- **NFR-5 Auditability:** append-only audit log and review decisions (REV-1.2).
- **NFR-6 Cost and time:** every model call is logged with tokens, latency and run ID.
- **NFR-7 Resilience:** API starts without the database and reports degraded; `/healthz` (liveness, no DB) and `/readyz` (DB and migrations); runs are DB-backed jobs with a startup sweeper and visible failed state.
- **NFR-8 Local-first:** everything runs from one `docker compose up` on a clean clone.

## 9. Stack
Python 3.12 with `uv`; FastAPI; Postgres with SQLAlchemy 2.0 and Alembic; tree-sitter for parsing; React and TypeScript for the review UI with API types generated from OpenAPI; Docker for the sandbox; a local model served through an OpenAI-compatible interface behind one client interface. No Java, no PHP, no Conda. Each non-obvious choice gets a short ADR in the PR that introduces it.

## 10. Data schemas (summary)
Tables: `snapshots`, `snapshot_files`, `claims`, `claim_versions`, `evidence`, `verification_results`, `review_items`, `review_decisions`, `artifacts`, `audit_log`, `jobs`, `model_calls`. Claim fields: id, text, status, kind, snapshot hash, run id, producer (agent and version), created time. Evidence fields per EVD-1.2 and 1.3. Decisions and audit rows are append-only. Full DDL in the DB-schema PR, not here.

## 11. Verification checks V-1 to V-10
| ID | Check | Rule |
|---|---|---|
| V-1 | claim has at least one evidence ref | EVD-1.1 |
| V-2 | every ref resolves in the snapshot | EVD-1.2 |
| V-3 | excerpt hash matches | EVD-1.3 |
| V-4 | file range within the line limit | EVD-1.4 |
| V-5 | status is one of three and matches how it was produced | CLM-1.1 to 1.3 |
| V-6 | no model-only Confirmed | CLM-1.2 |
| V-7 | no cited-file is generated or vendored unless the claim says so | EVD-1.6 |
| V-8 | document sentence maps to a claim | CLM-1.6 |
| V-9 | secrets and personal data absent from claim and excerpt | SEC-1.3, 1.5 |
| V-10 | explanation consistent with evidence: heuristic (token and symbol overlap), may only demote, never confirms | VER-1.6, VER-1.7 |

## 12. Safety invariants (never weaken)
No acceptance without a human decision. Errors are blocks. The verifier decides; a judge can only demote. Legacy text is data in delimited blocks, and the generating call has no tools. Legacy code is read-only. No hosted model for any code. One constants file.

## 13. Escalation to the review queue
Anything Unknown, Inferred, stale or failing a check lands in the queue (REV-2.1) with the reason and the check ID.

## 14. External input contract
`docs/input-contract.md` (written in its own PR) defines: accepted sources (GitHub URL with ref, local directory path; archive only as a fallback), repo layout accepted, schema dump dialects (SQL text only), log format, ticket export format. Anything outside it is rejected with a message, not guessed.

## 15. Security and prompt injection
Code comments and strings in the legacy app are untrusted and may contain instructions. They are quoted into delimited blocks, never concatenated into instructions (SEC-2.2). Adversarial fixture cases cover this (§17).

## 16. Time and text semantics
Store UTC; one `time_utils.py`; injected clock in tests. Normalize line endings to LF and decode UTF-8 before counting lines (EVD-1.5); undecodable files are cited by byte range. The "snapshot" is not an upload step: it is the pinned revision from FR-1 (commit SHA or working-tree hash), and the thing every claim cites. **Why it must exist [Certain]:** a live repo changes under a running analysis, so a line number cited at 10:00 can point at different code at 10:05; pinning is what keeps EVD-1.2 and EVD-1.3 true.

## 17. Fixture application and edge cases
A small synthetic Node/Express app with a **human-written answer key**, built to hold these traps (each trap is a numbered case that mock data, answer key and tests all share):
1. route registered in a loop; 2. route behind a conditional; 3. dynamic `require`; 4. dead code that looks live; 5. function named opposite to its behavior; 6. comment that contradicts the code; 7. string-built SQL; 8. parameterized SQL; 9. ORM query plus raw query on one table; 10. column never read; 11. column written by two paths; 12. config key overridden by environment; 13. config key never used; 14. feature flag changing a rule; 15. validation in middleware; 16. validation duplicated with different limits; 17. rounding rule; 18. date or timezone rule; 19. callback chain; 20. promise chain; 21. async/await; 22. error swallowed silently; 23. retry with backoff; 24. scheduled job; 25. external HTTP call; 26. message queue producer; 27. generated code file; 28. vendored library; 29. hard-coded secret (must be redacted; built from a string scanners do not match, listed in `.secrets.baseline`); 30. personal data in sample data; 31. file with invalid encoding; 32. CRLF line endings; 33. prompt-injection comment ("ignore previous instructions"); 34. undeclared dependency; 35. test file that documents a behavior the code no longer has.
The answer key lists the true facts for each trap. It is written by hand and reviewed by Aditya line by line; the model under test never writes it. Review counts only when Aditya says so, not when a PR merges.

## 18. Metrics
Coverage (REV-3.1); accuracy with interval (REV-3.2 to 3.4); fixture precision and recall per claim kind with Wilson intervals; verifier catch rate on the bad corpus and false-block rate on the good corpus (VER-1.4); characterization tests kept, passed and dropped (TST-1.5); model cost and time per run; reviewer minutes per accepted claim.

## 19. Evaluation plan
1. **Fixture:** analyzers scored against the answer key before any model is involved.
2. **Baseline:** a grep and regex finder for routes, SQL and validations. Agents must beat it. It is never tuned to the fixture.
3. **Verifier corpora:** start with 50 bad and 50 good claims, grow to 150 each before v1.
4. **CI smoke eval:** fake model, recorded outputs.
5. **Live eval:** on Aditya's machine with the local model; a run that hits errors or timeouts is invalid, not a pass.
6. **Pilot:** one open-source Node/Express slice; reviewer samples claims (REV-3.3).
7. **Time saved:** before the agents run, Aditya does a manual analysis of the pilot slice with a stopwatch, once. Platform time is reviewer minutes plus run time. The number is reported whatever it is.
Results are committed under `evals/results/YYYY-MM-DD-<run-id>/` with model and prompt hashes.

## 20. Environments
One deployed environment, `staging`, on Render, fixture data only, replaying recorded model outputs produced by a local run and committed as fixtures. Local compose for everything else, including live runs and the pilot. No production, no non-prod (decision D-4). `develop` deploys staging; `main` is release only.

## 20a. Changes from v1.0
A1 pilot sized to review budget; A2 two-stage dependency fetch; A4 V-10 is a heuristic; A5 CLM-1.8; A6 Modernization reads accepted claims only; A7 pinned revision wording; A8 permissive licence; A9 fixture secret pattern; A10 coverage denominator; A11 ingest limits for all sources; A12 constants proposed; A13 CLI before UI; A14 recorded fixtures. A3 remains open.

## 21. Definition of done (per change)
Cites the FR or rule ID; no invariant weakened; lint, types, tests pass locally and in CI; new behavior has a failure-path test; migrations apply and reverse; logs carry no source text or personal data; docs, runbook, `.env.example` and ADRs updated.

## 22. Open questions
1. **Resolved for design purposes (A3, 2026-11-04):** operator machine is a laptop with 31.5 GB shared memory, an Intel Arc integrated GPU (name truncated in the screenshot, probably the 140V) and an Intel NPU. Design target: a 7B to 8B-class instruction model, 4-bit quantized, served locally behind one OpenAI-compatible interface. Speed and quality are unmeasured and must be benchmarked in Phase 3 before any live eval.
2. **Open:** the pilot app, which must be permissively licensed (SEC-3.2), and its slice, sized to REV-3.5.
3. **Open:** ES modules support in the fixture, or CommonJS only for v1.

Resolved by the gap audit: review is a CLI with Markdown first and the React UI after the pilot (A13); unreadable modules count in the coverage denominator (REV-3.1).
