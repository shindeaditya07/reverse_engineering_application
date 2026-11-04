# Strata: Tech Stack

**Version:** 0.1 (2026-11-04), **draft**
**Spec reference:** `spec.md` v0.1 §10
**Status:** Proposed. Choices marked *decided by ADR* are only final once that ADR is accepted.

**Two stacks, don't confuse them.** The **platform** is built on the ReplyDesk stack (Python,
FastAPI, Postgres, React + TypeScript). The **pilot legacy app** it analyses is legacy server-side
JavaScript (decided 2026-11-04). Sections 1, 3, 5 and 6 are the platform; sections 2 and 4 are
what it needs to read and run the legacy app.

ReplyDesk kept its stack in the spec and the README. This project gets one stack file because the
analysis toolchain is larger and each piece needs a reason. The spec and README link here; they do
not repeat the table (one source per fact).

Confidence tags: **[Certain]** the tool exists and does this; **[Likely]** a strong expectation
that it fits, to confirm in Phase 1; **[Guessing]** a placeholder until the pilot is chosen.

---

## 1. Platform Core

| Layer | Choice | Why | Alternatives rejected |
|---|---|---|---|
| Language | Python 3.12, `uv` | Same as ReplyDesk; best ecosystem for parsing (tree-sitter bindings, sqlglot) and model clients. **Never Conda.** | Java/Kotlin (better for JVM analysis, worse for everything else) |
| API | FastAPI + Pydantic v2 | Pydantic models double as JSON Schema for model structured output and OpenAPI [Certain] | Django (heavier, ORM we don't want) |
| Store | PostgreSQL 16 | Claims, evidence, graph, review, audit, jobs in one transactional store. Graph traversal via recursive CTEs [Certain]. *ADR-0003* | Neo4j (second database to secure and back up for queries Postgres handles at this scale) |
| ORM / migrations | SQLAlchemy 2.0, Alembic | Same as ReplyDesk | — |
| Jobs | DB-backed job table, `SELECT … FOR UPDATE SKIP LOCKED` | Reuses ReplyDesk ADR-0002 pattern; long runs survive restarts | Celery/Redis (extra infra) |
| Orchestration | Plain Python pipeline over the job table | Every stage is inspectable and replayable. *ADR-0001* | LangGraph, CrewAI, AutoGen (opaque control flow, harder to make deterministic; reconsider for v2 agents) |
| Config | pydantic-settings, one `Settings` object | Same as ReplyDesk | — |

## 2. Analysis Toolchain

| Job | Choice | Notes |
|---|---|---|
| Multi-language parsing | **tree-sitter** via `py-tree-sitter` + per-language grammars [Certain] | Concrete syntax trees for dozens of languages with one API; error-tolerant on broken legacy files. *ADR-0002* |
| Name resolution (pilot language: legacy Node.js) | `tree-sitter-javascript` [Certain] + our own CommonJS `require` resolver (Node's resolution algorithm: relative paths, `index.js`, `package.json` `main`, `node_modules` lookup) + optional **TypeScript compiler API sidecar** with `allowJs`/`checkJs` for type-based call resolution [Certain the API supports JS; Likely it resolves enough legacy CommonJS to be worth a Node sidecar] | tree-sitter parses but does not resolve. Plain `require` resolution is deterministic and covers most edges; computed properties, `require(variable)` and prototype patching stay Inferred (TAG-2.5). Add the sidecar only if the fixture shows too many Inferred edges. |
| Framework adapter | Express: `app.METHOD`/`router.METHOD`/`app.use` → routes and middleware chains, including mounted sub-routers | Pattern rules over the AST, tested on fixture traps 25 and 33. |
| SQL / DDL | **sqlglot** [Certain] | Parses DDL and queries across many dialects; gives column-level lineage for static SQL. |
| Stored procedures | sqlglot where the dialect is supported; else tree-sitter grammar for the dialect if one exists; else text excerpt + Inferred [Likely] | PL/SQL and T-SQL coverage is uneven. |
| Config files | Standard parsers: `PyYAML`/`ruamel.yaml`, `configparser`, `lxml`, `.properties` parser | Need key paths with line numbers, so parsers must keep positions (`ruamel.yaml` does [Certain]; others need a thin wrapper). |
| Dependency inventory / SBOM | **syft** (CycloneDX output) + direct manifest parsing [Certain] | syft for breadth, own parsers for line-level evidence. |
| Vulnerable / outdated deps | **grype** or **osv-scanner** against the SBOM [Certain] | Input to the tech-debt map. Runs offline with a mirrored DB in the private environment. |
| Secret scanning | **gitleaks** + **detect-secrets** [Certain] | Two scanners, union of findings; values redacted on ingest. |
| PII scanning | **Presidio** (analyzer + anonymizer) [Certain it exists; Likely adequate for logs/tickets] | Runs before storage of logs, sample data and tickets. |
| Complexity / metrics | **lizard** (cyclomatic complexity, supports JavaScript) [Certain] | Input to tech-debt map. |
| Node dependency audit | `npm audit` needs the registry, so use **osv-scanner** on the lockfile with an offline DB [Likely] | Old lockfiles (`npm-shrinkwrap.json`, lockfile v1) must parse; test on the fixture. |
| Language detection | Extension + shebang + content heuristics; `enry`/linguist-style rules [Likely] | Must also classify generated and vendored code (spec §17 traps 29, 30). |
| Code search for model context | Symbol index + graph neighbourhood first; **pgvector** only if evals show graph retrieval misses context [Likely] | ReplyDesk needed vectors for policy prose; code has structure we can use instead. |

## 3. Model Layer

| Job | Choice | Notes |
|---|---|---|
| Interface | One `ModelGateway` (ReplyDesk pattern): prompt version + hash, retries on transient errors only, circuit breaker, schema validation, cost record | Application code never imports a provider SDK. |
| Producer models | **Decided by ADR-0004** | Rule explanation, prose, test-case proposal, modernization. |
| Judge model | **Decided by ADR-0004**, different model from producer | |
| Structured output | JSON Schema exported from Pydantic models | Schema and validator cannot drift. |
| Temperature | 0 for extraction and judging | Record actual value per call. |

## 4. Sandbox and Characterization Tests

| Job | Choice | Notes |
|---|---|---|
| Isolation | Docker, `--network none`, read-only snapshot mount, non-root, CPU/memory/time limits; **gVisor** (`runsc`) runtime where available [Certain it exists; Likely worth it] | SAF-3.4. Legacy code is untrusted. *ADR-0005* |
| Legacy runtime | Official `node:<version>` image pinned to the pilot's `engines` field or `.nvmrc`; old versions (Node 0.10–12) are still published as images [Likely; confirm for the chosen pilot] | Dependencies installed by the operator from a pre-filled npm cache (`npm ci --offline` / `npm install --offline`), never by the legacy build reaching the registry. Native addons (`node-gyp`) are the main build risk. |
| Legacy database | MySQL/Postgres/etc. container matching the pilot dialect, restored from DDL + synthetic seed, inside the same no-network sandbox network | Testcontainers can manage this from the harness [Certain]. |
| Black-box tests | pytest + `httpx` against the Express app's HTTP routes; subprocess for `bin` scripts; approval / golden-master files [Certain] | Default for v1: drives the app from outside (TST-7.3). Same test stack as the platform, so no second test language. |
| White-box tests (optional) | Node test files (e.g. mocha, often already the legacy app's own choice) in a separate tree that `require`s legacy modules read-only [Likely] | Only for pure functions black-box tests cannot reach. |
| Coverage of legacy code | **c8** (V8's built-in coverage, no source instrumentation) on Node ≥ 10.12; **nyc** (instruments in memory at load time) for older Node [Likely] | Neither edits files on disk, so SAF-3.1 holds. |

## 5. Review UI

| Layer | Choice | Notes |
|---|---|---|
| Framework | React 18 + TypeScript (strict) + Vite | Same as ReplyDesk. |
| Server state | TanStack Query | Same as ReplyDesk. |
| API types | `openapi-typescript` from the FastAPI schema | Never hand-written. |
| Source viewer | Shiki for highlighting, read-only, line anchors | Monaco only if editing is ever needed (it is not, SAF-3.1). |
| Diagrams | Mermaid rendered client-side; `@mermaid-js/mermaid-cli` for export [Certain] | Mermaid renders in GitHub and most Markdown tools; PlantUML export is v2. |

## 6. Quality, CI and Delivery

| Job | Choice |
|---|---|
| Python lint / types | ruff (lint + format), mypy `--strict` |
| Frontend lint | eslint, prettier |
| Tests | pytest, pytest-cov, hypothesis (for the verifier and normalisers), vitest |
| Security | detect-secrets (pre-commit), pip-audit, npm audit |
| Containers | Multi-stage, non-root, pinned base images |
| CI | GitHub Actions on the **platform** repo, fixture app only (PRV-4.1) |
| Delivery | Docker Compose bundle for a private single-tenant install; staging host for the fixture and open-source pilot only |

## 7. Explicitly Not in v1

- Agent frameworks (LangGraph, CrewAI, AutoGen): ADR-0001.
- Graph database: ADR-0003.
- Vector search over code: only if evals show it is needed.
- PlantUML, C4 tooling beyond Mermaid's C4 support.
- Any SaaS that receives legacy code other than the model endpoint in ADR-0004.
