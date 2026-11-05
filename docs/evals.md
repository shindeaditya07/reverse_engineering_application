# Eval harness

`services/evals/` measures output against the reviewed answer key before any model is
involved (spec section 19). It has four parts and one command.

| Part | What it does |
|---|---|
| `score.py` | Precision and recall per claim kind, overall, and per trap, each with a Wilson 95% interval; overclaims; what was missed |
| `runner.py` | Runs an analyzer over units of work and says whether the run is valid |
| `verifier_eval.py`, `corpus.py` | Catch rate on the seeded bad claims, false-block rate on the good ones (VER-1.4) |
| `results.py` | Writes `evals/results/YYYY-MM-DD-<run-id>/` with `report.md` and `manifest.json` |

`make eval-smoke` (`python -m services.evals smoke`) is the CI smoke eval. It calls no model.
It fails, and so fails the `Eval Smoke` job and the staging deploy, if the verifier misses
a seeded bad claim or if the scoring pipeline gives a wrong answer for two runs whose score
is known: a run that copies the key (must be 100%, no overclaims) and an empty run (must be
0%). **It does not show that any analyzer is good.** None exists yet; `make eval`, the live
eval, is Phase 3 and still fails on purpose.

## What the scores mean

A produced claim matches a key fact when it has the same kind and one of its cited places
overlaps one of the fact's places. Matching is one to one, greedy in claim-ID order, largest
overlap first.

- **Recall is exact for the key.** The key lists the true facts for 35 traps, not every fact
  in the fixture.
- **Precision is a floor.** A true claim the key does not list counts against it.
- **An overclaim** is a matched claim with a stronger status than the key's.
- **A fact with no evidence cannot be matched by place** and is listed as not scorable
  (today one: T18-F2, an Unknown). It is never counted either way.
- **Small samples say little.** The key has 41 scorable facts across 19 kinds, so most kinds
  have one to three facts. A perfect kind with one fact has a 95% interval of 21% to 100%.
  Read the overall rows; the per-kind rows only show where to look.

## Valid and invalid runs

A unit of work that raises, including a timeout, is a failure. Failures are counted on their
own and never turned into an empty result. Any failure makes the run invalid, not a pass,
and three in a row stop it (AGENTS.md section 10). The failure records the exception type
only, never its message, since a provider message can echo a prompt. "Three in a row" is not
a number in `rules.md`, so it is a constant in `runner.py`, not in `rules_constants.yaml`.

## Results folder

Real runs go to `evals/results/YYYY-MM-DD-<run-id>/` and are committed with the model and
prompt hashes (`manifest.json` also records the commit and the answer-key hash). A run ID is
used once; reusing it is an error. The smoke eval prints to the terminal and writes a folder
only when you pass `--out`; do not commit those. The README eval table stays empty until a
real run exists.

## Not here yet

- **Coverage (REV-3.1), accuracy (REV-3.2 to 3.4), reviewer minutes and model cost** need the
  database, the review CLI and a model. They come with those components.
- **Characterization-test counts (TST-1.5)** come with the sandbox.
- **The grep baseline** (build-plan step 10) is its own PR. Agents must beat it.
- **Corpora grow to 150 each before v1** (spec section 19); they are 50 and 50 now.
