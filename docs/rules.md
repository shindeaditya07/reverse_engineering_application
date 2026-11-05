# Evidence and output rules

Version 1.2 · 2026-11-05 · draft for review · merges amendments A1 to A14 (A3 still open) · adds OPS-1.2 · source: `business-case.md` v0.1

These are the rules about how **this platform** may make statements about someone else's legacy application. They are not the legacy app's business rules; those are *outputs* (the business rules catalog). Every rule has a stable ID. Code, tests, labels and PRs cite IDs, never prose. Numbers appear here and are copied into `rules_constants.yaml` keyed by the same ID; a CI check later verifies each value appears in its cited passage.

Rule strength: **MUST / MUST NOT** are enforced by a test, lint or CI job. **SHOULD** is a default that can be overridden with a recorded reason.

## 1. Evidence (EVD)

- **EVD-1.1** A claim is one atomic statement about the legacy application. Every claim MUST carry at least one evidence reference. A claim with none MUST NOT be stored as Confirmed or Inferred; it is Unknown.
- **EVD-1.2** An evidence reference is one of: a file range (`path`, `start_line`, `end_line`), a schema object (table, column, index, constraint), a config key, a build or deploy script step, a log line, or a ticket reference. Each reference MUST resolve to bytes in the frozen snapshot.
- **EVD-1.3** Each reference stores the pinned revision (SEC-1.6) and a content hash of the cited excerpt. If the excerpt no longer matches its hash, the claim MUST be marked stale and returned to the review queue.
- **EVD-1.4** A file-range reference MUST NOT span more than 40 lines. Longer spans are split into several references.
- **EVD-1.5** Line numbers count from 1, after normalizing line endings to LF, in the decoded UTF-8 text of the snapshot file. Files that cannot be decoded are cited by byte range instead.
- **EVD-1.6** The platform MUST NOT cite generated or vendored files as evidence of authored behavior unless the claim is about that file.

## 2. Claim status (CLM)

- **CLM-1.1** Every claim MUST have exactly one status: **Confirmed**, **Inferred** or **Unknown**.
- **CLM-1.2 Confirmed** means a deterministic analysis (parser, schema reader, config reader) or a passing characterization test directly shows the statement. A language model alone MUST NOT produce a Confirmed claim.
- **CLM-1.3 Inferred** means a model or heuristic proposes the statement from cited evidence and a deterministic check found the evidence consistent with it, but nothing proves it. Inferred claims MUST be reviewed by a human before they appear in the final documentation as accepted.
- **CLM-1.4 Unknown** means the evidence is missing, conflicting or not resolvable. Unknown claims MUST go to the review queue and MUST NOT be written as statements of fact in any output.
- **CLM-1.5** A claim MUST NOT be promoted from Inferred to Confirmed by repeating or rewording it. Promotion needs new deterministic evidence or a passing test.
- **CLM-1.6** Documentation text MUST be assembled from stored claims. Any sentence in a generated document that is not backed by a claim MUST be rejected by the verifier.
- **CLM-1.8** A claim can be Confirmed by a test only if it carries a reference to that test and the test's assertion names the same input and output the claim states. A test that merely exercises the code does not confirm a claim. The reviewer sees claim and test side by side. Otherwise the claim stays Inferred.
- **CLM-1.7** The platform MUST state what it did not analyze (skipped files, unsupported languages, unreadable inputs) as claims in the open-questions list, not omit them silently.

## 3. Verification (VER)

- **VER-1.1** The verifier is deterministic code and is the authority. A model judge MAY demote a claim (Confirmed to Inferred, Inferred to Unknown) and MAY add blocks; it MUST NOT approve or promote.
- **VER-1.2** Verifier checks V-1 to V-10 are defined in the spec. Each failing check MUST name the claim ID and the check ID.
- **VER-1.3** Verification fails closed: an error, timeout or missing input is a block, never a pass.
- **VER-1.4** The verifier MUST be tested against a corpus of known-bad claims and a corpus of known-good claims. It MUST catch 100% of the seeded bad corpus. The false-block rate on the good corpus is reported with a confidence interval.
- **VER-1.5** The verifier package MUST keep at least 95% branch coverage, enforced in CI.
- **VER-1.7** Check V-10 (explanation consistent with evidence) is a heuristic. It MAY demote a claim to Unknown when its overlap score is below 0.5. It MUST NOT confirm or promote anything, and Confirmed status MUST NOT depend on it. Its catch rate is reported separately.
- **VER-1.6** A claim whose model-generated explanation contradicts its cited evidence MUST be demoted to Unknown and queued.

## 4. Human review (REV)

- **REV-1.1** Every output MUST be reviewed by a human, claim by claim, before it is marked accepted. There is no automatic acceptance path, for any status, at any confidence. A batch accept control is allowed only if each claim is still recorded as its own decision (REV-1.2).
- **REV-1.2** A review decision is accept, edit or reject, recorded with reviewer, time and reason. Review decisions are append-only.
- **REV-1.3** An edited claim goes through the verifier again before it can be accepted.
- **REV-2.1** The review queue holds all Unknown claims, all Inferred claims, stale claims and verifier failures.
- **REV-3.1** Documentation coverage is computed, not claimed: modules and endpoints found by Discovery with at least one accepted claim, divided by all modules and endpoints found. The denominator is always shown. A module the parser cannot read stays in the denominator as undocumented and also appears as an Unknown claim carrying the parse error.
- **REV-3.2** Accuracy is the share of sampled claims a human marks correct. The target is 90%.
- **REV-3.3** The accuracy sample is drawn at random by a script from claims the reviewer has not yet seen, with a minimum of 60 claims. The sample size and a Wilson 95% confidence interval are always reported with the rate.
- **REV-3.5** The pilot slice MUST be sized so the total claims to review is at most 400. If a run exceeds it, the slice is narrowed, not the review shortened.
- **REV-3.4** If the interval's lower bound is below the target, the report MUST say the target is not demonstrated, even if the point estimate passes.

## 5. Security and legacy-code handling (SEC)

- **SEC-1.1** The legacy repository is read-only. The platform MUST NOT write to it, commit to it or push to it. It reads from a read-only clone or read-only mount of the pinned revision (SEC-1.6), and a hash check proves the source unchanged before and after every run.
- **SEC-1.2** The platform MUST NOT connect to any production system or any live database from the legacy app's configuration. Database input is a schema or dump file only.
- **SEC-1.3** Secrets found in the input (keys, passwords, tokens) MUST be redacted before storage, and the redaction MUST be recorded as a finding. A secret MUST NOT appear unredacted in any claim, log, model prompt or output.
- **SEC-1.4** Ingest MUST reject any source (cloned repo, local path or archive) that exceeds 500 MB unpacked, 20000 files, or a directory depth of 30, and any file or symlink that resolves outside the source root.
- **SEC-1.6** The input is a GitHub repository URL or a local directory path. The platform MUST resolve it to a pinned revision (commit SHA, or a working-tree content hash for a local path) before analysis starts, and every claim MUST cite that revision. If the source changes during a run, the run continues on the pinned revision and the change is reported.
- **SEC-1.7** A GitHub access token MUST stay on the operator's machine. It MUST NOT be written to the database, logs, snapshots, claims or model prompts.
- **SEC-1.5** Personal data found in inputs MUST be flagged and masked in outputs.
- **SEC-2.1** All model calls use a private or local model. No code, excerpt or derived text from the legacy application MUST be sent to a hosted model API. (Decision D-2.)
- **SEC-2.2** Text from the legacy application is untrusted data. It MUST be passed to models inside delimited blocks, and the generating call MUST have no tools and no network.
- **SEC-2.3** CI MUST NOT call a live model. Tests use a fake client and recorded outputs.
- **SEC-3.1** Hosted staging holds only the synthetic fixture. Real legacy code MUST NOT be uploaded to any hosted service.
- **SEC-3.2** The pilot application MUST have a permissive licence (MIT, Apache-2.0 or BSD). Pilot source and pilot results containing source excerpts MUST NOT be committed to the platform repo.

## 6. Characterization tests (TST)

- **TST-1.1** A characterization test records current behavior of the original application. It MUST NOT assert behavior the platform inferred but never observed.
- **TST-1.2** Tests run only in the sandbox: no network, read-only mount of the pinned revision, no access to host files or credentials.
- **TST-1.6** Dependencies are fetched in a separate stage from the lockfile only, with install scripts disabled, and no legacy code is executed in that stage. The test stage then mounts them read-only. An application that needs install scripts or native builds is reported as not testable with the reason (CLM-1.7). It is not worked around.
- **TST-1.3** Sandbox limits are 2 CPUs, 2048 MB of memory and a 300 second timeout per test run. A run that exceeds a limit is a failure, not a pass.
- **TST-1.4** A test that fails against the original application is a defect in the test. It MUST be reported, and MUST NOT be edited until it passes without a recorded reason from a reviewer.
- **TST-1.5** The success report states the number of tests kept, passed and dropped, each dropped test with its reason.

## 7. Outputs (OUT)

- **OUT-1.1** Diagrams MUST be generated from stored analysis data, not written freehand by a model. Every node and edge in a diagram MUST map to a claim.
- **OUT-1.2** Every document in the output bundle carries the snapshot hash, run ID and date.
- **OUT-1.3** The migration plan, tech-debt map and target architecture are proposals. They MUST be labeled as such and every risk MUST cite a claim.
- **OUT-1.5** The Modernization agent MUST read accepted claims only. Anything it needs that is not accepted appears in the plan as an Unknown dependency.
- **OUT-1.4** Outputs state rules and observations only. They MUST NOT promise that a migration will be safe.

## 8. Operations (OPS)

- **OPS-1.1** A job MUST retry at most 3 times, then enter a visible failed state. A model call MUST time out after 120 seconds.
- **OPS-1.2** A job that is still running 600 seconds after it was claimed MUST be presumed dead and swept: it counts as a failed attempt under OPS-1.1. A running job MUST be stopped at the same limit, so the sweeper never requeues work that is still running. [enforced by: job runner tests]

## 9. Notes for the development team

- Rule IDs go in code comments, test names and PR descriptions.
- Numbers live in `rules_constants.yaml`; never copy them from this prose into code.
- Open question for the spec: V-1 to V-10 definitions, claim schema, and which of the nine agents are deterministic.
- Fixture secrets MUST be built from strings that scanners do not match, listed in `.secrets.baseline` (amendment A9).
- Still open: the local model and hardware (amendment A3). SEC-2.1 stands; live runs wait on it.
- Thresholds 0.5 (VER-1.7), 3 retries and 120 seconds (OPS-1.1) are my proposals; adjust freely.
