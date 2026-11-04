# Strata: Build Plan

**Version:** 0.1 (2026-11-04), **draft**
**Spec reference:** `spec.md` v0.1
**Status:** Proposed. Spec and policies define behaviour; this file defines order of work and why.

---

## Overview

Five phases, each with a deliverable and a `make` target that validates it. No phase starts until
CI is green on the previous one.

**Core principle (kept from ReplyDesk):** build the thing that can tell you whether you are right
before building the thing you want to be right. Here that means the **fixture legacy app with its
answer key, the claim store and the deterministic verifier come before any model call.**

**Second principle (new here):** deterministic analysis before LLM analysis. If the parser cannot
find the entry points, no prompt will fix it.

---

## Phase 1 — Foundation, Fixture and Verifier

**Validation:** `make lint && make test && make eval-smoke && make policy-check`

### Goal

Everything needed to measure correctness, before any agent exists.

### Deliverables

**1.1 Repository scaffold** — layout from `AGENTS.md` §2, compose (db, api, review-ui stub,
sandbox stub), Makefile targets (stubs allowed), `.env.example`, pre-commit, skeleton CI.

**1.2 Policies in code** — `policy_constants.yaml`, `make policy-check` (constants ↔ passages,
SHA-256 lock on `policies.md`).

**1.3 Claim store** — Pydantic models and migration `0001_initial`: `snapshots`, `snapshot_files`,
`claims`, `claim_versions`, `evidence`, `verification_results`, `review_items`,
`review_decisions`, `artifacts`, `audit_log`, `jobs`, `model_calls`. DB constraints per
`AGENTS.md` §8.

**1.4 Snapshot ingest** — freeze (hash, content-addressed store, read-only mount), archive safety
checks, secret scan with redaction, PII scan. Safety tests: hash unchanged, hostile archives
rejected, secret never stored unredacted.

**1.5 Evidence resolver** — resolve every evidence ref kind in `policies.md` EVD-1.2 to bytes;
excerpt extraction and hashing; line-ending and encoding handling (spec §20).

**1.6 Deterministic verifier V-1 to V-10** — with the bad-claim and good-claim corpora (start with
50 + 50, grow to 150 + 150 before v1). ≥ 95% branch coverage.

**1.7 Fixture legacy application** — a small legacy-style Node.js/Express app (CommonJS,
callbacks, raw SQL plus one ORM), covering all 33 traps in spec §17, with a human-written answer
key in `fixtures/answer-key/`. Builds and runs in the sandbox stub.

**1.8 Eval harness** — `make eval-smoke` scores analyzer output against the answer key (precision,
recall, Wilson intervals) and the verifier against the corpora. Evaluator unit-tested on
hand-computed cases.

**Rationale:** the fixture and verifier must exist before Phase 2 so every analyzer is measured
the day it lands.

**Language decided (2026-11-04): legacy JavaScript.** Choosing the specific pilot app (spec §23
q1) fixes the Node version and SQL dialect the fixture should mimic.

---

## Phase 2 — Deterministic Agents: Discovery, Code Analysis, Data

**Validation:** `make eval-smoke` meets the Phase 2 targets in spec §19 on the fixture.

### Deliverables

**2.1 Job runner** — DB-backed jobs (ReplyDesk ADR-0002 pattern), run graph per snapshot,
idempotent per `(run_id, job_type, input_hash)`, resume after restart.

**2.2 Discovery** — inventory, language detection with generated/vendored classification,
manifest parsing, syft SBOM, entry-point detectors, integration detectors. All emitted as claims.

**2.3 JavaScript adapter** — `tree-sitter-javascript` parse, symbol index, CommonJS `require`
resolver, Express adapter (routes, middleware chains, sub-routers). Measure the Confirmed-edge
share on the fixture; add the TypeScript-compiler-API sidecar only if it is too low.

**2.4 Call graph and data flow** — edges tagged Confirmed/Inferred/Unknown per TAG-2.5; def-use
flow to persistence and output.

**2.5 Data** — sqlglot DDL parse, ORM mapping, query extraction, entity model, ER graph, static
column lineage.

**2.6 Metrics inputs** — lizard complexity, coupling, dependency age and vulnerability (grype or
osv-scanner, offline DB).

**Rationale:** these produce the graph that every later agent reads. Their errors compound, so
they are measured in isolation first.

---

## Phase 3 — Model Layer: Business Rules, Judge, Review Queue

**Validation:** `make eval` (live models, staging) meets business-rule recall goal and 100% bad-claim
catch with the judge enabled.

### Deliverables

**3.1 ModelGateway** — adapters for the provider(s) in ADR-0004, `FakeModelClient`, prompt
hashing, retries, circuit breaker, cost records.

**3.2 Rule candidates** — deterministic extraction (conditionals with literals, validation
annotations, constraints, triggers, procedures).

**3.3 Rule explainer** — LLM names and explains each candidate with citations; stable `rule_id`.

**3.4 Judge** — second-pass support check; downgrade/block only.

**3.5 Retry and fallback** — spec §13.3.

**3.6 Review queue backend** — triggers from REV-5.2, decisions per REV-5.3, decisions as evidence
(REV-5.5).

**Blocker:** ADR-0004 (model hosting) must be accepted before 3.1.

---

## Phase 4 — Outputs and Review UI

**Validation:** every output in spec §15 generated for the fixture and passing verification pass 2.

### Deliverables

**4.1 Diagram renderer** — Mermaid from graph and schema; Inferred dashed; Unknown listed.

**4.2 Documentation writer** — module docs, interface reference, glossary, runbooks, from verified
claims only; V-5 on every sentence.

**4.3 Review UI** — queue, claim/evidence/source side by side, decisions, artifact approval.

**4.4 Exports** — Markdown docs tree; watermark on unapproved artifacts.

**4.5 Metrics dashboard and audit view.**

---

## Phase 5 — Characterization Tests, Modernization, Pilot

**Validation:** spec §22 Definition of Done.

### Deliverables

**5.1 Sandbox** — ADR-0005: build and run the legacy app with no network, DB from DDL + synthetic
seed, coverage agent, limits, teardown.

**5.2 Test generator** — harness per entry-point type, LLM-proposed cases, stability runs
(TST-7.4), suspected-defect labelling, coverage report.

**5.3 Modernizer** — tech-debt map, risk map, target architecture, phased plan with test safety
nets (MOD-8.x).

**5.4 Manual baseline** — the time-saved baseline (spec §19) is performed **before** the pilot run
is shown to the person doing it.

**5.5 Pilot run** — full analysis, human review, accuracy sampling, time-saved measurement, README
results.

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Pilot app cannot be built or run in a sandbox (old Node, native addons via node-gyp, install scripts needing network) | **High** | High | Choose the pilot partly on buildability; try the sandbox build in week 1, before committing to the pilot |
| JavaScript's dynamism leaves call graphs mostly Inferred | **High** | High | Measure Confirmed-edge share on the fixture early; TypeScript-compiler-API sidecar; let characterization tests confirm edges (TST-7.5); report the share honestly |
| Model endpoint not allowed for client code | Medium | **Critical** | ADR-0004 decided before Phase 3; self-hosted fallback path in the gateway |
| Verifier passes claims that are syntactically cited but semantically wrong | **High** | High | V-1..V-4 only prove the citation is real, not that it supports the claim; the judge and human sampling cover the gap; report the gap honestly |
| 90% accuracy target unmeasurable for lack of reviewer time | Medium | High | Fix reviewer hours before Phase 5 (spec §23 q4); stratified sample sized to the time available, interval reported |
| Fixture overfits: analyzers tuned to the 33 traps, fail on the real pilot | Medium | Medium | Pilot accuracy sampled independently; add a second, unseen fixture slice before v1 |
| Scope creep to a second language | Medium | Medium | One language in v1 (spec §5); adapters are the extension point, not a v1 deliverable |
| Hostile legacy content (injection in comments, hostile symlinks, zip bombs) | Low | High | Delimiting, V-10, archive checks, safety tests |
| Time-saved claim not credible (no real baseline) | **High** | Medium | Baseline protocol in spec §19, done before the pilot output exists |

---

## Open Items at Build Start

1. Choose the specific legacy Node.js pilot app (spec §23 q1; language decided) → before Phase 2.
2. Decide model hosting and data residency (ADR-0004) → before Phase 3.
3. Name the reviewer and their weekly hours (spec §23 q4) → before Phase 5.
4. Define the manual baseline protocol and who runs it (spec §23 q3) → before Phase 5.
5. Confirm the SQL dialect of the pilot schema (spec §23 q5) → before Phase 2.5.
