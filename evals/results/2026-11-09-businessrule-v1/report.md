# Business Rule agent on the fixture

- Candidates found (no model): 16
- Key facts inside a candidate (the ceiling for recall): 10/11 (not covered: T17-F1)
- Recall on rule and validation facts: 64% (7/11, 95% interval 35% to 85%)
- Precision: 41% (7/17, 95% interval 22% to 64%) (a floor: the key lists only the trap facts)
- Missed facts: T05-F1, T17-F1, T23-F1, T33-F2
- Model rules discarded (line outside span, empty, too long): 2
- Claims blocked by the verifier: 3 of 18
- Claims by status: 17 inferred, 1 unknown

## Reading this

- Candidate signals were written after the fixture was read: optimistic.
- Matching is by kind and cited lines, not by whether the sentence is true. A human must still check the wording against the code.
