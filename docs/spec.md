# Strata: Evidence-Linked Reverse Engineering for Legacy Applications

**Spec version:** 0.1 (2026-11-04), **draft**
**Status:** Proposed source of truth for the project. Once approved, any request that contradicts
this file must be flagged, not silently obeyed.
**Policy reference:** `policies.md` v0.1. Lock file SHA-256 validated by CI once approved.
**Working name:** "Strata" is a placeholder.

---

## 1. Overview

Strata is a human-in-the-loop platform that analyses an undocumented legacy application (source,
configuration, database schema, build scripts, and optionally logs and tickets) and produces
documentation, diagrams, a business-rules catalog, characterization tests and a modernization plan.
Every factual statement it produces is a **claim** linked to a location in the analysed snapshot
and tagged **Confirmed**, **Inferred** or **Unknown**. A deterministic verifier checks every claim
against its evidence before a human sees it. Unknowns go to a review queue instead of being
guessed. A human approves every output. The platform never modifies the legacy code and never
connects to production systems.

---

## 2. Context and Problem

Software maintenance consumes most of an application's lifetime cost. Long-lived applications
often have missing or outdated documentation, so teams cannot safely change, migrate or modernize
them. The knowledge is in the code, but recovering it by hand takes weeks of senior time.

Given a legacy application's artifacts, the system must:
- Inventory what exists: languages, modules, entry points, dependencies, integrations.
- Recover structure: call graphs, data flows, the data model.
- Recover behaviour: business rules and validations, each linked to file and line.
- Lock in current behaviour with characterization tests.
- Propose how to modernize it, with risks tied to the evidence.

So that a team can maintain or rebuild the application without guessing.

---

## 3. Goal

A pipeline that turns one legacy snapshot into verified, evidence-linked documentation and a
modernization plan, measured on one pilot application, with a human approving every output.

---

## 4. Design Decision: Pipeline First, Agents Later

The use case lists nine agents. Most of what they do is **deterministic analysis** that a parser
does better, cheaper and reproducibly than a language model. An LLM is used only where the job is
reading meaning into code or writing prose. This mirrors ReplyDesk, where seven proposed agents
became three LLM steps and deterministic code.

The nine agents remain the product's vocabulary (UI, docs, metrics are organised by them), but
each is implemented as the cheapest reliable mechanism:

| # | Agent | Implementation in v1 | LLM? | Why |
|---|---|---|---|---|
| 1 | Discovery | Function: file inventory, language detection, manifest parsing (`package.json`, `npm-shrinkwrap.json`/`package-lock.json`, `bower.json`), SBOM, entry-point patterns (`app.get/post/use`, `router.*`, `http.createServer`, `bin` scripts, cron/agenda/node-schedule jobs, queue consumers), integration detectors (`request`/`axios`/`http` clients, DB connection strings, SMTP via nodemailer, file drops) | No | Inventory is pattern matching; a model adds error, not insight. |
| 2 | Code Analysis | Function: tree-sitter parse → symbol index → `require` graph → call graph and def-use data flow; Express adapter for routes and middleware chains | No (LLM only proposes resolutions for unresolved dynamic calls, always Inferred) | The use case requires AST-based analysis, and graph facts must be reproducible. |
| 3 | Business Rule | **Hybrid**: deterministic candidate extraction (conditionals with literals, validator schemas such as Joi/express-validator/Mongoose validators, SQL constraints, triggers, stored procedures) → **LLM** names and explains each rule with citations | Yes | Finding candidates is mechanical; saying what a rule *means* is not. |
| 4 | Data | Function: SQL DDL parse (sqlglot), ORM mapping parse, query extraction → entity model, ER graph, column-level lineage where statically visible | No (LLM only drafts column descriptions, Inferred) | Schemas are structured input. |
| 5 | Diagram | Function: render Mermaid from graph and schema catalog | No | OUT-6.3: diagrams come from the graph, not a model's imagination. |
| 6 | Documentation | **LLM** writes prose **from verified claims only** (never from raw code) | Yes | Writing is the model's strength; restricting input to claims keeps it grounded. |
| 7 | Test | **Hybrid**: deterministic harness and input discovery from entry points + **LLM** proposes test cases; sandbox executes them | Yes | Choosing interesting inputs benefits from a model; pass/fail does not. |
| 8 | Verification | **Deterministic verifier first** (rules V-1 to V-10), **LLM judge** second, can only downgrade or block | Judge only | The verifier is the authority; the judge adds semantic coverage. |
| 9 | Modernization | **LLM** over verified findings + deterministic metrics (coupling, complexity, coverage, dependency age) | Yes | Strategy is judgement; its inputs must be facts. |

Agent behaviour in the strict sense (tool-calling loops where a model decides which files to read
next) is a **v2 topic**, and only after the eval harness can measure whether it helps.

Recorded in `docs/adr/0001-pipeline-first.md`.

---

## 5. Scope

### In Scope (v1)

- One analysed language for the pilot: **legacy server-side JavaScript** (CommonJS Node.js,
  typically Express 3/4 era, callbacks and promises, no TypeScript), decided 2026-11-04. The
  parsing layer is designed so further languages are adapters. ES modules, TypeScript sources and
  browser-side bundles are recorded in the inventory but not deeply analysed in v1.
- SQL schema from a DDL file or schema-only dump, for one SQL dialect.
- Configuration files (JSON, YAML, INI, `.env`, `config/*.js`), build scripts (npm scripts, Grunt, Gulp, Make,
  shell) parsed as data.
- Optional inputs: runtime logs, existing docs, tickets (CSV or JSON export).
- All nine agents as in §4.
- Claim store with evidence resolution, verification and review queue.
- Review UI: queue, claim and evidence viewer side by side with the source, approve/correct/reject.
- Outputs listed in §15.
- Characterization tests run in a network-isolated sandbox.
- Labeled evaluation harness with a seeded fixture legacy application (§17).
- Append-only audit log and metrics dashboard.

### Out of Scope (v1)

- Automatic full code rewrite (MOD-8.3).
- Mainframe sources (COBOL, JCL, PL/I, RPG) and non-text sources (binaries, images, scanned docs).
- Any write to the legacy repository, including patches, instrumentation or test hooks (SAF-3.1).
- Any connection to production systems (SAF-3.2).
- Multi-repository and microservice-estate analysis (one repository per run in v1).
- Agentic tool-calling loops (§4).
- Running the platform as a public multi-tenant SaaS.

---

## 6. Users

- **Reviewer / analyst (primary):** a developer or architect who knows the domain a little, works
  the review queue, confirms or corrects claims, approves artifacts.
- **Maintainer (consumer):** reads the approved docs and catalog to change the system safely; runs
  the characterization suite before and after a change.
- **Modernization lead (consumer):** reads the tech-debt map and migration plan, decides phases.
- **Platform operator:** sets up the private environment, loads snapshots, manages model access.

---

## 7. Core Flow

```
snapshot in (repo archive or commit, schema DDL, configs, build scripts, optional logs/tickets)
  → freeze: hash everything, mount read-only, record snapshot_id           (SAF-3.1, EVD-1.4)
  → secret + PII scan; redact before anything else reads it               (SAF-3.6, PRV-4.4)
  → Discovery: inventory, manifests, SBOM, entry points, integrations
  → Code Analysis: parse → symbol index → call graph → data flow
  → Data: DDL + ORM + queries → entity model, ER graph, lineage
  → Business Rule: deterministic candidates → LLM explains with citations
  → Verification pass 1 (V-1..V-10 → LLM judge)
      (fail → retry once with reasons → fail again → claim becomes Unknown → review queue)
  → Review queue (Unknowns, conflicts, high-impact Inferred)                (REV-5.2)
  → Diagram: render from graph + schema catalog
  → Documentation: prose from verified claims only
  → Test: generate characterization tests → run in sandbox N times → keep stable passes
  → Modernization: target architecture, risk and tech-debt map, phased plan
  → Verification pass 2 on every generated artifact
  → Human approval per artifact                                             (REV-5.1)
  → Export + audit log + metrics
```

---

## 8. Functional Requirements

| ID | Requirement |
|---|---|
| FR-1 | Accept a snapshot as a git commit (bundle or local path) or an archive, plus optional schema DDL, config set, logs and ticket export. Compute and store a snapshot ID from content hashes. Ingestion is idempotent on the snapshot ID. |
| FR-2 | Mount the snapshot read-only for every analysis step. No step may open a legacy file for writing (SAF-3.1). |
| FR-3 | Run secret and PII scans on every ingested file before analysis; store findings by location with values redacted (SAF-3.6, PRV-4.4). |
| FR-4 | Discovery: produce the inventory of languages (with line counts), modules, entry points (HTTP routes, main methods, scheduled jobs, message listeners, CLI commands), dependencies with versions, and external integrations, each as a claim with evidence. |
| FR-5 | Code Analysis: parse every supported source file to an AST with tree-sitter; resolve `require()` targets (relative paths, `node_modules`, `index.js`, `package.json` `main`); build a symbol index; build a call graph with each edge tagged (static-resolved = Confirmed, dynamic-resolved = Inferred, unresolved = Unknown) and data flow for variables reaching persistence and output. |
| FR-6 | Data: parse DDL into a schema catalog (tables, columns, types, keys, constraints, indexes, views, triggers, procedures); map ORM entities and raw queries to schema objects; produce the entity model and column-level lineage where statically visible. |
| FR-7 | Business Rule: extract rule candidates deterministically; have the LLM name, explain and categorise each rule, citing file and line; store each rule as a claim. |
| FR-8 | Verification: run rules V-1 to V-10 (§13) on every claim and every generated artifact; then the LLM judge; retry once on failure; downgrade to Unknown and queue on second failure. |
| FR-9 | Review queue: create review items per REV-5.2 with a specific question; record decisions per REV-5.3; feed confirmed and corrected decisions back as evidence (REV-5.5). |
| FR-10 | Diagram: render architecture (module/component), sequence (per selected entry point), workflow (per business process), and ER diagrams in Mermaid from stored graph data (OUT-6.3). |
| FR-11 | Documentation: generate technical docs per module, interface and API reference per entry point, glossary from domain terms in identifiers and schema, and runbooks from build/deploy scripts and config, writing only from verified claims (OUT-6.2). |
| FR-12 | Test: generate characterization tests per entry point and per business rule; build and run the legacy application in the sandbox (SAF-3.4); accept tests per TST-7.4. |
| FR-13 | Modernization: produce target architecture, risk and tech-debt map, and phased migration plan per MOD-8.1 to MOD-8.3. |
| FR-14 | Review UI: queue sorted by impact; claim, evidence excerpt and full source view side by side; approve, correct, reject, defer; artifact approval. |
| FR-15 | Export: approved artifacts as a Markdown docs tree (with Mermaid) and the test suite as a runnable project; unapproved artifacts are watermarked (REV-5.1). |
| FR-16 | Metrics (§18) computed from stored data. |
| FR-17 | Append-only audit log of every ingestion, agent run, model call, verification result, review decision, approval and export, with actor and time. |
| FR-18 | Re-run on a new snapshot re-verifies existing claims and reports which changed, broke or still hold (EVD-1.4). |

---

## 9. Non-Functional Requirements

- **Safety:** the legacy tree is never written; production is never contacted; legacy code runs
  only in the sandbox with network disabled.
- **Confidentiality:** legacy content stays in the deployment; the only external recipient is the
  model endpoint approved in ADR-0004; CI never sees client code (PRV-4.1).
- **Auditability:** every claim is reproducible from stored inputs: snapshot ID, analyzer version,
  prompt version and hash, model ID, input excerpt hashes.
- **Determinism:** deterministic stages produce byte-identical output on the same snapshot and
  platform version. LLM stages run at temperature 0 and record everything needed to replay them.
- **Cost:** tokens and cost recorded per call, per agent and per run; prices live in config.
- **Scale target (v1):** a repository of up to 200k lines of code in the pilot language analysed
  end to end in under 4 hours on one machine. [Guessing: set after the first fixture run.]
- **Resilience:** long runs are broken into idempotent jobs in a DB-backed job table; a restart
  resumes, never duplicates.
- **Observability:** structured JSON logs with `run_id`, `snapshot_id`, `agent`, `stage`; no
  legacy source in logs.
- **Local-first:** the whole platform runs with one `docker compose up` on a machine inside the
  private environment, without internet access except to the approved model endpoint.

---

## 10. Stack

Specified, with rationale and alternatives, in `docs/tech-stack.md`. Decisions that are not
obvious have ADRs in `docs/adr/`. Summary: Python 3.12 (`uv`), FastAPI, PostgreSQL 16 as claim
store and graph store, tree-sitter for parsing, sqlglot for SQL, React + TypeScript for the review
UI, Docker sandbox with `--network none` for legacy execution, one `ModelGateway` for all model
calls.

---

## 11. Snapshot Schema

```json
{
  "snapshot_id": "sha256 of the manifest below",
  "source": {
    "kind": "git | archive",
    "repo_name": "string",
    "commit": "string|null",
    "archive_sha256": "string|null"
  },
  "inputs": [
    {
      "kind": "source | schema | config | build | log | ticket | doc",
      "path": "string (relative to the snapshot root)",
      "sha256": "string",
      "bytes": 0
    }
  ],
  "created_at": "ISO-8601 UTC",
  "created_by": "string",
  "platform_version": "string"
}
```

---

## 12. Claim Schema

The claim is the unit of everything. Docs, diagrams, catalogs and plans are views over claims.

```json
{
  "claim_id": "uuid",
  "snapshot_id": "string",
  "agent": "discovery | code_analysis | business_rule | data | diagram | documentation | test | verification | modernization | human",
  "kind": "inventory | entry_point | dependency | integration | call_edge | data_flow | schema_fact | lineage | business_rule | validation | glossary_term | behaviour | tech_debt | risk | recommendation | conflict | question",
  "subject": { "type": "file | module | symbol | endpoint | table | column | rule | artifact", "ref": "string" },
  "statement": "string (one sentence, plain language)",
  "tag": "confirmed | inferred | unknown",
  "evidence": [
    {
      "ref": "code:lib/billing/invoice.js#L120-L134",
      "kind": "code | schema | config | build | log | doc | graph | test | review",
      "excerpt": "string (verbatim, ≤ max_evidence_excerpt_lines)",
      "excerpt_sha256": "string",
      "role": "supports | contradicts | context"
    }
  ],
  "reasoning": "string|null (required when tag = inferred)",
  "confirm_by": "string|null (required when tag = inferred or unknown)",
  "question": "string|null (required when tag = unknown)",
  "depends_on": ["claim_id"],
  "category": ["money", "auth", "data_deletion", "..."],
  "policy_refs": ["TAG-2.5"],
  "provenance": {
    "analyzer": "string@version",
    "prompt_version": "string|null",
    "prompt_hash": "string|null",
    "model": "string|null",
    "created_at": "ISO-8601 UTC"
  },
  "verification": {
    "status": "pending | passed | failed | downgraded | error",
    "rule_failures": [ { "rule": "V-3", "detail": "string" } ],
    "judge": { "verdict": "supported | unsupported | partial", "confidence": 0.0 } 
  },
  "review": { "status": "none | queued | confirmed | corrected | rejected | deferred", "decision_id": "string|null" }
}
```

**Notes:**
- A business rule claim additionally carries `rule_id` (stable, e.g. `BR-INV-004`), `trigger`
  (when it fires), `condition`, `effect`, and `entry_points` that reach it.
- `depends_on` drives TAG-2.6: a claim's effective tag is the minimum of its own and its
  dependencies'.

---

## 13. Verification Rules

A claim or artifact passes only if all applicable rules hold. Failures are structured (rule, span,
missing evidence) and feed the retry prompt, the audit log, the review UI and the metrics.

### 13.1 Deterministic Verifier (runs first, is the authority)

**V-1 (Evidence exists):** every evidence `ref` names a file or schema object present in the
snapshot, and every line range lies inside the file (EVD-1.3).

**V-2 (Excerpt matches):** the stored `excerpt` equals the snapshot content at the cited range,
and `excerpt_sha256` matches (EVD-1.3, EVD-1.6).

**V-3 (Symbols exist):** every identifier the statement names in code formatting (class, method,
table, column, endpoint, config key) exists in the symbol index or schema catalog and appears in,
or is graph-linked to, a cited excerpt.

**V-4 (Values match):** every literal value in the statement (number, string, status code,
threshold, date) appears in a cited excerpt after normalisation (separators, quoting, units).

**V-5 (No uncited facts):** in generated prose, every factual sentence maps to at least one claim
ID (OUT-6.2). Sentences with no claim fail.

**V-6 (Tag is legal):** Confirmed requires rank 1–2 evidence (EVD-1.5); dynamic constructs cap at
Inferred (TAG-2.5); absence claims cap at Inferred (TAG-2.7); Inferred requires `reasoning` and
`confirm_by`; Unknown requires `question`.

**V-7 (Graph consistency):** every node and edge in a diagram exists in the graph or schema
catalog with the same tag; no diagram element lacks an ID (OUT-6.3).

**V-8 (Tag propagation):** a claim's tag is not stronger than the weakest claim in `depends_on`
(TAG-2.6).

**V-9 (No leaks):** no secret value or unmasked PII appears in the claim or artifact
(SAF-3.6, PRV-4.4).

**V-10 (No injection echo):** the output does not follow, repeat as instruction, or act on text
from legacy content that reads as an instruction (PRV-4.3).

### 13.2 LLM Judge (second pass)

- Asks one question per claim: does the cited evidence support this statement, partly, or not?
- Can block or downgrade; **cannot** override a deterministic failure or upgrade a tag (TAG-2.4).
- Must be a different model from the one that produced the claim; a different provider where
  possible (ADR-0004). This is weaker than it sounds: see the ReplyDesk lesson in ADR-0004.
- Its verdict and confidence are stored with the claim.

### 13.3 Retry and Fallback

- On failure: retry the producing step once with the structured failure reasons.
- On second failure: the claim becomes **Unknown** with the failures as its `question`, and goes to
  the review queue. A failing claim is never published as a lower-quality fact.

### 13.4 Verifying the Verifier

- A seeded bad-claim corpus (§19) with known violations of every rule. The verifier must catch
  every one; the false-block rate on a good-claim corpus is measured and reported.
- ReplyDesk's first eval report had to be corrected because the evaluator miscounted. Every
  evaluator and metric script here has its own unit tests on hand-computed cases.

---

## 14. Review Queue Rules

Review items are created per REV-5.2. Behaviour per item type:

| Trigger | Effect on artifacts |
|---|---|
| Unknown claim | Listed in the open-questions output; any artifact sentence depending on it is withheld and replaced by a visible "open question" marker. |
| Conflicting evidence | Both sides shown; artifact shows the conflict, not a chosen side. |
| High-impact Inferred | Shown in artifacts with an *Inferred* badge; artifact cannot be approved until each is confirmed, corrected or explicitly accepted as Inferred with a reason. |
| Verification failed twice | As Unknown. |
| Verification errored | As Unknown; also raises an operator alert (fail closed). |
| Unresolved dynamic dispatch | Edge drawn dashed or omitted per OUT-6.3; item asks which implementation is used. |

Queue order: high-impact category first, then number of artifacts blocked, then age.

---

## 15. Output Artifact Contract

| Output | Produced by | Form |
|---|---|---|
| Interface and dependency inventory | Discovery | Markdown tables + JSON |
| Architecture diagram | Diagram (from Code Analysis) | Mermaid |
| Sequence diagrams (per selected entry point) | Diagram | Mermaid |
| Workflow diagrams (per business process) | Diagram (from Business Rule) | Mermaid |
| ER diagram + data dictionary + lineage | Data, Diagram | Mermaid + Markdown |
| Business rules catalog | Business Rule | Markdown + JSON, one entry per `rule_id` |
| Technical docs per module | Documentation | Markdown |
| API and interface reference | Documentation | Markdown |
| Glossary | Documentation | Markdown |
| Runbooks (build, deploy, configure) | Documentation | Markdown |
| Characterization test suite | Test | Runnable project + coverage report |
| Open-questions list | Verification + review queue | Markdown + JSON |
| Tech-debt and risk report | Modernization | Markdown |
| Target architecture and migration plan | Modernization | Markdown + Mermaid |

Every artifact meets OUT-6.1 (provenance header) and OUT-6.2 (claim-linked prose).

---

## 16. Security and Prompt Injection

- Legacy content is untrusted data (PRV-4.3). It reaches a model only inside delimited blocks
  (`<legacy_source path="…" lines="…">…</legacy_source>`) with an explicit data-not-instructions
  statement; delimiter strings inside legacy content are escaped.
- Model steps have no tools and no side effects. They receive excerpts and return JSON.
- The secret scan runs before any model call; a prompt containing a detected secret is not sent.
- The sandbox has no network, no mounted credentials, CPU/memory/time limits, and runs as a
  non-root user. It is destroyed after each test run.
- The review UI renders legacy text and model text as text, never as HTML.
- Single-tenant deployment: one deployment per client environment. No cross-client data.

---

## 17. Fixture Legacy Application: Required Edge Cases

ReplyDesk's mock store with 31 seeded edge cases is what made its evals possible. The equivalent
here is a **fixture legacy application** written for this project in legacy-style Node.js
(CommonJS, Express, callbacks, a SQL database via a raw driver plus one ORM such as Sequelize), with an
**answer key**: every module, entry point, call edge, table, rule and trap is listed with its
location. The real pilot application measures value; the fixture measures correctness.

The fixture must include all of these:

| # | Trap | What a correct analysis does | Policy |
|---|---|---|---|
| 1 | Validation rule with a literal threshold in an `if` | Confirmed rule, value matches | V-4 |
| 2 | Same rule duplicated with a different threshold in two places | Conflict claim, review item | EVD-1.7 |
| 3 | Comment that contradicts the code beneath it | Code wins; conflict recorded | EVD-1.5 |
| 4 | Outdated README describing a removed feature | Doc claim ≤ Inferred; conflict | EVD-1.5 |
| 5 | Dead method with no callers | "Unused" ≤ Inferred, searches listed | TAG-2.7 |
| 6 | Function reached only by computed property (`handlers[action]()`) or `require(variable)` | Edge Inferred, not "dead" | TAG-2.5 |
| 7 | Two modules with the same exports, one chosen by config or `NODE_ENV` | Edge Inferred, review item | TAG-2.5 |
| 8 | Dynamic SQL built by string concatenation or template literal | Lineage Inferred | TAG-2.5 |
| 9 | Business rule implemented in a DB trigger | Rule found in schema | FR-6 |
| 10 | Business rule in a stored procedure | Rule found, linked to callers | FR-6 |
| 11 | Magic number with no name (e.g. tax rate `0.18`) | Rule with value cited | V-4 |
| 12 | Rule driven by a config value | Rule cites config key and code | EVD-1.2 |
| 13 | Commented-out code containing an older rule | Not reported as current behaviour | EVD-1.5 |
| 14 | Hardcoded credential in `config/*.json` or a committed `.env` | Finding by location, value redacted | SAF-3.6 |
| 15 | Comment containing an instruction to an AI | Ignored; flagged | PRV-4.3, V-10 |
| 16 | npm `postinstall` or `deploy` script / Gruntfile task that calls the network | Parsed, never executed | SAF-3.5 |
| 17 | Scheduled job entry point (`node-cron` / `setInterval` in a worker) | Entry point found | FR-4 |
| 18 | Message or event listener entry point (`emitter.on`, queue consumer) | Entry point found | FR-4 |
| 19 | Outbound HTTP integration with URL in config | Integration found | FR-4 |
| 20 | Table with no foreign keys but an implied relation by naming | Relation Inferred | TAG-2.2 |
| 21 | Column whose meaning is only in a ticket | Description Inferred from doc | EVD-1.5 |
| 22 | Non-deterministic output (timestamp, random ID) | Test marks it, does not flake silently | TST-7.4 |
| 23 | Observable bug (off-by-one in a date window) | Test asserts it, labelled suspected defect | TST-7.1 |
| 24 | Money handled as JS `Number` with `toFixed` rounding | Tech-debt finding | MOD-8.1 |
| 25 | Route registered without the auth middleware the others use | Risk finding, high impact | REV-5.2 |
| 26 | Circular `require` between two modules | Tech-debt finding, diagram shows it | FR-10 |
| 27 | Unicode lookalike in an identifier or literal | V-3/V-4 do not false-pass | V-3, V-4 |
| 28 | Very long function or callback pyramid (>500 lines) | Excerpts stay within limits | EVD-1.6, PRV-4.2 |
| 29 | Minified or bundled file (`public/js/app.min.js`) | Classified as generated, not documented as hand-written | FR-4 |
| 30 | `node_modules` or a vendored library (jQuery) committed to the repo | Classified as dependency, not app code | FR-4 |
| 31 | Loose equality and truthiness in a rule (`if (qty == "0")`, `if (!discount)`) | Rule states the actual JS semantics, not the intended ones | TST-7.1 |
| 32 | Monkey-patched prototype or global (`Array.prototype.sum`, `global.db`) | Edge resolved or Inferred, not missed | TAG-2.5 |
| 33 | Middleware that mutates `req` used by a later handler | Data flow across the middleware chain recorded | FR-5 |

Each trap is referenced by at least one answer-key entry and at least one eval case.

---

## 18. Metrics Dashboard (v1)

| Metric | Definition |
|---|---|
| Module coverage | Modules with an approved doc section / modules in inventory |
| Endpoint coverage | Entry points with an approved interface reference / entry points found |
| Claims by tag | Count and share of Confirmed / Inferred / Unknown, per agent |
| Verification failures | Count by rule V-1 to V-10, and judge blocks, per agent |
| Review queue | Open items, by trigger; median time to decision |
| Reviewer-sampled accuracy | Correct / sampled, with Wilson interval (REV-5.4) |
| Characterization tests | Generated, stable-passing, non-deterministic, suspected-defect; entry-point and rule coverage |
| Cost | Tokens and currency per agent and per run |
| Run time | Wall time per stage and end to end |
| Time saved | Reviewer hours on the platform vs. the manual baseline (§19) |

All metrics are computed from stored data.

---

## 19. Evaluation Plan

Evals are built before features.

### Datasets

- **Fixture answer key** (§17): the ground truth for inventory, entry points, call edges, schema,
  rules and traps. Written by a human, never by the model being evaluated.
- **Seeded bad-claim corpus** (target 150+): claims violating each of V-1 to V-10 and each TAG
  rule. The verifier must catch every one.
- **Good-claim corpus** (target 150+): correct claims, to measure false blocks.
- **Pilot application** (§23, open question 1): no answer key; measured by reviewer sampling and
  time saved.

### Metrics

| Metric | Target (v1) |
|---|---|
| Entry-point recall on fixture | ≥ 0.95 |
| Static call-edge precision / recall on fixture | Report; precision ≥ 0.98 for Confirmed edges |
| Schema object recall on fixture | 1.00 (it is parsed, not inferred) |
| Business-rule recall on fixture | Report; goal ≥ 0.80 |
| Trap handling on fixture | Every trap in §17 handled as specified |
| Seeded bad claims caught | 100% |
| False-block rate on good claims | Report; goal ≤ 0.05 |
| Reviewer-sampled accuracy on pilot | ≥ 0.90, lower Wilson bound reported |
| Characterization tests stable-passing on pilot | Report count and coverage; 100% of accepted tests pass against the original |
| Time saved on pilot | Report vs. baseline |

### Time-saved baseline

The success criterion needs a manual baseline, and none exists yet. Options, in order of
credibility: (a) a person analyses a defined slice of the pilot by hand, timed, before seeing
platform output; (b) a person documents half the modules by hand and the platform does the other
half, both reviewed to the same standard. Self-estimates are not a baseline. See §23, open
question 3.

### Process

- Version and hash every prompt; record model and temperature per run.
- Each run stores outputs under `evals/results/YYYY-MM-DD-<run-id>/`.
- Report every number, including bad ones (OUT-6.5). Corrections are published as a
  `CORRECTION.md` next to the report, never as a silent edit.

---

## 20. Snapshot Semantics

- Every fact is true *of a snapshot*. Claims never float free of a `snapshot_id`.
- Line numbers refer to the snapshot as ingested, after CRLF normalisation is recorded but not
  applied (the excerpt is stored with original bytes; line splitting accepts `\n`, `\r\n`, `\r`).
- Encoding: files are decoded with detected encoding; the detected encoding is recorded per file.
  Undecodable files are listed in the inventory as unsupported, never silently dropped.
- Re-analysis on a new snapshot (FR-18) maps claims by `subject` and re-verifies them; it never
  copies tags across snapshots.
- Never read "now" inside analysis logic; inject a clock so runs are reproducible.

---

## 21. Build Environments

| Environment | Purpose | Data allowed |
|---|---|---|
| **Local** | Development | Fixture app, open-source pilot |
| **CI** | Every PR | Fixture app only; no live model calls (recorded fixtures) |
| **Staging** | Integration, full evals with live models | Fixture app, open-source pilot |
| **Private deployment** | Real client legacy code | Client code, inside the client's environment only |

There is no shared production SaaS in v1. A "production" deployment is a private, single-tenant
install (PRV-4.1). Details in `docs/branching-and-environments.md`.

---

## 22. Definition of Done (v1)

- [ ] One `docker compose up` starts the platform from a clean clone.
- [ ] `make lint`, `make test`, `make eval-smoke`, `make eval` pass.
- [ ] Every fixture trap (§17, 33 traps) handled as specified; 100% of seeded bad claims caught.
- [ ] Pilot application analysed end to end; every output in §15 produced and human-approved.
- [ ] Reviewer-sampled accuracy on the pilot reported with Wilson interval; target ≥ 0.90.
- [ ] Characterization suite passes against the sandboxed original pilot.
- [ ] Time saved measured against a real baseline and reported honestly.
- [ ] No step wrote to the legacy tree (verified by snapshot hash before and after) and no network
      call left the sandbox (verified by sandbox network policy logs).
- [ ] README shows architecture, how to run, eval results with model and prompt hashes, known
      limitations.

---

## 23. Open Questions

1. **Pilot application.** Language decided 2026-11-04: legacy server-side JavaScript (Node.js,
   Express era). Still open: which app. Criteria: open source, CommonJS, roughly 10k–100k lines
   of app code, real business rules (orders, pricing, permissions), a SQL schema, few or no tests
   and thin docs, and it must build and run in a no-network sandbox with dependencies pre-fetched.
   Blocks Phase 1.7 only for the Node version and SQL dialect; the fixture can start now.
2. **Model hosting and data residency.** Can legacy code be sent to a hosted model API at all, and
   under what terms? Decides ADR-0004. Blocks Phase 3. If the answer is "no external API", a
   self-hosted model is needed and quality targets must be re-set.
3. **Time-saved baseline.** Who performs the manual analysis, on which slice, and when? Must
   happen before that person sees platform output.
4. **Reviewer.** Who reviews, and how many hours per week? Accuracy sampling at 100+ claims is
   roughly 4–8 hours of expert time per run. [Guessing: 2–5 minutes per claim.]
5. **SQL dialect** of the pilot schema.
6. **High-impact categories** beyond the defaults in REV-5.2.
