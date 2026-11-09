# Diagram agent (FR-6, OUT-1)

Status: built for Phase 3 item 4. No model is involved; diagrams are drawn from stored claims only.

## How it works
1. `load.py` reads a run's claims from the claim store. Unknown and withheld claims are never drawn.
   `--accepted-only` also drops claims a human has not accepted.
2. `extract.py` parses the claim templates the analyzers write (tables, relations, SQL access,
   routes, HTTP/socket/timer calls, async flows). A contract test fails if an analyzer changes a
   template. Claims that do not parse, including edited free-text claims, are listed under
   "Not drawn" with the reason.
3. `render.py` builds Mermaid: an ER diagram, an architecture flowchart (files, tables, outbound
   calls) and one workflow flowchart per flow claim. Inferred claims are dashed and labelled
   "(inferred)".
4. Every node and edge carries the keys of the claims that support it (OUT-1.1); the builder raises
   if none are given. `diagrams.map.json` holds the mapping.
5. `diagrams.md` opens with the snapshot hash, run ID and date (OUT-1.2).

## Running it
`python -m services.diagram RUN_ID [--accepted-only] [--out DIR]`

## Limits
- ER attribute type is the literal word `column`; claims do not state types.
- The call graph is not used: call edges are not claims.
- No sequence diagram yet (FR-6 names one).
- Labels are sanitised so legacy names cannot inject Mermaid syntax.
- `scripts/check_mermaid.mjs` runs the real Mermaid parser. It is not run in CI; the test that uses
  it is skipped unless `MERMAID_DIR` points at an install of mermaid and jsdom.
