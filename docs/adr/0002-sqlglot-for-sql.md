# 0002. Read SQL with sqlglot, MySQL dialect

- Status: accepted
- Date: 2026-11-06

## Context

The Data agent (FR-4) must read `CREATE TABLE` statements and the SQL strings found in code:
which tables, which columns, which are written. Regexes break on joins, aliases, `SELECT *`
and `INSERT ... SELECT`, and a wrong "this column is never used" claim is the costly mistake.
The pilot is Node/Express, and the fixture's SQL is MySQL-flavoured.

## Decision

Add `sqlglot` (pure Python, pinned in `uv.lock`) and parse with `read="mysql"`. Take line
numbers from the parser's own identifier positions. A statement it cannot parse, or a kind it
does not read (anything but SELECT, INSERT, UPDATE, DELETE), becomes an Unknown claim instead
of a guess. Record the sqlglot version in each committed result.

## Consequences

- One dialect. PostgreSQL, SQL Server or Oracle code needs a per-app dialect setting; until
  then a statement that only another dialect accepts is Unknown, visibly.
- A parser upgrade can change what parses, so results are tied to the version and a bump needs
  a re-run.
- No new native build. Dependency Audit (pip-audit) covers it like the others.
- sqlglot parses SQL it is given; it never runs it and never connects to a database.
