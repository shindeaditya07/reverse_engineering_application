# Data agent

`services/data/` is FR-4: deterministic, no model. It reads `CREATE TABLE` statements and the
SQL in the code, and states tables, relations, which code reads and writes which column, and
which columns nothing touches. `python -m services.data [--out evals/results]` runs it on the
fixture, verifies every finding and scores it against the reviewed key ([evals.md](evals.md)).

## What it produces

| Kind | Finding | Status |
|---|---|---|
| `table` | A table with its columns and primary key, citing the `CREATE TABLE` | Confirmed |
| `relation` | A declared foreign key (inline or table level) | Confirmed |
| `relation` | `customer_id` next to a `customers` table with an `id`, and no foreign key | Inferred: the name suggests it, nothing declares it |
| `sql_read` / `sql_write` | One statement: its verb, tables and columns | Confirmed when the text is in the code; Inferred when a table name was passed in from a caller |
| `sql_write` | A column written from two or more places, counting the schema default when an `INSERT` leaves the column out | Inferred: "no other writer" is an absence claim |
| `column` | A schema column no statement refers to | Inferred, and only when every statement was resolved |
| `unresolved` | SQL computed at run time, SQL it cannot parse, a table name it cannot follow, a schema file that does not parse | Unknown (CLM-1.4, CLM-1.7) |

The **ER model** (`DataAnalysis.er`, `ErModel.as_dict()`) is the same schema data as plain JSON
for the Diagram agent. It is not a claim.

## How a statement is resolved

The first argument of `x.query(...)`, `x.queryAsync(...)` or `x.execute(...)` is evaluated as a
string: a literal, a `+` chain, a template, a constant declared once in the same file, or a
parameter. A parameter is followed one step: every call site of the function (through a
`require` alias, a destructured import or a local call) must pass a string, and each distinct
value gives its own claim. Anything else becomes a `__dynN__` token. A token in a value
position (`status = '` + x + `'`) is stated in the claim ("part of the statement text is
computed at run time and concatenated in") and the statement is still read. A token where a
table belongs makes the claim Unknown.

A call on a first-party module counts only if that module defines a function of that name
(`db.query` yes, `reports.query` no). A call on a database driver whose SQL is a plain
parameter (`pool.query(sql, ...)` inside `lib/db.js`) is **plumbing**: it is listed in the
report and its callers carry the claims.

## Personal data

`pii.py` runs the ingest scanner's personal-data patterns (SEC-1.5) over data-like text files
(`.json .ndjson .csv .tsv .sql .txt .yml .yaml .xml`) that are not vendored or generated. A file
with a match gets one **Inferred** `pii` claim (`data:pii:<path>`) that names the kinds and the
lines: e-mail addresses, phone numbers, SSN-like and card-like numbers, and fields named like
personal data. **The values are never repeated.** Source code is not scanned: a fake address in a
test is not sample data.

Two things to know when reviewing one:

- **The claim cites a line that matches nothing**, the nearest before the first match. A cited
  line with personal data would make V-9 withhold the claim, so the evidence cannot be the lines
  the claim is about; their numbers are in the text. If every line matches, the claim has no
  evidence and is stored Unknown. Whether V-9 should allow a masked excerpt is a rules question,
  not decided here.
- **The scanner does not find names or free-text addresses** under a plain field name. The
  fixture's names are found only because the same records hold e-mail addresses. The claim says
  the file may hold more.

## What it does not do

- **Names and free-text addresses as personal data.** See "Personal data" below.
- **Query builders it cannot see through.** The fixture's ORM works because one function
  receives the table name as a literal. A builder that assembles columns or tables from data
  gives Unknown claims, which is the right answer and a lot of review work on a real app.
- **Stored procedures, views, triggers, migrations as the source of truth.** Only `CREATE
  TABLE` statements in `.sql` files are read. A schema built by migration code is not found,
  and the report cannot tell that apart from a database with no tables.
- **Lineage is column-level and static.** It says which statements touch a column, not which
  values flow where, and not which runs happen.
- **Data flow in JavaScript** (FR-3) is still not built; this agent follows constants and one
  call level, nothing more.
- **A constant declared twice** in one file (shadowing) is treated as unresolvable, and so is a
  constant defined in another file.

## Reading the score

- Recall and precision cover three kinds (6 key facts), so every interval is wide.
- **Precision is a floor.** The key lists six data facts; the fixture has sixteen statements,
  six multi-writer columns and more. The rest are real, so the report shows 26%. I read the
  unmatched claims in the result and found none that were wrong, but that was one reader, once.
- **The analyzer was written after the fixture was read.** Recall of 6/6 shows the approach can
  find these, not how it does on another app. The pilot is the real test.
- The analyzer sources (`agent.py`, `schema.py`, `sql.py`) are fingerprinted and a test fails if
  they change without a re-run committed under `evals/results/`.

## Storing

`services/data/store.py` verifies each finding and stores it through the claim writer
([claims.md](claims.md)) as `data@1`. The worker queues it as the `data` job ([worker.md](worker.md)); it needs no other agent's claims, so no order is enforced.
