# ReachOps Codex Instructions

## Canonical read order

Before planning or modifying ReachOps, read these files in order:

1. `ReachOps/docs/REACHOPS_MASTER_EXECUTION_CONTRACT_V1.md`
2. `ReachOps/docs/REACHOPS_EXECUTION_STATE.md`
3. `ReachOps/docs/REACHOPS_GOAL_MODE_EXECUTION.md`
4. `ReachOps/docs/REACHOPS_PM_DELIVERY_BASELINE.md`
5. The code and tests relevant to the selected milestone.

The master execution contract defines the product target and non-negotiable boundaries. The execution-state file defines current progress and the next eligible work. The older goal-mode and PM documents are acceptance/runbook references; they must not override the master contract.

## Product identity

ReachOps is an independent, sellable Windows 10/11 local client. It is not an OPC runtime module. Customer business data remains on each customer device in an independent local SQLite runtime. OPC may receive only project-level, aggregated, and redacted delivery metrics or evidence summaries.

## Autonomous task-selection loop

At the start of every Codex task:

1. Inspect `git status`, current branch, latest commits, and open work relevant to the task.
2. Re-read the master contract and execution state.
3. Verify the execution state against current code and tests; do not trust stale status text.
4. Select the highest-priority item whose status is `READY` and whose dependencies are satisfied.
5. Execute one atomic milestone or one coherent PR-sized slice.
6. Run the required tests and truthfulness gates.
7. Update `ReachOps/docs/REACHOPS_EXECUTION_STATE.md` with evidence, remaining blockers, and the next item.
8. Commit only the intended files. Do not merge `main`.
9. Produce a final report with verified facts, tests, evidence paths, unresolved blockers, commit SHA, and rollback instructions.

When the highest-priority item is blocked by an external Windows/ixBrowser/TikTok/CEO dependency, mark it `BLOCKED`, preserve the exact evidence, and continue with the highest-priority non-blocked engineering item. Do not wait idly and do not fabricate external validation.

## Scope discipline

- Do not rewrite the whole application or replace the existing stack without an explicit contract change.
- Prefer incremental migrations, compatibility layers, and reversible commits.
- Do not introduce new top-level product modules, agents, or vendors unless required by the master contract.
- Do not modify unrelated files or clean up the repository broadly as part of a scoped milestone.
- Do not delete historical customer/runtime data. Database migrations must be idempotent and rollback-aware.
- Do not weaken tests or redefine a failure as success merely to obtain a green build.
- Existing baseline failures must be reported separately from new regressions.

## Truthfulness invariants

The following states are distinct and must never be collapsed into one `success` value:

- plan created
- process started
- simulated
- dry run
- preflight passed
- live submission attempted
- live submission unverified
- evidence-verified live success
- reply received
- qualified lead
- conversion
- revenue recorded

Only an evidence-verified live platform action may advance a lead to `contacted`. A keyword match may create a candidate or model-high-intent lead, but it is not a qualified lead. A qualified lead requires a reply whose content confirms a real need.

## External-action safety

Default behavior is no-submit. Every real comment or public reply requires per-action human approval.

Hard-stop states:

- CAPTCHA or security challenge
- login expired or login required
- account restricted
- platform rate limit or temporary enforcement
- comment capability restricted
- abnormal verification gate

For hard-stop states:

- stop the current run/scope
- do not switch accounts to bypass the state
- do not continue the same target
- do not create an automatic fallback action
- capture evidence and require human handling

Only bounded infrastructure failures such as browser crash, ixBrowser temporary startup failure, proxy connectivity failure, or ordinary page timeout may use limited retry/account switching according to policy.

## Privacy and secret handling

Never commit or upload:

- TikTok cookies or browser sessions
- account credentials
- AI API keys
- proxy credentials
- customer SQLite databases
- real customer screenshots or raw DOM evidence
- real usernames/targets in tests or fixtures
- local acceptance input files containing authorized targets

Use Windows Credential Manager for secrets. ixBrowser owns its cookies and login state. GitHub contains only code, schemas, tests, and redacted fixtures.

## Required validation

For every code-changing milestone, run the most relevant subset and record exact outcomes:

```bash
python -m py_compile <changed_python_files>
python -m unittest -v tests.test_truthful_execution_semantics
python -m unittest -v tests.test_reachops_campaign
python tools/reachops_operator_pressure.py --json
python tools/reachops_delivery_audit.py --json
python tools/reachops_goal_delivery_runner.py --json
python tools/reachops_goal_status_report.py --json
python tools/reachops_repository_cleanliness_check.py --json
git diff --check
```

Environment-blocked commands must be reported with command, exit code, and error. They must not be reported as passed.

## Branch and commit rules

- Never commit directly to `main`.
- Use the branch supplied by the Codex task. If operating locally on `main` and branch creation is permitted, use `codex/<milestone>-<slug>`.
- Keep each commit intentional and reviewable.
- Do not amend or rewrite unrelated history.
- Prefer a draft PR until local validation and review are complete.
- Real Windows/TikTok acceptance is a separate gate from implementation completion.

## Completion report format

Every completed task must report:

A. Verified facts
B. Code and schema changes
C. Tests and exact results
D. Evidence and artifact paths
E. Safety/privacy checks
F. External-environment blockers
G. Execution-state update
H. Commit SHA / branch / PR
I. Rollback method
J. Next highest-priority action
