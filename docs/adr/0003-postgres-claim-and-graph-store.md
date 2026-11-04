# 0003. Postgres holds claims, evidence and the graph

- Status: proposed
- Date: 2026-11-04
- Blocks: build-plan 1.3

## Context

We store snapshots, symbols, call and data-flow edges, schema facts, claims with evidence,
verification results, review decisions, artifacts, an audit log and jobs. Claims, edges and
review decisions must change together transactionally, and the audit log must be append-only.

## Options

- **Postgres only**, graph as `nodes`/`edges` tables, traversal with recursive CTEs. One database
  to secure, back up and run inside a private environment.
- **Postgres + Neo4j** for the graph: nicer graph queries, but a second store to keep consistent
  and secure, for graphs that at v1 scale (one repo, ≤200k LOC) fit comfortably in Postgres.
  [Likely; measure on the pilot.]
- **Files (JSON/SQLite per run):** simple, but weak for concurrent review and audit.

## Decision

Postgres 16 only. Graph queries live in one module with tests. Revisit if a traversal needed by
the UI or the modernizer exceeds a few seconds on the pilot.

## Consequences

- One transactional boundary for claims, evidence and review.
- Recursive CTEs are harder to read than Cypher; keep them in one place.
- Matches ReplyDesk's operational model (one Postgres, DB-backed jobs).
