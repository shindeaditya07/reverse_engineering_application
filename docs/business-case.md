# Business case: Agentic Legacy Application Reverse-Engineering and Documentation Platform

Version 0.1 · 2026-11-04 · draft for Aditya's review · Phase 1, step 1 of the playbook

Source of truth for the goal text is the project description. Decisions recorded on 2026-11-04 are in section 11.

## 1. Context
Software maintenance takes 60 to 80% of lifetime cost. Many long-lived applications have missing or outdated documentation, so teams cannot safely change, migrate or modernize them.

## 2. Problem
Given an undocumented legacy application (source code, configs, database schema, build and deploy scripts, optionally logs and tickets), recover its architecture, behavior and business rules well enough to maintain it or rebuild it to current standards.

## 3. Goal
A multi-agent system that analyzes the legacy codebase and produces verified, evidence-linked documentation and a modernization plan. A human reviews every output.

## 4. Inputs
Source repository; database schema or dump; configuration files; build and deployment scripts; runtime logs (optional); existing partial docs or tickets (optional).

## 5. Agents (as briefed)
1. Discovery: languages, modules, entry points, dependencies, external integrations.
2. Code Analysis: call graphs and data flows from static analysis (AST, not plain text).
3. Business Rule: rules and validations, each linked to file and line.
4. Data: data model, ER diagram, lineage.
5. Diagram: architecture, sequence and workflow diagrams (Mermaid or PlantUML) from analysis results.
6. Documentation: technical docs, API and interface references, glossary, runbooks.
7. Test: characterization tests that lock in current behavior.
8. Verification: checks every claim against source evidence; flags unsupported statements.
9. Modernization: target architecture, risk and tech-debt map, phased migration plan.

## 6. Outputs
Architecture and workflow diagrams; ER diagram; technical documentation; business rules catalog; interface and dependency inventory; characterization test suite; open-questions list; tech-debt report; migration plan.

## 7. Constraints
- C-1 Every statement cites its source (file, line or schema object). No uncited claims.
- C-2 Every finding is marked Confirmed, Inferred or Unknown.
- C-3 Never modify the legacy code. Never connect to production systems.
- C-4 Unknowns go to a human review queue, not a guess.
- C-5 The code stays in a secure, private environment.

## 8. Success criteria
- SC-1 Documentation coverage: share of modules and endpoints documented.
- SC-2 Accuracy: sampled claims verified correct by a human reviewer, target 90% or more.
- SC-3 Characterization tests pass against the original application.
- SC-4 Time saved versus manual analysis, measured on one pilot application.

## 9. Out of scope (v1)
Automatic full code rewrite. Mainframe or non-text sources.

## 10. Ambiguities to resolve in the rules file and spec (not guessed here)
1. "Documented" in SC-1: does a module count if one claim is accepted, or only above a threshold? Proposed: at least one accepted claim per module and per endpoint, reported with the denominator.
2. SC-2 sampling: random sample size and who samples. Depends on reviewer hours.
3. SC-3: "pass against the original" means tests run against the unmodified legacy app in a sandbox. Tests that fail on the original are defects in the tests, not in the app.
4. C-5 versus any hosted service: see decision D-2.
5. "Multi-agent" versus the playbook's "pipeline first": the spec will decide which agents are deterministic code and which use a model.

## 11. Decisions recorded 2026-11-04
- D-1 Pilot: a slice of a real open-source Node/Express application, in addition to a synthetic fixture with a human-written answer key. App not chosen yet.
- D-2 Model hosting: a private or local model for all code, including the pilot and the fixture. No hosted model API for any analysis. Consequence: staging cannot call a live model; it runs recorded outputs only, and live runs happen on the owner's machine or private infrastructure.
- D-3 Reviewer time: assumed 4 hours per week (Claude's choice, delegated by Aditya). Revisit after the first review session.
- D-4 One deployed environment: `staging`, fixture data only.
- D-5 Platform stack: Python 3.12 with uv, FastAPI, Postgres, React and TypeScript. No Java or PHP.
