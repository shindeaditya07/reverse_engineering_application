# Code Analysis agent

`services/codeanalysis/` is part of FR-3: deterministic, no model. It parses first-party
JavaScript with tree-sitter and states what the syntax tree shows.
`python -m services.codeanalysis [--out evals/results]` runs it on the fixture, verifies every
finding and scores it against the reviewed key ([evals.md](evals.md)).

## What it produces

| Kind | Finding | Status |
|---|---|---|
| `route` | An Express route registration. A `forEach` over a literal list is expanded; a condition around it and the router's mount prefix are stated and cited | Confirmed when the receiver is bound to `express()` or `express.Router()` in the same file and the whole path is literal |
| `route` | A router that is never mounted | Inferred: the full path is not known |
| `route` | A path computed at run time, a loop that is not over a literal list | Unknown |
| `error_handling` | A `catch` block or `.catch(...)` callback with no statements | Confirmed |
| `dead_code` | An exported function nothing else in the snapshot references | Inferred |
| `dependency` | A `require` with a computed path (Code Analysis owns it; Discovery does not report it) | Unknown (CLM-1.4): the module loaded is not known and calls through it cannot be followed |
| `flow` | Nested error-first callbacks (two or more deep), a promise chain with two or more `.then` steps, or an `async` function with two or more `await`s | Confirmed: restates the tree (`flow.py`) |
| `unresolved` | A first-party file that did not parse, is not UTF-8, or is not JavaScript | Unknown (CLM-1.7) |

It also builds a **call graph** (`Analysis.calls`): edges between functions of the snapshot
that a call resolves to, through local names, `const x = require(...)` aliases and
destructured imports. It is returned for later agents. It is not a claim, so the verifier and
the review queue never see it.

## Flow

`flow.py` states how control passes from one asynchronous step to the next, in three shapes:

- **Callbacks.** A call whose last argument is a function with an `err`, `error` or `e` first
  parameter (optionally numbered), nested two or more deep. The claim lists the calls on the
  deepest path. A callback without an error parameter, such as `forEach`, is not counted.
- **Promise chains.** A call followed by two or more `.then` steps (`.catch` and `.finally` count
  as steps once the chain qualifies).
- **Async functions.** An `async` function with two or more `await`s that belong to it, not to a
  function nested in it. Steps are listed "in source order": a step in a loop or branch may run
  zero or many times, and the claim does not say.

These claims are structural. They do not say what a step means ("read the order"): that is not in
the tree. The answer key's prose is matched by kind and overlapping span only, so a flow "hit"
means the right function was found, not that the key's sentence was reproduced. Steps passed as
a named callback, a function stored in a variable and used later, `Promise.all`, `async.waterfall`
and event emitters are not followed. The fixture's `chargeWithRetry` is reported too (two awaits);
the key does not list it, so it counts against precision.

**Not built: value-level data flow** (where a request field ends up, which values reach a SQL
call or a response). That is a separate, larger piece and is still owed.

## How "dead" is decided, and where it is wrong

A function is reported only if it is exported by an object literal, `exports.x =` or
`module.exports.x =`, and none of these holds:

- another file reaches it by `alias.name`, by destructuring or by `require(...).name`;
- another file uses the whole module as a value (`use(require('./x'))`, `use(alias)`,
  `alias[name]`): then any name in it may be used;
- the same file uses it outside its own body and its export line;
- the file is `package.json`'s `main`, or sits where a computed `require` can reach it
  (`require('./plugins/' + name)` protects `plugins/`; a fully computed one turns every dead
  code claim off).

References from test files do not count: code only a test calls is still dead for the
application. That is a choice, stated in the claim's logic and not in its text.

It stays **Inferred**, never Confirmed: reflection, `eval` or a path built somewhere the
analyzer cannot see would defeat it, and a function reachable only from other dead functions
is not reported (one level only).

## What it does not do

- **Value-level data flow.** FR-3 asks for it. It is not built; `flow` above is control flow
  across steps only. The key's `config` facts are not attempted and not scored.
- **ES modules, TypeScript, JSX.** CommonJS and ES2022 syntax that the JavaScript grammar
  reads; a file the parser reports errors in is skipped whole and claimed Unknown. (CommonJS
  only is an open decision, not a settled one.)
- **Routes from anything but `app.get(...)`-style calls**: `app.route('/x').get(...)`,
  `router.use(path, handler)` as an endpoint, and routes added by a framework other than
  Express are not found.
- **Receivers it cannot see bound.** `const app = express()` must be in the same file as the
  route call. An app passed in as an argument gets no routes, silently. That is a gap, and a
  `no route found` case cannot be told apart from a file with no routes.
- **Shadowing.** An inner variable named like an import is treated as the import. That can only
  keep code alive (fewer dead claims), never kill it.

## Reading the score

- Recall and precision cover four kinds (5 key facts), so every interval is very wide. `dependency` is scored only for T03-F1, the one dependency fact Code Analysis owns. The key says Confirmed and the claim is Unknown (the path is computed); matching ignores status, so it counts as found, and only a stronger status than the key's would be an overclaim.
- **Precision is a floor.** The key lists two routes; the fixture has ten. The other eight are
  real, so the report shows 20% route precision and 38% overall. That says the key is thin, not
  that the claims are wrong.
- **The analyzer was written after the fixture was read.** Recall of 4/4 shows the approach can
  find these, not how it does on another app. The pilot is the real test.
- The analyzer source is fingerprinted (`analyzer_sha256`) and a test fails if it changes
  without a re-run committed under `evals/results/`.

## Storing

`services/codeanalysis/store.py` verifies each finding and stores it through the claim writer
([claims.md](claims.md)) as `codeanalysis@1`. The worker queues it as the `code_analysis` job ([worker.md](worker.md)); it needs no other agent's claims, so no order is enforced.
