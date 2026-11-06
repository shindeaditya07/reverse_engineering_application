# Discovery on the fixture (no model)

- Recall on Discovery's kinds (dependency, encoding, integration, job, provenance): 80% (8/10, 95% interval 49% to 94%)
- Precision: 100% (8/8, 95% interval 68% to 100%) (a floor: the key lists only the trap facts)
- Missed facts: T03-F2, T24-F2
- Unmatched claims: none
- Overclaims: 0
- Findings blocked by the verifier: 0 of 8

## Per kind

- dependency: recall 50% (1/2, 95% interval 9% to 91%); precision 100% (1/1, 95% interval 21% to 100%)
- encoding: recall 100% (2/2, 95% interval 34% to 100%); precision 100% (2/2, 95% interval 34% to 100%)
- integration: recall 100% (2/2, 95% interval 34% to 100%); precision 100% (2/2, 95% interval 34% to 100%)
- job: recall 50% (1/2, 95% interval 9% to 91%); precision 100% (1/1, 95% interval 21% to 100%)
- provenance: recall 100% (2/2, 95% interval 34% to 100%); precision 100% (2/2, 95% interval 34% to 100%)

## Inventory

- Languages: 2 JSON, 27 JavaScript, 1 SQL
- Entry point (package.json main): app.js; scripts: start, test
- Declared dependencies: express, mysql
- Generated: generated/api_client.js; vendored: vendor/tinyid.js

## Not analysed

- `lib/legacy_labels.js`: undecodable

The patterns were written after the fixture was read, so this score is optimistic.
Routes, call graphs and data flow are Code Analysis, not Discovery.
