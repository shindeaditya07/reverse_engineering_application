# Code Analysis on the fixture (no model)

- Recall on its kinds (dead_code, dependency, error_handling, flow, route): 100% (8/8, 95% interval 68% to 100%)
- Precision: 47% (8/17, 95% interval 26% to 69%) (a floor: the key lists only the trap facts)
- Missed facts: none
- Unmatched claims: ca:async-flow:services/orders_service.js:12, ca:route:routes/customers.js:20, ca:route:routes/customers.js:9, ca:route:routes/orders.js:11, ca:route:routes/orders.js:19, ca:route:routes/orders.js:26, ca:route:routes/orders.js:33, ca:route:routes/products.js:13, ca:route:routes/products.js:9
- Overclaims: 0
- Findings blocked by the verifier: 0 of 18
- Findings by status: 15 confirmed, 1 inferred, 2 unknown
- Call graph: 36 resolved call edges (not claims)

## Per kind

- dead_code: recall 100% (1/1, 95% interval 21% to 100%); precision 100% (1/1, 95% interval 21% to 100%)
- dependency: recall 100% (1/1, 95% interval 21% to 100%); precision 100% (1/1, 95% interval 21% to 100%)
- error_handling: recall 100% (1/1, 95% interval 21% to 100%); precision 100% (1/1, 95% interval 21% to 100%)
- flow: recall 100% (3/3, 95% interval 44% to 100%); precision 75% (3/4, 95% interval 30% to 95%)
- route: recall 100% (2/2, 95% interval 34% to 100%); precision 20% (2/10, 95% interval 6% to 51%)

## Not analysed

- `lib/legacy_labels.js`: unreadable: 'lib/legacy_labels.js' is not UTF-8; cite a byte range instead

## Reading this

- The unmatched route claims are real routes the key does not list: the key holds only the trap facts, so precision here is a floor.
- The analyzer was written after the fixture was read, so this score is optimistic.
- T03-F1 is Confirmed in the key and stated Unknown here (the path is computed, so the module loaded is not known). Matching ignores status, so it counts as found; a stronger status than the key's would be an overclaim, a weaker one is not.
- `flow` claims are structural (nested error-first callbacks, a `.then` chain, an async function with several awaits). They do not say what each step means, so the key's prose is matched by kind and span only. Value-level data flow is not built. `config` is not built either, so it is not scored.
