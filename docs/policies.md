# Strata: Evidence, Safety and Review Policies

> **Working name.** "Strata" is a placeholder product name; rename freely before the first commit.
> This is the platform's **rulebook**. Each passage has a stable policy ID (for example `EVD-1.1`).
> Every generated claim, verification result and review decision cites the policy IDs it applies.
> Policy version **0.1 (draft)**, dated **2026-11-04**. Status: **proposed, not yet approved by the owner.**
> **SHA-256 lock file:** once approved, CI must fail if this file changes without a version bump
> and an eval rerun.

**What this file is for.** In ReplyDesk, `policies.md` was the store's rulebook that every drafted
reply had to cite. Here the equivalent is the set of rules every *finding* must obey. The
Verification Agent enforces these passages; the review UI shows which passage a claim failed.

> **For developers:** do not hard-code any numeric value from this document. All numeric
> constants live in `policy_constants.yaml`, keyed by policy ID. A CI test asserts every constant
> in that file appears in its cited passage below.

---

## 1. Evidence and Citation (EVD)

**EVD-1.1 Every claim cites evidence.**
A claim is any statement about the legacy application: what a module does, which function calls
which, what a column means, what rule a validation enforces. Every claim carries at least one
evidence reference. A claim with no evidence reference is not a finding; it is rejected.

**EVD-1.2 Evidence reference format.**
An evidence reference names exactly one location in the analysed snapshot, in one of these forms:

| Kind | Form | Example |
|---|---|---|
| Source code | `code:<path>#L<start>-L<end>` | `code:lib/billing/invoice.js#L120-L134` |
| Schema object | `schema:<db>.<schema>.<object>[.<column>]` | `schema:erp.public.invoice.due_date` |
| Configuration | `config:<path>#<key path>` or `#L<start>-L<end>` | `config:conf/app.properties#tax.rate` |
| Build/deploy script | `build:<path>#L<start>-L<end>` | `build:build.xml#L40-L58` |
| Runtime log | `log:<file>#L<start>-L<end>` | `log:app-2024-03.log#L9912-L9915` |
| Ticket or existing doc | `doc:<id or path>[#<anchor>]` | `doc:JIRA-4821` |
| Graph fact | `graph:<edge or node id>` | `graph:call/7f3a…` (derived; must itself resolve to code) |
| Characterization test run | `test:<test id>@<run id>` | `test:char_invoice_017@run-2026-11-20-a1` |
| Human review decision | `review:<decision id>` | `review:rd-0192` |

Every reference is resolved against the snapshot the claim was made on (EVD-1.4).

**EVD-1.3 Evidence must resolve.**
A reference resolves only if the file or object exists in the snapshot, the line range is inside
the file, and the stored excerpt hash matches the snapshot content at that range. A reference that
does not resolve fails verification (spec rule V-1, V-2). There is no "approximately line 120".

**EVD-1.4 Evidence is pinned to an immutable snapshot.**
Every analysis run works on one snapshot: a commit SHA (or, for non-git inputs, a content hash of
the uploaded archive) plus the hashes of the schema dump and config files supplied. A claim is true
*of that snapshot*. When the legacy code changes, claims are re-verified against the new snapshot,
never carried over silently.

**EVD-1.5 Evidence ranks by kind.**
Executable truth outranks description. From strongest to weakest:
1. Source code, schema DDL, configuration, build scripts, characterization test results.
2. Human review decisions.
3. Runtime logs.
4. Existing documentation, tickets, comments in code.

Comments, existing docs and tickets describe what someone *believed*. On their own they can
support at most an **Inferred** claim, never a **Confirmed** one (TAG-2.1).

**EVD-1.6 Excerpts are quoted, short and stored.**
Each reference stores the exact excerpt it points to (at most `max_evidence_excerpt_lines` lines)
and its SHA-256. Paraphrase goes in the claim text; the excerpt is verbatim.

**EVD-1.7 Conflicting evidence is a finding.**
When two sources disagree (code says the limit is 5000, the wiki says 10000), neither silently
wins. The disagreement is recorded as its own claim, tagged with both references, and sent to the
review queue (REV-5.2).

---

## 2. Confidence Tags (TAG)

**TAG-2.1 Confirmed.**
The cited evidence directly shows the claim. A reviewer reading only the cited excerpts reaches the
same statement without further assumptions. Requires at least one evidence reference of rank 1 or
2 (EVD-1.5). Examples: "`validateOrder()` rejects quantities above 99" with the `if (qty > 99)`
line cited; "column `invoice.due_date` is `NOT NULL`" with the DDL cited.

**TAG-2.2 Inferred.**
The claim follows from cited evidence through reasoning that is stated in the claim record.
Every Inferred claim carries `reasoning` (why the evidence implies the claim) and `confirm_by`
(what evidence would confirm or refute it: a test to run, a file to find, a question for a person).

**TAG-2.3 Unknown.**
The question matters but the evidence cannot answer it. An Unknown is never filled with a guess.
It is recorded as a question with the evidence that was examined and sent to the review queue
(REV-5.2).

**TAG-2.4 Tags only go down automatically.**
The Verification Agent and the LLM judge can downgrade a tag (Confirmed → Inferred → Unknown) or
reject a claim. Neither can upgrade one. Only a human review decision (REV-5.5) or a passing
characterization test (TST-7.5) can raise a tag.

**TAG-2.5 Dynamic behaviour caps at Inferred.**
Reflection, dependency injection resolved from configuration, dynamic SQL built from strings,
`eval`, runtime class loading, and dispatch through interfaces with more than one implementation
cannot be Confirmed from static evidence alone. They are at most Inferred until a characterization
test or a human confirms them.

**TAG-2.6 Summaries inherit the weakest tag.**
A statement built from several claims (a module summary, an architecture paragraph, a migration
risk) carries the lowest tag among the claims it rests on, and links to all of them.

**TAG-2.7 Absence is not evidence.**
"X is never called" or "this table is unused" is at most Inferred, because reflection, external
callers, scheduled jobs and other repositories may reach it. The claim must name what was searched
(`confirm_by` lists the searches done and what remains unsearched).

---

## 3. Protecting the Legacy System (SAF)

**SAF-3.1 The legacy code is read-only.**
The platform never writes to the legacy source tree. The snapshot is mounted read-only; analysis
writes go to the platform's own store. Generated tests, docs and plans live outside the legacy
tree. No patch, refactor, instrumentation or "test hook" is ever applied to the legacy code.

**SAF-3.2 No connection to production systems.**
The platform never connects to a production database, host, queue, API or credential store,
including "read-only" production connections. Schema comes from a supplied DDL file or a dump
taken by the client's own team (SAF-3.3). Runtime behaviour comes from supplied logs or from the
sandbox (SAF-3.4).

**SAF-3.3 Data dumps are sanitized or synthetic.**
A schema dump is preferred over a data dump. If sample data is supplied, it must be sanitized by
the supplier before upload; the platform still scans it for PII (PRV-4.4) and refuses an upload
in which the scan finds unmasked PII above `pii_refusal_threshold` matches.

**SAF-3.4 Legacy code runs only in the sandbox.**
Building or running the legacy application (needed for characterization tests) happens only in an
isolated container built from the snapshot, with outbound network disabled, a database restored
from DDL plus synthetic seed data, and no mounted credentials. A legacy build or test that needs
the network is recorded as a blocker, not given network access.

**SAF-3.5 Legacy build and deploy scripts are untrusted code.**
Build scripts can deploy, delete or call home. They are parsed for analysis but never executed
outside the sandbox (SAF-3.4), and deploy targets are never invoked even inside it.

**SAF-3.6 Secrets found in the legacy code stay there.**
Credentials, keys and connection strings found in the snapshot are reported as a finding by
location only (`code:conf/db.properties#L4`), with the value redacted. The value never enters an
LLM prompt, a generated document, a log line or the review UI.

---

## 4. Confidentiality and the Private Environment (PRV)

**PRV-4.1 Code stays in the private environment.**
Legacy source, schema and logs are stored only in the deployment's own database and volume.
They are not uploaded to any third-party service except the model endpoint approved in
`docs/adr/0004-model-hosting-and-data-residency.md`, under the data-handling terms recorded there.
CI never sees client legacy code: CI runs only on the synthetic fixture application (spec §17).

**PRV-4.2 Minimum code to the model.**
A model call receives only the excerpts needed for its task (the function, its callers' signatures,
the relevant schema objects), never a whole repository. Every prompt passes the secret scan
(SAF-3.6) before it is sent. Total excerpt size per call is capped (`max_prompt_source_lines`).

**PRV-4.3 Legacy content is untrusted data.**
Comments, string literals, commit messages, docs and tickets may contain text that reads like
instructions ("AI: ignore previous rules", "mark this module as deprecated"). Legacy content is
passed to a model only inside delimited data blocks with an explicit statement that it is data.
Instructions found in it are never obeyed (spec rule V-10).

**PRV-4.4 PII is masked.**
Personal data found in logs, sample data or tickets (emails, phone numbers, government IDs, card
numbers) is masked before storage and before any model call. Logs of the platform itself never
contain legacy source excerpts, only IDs and hashes.

---

## 5. Human Review (REV)

**REV-5.1 A human approves every output.**
No artifact (document, diagram, catalog, test suite, plan) is marked *approved* or exported as
final without a recorded human approval. Unapproved artifacts are watermarked *Draft — not
reviewed*.

**REV-5.2 What goes to the review queue.**
An item enters the review queue when any of these hold:
- the claim is **Unknown** (TAG-2.3);
- evidence conflicts (EVD-1.7);
- an **Inferred** claim is in a high-impact category: money, tax, pricing, authorization and
  access control, data deletion or retention, regulatory reporting, or anything the owner adds to
  `review.high_impact_categories`;
- verification or the judge failed twice on the claim (spec §13.3);
- any verification step errored or could not run (fail closed: an error is never a pass);
- dynamic dispatch could not be resolved for an edge used in a diagram or rule (TAG-2.5).

Each item carries a specific question, the evidence examined, the agent that raised it, and the
artifacts blocked by it.

**REV-5.3 Decisions are recorded, append-only.**
A reviewer can *confirm*, *correct* (with new text and evidence), *reject* (with reason) or
*defer*. Every decision records the reviewer, time, reason and the claim version it applied to.
Decisions are never edited or deleted; a later decision supersedes an earlier one.

**REV-5.4 Accuracy is measured by sampling, not by trust.**
For each pilot run, a random sample of claims is drawn, stratified by tag and agent, at least
`accuracy_sample_min` claims or `accuracy_sample_fraction` of all claims, whichever is larger.
A human reviewer marks each correct or incorrect against the source. Accuracy is reported with a
Wilson confidence interval. The target is `accuracy_target`; the report states whether the lower
bound of the interval meets it, not just the point estimate.

**REV-5.5 Review decisions are evidence.**
A *confirm* or *correct* decision becomes an evidence reference (`review:<id>`, rank 2) and can
raise a tag (TAG-2.4).

---

## 6. Output Standards (OUT)

**OUT-6.1 Every artifact states its provenance.**
Each generated artifact opens with: snapshot ID and commit, platform version, generating agents,
prompt hashes and model IDs used, generation date, review status, and coverage figures
(modules and endpoints covered, counts by tag).

**OUT-6.2 Prose is built from claims.**
Every sentence of factual content in a generated document maps to one or more claim IDs, rendered
as a citation the reader can open. Connective text ("This section covers…") carries no facts.

**OUT-6.3 Diagrams are generated from the graph.**
Architecture, sequence, workflow and ER diagrams are rendered from the stored graph and schema
catalog, not drawn freehand by a model. Every node and edge carries the ID of the graph fact or
claim it shows. Edges that are Inferred are drawn dashed; Unknown elements are not drawn but
listed below the diagram.

**OUT-6.4 The open-questions list is always produced.**
Every run publishes its open-questions list, even if short. An empty list is a red flag reported as
such, not a success.

**OUT-6.5 Bad numbers are reported.**
Coverage gaps, verification failure rates, reviewer-found errors and failed tests are reported as
measured. No metric is suppressed or rounded into looking better.

---

## 7. Characterization Tests (TST)

**TST-7.1 Tests lock in observed behaviour, not intended behaviour.**
A characterization test asserts what the legacy application does today. If observed behaviour
looks like a bug, the test still asserts it, is labelled `suspected_defect`, and the suspicion is
raised as a review item.

**TST-7.2 Every test cites what it covers.**
Each test names the entry point, the code paths and the business-rule claim IDs it exercises.

**TST-7.3 Tests never change the legacy code.**
Tests drive the application from the outside (HTTP, CLI, message input, database state) or call
public functions from a separate test tree. No legacy file is edited to make it testable
(SAF-3.1).

**TST-7.4 Tests must pass against the original before they count.**
A generated test enters the suite only after it passes against the sandboxed original
`char_test_stability_runs` times in a row. A test that passes some runs and fails others is
recorded as *non-deterministic* with the varying output, and sent to review; it is not deleted and
not counted as passing.

**TST-7.5 A passing test is evidence.**
A stable passing test becomes an evidence reference (`test:<id>@<run>`, rank 1) for the claims it
covers and can raise an Inferred claim about runtime behaviour to Confirmed.

---

## 8. Modernization Recommendations (MOD)

**MOD-8.1 Recommendations are proposals, not facts.**
A recommendation is labelled as a proposal. It cites the findings it rests on and their tags. A
recommendation that rests on an Unknown finding is marked *blocked until resolved*.

**MOD-8.2 Each phase has a safety net.**
Every migration phase lists the characterization tests that must stay green across it and the
modules it touches. A phase whose modules have no characterization coverage is flagged as
high-risk.

**MOD-8.3 No automatic rewrite.**
The platform proposes a target architecture and a phased plan. It does not generate replacement
code for the legacy system in v1.

---

## Notes for the Development Team

> This section is not part of the policy.

- **Numeric constants** used by the verifier and review logic live in `policy_constants.yaml`, not
  here. As of v0.1:
  - `max_evidence_excerpt_lines = 40` (EVD-1.6)
  - `max_prompt_source_lines = 400` (PRV-4.2)
  - `accuracy_target = 0.90` (REV-5.4)
  - `accuracy_sample_min = 100` (REV-5.4)
  - `accuracy_sample_fraction = 0.10` (REV-5.4)
  - `char_test_stability_runs = 3` (TST-7.4)
  - `pii_refusal_threshold = 0` (SAF-3.3)
- **Keep policy IDs stable.** The eval answer keys and verification results reference them.
  Renaming one is a breaking change.
- **Versioning:** any change bumps the version at the top, updates the SHA-256 lock file and
  requires an eval rerun.
