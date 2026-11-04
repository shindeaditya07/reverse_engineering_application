# 0004. Model hosting and data residency

- Status: **proposed — needs the owner's decision**
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

Not yet made. Recommendation: build the gateway so options 1–3 are configuration, run the
fixture and open-source pilot on option 1, and require each private deployment to pick its option
explicitly at install, recorded in its own config and audit log.

## Consequences

- Option 1 is fine for the fixture and an open-source pilot (nothing confidential); it may be
  unacceptable for a real client.
- If the real target is option 3, quality numbers from option 1 runs do not transfer; the README
  must say which option produced each eval result.
- The judge-independence rule (AGENTS §5) needs two models available under whichever option is
  chosen.
