# Business Rule agent (FR-5)

Status: built for Phase 3 item 2. One recorded run exists: `businessrule-v1` (qwen2.5-coder:7b).

## How it works
1. **Finder (deterministic, `candidates.py`).** Picks spans of at most 40 lines that look like
   domain behaviour: a comparison with a number or string literal, `*` `/` `%` by a number, an
   object holding two or more numbers, a `throw`, or a `res.status(4xx)`. Functions over 40 lines
   contribute their direct `if` statements. Test files are skipped; files it cannot read are
   stated as Unknown claims, never dropped (CLM-1.7).
2. **Model (`agent.py`, `prompt.py`).** For each span the local model is asked for plain-English
   WHEN/THEN rules as JSON. Legacy text goes only inside the delimited block (SEC-2.2).
3. **Claims.** Each rule is an `Inferred` claim produced by a model (CLM-1.2). Its evidence is the
   finder's span, never lines the model chose: a rule whose `line` is outside the span, empty, over
   300 characters or not an integer is discarded and counted. A failed call or unreadable reply
   becomes an Unknown claim for that span (CLM-1.4). The sentence is also the claim's explanation,
   so V-10 compares it with the cited code and may demote it.

Claim IDs: `br:<path>:<line>:<n>` (rule), `br:unexplained:<span>` and `br:unread:<path>` (Unknown).

## Running it
- `python -m services.businessrule prompts --out prompts.json` writes the 16 fixture prompts.
- `python scripts/record_replies.py --prompts prompts.json --model <name>` sends them to a local
  model and writes `recording.json`. It uses only the standard library, so it runs on plain
  Windows. It refuses non-local endpoints.
- `python -m services.businessrule run --recording recording.json` replays it with no model and
  prints the score. `live [--record FILE]` uses `MODEL_ENDPOINT` directly; never in CI (SEC-2.3).

## What the score means
- Matching is by kind and cited lines. It does not check that the sentence is true; a human
  reviews that. `rule` and `validation` facts are scored as one kind.
- The report states the **ceiling**: key facts that lie inside a candidate, found without a model
  (10 of 11 on the fixture; T17-F1 is missed because `subtotal * config.taxRate` has no literal).
- The signals were chosen after the fixture was read, and broadened once after seeing which key
  spans the first version missed. Treat fixture numbers as optimistic.
- The prompt is the benchmarked v2 prompt plus one sentence allowing `{"rules":[]}`. That
  sentence was not in the benchmark.

## Not built yet
Worker wiring (job type and queue), retry-then-demote (Phase 3 item 3), cross-file rules (a rule
split between a caller and a callee is two partial claims), and rules inside config tables.

## First recorded result (2026-11-09)
Key score: recall 7/11, precision 7/17 (floor). Hand audit: 16 of 17 sentences true, 1 false
(a flipped sign in the order total), V-10 demoted 3 true sentences. Details in
`evals/results/2026-11-09-businessrule-v1/hand-audit.md`. Re-record with the steps above after
any change to the finder or prompt; `tests/test_businessrule.py` fails until prompts.json and
the recording match.
