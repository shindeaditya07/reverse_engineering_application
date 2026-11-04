# Database (claim store)

Schema for spec section 10. Models: `services/db/models.py`. Migration: `migrations/versions/0001_initial_claim_store.py`. Apply with `make migrate` against `DATABASE_URL`; a migration is never run at API startup.

## Rules enforced by the database
| Rule | How |
|---|---|
| REV-1.1 no acceptance without a decision | no "accepted" column exists; a claim is accepted only through `review_decisions` (test checks no column name contains "accept") |
| REV-1.2 decisions append-only | trigger on `review_decisions` (no UPDATE, DELETE, TRUNCATE) |
| NFR-5 audit append-only | same trigger on `audit_log` |
| CLM-1.5 claims versioned | same trigger on `claim_versions`; text and status live there |
| CLM-1.2 model alone never Confirmed | CHECK `confirmed_not_model_only` |
| EVD-1.1 Confirmed or Inferred needs evidence | deferred constraint trigger, checked at commit |
| EVD-1.4 span at most 40 lines | CHECK `file_range_valid`; the literal 40 is tested against `rules_constants.yaml` |
| jobs idempotent | unique (`run_id`, `job_type`, `input_hash`) |
| `model_calls` hold no text | only hashes and counts, by column design |

## Tests
`tests/test_db_schema.py` needs Postgres at `DATABASE_URL`. Locally they skip when it is unreachable; CI sets `REQUIRE_DB=1`, so an unreachable database is a failure, never a pass.

Local database (Docker):

```bash
docker compose up -d db
```

```bash
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/platform make migrate
```

## Caveats
- Tests run in a rolled-back transaction, so they leave no rows. Append-only means test data in a committed database could never be deleted; do not point tests at a database you care about.
- To change the schema, add migration 0002; never edit 0001 after it is applied anywhere.
