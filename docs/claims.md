# Claim writer

`services/claims/` is the one place an analyzer's claims enter the store. `verify_and_store` runs V-1 to V-10 on a claim and then `store_claim` writes it in the caller's transaction: the claim, its first version, its evidence rows, one row per check, a review item if it needs one, and an audit entry. `services/discovery/store.py` is the first caller.

| Rule | What the writer does | Test |
|---|---|---|
| Idempotent per run | `claims` has a stable `key` and `UNIQUE (run_id, key)`. A second write of the key returns the first and adds nothing, so a run killed halfway and resumed does not duplicate (AGENTS.md section 4). | `test_writing_the_same_key_twice_in_a_run_adds_nothing` |
| Failed means Unknown | A claim that failed any check, or is stale, is stored as `unknown` and queued as `verifier_failure` or `stale`. V-4, V-7 and V-9 failures do not demote in the verifier; the writer still refuses to let them keep a status. The requested status stays in the audit entry. | `test_a_claim_that_fails_without_being_demoted_still_cannot_stand` |
| No secret stored | A V-9 failure means the text matched a secret or personal-data pattern. A fixed placeholder is stored instead; the check ID is the only trace (SEC-1.3, SEC-1.5). | `test_a_claim_holding_a_secret_is_stored_without_its_text` |
| Evidence only if it resolves | Evidence rows are written for references that resolve, with the hash computed at write time. The database refuses Confirmed or Inferred with none. | corpus test below |
| Malformed claim | A status or producer kind the schema has no value for raises `ClaimRejected` and writes nothing. That is an analyzer bug; the job fails visibly (OPS-1.1). | `test_a_claim_with_an_unknown_status_or_producer_is_rejected_unwritten` |
| Audit holds no text | IDs, kinds, check IDs and counts only (NFR-5). | covered with the secret test |

`test_no_claim_from_either_corpus_can_leave_a_confirmed_or_inferred_status_unbacked` writes all 100 verifier-corpus claims and runs the deferred evidence trigger after each, as COMMIT would.

## Not covered

- **Concurrent writers** of the same key rely on `ON CONFLICT DO NOTHING` on the unique constraint. It is not tested with two live connections: committed `claim_versions` rows cannot be deleted (CLM-1.5), so such a test would leave rows behind.
- **A run record.** The spec says every step writes one. There is no `runs` table; the `jobs` row and the audit entries are what exist. Say if you want a table.
- **Re-analysis versions.** Only version 1 is written. Stale detection on a new revision and later versions are separate work (EVD-1.3).
- **The worker.** It stores Discovery, Code Analysis and Data findings through this writer ([worker.md](worker.md)).
