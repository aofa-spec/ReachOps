# ReachOps Execution State

- Schema: `reachops.execution_state.v1`
- Contract: `REACHOPS_MASTER_EXECUTION_CONTRACT_V1.md`
- Last manually reconciled: `2026-07-19`
- Rule: verify every status against the repository before acting.

## Current project state

ReachOps is an independent Windows 10/11 local client project. Product direction is locked. The project is in engineering convergence, not final customer delivery.

## Milestone status

| Priority | Milestone | Status | Verified evidence | Exit condition |
|---|---|---|---|---|
| P0 | Truthful execution semantics | `IN_REVIEW` | Draft PR #10, branch `agent/reachops-truthful-execution-p0`; rebased on `origin/main`; evidence verification blocker fixed so live mode alone cannot set `evidence_verified`; unverified live submissions are tracked as `submitted_unverified` and do not increment generic success or `execution_success`; `tests.test_truthful_execution_semantics` 7/7 passed on 2026-07-17; exact campaign baseline comparison shows 230 tests on main and PR, both with 14 failures and 1 existing live-readiness error, `new_failures=0`, `new_errors=0` | Review and merge without new Evidence regressions; preserve no-live-action boundary; external Windows/TikTok acceptance remains separate |
| P1 | Immutable Campaign Run / Observation model | `IN_PROGRESS` | Branch `codex/p1-lead-decision-versioning` adds append-only, versioned lead-decision ledger. Campaign/run/observation foundation remains in separate Draft PRs and is not assumed merged on `main`. | Idempotent migrations; run-scoped observations; historical decisions immutable; tests pass |
| P2 | Windows local security, licensing, backup, device seats | `PLANNED` | Product contract locked | Windows Credential Manager, minimal license client, 7-day grace, encrypted backup/restore, tests |
| P3 | Public comment-reply monitoring and lead lifecycle | `PLANNED` | Product contract locked | Automatic public reply detection; action linkage; qualified-lead state; manual conversion/revenue capture |
| P4 | Bilingual UI, installer, update, Windows acceptance | `PLANNED` | Existing packaging/runbook exists but final external acceptance is incomplete | Win10/11 installer, zh-CN/en-US UI, update flow, acceptance matrix, authorized live evidence |
| P5 | DM inbox monitoring | `DEFERRED` | Explicitly deferred behind public reply monitoring | Separate privacy/evidence contract and acceptance after P3/P4 |

## Next autonomous action

1. Review PR #10 evidence-truthfulness correction and merge only after accepting the known non-P0 baseline failures separately.
2. Do not expand PR #10 with P1.
3. After P0 merges, start P1 on a separate branch/PR:
   - add `campaign_runs`
   - add `source_observations`
   - add `content_observations`
   - add `comment_observations`
   - add `candidate_observations`
   - add versioned `lead_decisions`
   - keep existing global entities for compatibility
   - scope scoring and lead creation to run/batch observations
   - add idempotent migration and rollback evidence
   - add cross-campaign isolation tests

## Known external blockers

- Authorized Windows + ixBrowser + logged-in TikTok environment is required for final platform validation.
- Real targets and activation inputs must remain local and git-ignored.
- Windows code-signing certificate is not currently available; internal builds may show an unknown-publisher warning.
- Natural user replies cannot be guaranteed; authorized test accounts may validate reply-linking mechanics, while natural reply rate remains a business observation.

## Latest P0 verification snapshot

- Date: `2026-07-17`
- Branch: `agent/reachops-truthful-execution-p0`
- Scope: PR #10 P0 Evidence truthfulness blocker only.
- Code evidence:
  - Live success calls `_valid_execution_evidence(...)` before setting `evidence_verified`.
  - URI evidence, including generated `evidence://...` stubs, cannot verify live success.
  - Missing/invalid mandatory live evidence remains `LIVE_SUBMIT_EVIDENCE_MISSING`.
  - Optional invalid live evidence records `status=submitted_unverified`, `submission_state=submitted_unverified`, `verification_state=pending`, `evidence_verified=0`, increments `submitted_unverified` and `live_submitted`, does not increment generic `success`, `execution_success`, or `live_verified`, and keeps actions/leads out of completed/contacted.
  - Summary/result schemas now expose `submitted_unverified` separately in action-router results, storage truth counts, workflow execution summaries, and operator-pressure funnel summaries.
- Tests and checks:
  - `python` command unavailable in this shell: exit `127`, `zsh:1: command not found: python`.
  - `/usr/bin/python3 -m py_compile ReachOps/workbench/action_router.py ReachOps/workbench/workflow_service.py ReachOps/intelligence/storage.py tools/reachops_operator_pressure.py tools/reachops_delivery_audit.py tools/reachops_live_submit_acceptance.py tests/test_truthful_execution_semantics.py tests/test_reachops_campaign.py`: passed; log `/tmp/reachops-pr10-pycompile.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - Exact campaign baseline comparison:
    - `origin/main` clean worktree `/tmp/reachops-main-baseline-pr10` at `2412f2d`: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign` ran 230 tests, failed with 14 failures and 1 error; log `/tmp/reachops-main-baseline-pr10-campaign.log`.
    - PR #10 head: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign` ran 230 tests, failed with the same 14 failures and 1 error; log `/tmp/reachops-pr10-head-campaign-after-fix.log`.
    - Comparison artifact `/tmp/reachops-pr10-baseline-comparison-after-fix.json`: `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, summary includes `submitted_unverified=0`; output `/tmp/reachops-pr10-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; Evidence guard check passed, failures are non-P0 delivery/UI/funnel baseline checks.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-pr10-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-pr10-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - Fixture live execution remains blocked by default and is only enabled in explicit test fixture paths through `REACHOPS_ALLOW_TEST_FIXTURE_LIVE=1`.

## Non-blocking engineering work available

- P1 observation model and migration.
- LeadDecision versioning and unified scoring contract.
- Follow/DM evidence validators in no-submit fixtures.
- Windows Credential Manager abstraction and unit tests.
- Encrypted backup format and restore tests.
- License state machine and 7-day grace logic.
- Localization resource extraction for `zh-CN` and `en-US`.
- Public reply-monitor parser using redacted/replay fixtures.

## Latest P1 lead-decision verification snapshot

- Date: `2026-07-19`
- Branch: `codex/p1-lead-decision-versioning`
- Draft PR: #17 `ReachOps P1: versioned lead decision ledger`
- Commit: `8e81baa` adds the append-only lead-decision ledger, versioning, idempotency, migration compatibility, and focused tests; the follow-up commit on the same PR preserves candidate batch attribution when the active batch changes before lead evaluation.
- Scope: P1 lead decision traceability/versioning only. No Windows package, EXE, installer, ixBrowser runtime, or TikTok live-submit work was performed.
- Code evidence:
  - Added local SQLite table `lead_decisions` as an append-only ledger for operation-lead decisions.
  - Each decision records schema version, rule version, lead ID, candidate ID, content ID, batch ID, score, confidence, reason, evidence, fingerprint, and decision JSON.
  - Each decision now also exposes the master-contract traceability fields as queryable columns and in `decision_json`: `campaign_id`, `run_id`, `candidate_observation_id`, `intent_type`, component scores, `feature_snapshot`, `classifier_version`, `provider_version`, and `human_review_status`.
  - Follow-up hardening in Draft PR #17 records operator action review as an append-only `human_review` LeadDecision audit event; it does not rewrite or erase the prior model/rule decision row.
  - `list_lead_decisions()` can now filter by `campaign_id` and `run_id`, with matching SQLite indexes for campaign/run-scoped reporting and export isolation.
  - Repeated identical upserts are idempotent through `UNIQUE(lead_id, decision_fingerprint)`.
  - Repeated identical human-review updates are idempotent; changed review evidence or status appends a later decision version.
  - Changed scoring/reason/context appends a new `decision_version` without rewriting prior rows.
  - New operation leads and lead-decision ledger rows resolve batch attribution as explicit decision context first, then candidate observation batch, then current active batch, preventing old observations from being silently attributed to a later run.
  - Legacy databases gain the table on init but do not fabricate historical decision rows for old `operation_leads`.
  - `list_operation_leads()` exposes `latest_decision_version` so lead rows can be traced back to the immutable ledger.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py ReachOps/intelligence/operation_lead_manager.py tests/test_lead_decisions.py`: passed; log `/tmp/reachops-pr17-batch-trace-pycompile.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_lead_decisions`: passed, 6 tests; log `/tmp/reachops-pr17-batch-trace-tests.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-pr17-batch-trace-truth.log`.
  - Campaign regression comparison:
    - branch `codex/p1-lead-decision-versioning`: 230 tests, 14 failures, 1 error; log `/tmp/reachops-pr17-batch-trace-campaign.log`.
    - `origin/main`: 230 tests, 14 failures, 1 error; log `/tmp/reachops-main-baseline-pr17-batch-trace-campaign.log`.
    - comparison result: `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-pr17-batch-trace-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-pr17-batch-trace-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, `status=not_ready`, `final_delivery_ready=false`; output `/tmp/reachops-pr17-batch-trace-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, `status=failed`, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=27`, `final_pending_external_validation=3`, `final_failed=3`; output `/tmp/reachops-pr17-batch-trace-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed; missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr17-batch-trace-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed; failed checks are `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr17-batch-trace-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-pr17-batch-trace-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-pr17-batch-trace-diff-check.log`.
  - Contract-field rerun: `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py ReachOps/intelligence/operation_lead_manager.py tests/test_lead_decisions.py`: passed; log `/tmp/reachops-pr17-contract-fields-pycompile.log`.
  - Contract-field rerun: `/usr/bin/python3 -m unittest -v tests.test_lead_decisions`: passed, 7 tests; log `/tmp/reachops-pr17-contract-fields-tests.log`.
  - Contract-field rerun: `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-pr17-contract-fields-truth.log`.
  - Contract-field rerun: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with the same known failure/error set as `origin/main`; branch and main both ran 230 tests with 14 failures and 1 error; comparison artifact `/tmp/reachops-pr17-contract-fields-baseline-comparison.json`, `new_failures=[]`, `new_errors=[]`.
  - Contract-field rerun: `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-pr17-contract-fields-operator-pressure.json`.
  - Contract-field rerun: `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-pr17-contract-fields-delivery-audit.json`.
  - Contract-field rerun: `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, `status=not_ready`, `final_delivery_ready=false`; output `/tmp/reachops-pr17-contract-fields-goal-delivery-runner.json`.
  - Contract-field rerun: `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=27`, `final_pending_external_validation=3`, `final_failed=3`; output `/tmp/reachops-pr17-contract-fields-goal-status-report.json`.
  - Contract-field rerun: `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr17-contract-fields-package-check.json`.
  - Contract-field rerun: `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr17-contract-fields-final-gate.json`.
  - Contract-field rerun: `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-pr17-contract-fields-cleanliness.json`.
  - Contract-field rerun: `git diff --check`: passed; log `/tmp/reachops-pr17-contract-fields-diff-check.log`.
  - Review hardening rerun: `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py ReachOps/intelligence/operation_lead_manager.py tests/test_lead_decisions.py`: passed; log `/tmp/reachops-pr17-review-pycompile.log`.
  - Review hardening rerun: `/usr/bin/python3 -m unittest -v tests.test_lead_decisions`: passed, 9 tests; log `/tmp/reachops-pr17-review-focused.log`.
  - Review hardening rerun: `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-pr17-review-truth.log`.
  - Review hardening rerun: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with the same known failure/error set as `origin/main`; branch and main both ran 230 tests with 14 failures and 1 error; comparison artifact `/tmp/reachops-pr17-review-baseline-comparison.json`, `new_failures=[]`, `new_errors=[]`.
  - Review hardening rerun: `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-pr17-review-operator-pressure.json`.
  - Review hardening rerun: `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-pr17-review-delivery-audit.json`.
  - Review hardening rerun: `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, `status=not_ready`, `final_delivery_ready=false`; output `/tmp/reachops-pr17-review-goal-delivery-runner.json`.
  - Review hardening rerun: `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, `status=failed`, summary `final_passed=27`, `final_pending_external_validation=3`, `final_failed=3`; output `/tmp/reachops-pr17-review-goal-status-report.json`.
  - Review hardening rerun: `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr17-review-package-check.json`.
  - Review hardening rerun: `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr17-review-final-gate.json`.
  - Review hardening rerun: `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-pr17-review-cleanliness.json`.
  - Review hardening rerun: `git diff --check`: passed; log `/tmp/reachops-pr17-review-diff-check.log`.
  - Final PR #17 closeout rerun: `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py ReachOps/intelligence/operation_lead_manager.py tests/test_lead_decisions.py`: passed; log `/tmp/reachops-pr17-final-pycompile.log`.
  - Final PR #17 closeout rerun: `/usr/bin/python3 -m unittest -v tests.test_lead_decisions`: passed, 9 tests; log `/tmp/reachops-pr17-final-focused.log`.
  - Final PR #17 closeout rerun: `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-pr17-final-truth.log`.
  - Final PR #17 closeout rerun: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with the same known failure/error set as `origin/main`; branch and main both ran 230 tests with 14 failures and 1 error; comparison artifact `/tmp/reachops-pr17-final-baseline-comparison.json`, `new_failures=[]`, `new_errors=[]`.
  - Final PR #17 closeout rerun: `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-pr17-final-operator-pressure.json`.
  - Final PR #17 closeout rerun: `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-pr17-final-delivery-audit.json`.
  - Final PR #17 closeout rerun: `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, `status=not_ready`, `final_delivery_ready=false`; output `/tmp/reachops-pr17-final-goal-delivery-runner.json`.
  - Final PR #17 closeout rerun: `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, `status=failed`, summary `final_passed=27`, `final_pending_external_validation=3`, `final_failed=3`; output `/tmp/reachops-pr17-final-goal-status-report.json`.
  - Final PR #17 closeout rerun: `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr17-final-package-check.json`.
  - Final PR #17 closeout rerun: `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr17-final-final-gate.json`.
  - Final PR #17 closeout rerun: `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-pr17-final-cleanliness.json`.
  - Final PR #17 closeout rerun: `git diff --check`: passed; log `/tmp/reachops-pr17-final-diff-check.log`.
- Remaining blockers:
  - Windows final artifacts are still missing: `dist/ReachOps/ReachOps.exe`, `dist/installer/ReachOps-Setup-0.4.0.exe`, `dist/installer/reachops-update-manifest.json`, and `reports/reachops_acceptance/acceptance_summary.json`.
  - External authorized live TikTok validation remains pending and must not be fabricated on Mac.
  - Existing delivery audit and campaign baseline failures remain separate from this P1 lead-decision slice.

## State-update rules

Codex must update this file at the end of each milestone with:

- status transition
- commit and PR
- tests executed and exact result
- evidence paths
- blockers
- next autonomous action

Do not write `COMPLETE` unless every exit condition is supported by evidence. Implementation completion and external live acceptance are separate states.
