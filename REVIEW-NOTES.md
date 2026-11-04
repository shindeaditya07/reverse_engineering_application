# How these base docs map to ReplyDesk

Source studied: `shindeaditya07/triage_automation_ecommerce` (ReplyDesk), founding commits
`5954ad6` (README, 2026-10-18) and `0013734` (docs, 2026-10-19), plus the ADRs written in Phase 2.

| ReplyDesk | Here | Change and why |
|---|---|---|
| README first | `README.md` | Same role. Shorter: no badges or setup steps until code exists. |
| `docs/spec.md` (23 sections, FR table, precedence) | `docs/spec.md` | Same 23-section skeleton. Ticket schema → snapshot + **claim** schema; grounding G-1..G-10 → verification V-1..V-10; escalation → review queue; mock store's 31 edge cases → **fixture legacy Node.js app with 33 traps and an answer key**; time semantics → snapshot semantics. |
| `docs/policies.md` (store rulebook, stable IDs RET-1.1) | `docs/policies.md` | Same idea, different domain: the rulebook is now evidence (EVD), tags (TAG), safety (SAF), privacy (PRV), review (REV), outputs (OUT), tests (TST), modernization (MOD). Claims cite these IDs as drafts cited RET/REF. |
| `policy_constants.yaml` + SHA lock | `policy_constants.yaml` | Same mechanism. |
| `docs/AGENTS.md` (binding rules, safety invariants first) | `docs/AGENTS.md` | Same 15-section skeleton. Invariants rewritten for read-only legacy code, no production contact, sandbox-only execution, tags only go down. This is the coding-standards doc. |
| Stack in spec §10 + README table | `docs/tech-stack.md` | New file, because you asked for it and the analysis toolchain needs reasons per tool. Spec and README link to it instead of repeating it. |
| `docs/build-plan.md` (5 phases, eval harness first) | `docs/build-plan.md` | Same principle, plus "deterministic analysis before LLM analysis". |
| `docs/branching-and-environments.md` (~1,000 lines) | same name, ~100 lines | Kept the rules and branch map; setup scripts belong in the repo once they exist. |
| ADRs named as open items, written during Phase 2 | `docs/adr/0000`–`0005` | Written now as **proposed**, because 0004 (model hosting) and 0005 (sandbox) decide whether the constraints can be met at all. |
| `docs/replydesk-agent-guide.md` (stale duplicate of AGENTS.md) | — | Not repeated. One rules file. |
| Spec cites `spec-amendments.md`, which is not in the repo | — | Rule added: never reference a document that is not committed. |
| ADR-0003 original choice not what shipped; judge ended up the same provider | ADR-0004, AGENTS §5 | Judge independence enforced at the gateway; ADRs amended in place with dated notes. |
| Eval report needed `CORRECTION.md` (evaluator miscounted) | spec §13.4, AGENTS §6 | The evaluator and metric scripts get their own tests. |
