# Grep baseline on the fixture (no model)

Run status: **valid**

## Against the answer key

- Recall: 20% (8/41, 95% interval 10% to 34%)
- Precision (a floor, see docs/evals.md): 27% (8/30, 95% interval 14% to 44%)
- Traps with every scorable fact found: 20% (7/35, 95% interval 10% to 36%)
- Overclaims (stronger status than the key): 0

| Kind | Precision | Recall |
|---|---|---|
| adversarial | n/a (0 of 0) | 0% (0/1, 95% interval 0% to 79%) |
| column | n/a (0 of 0) | 0% (0/1, 95% interval 0% to 79%) |
| config | n/a (0 of 0) | 0% (0/2, 95% interval 0% to 66%) |
| dead_code | n/a (0 of 0) | 0% (0/1, 95% interval 0% to 79%) |
| dependency | n/a (0 of 0) | 0% (0/3, 95% interval 0% to 56%) |
| encoding | n/a (0 of 0) | 0% (0/2, 95% interval 0% to 66%) |
| error_handling | n/a (0 of 0) | 0% (0/1, 95% interval 0% to 79%) |
| flow | n/a (0 of 0) | 0% (0/3, 95% interval 0% to 56%) |
| integration | n/a (0 of 0) | 0% (0/2, 95% interval 0% to 66%) |
| job | n/a (0 of 0) | 0% (0/2, 95% interval 0% to 66%) |
| pii | n/a (0 of 0) | 0% (0/1, 95% interval 0% to 79%) |
| provenance | n/a (0 of 0) | 0% (0/2, 95% interval 0% to 66%) |
| route | 20% (2/10, 95% interval 6% to 51%) | 100% (2/2, 95% interval 34% to 100%) |
| rule | n/a (0 of 0) | 0% (0/9, 95% interval 0% to 30%) |
| secret | n/a (0 of 0) | 0% (0/1, 95% interval 0% to 79%) |
| sql_read | 33% (3/9, 95% interval 12% to 65%) | 100% (3/3, 95% interval 44% to 100%) |
| sql_write | 29% (2/7, 95% interval 8% to 64%) | 100% (2/2, 95% interval 34% to 100%) |
| test | n/a (0 of 0) | 0% (0/1, 95% interval 0% to 79%) |
| validation | 25% (1/4, 95% interval 5% to 70%) | 50% (1/2, 95% interval 9% to 91%) |

Missed facts: T03-F1, T03-F2, T04-F1, T05-F1, T05-F2, T06-F1, T06-F2, T10-F1, T12-F1, T13-F1, T14-F1, T16-F1, T17-F1, T18-F1, T19-F1, T20-F1, T21-F1, T22-F1, T23-F1, T24-F1, T24-F2, T25-F1, T26-F1, T27-F1, T28-F1, T29-F1, T30-F1, T31-F1, T32-F1, T33-F1, T33-F2, T34-F1, T35-F1
Not scorable (no evidence): T18-F2

## Scope

The baseline only looks for: route, sql_read, sql_write, validation. Recall on those kinds alone: 89% (8/9, 95% interval 57% to 98%).

## Not analysed

- `lib/legacy_labels.js`: undecodable

Claims produced: 30 (every one Inferred; a regex hit is not a parse).
The patterns were written before the first score and are not tuned to the fixture.
