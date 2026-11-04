# 0001. Pipeline first: nine agents, mostly deterministic

- Status: proposed
- Date: 2026-11-04
- Blocks: Phase 2 design

## Context

The use case names nine agents. The obvious build is nine LLM agents in a framework, each reading
code and writing findings. That build has three problems for this product:

- **Evidence.** Every claim must cite file and line. A model reading text produces plausible line
  numbers; a parser produces exact ones.
- **Reproducibility.** Inventories, call graphs and schemas must be identical on every run, so
  they can be re-verified on a new snapshot (spec FR-18). LLM output is not.
- **Cost and scale.** Sending a 200k-line repository through a model, repeatedly, costs more and
  runs slower than parsing it once.

ReplyDesk made the same call: seven proposed agents became three LLM steps and deterministic code,
and its spec says agents are a v2 topic after the eval harness exists.

## Options

- **Nine LLM agents in a framework (LangGraph/CrewAI).** Fast to demo, impossible to verify, and
  the framework hides control flow. Rejected for v1.
- **Deterministic analyzers + LLM only where meaning or prose is needed, in a plain job pipeline.**
  Chosen.
- **No LLM at all.** Cannot explain rules, write docs or plan migrations. Rejected.

## Decision

Implement Discovery, Code Analysis, Data and Diagram as deterministic analyzers; Business Rule and
Test as hybrid (deterministic candidates, LLM explanation or proposal); Documentation and
Modernization as LLM steps over verified claims only; Verification as deterministic rules plus an
LLM judge. Run them as idempotent jobs in a Postgres job table (spec §4).

## Consequences

- Graph facts are exact and cheap; Confirmed means something.
- We must write and maintain a language adapter per language, including name resolution. This is
  the hardest engineering in the project.
- The "multi-agent" label is honest about responsibilities but not about mechanism. Say so in the
  README rather than overselling.
- Agent loops (a model choosing what to read next) can be added in v2 where evals show gaps, for
  example resolving dynamic dispatch.
