# 0004. Model hosting and data residency

- Status: **accepted for the fixture and open-source pilot only (2026-11-04); open for client installs**
- Date: 2026-11-04
- Blocks: build-plan 3.1 (ModelGateway) and every LLM step

## Context

The constraint "the code stays in a secure, private environment" collides with any hosted model
API: the excerpts we send leave the environment. This is the decision most likely to change the
product, so it is made before the model layer is built, not discovered later.

Second force: the judge must fail differently from the producer. ReplyDesk planned a judge from a
different provider (its ADR-0003), but the measured run used the same provider for both, which
weakened the check. Plan for independence that survives cost and availability pressure.

## Options

1. **Hosted API with contractual zero data retention / no training** (enterprise terms from a
   major provider), excerpts only, secret-scanned, through an egress allowlist. Best quality.
   Code leaves the environment in transit, under contract.
2. **Hosted model inside the client's own cloud account** (e.g. a provider's model served through
   the client's cloud tenancy). Code stays in the client's cloud boundary. Quality close to 1;
   setup per client.
3. **Self-hosted open-weight model** on the client's hardware. Code never leaves. Lower quality on
   rule explanation and prose, real GPU cost; accuracy targets must be re-measured.
4. **Mixed:** self-hosted for anything touching raw excerpts (rule explainer, test proposer),
   hosted for steps that see only verified claims (doc writer, modernizer). Claims still contain
   excerpts, so this only helps if prose steps are given redacted claims.

## Decision

**Scope accepted 2026-11-04: the fixture application and one open-source pilot application, both
public code.** For this scope, use option 1: a hosted API with zero-data-retention / no-training
terms. The code is public, so the "stays private" constraint does not apply to it, and the
README says so plainly.

**Not decided: real client code.** Each private deployment must pick option 1, 2 or 3 explicitly at
install time, recorded in its own config and audit log. This project does not claim private-
environment support for hosted-model installs it has not built or measured. Quality numbers from
option 1 runs do not transfer to option 3.

Build rules that follow:
- The `ModelGateway` makes options 1 to 3 a configuration choice (AGENTS §5).
- Producer and judge use **different providers**, enforced by the gateway (it refuses the same
  model ID for both unless `JUDGE_SAME_MODEL_OK=true`). ReplyDesk's ADR-0003 planned this and the
  measured run then used one provider for both; this ADR is amended in place, with a dated note,
  if reality differs.
- Reuse the ReplyDesk gateway pattern (adapters over plain HTTPS, retries on transient errors,
  per-model circuit breaker, call records) rather than rewriting it.
- Every eval result in the README names the option, models and prompt hashes that produced it.

## Consequences

- Option 1 is fine for the fixture and an open-source pilot (nothing confidential); it may be
  unacceptable for a real client.
- If the real target is option 3, quality numbers from option 1 runs do not transfer; the README
  must say which option produced each eval result.
- The judge-independence rule (AGENTS §5) needs two models available under whichever option is
  chosen.
