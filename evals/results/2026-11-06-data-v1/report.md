# Data agent on the fixture (no model)

- Recall on its kinds (column, sql_read, sql_write): 100% (6/6, 95% interval 61% to 100%)
- Precision: 26% (6/23, 95% interval 13% to 46%) (a floor: the key lists only the trap facts)
- Missed facts: none
- Unmatched claims: data:lineage:customers.email, data:lineage:customers.loyalty_tier, data:lineage:customers.name, data:lineage:orders.updated_at, data:sql:db/seed.js:7, data:sql:jobs/nightly.js:7, data:sql:routes/customers.js:14, data:sql:routes/customers.js:21, data:sql:routes/orders.js:34, data:sql:routes/orders.js:38, data:sql:routes/products.js:14, data:sql:services/notify.js:11, data:sql:services/notify.js:9, data:sql:services/orders_service.js:28, data:sql:services/orders_service.js:33, data:sql:services/orders_service.js:39, data:sql:services/reports.js:10
- Overclaims: 0
- Findings blocked by the verifier: 0 of 27
- Findings by status: 18 confirmed, 9 inferred
- Schema: 3 tables, 1 relations; 16 SQL statements resolved

## Per kind

- column: recall 100% (1/1, 95% interval 21% to 100%); precision 100% (1/1, 95% interval 21% to 100%)
- sql_read: recall 100% (3/3, 95% interval 44% to 100%); precision 33% (3/9, 95% interval 12% to 65%)
- sql_write: recall 100% (2/2, 95% interval 34% to 100%); precision 15% (2/13, 95% interval 4% to 42%)

## Not analysed

- `lib/legacy_labels.js`: unreadable: 'lib/legacy_labels.js' is not UTF-8; cite a byte range instead
- `lib/db.js` line 9: a driver call whose SQL is a parameter; its callers are analysed
- `lib/db.js` line 14: a driver call whose SQL is a parameter; its callers are analysed

## Reading this

- The unmatched claims are mostly real statements and columns the key does not list: the key holds only the trap facts, so precision here is a floor.
- The analyzer was written after the fixture was read, so this score is optimistic.
- Not built yet, so not scored: `pii` (personal data in sample files).
