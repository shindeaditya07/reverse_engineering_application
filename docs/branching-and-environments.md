# Strata: Branches and Environments

**Version:** 0.1 (2026-11-04), **draft**
**Spec reference:** `spec.md` v0.1 §21, `build-plan.md` v0.1

ReplyDesk's version of this file ran to about 1,000 lines with full setup scripts. Those scripts
belong in the repo (Makefile, compose files, workflows) once they exist; this file keeps the rules
and the map, and points at the scripts.

---

## Part 1 — Branches

```
main     (protected; every commit is a release tag)
  └── develop  (default and integration branch; merges deploy to staging)
        └── feature/p<phase>-<short-description>
```

- Feature branches are cut from `develop` and merge back by PR with green CI.
- One branch = one deliverable from `build-plan.md`.
- `develop` → `main` by PR when a release is cut; tag `v*` on `main`.
- Branches are deleted after merge.

### Branch map

| Phase | Branch | Deliverable | Depends on |
|---|---|---|---|
| 1 | `feature/p1-repo-scaffold` | 1.1 | — |
| 1 | `feature/p1-policy-check` | 1.2 | scaffold |
| 1 | `feature/p1-claim-store` | 1.3 | scaffold |
| 1 | `feature/p1-snapshot-ingest` | 1.4 | claim-store |
| 1 | `feature/p1-evidence-resolver` | 1.5 | snapshot-ingest |
| 1 | `feature/p1-verifier` | 1.6 | evidence-resolver, policy-check |
| 1 | `feature/p1-fixture-app` | 1.7 | scaffold (pilot language decided) |
| 1 | `feature/p1-eval-harness` | 1.8 | verifier, fixture-app |
| 2 | `feature/p2-job-runner` | 2.1 | claim-store |
| 2 | `feature/p2-discovery` | 2.2 | job-runner |
| 2 | `feature/p2-lang-javascript` | 2.3 | job-runner |
| 2 | `feature/p2-call-graph` | 2.4 | lang adapter |
| 2 | `feature/p2-data-model` | 2.5 | job-runner |
| 2 | `feature/p2-code-metrics` | 2.6 | discovery |
| 3 | `feature/p3-model-gateway` | 3.1 | ADR-0004 accepted |
| 3 | `feature/p3-rule-candidates` | 3.2 | call-graph, data-model |
| 3 | `feature/p3-rule-explainer` | 3.3 | model-gateway, rule-candidates |
| 3 | `feature/p3-judge` | 3.4–3.5 | model-gateway, verifier |
| 3 | `feature/p3-review-queue` | 3.6 | claim-store |
| 4 | `feature/p4-diagrams` | 4.1 | call-graph, data-model |
| 4 | `feature/p4-doc-writer` | 4.2 | judge |
| 4 | `feature/p4-review-ui` | 4.3 | review-queue |
| 4 | `feature/p4-exports` | 4.4 | doc-writer, diagrams |
| 4 | `feature/p4-metrics` | 4.5 | review-queue |
| 5 | `feature/p5-sandbox` | 5.1 | fixture-app |
| 5 | `feature/p5-char-tests` | 5.2 | sandbox, rule-explainer |
| 5 | `feature/p5-modernizer` | 5.3 | judge, code-metrics |
| 5 | `feature/p5-pilot-run` | 5.5 | everything |

`feature/p5-sandbox` can start as soon as the fixture builds; it carries the biggest schedule risk
(build-plan risk register), so start it early in parallel.

---

## Part 2 — Environments

| | Local | CI | Staging | Private deployment |
|---|---|---|---|---|
| Purpose | Development | PR validation | Integration, live-model evals | Real client analysis |
| Trigger | `make up` | Every push | Merge to `develop` | Manual install of a `v*` release |
| Legacy inputs allowed | Fixture, open-source pilot | **Fixture only** | Fixture, open-source pilot | Client code |
| Model calls | Live (developer key) or fake | **Fake only (recorded)** | Live | Endpoint per ADR-0004 |
| Sandbox network | none | none | none | none |
| Data lifetime | Developer's choice | Per job | Wiped per eval run | Client's retention policy |

**Rules:**
- **Client code never goes to Local, CI or Staging.** Those environments only see the fixture and
  public open-source code (PRV-4.1).
- **The private deployment runs inside the client's environment**, single-tenant, with egress
  allowed only to the approved model endpoint (or none, if the model is self-hosted).
- All differences are environment variables; `.env.example` lists them all.
- No public production SaaS in v1.
