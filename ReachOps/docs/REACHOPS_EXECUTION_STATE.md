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
| P0 | Truthful execution semantics | `COMPLETE` | PR #10 squash-merged to `main` as `887f7068ad313c7d3cddf971362cdce42c555946`; live mode alone cannot set `evidence_verified`; unverified live submissions are tracked as `submitted_unverified` and do not increment generic success or `execution_success`; `tests.test_truthful_execution_semantics` 7/7 passed on 2026-07-17; exact campaign baseline comparison before merge showed `new_failures=0`, `new_errors=0` | Preserve no-live-action boundary; external Windows/TikTok acceptance remains separate |
| P1 | Immutable Campaign Run / Observation model | `IN_REVIEW` | Draft PR #12, branch `codex/p1-immutable-campaign-run-observations`; review pass adds deterministic legacy run handling, run-scoped traceability for observations/actions/executions/events/errors, storage-layer automatic ledger writes from collection tasks/content/candidates/leads, workflow scoring observation traceability, workflow collector traceability, run-scoped campaign artifact exports, and delivery-audit funnel isolation aligned with P0 truthfulness; focused coverage for campaign isolation, run isolation, observation/action/evidence traceability, migration compatibility, workflow-storage ledger writes, workflow-scoring ledger writes, workflow collector trace, export isolation, and idempotency; latest `tests.test_campaign_run_observations` 13/13 passed on 2026-07-19; campaign regression comparison against `main` showed `new_failures=[]`, `new_errors=[]` | Keep PR #12 Draft for review; do not expand into broader lead lifecycle semantics |
| P2 | Windows local security, licensing, backup, device seats | `PLANNED` | Product contract locked | Windows Credential Manager, minimal license client, 7-day grace, encrypted backup/restore, tests |
| P3 | Public comment-reply monitoring and lead lifecycle | `PLANNED` | Product contract locked | Automatic public reply detection; action linkage; qualified-lead state; manual conversion/revenue capture |
| P4 | Bilingual UI, installer, update, Windows acceptance | `PLANNED` | Existing packaging/runbook exists but final external acceptance is incomplete | Win10/11 installer, zh-CN/en-US UI, update flow, acceptance matrix, authorized live evidence |
| P5 | DM inbox monitoring | `DEFERRED` | Explicitly deferred behind public reply monitoring | Separate privacy/evidence contract and acceptance after P3/P4 |

## Next autonomous action

1. Review Draft PR #12 from branch `codex/p1-immutable-campaign-run-observations`.
2. Keep PR #9 frozen until it is re-reviewed or split against the P0/P1 contract.
3. After PR #12 review, continue with the next isolated PR-sized slice: broader LeadDecision lifecycle semantics, Windows Credential Manager, or P4 Web runtime smoke depending on merge/review order.

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

## Latest P1 verification snapshot

- Date: `2026-07-19`
- Branch: `codex/p1-immutable-campaign-run-observations`
- PR: Draft PR #12
- Commit: current review hardening commits on this branch; final SHA is reported in the completion report.
- Scope: P1 runtime data-contract slice covering storage traceability plus workflow scoring traceability; no PR #9 changes and no real TikTok action.
- Code evidence:
  - Added `campaign_runs` as the immutable run ledger, one run per collection batch, with idempotent backfill for existing batches.
  - Added `source_observations`, `content_observations`, `comment_observations`, `candidate_observations`, and versioned `lead_decision_observations`.
  - Added `run_id` compatibility columns to collection tasks, discovered creators/content, shop content, candidates, leads, actions, outreach executions, events, and errors.
  - Added storage APIs to record run-scoped observations and append lead decisions without mutating prior decisions.
  - Existing workflow storage writes now automatically populate the run ledger when an active collection batch is set: `create_collection_task(...)` records `source_observations`, `upsert_content(...)` records `content_observations`, `upsert_candidate(...)` records `comment_observations` and `candidate_observations`, and `upsert_operation_lead(...)` appends changed versioned `lead_decision_observations`.
  - `create_collection_batch(...)` now records the `collection_batch_created` growth event directly with the newly-created `run_id`, so the run trace includes the batch creation event before any active-batch context exists.
  - `comment_observations` now preserve distinct same-user comments in the same content/run by including `comment_text` in the idempotency key, while duplicate identical comments remain idempotent.
  - Added optional `run_id` filters for candidates, leads, actions, outreach executions, and execution counts.
  - Legacy migration now uses deterministic `legacy_run_<batch_id>` identifiers plus `legacy_backfill` metadata instead of random `run_*` IDs, and does not rewrite old candidate, lead, action, outreach execution, evidence-path, or error rows to claim a real run.
  - Legacy migration now keeps pre-P1 `collection_batches.run_id` blank for batches that originally had no run id; `run_id_for_batch(...)` resolves the explicit `campaign_runs` legacy compatibility row without making the historical batch row claim a real run.
  - `list_observations_for_run(...)` now returns the campaign run ledger row plus observation rows, run-scoped queued actions, outreach executions, events, and errors so action proposals, evidence paths, legacy handling strategy, and error context are traceable by run from one audit payload.
  - `create_outreach_execution(...)` now prefers the target `action_queue` row's `run_id` and `batch_id` over ambient active-batch context, so evidence records remain attached to the action's original run even if active-batch context changes before execution is recorded; legacy action rows with blank `run_id` stay blank and are not reassigned to a current active run.
  - `export_campaign_artifacts(..., batch_id=..., run_id=...)` now resolves the selected run, scopes candidates/leads/actions/executions/status counts by `run_id`, writes `export_scope` into JSON, and includes `run_id` in customers/actions/executions CSV outputs.
  - Operation lead and action queue uniqueness is now scoped by `run_id`, so the same repeated candidate/action can produce independent leads, actions, executions, and evidence in separate runs.
  - Legacy databases with global lead/action uniqueness are rebuilt idempotently to the run-scoped unique contract while preserving existing legacy rows with blank `run_id`.
  - `CandidateUserScorer.score_all(config)` now honors `config.active_batch_id` when provided, preventing scoring runs from recording historical candidates into the active run.
  - `update_candidate_score(...)` now appends stable idempotent `candidate_observations` with `score_updated:<fingerprint>` keys under the active run, so workflow scoring changes are traceable without mutating prior observations.
  - Workflow-level `GrowthIntelligenceService.run_collection(...)` coverage now verifies that a real collector path writes collection tasks, source/content/comment/candidate observations, lead decisions, queued actions, and growth events into one immutable run trace.
  - LeadDecision remains scoped to immutable versioned decisions in this PR; broader lead lifecycle semantics remain outside this storage-contract PR.
  - Run-trace decision rows are now stored as `lead_decision_observations`, not canonical `lead_decisions`, so PR #12 no longer claims or conflicts with PR #17's separate LeadDecision ledger scope.
  - PR #12 review hardening now preserves the master truth invariant for run-scoped lifecycle updates: an action status of `success` or `completed` cannot move a lead to `contacted` unless the same lead has a live outreach execution with `submission_state=verified_success`, `verification_state=verified`, and `evidence_verified=1`; preflight success and unverified live submissions remain non-contacted.
  - Delivery audit campaign-funnel isolation now uses `simulated_success` to prove the old campaign had dry-run action evidence while keeping `execution_success=0` for both old and new campaigns; this preserves P0 truthfulness semantics while proving the new campaign does not inherit old action results.
- Tests and checks:
  - Verified-contact review hardening: `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py ReachOps/intelligence/candidate_user_scorer.py ReachOps/intelligence/schemas.py ReachOps/workbench/workflow_service.py tools/reachops_delivery_audit.py tests/test_campaign_run_observations.py tests/test_truthful_execution_semantics.py tests/test_reachops_campaign.py`: passed, exit `0`; log `/tmp/reachops-pr12-verified-contact-pycompile-full.log`.
  - Verified-contact review hardening: `/usr/bin/python3 -m unittest -v tests.test_campaign_run_observations tests.test_truthful_execution_semantics`: passed, 20 tests, exit `0`; log `/tmp/reachops-pr12-verified-contact-focused.log`.
  - Verified-contact review hardening: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; branch log `/tmp/reachops-pr12-verified-contact-campaign.log`; `origin/main` baseline log `/tmp/reachops-main-baseline-pr12-verified-contact-campaign.log`; comparison artifact `/tmp/reachops-pr12-verified-contact-baseline-comparison.json`, `new_failures=[]`, `new_errors=[]`.
  - Verified-contact review hardening: `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-pr12-verified-contact-operator-pressure.json`.
  - Verified-contact review hardening: `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, summary `passed=47`, `pending_external_validation=3`, `failed=4`; output `/tmp/reachops-pr12-verified-contact-delivery-audit.json`.
  - Verified-contact review hardening: `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; blockers include local MVP evidence, Windows final artifacts, external authorized execution, and delivery audit failures; output `/tmp/reachops-pr12-verified-contact-goal-delivery-runner.json`.
  - Verified-contact review hardening: `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=28`, `final_pending_external_validation=3`, `final_failed=2`; output `/tmp/reachops-pr12-verified-contact-goal-status-report.json`.
  - Verified-contact review hardening: `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr12-verified-contact-package-check.json`.
  - Verified-contact review hardening: `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-verified-contact-final-gate.json`.
  - Verified-contact review hardening: `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`, `forbidden_count=0`; output `/tmp/reachops-pr12-verified-contact-cleanliness.json`.
  - Verified-contact review hardening: `git diff --check`: passed, exit `0`; log `/tmp/reachops-pr12-verified-contact-diff-check.log`.
  - Legacy strict migration review: `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py tests/test_campaign_run_observations.py ReachOps/intelligence/schemas.py ReachOps/workbench/workflow_service.py ReachOps/intelligence/candidate_user_scorer.py tools/reachops_delivery_audit.py`: passed, exit `0`.
  - Legacy strict migration review: `/usr/bin/python3 -m unittest -v tests.test_campaign_run_observations`: passed, 13 tests, exit `0`; log `/tmp/reachops-pr12-legacy-strict-p1-focused.log`.
  - Legacy strict migration review: `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-pr12-legacy-strict-truth.log`.
  - Legacy strict migration review: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; branch log `/tmp/reachops-pr12-legacy-strict-campaign.log`; `origin/main` baseline log `/tmp/reachops-main-baseline-pr12-legacy-strict-campaign.log`; comparison artifact `/tmp/reachops-pr12-legacy-strict-baseline-comparison.json`, `new_failures=[]`, `new_errors=[]`.
  - Legacy strict migration review: `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, exit `0`, `status=ok`; output `/tmp/reachops-pr12-legacy-strict-operator-pressure.json`.
  - Legacy strict migration review: `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, `status=failed`, summary `passed=47`, `pending_external_validation=3`, `failed=4`; failures are non-P1 Web/runtime delivery checks on this PR branch; output `/tmp/reachops-pr12-legacy-strict-delivery-audit.json`.
  - Legacy strict migration review: `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-legacy-strict-goal-delivery-runner.json`.
  - Legacy strict migration review: `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`, summary `final_passed=28`, `final_pending_external_validation=3`, `final_failed=2`; output `/tmp/reachops-pr12-legacy-strict-goal-status-report.json`.
  - Legacy strict migration review: `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, `status=failed`, `final_delivery_ready=false`; missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr12-legacy-strict-package-check.json`.
  - Legacy strict migration review: `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`, `status=failed`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-legacy-strict-final-gate.json`.
  - Legacy strict migration review: `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`, `forbidden_count=0`; output `/tmp/reachops-pr12-legacy-strict-cleanliness.json`.
  - Legacy strict migration review: `git diff --check`: passed, exit `0`; log `/tmp/reachops-pr12-legacy-strict-diff-check.log`.
  - Run ledger trace rerun: `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py tests/test_campaign_run_observations.py`: passed, exit `0`; log `/tmp/reachops-pr12-run-ledger-trace-pycompile.log`.
  - Run ledger trace rerun: `/usr/bin/python3 -m unittest -v tests.test_campaign_run_observations`: passed, 11 tests, exit `0`; log `/tmp/reachops-pr12-run-ledger-trace-focused.log`.
  - Run ledger trace rerun: `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-pr12-run-ledger-trace-truth.log`.
  - Run ledger trace rerun: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-pr12-run-ledger-trace-campaign.log`.
  - Run ledger trace baseline comparison: `origin/main` at `887f706` also ran 230 tests with 14 failures and 1 error; comparison artifact `/tmp/reachops-pr12-run-ledger-trace-baseline-comparison.json`, `new_failures=[]`, `new_errors=[]`.
  - Run ledger trace rerun: `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-pr12-run-ledger-trace-operator-pressure.json`.
  - Run ledger trace rerun: `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, summary `passed=47`, `pending_external_validation=3`, `failed=4`; output `/tmp/reachops-pr12-run-ledger-trace-delivery-audit.json`.
  - Run ledger trace rerun: `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-run-ledger-trace-goal-delivery-runner.json`.
  - Run ledger trace rerun: `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`; output `/tmp/reachops-pr12-run-ledger-trace-goal-status-report.json`.
  - Run ledger trace rerun: `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr12-run-ledger-trace-package-check.json`.
  - Run ledger trace rerun: `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-run-ledger-trace-final-gate.json`.
  - Run ledger trace rerun: `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`, `forbidden_count=0`; output `/tmp/reachops-pr12-run-ledger-trace-cleanliness.json`.
  - Run ledger trace rerun: `git diff --check`: passed, exit `0`; log `/tmp/reachops-pr12-run-ledger-trace-diff-check.log`.
  - Latest hardening rerun: `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py ReachOps/intelligence/candidate_user_scorer.py ReachOps/intelligence/schemas.py ReachOps/workbench/workflow_service.py tools/reachops_delivery_audit.py tests/test_campaign_run_observations.py tests/test_reachops_campaign.py`: passed, exit `0`; log `/tmp/reachops-pr12-funnel-truth-pycompile.log`.
  - Latest hardening rerun: `/usr/bin/python3 -m unittest -v tests.test_campaign_run_observations`: passed, 11 tests, exit `0`; log `/tmp/reachops-pr12-funnel-truth-focused.log`.
  - Latest hardening rerun: `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-pr12-funnel-truth-truth.log`.
  - Latest hardening rerun: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-pr12-funnel-truth-campaign.log`.
  - Latest hardening baseline comparison: `origin/main` also ran 230 tests with 14 failures and 1 error; comparison artifact `/tmp/reachops-pr12-funnel-truth-baseline-comparison.json`, `new_failures=[]`, `new_errors=[]`.
  - Latest hardening rerun: `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-pr12-funnel-truth-operator-pressure.json`.
  - Latest hardening rerun: `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, summary `passed=47`, `pending_external_validation=3`, `failed=4`; `漏斗只显示本轮 Campaign` now passes; output `/tmp/reachops-pr12-funnel-truth-delivery-audit.json`.
  - Latest hardening rerun: `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; blockers include Mac ixBrowser/API loop readiness, Windows final artifacts, and external authorized execution; output `/tmp/reachops-pr12-funnel-truth-goal-delivery-runner.json`.
  - Latest hardening rerun: `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`; output `/tmp/reachops-pr12-funnel-truth-goal-status-report.json`.
  - Latest hardening rerun: `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr12-funnel-truth-package-check.json`.
  - Latest hardening rerun: `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-funnel-truth-final-gate.json`.
  - Latest hardening rerun: `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`, `forbidden_count=0`; output `/tmp/reachops-pr12-funnel-truth-cleanliness.json`.
  - Latest hardening rerun: `git diff --check`: passed, exit `0`; log `/tmp/reachops-pr12-funnel-truth-diff-check.log`.
  - Action traceability rerun: `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py tests/test_campaign_run_observations.py`: passed, exit `0`; log `/tmp/reachops-pr12-action-trace-pycompile.log`.
  - Action traceability rerun: `/usr/bin/python3 -m unittest -v tests.test_campaign_run_observations`: passed, 11 tests, exit `0`; log `/tmp/reachops-pr12-action-trace-focused.log`.
  - Action traceability rerun: `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-pr12-action-trace-truth.log`.
  - Action traceability rerun: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-pr12-action-trace-campaign.log`.
  - Action traceability baseline comparison: `new_failures=[]`, `new_errors=[]`; artifact `/tmp/reachops-pr12-action-trace-baseline-comparison.json`.
  - Action traceability rerun: `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-pr12-action-trace-operator-pressure.json`.
  - Action traceability rerun: `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, summary `passed=47`, `pending_external_validation=3`, `failed=4`; output `/tmp/reachops-pr12-action-trace-delivery-audit.json`.
  - Action traceability rerun: `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; output `/tmp/reachops-pr12-action-trace-goal-delivery-runner.json`.
  - Action traceability rerun: `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`; output `/tmp/reachops-pr12-action-trace-goal-status-report.json`.
  - Action traceability rerun: `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr12-action-trace-package-check.json`.
  - Action traceability rerun: `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-action-trace-final-gate.json`.
  - `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py ReachOps/intelligence/candidate_user_scorer.py tests/test_campaign_run_observations.py`: passed, exit `0`.
  - `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py ReachOps/intelligence/candidate_user_scorer.py ReachOps/intelligence/schemas.py ReachOps/workbench/workflow_service.py tests/test_campaign_run_observations.py`: passed, exit `0`; log `/tmp/reachops-pr12-event-trace-pycompile.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_campaign_run_observations`: passed, 9 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_campaign_run_observations`: passed, 9 tests, exit `0`; log `/tmp/reachops-pr12-event-trace-focused.log`.
  - `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py tests/test_campaign_run_observations.py`: passed, exit `0`; log `/tmp/reachops-pr12-action-evidence-run-trace-pycompile.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_campaign_run_observations`: passed, 10 tests, exit `0`; log `/tmp/reachops-pr12-action-evidence-run-trace-focused.log`.
  - Final pre-commit rerun: `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py tests/test_campaign_run_observations.py`: passed, exit `0`; log `/tmp/reachops-pr12-action-evidence-run-trace-pycompile-final.log`.
  - Final pre-commit rerun: `/usr/bin/python3 -m unittest -v tests.test_campaign_run_observations`: passed, 10 tests, exit `0`; log `/tmp/reachops-pr12-action-evidence-run-trace-focused-final.log`.
  - Decision-observation boundary rerun: `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py ReachOps/intelligence/candidate_user_scorer.py ReachOps/intelligence/schemas.py ReachOps/workbench/workflow_service.py tests/test_campaign_run_observations.py`: passed; log `/tmp/reachops-pr12-decision-observations-pycompile.log`.
  - Decision-observation boundary rerun: `/usr/bin/python3 -m unittest -v tests.test_campaign_run_observations`: passed, 12 tests; log `/tmp/reachops-pr12-decision-observations-focused.log`.
  - Decision-observation boundary rerun: `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-pr12-decision-observations-truth.log`.
  - Decision-observation boundary rerun: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with the same known failure/error set as `origin/main`; branch and main both ran 230 tests with 14 failures and 1 error; comparison artifact `/tmp/reachops-pr12-decision-observations-baseline-comparison.json`, `new_failures=[]`, `new_errors=[]`.
  - Decision-observation boundary rerun: `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-pr12-decision-observations-operator-pressure.json`.
  - Decision-observation boundary rerun: `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, summary `passed=47`, `pending_external_validation=3`, `failed=4`; `漏斗只显示本轮 Campaign` is not failed; output `/tmp/reachops-pr12-decision-observations-delivery-audit.json`.
  - Decision-observation boundary rerun: `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, `status=not_ready`, `final_delivery_ready=false`; output `/tmp/reachops-pr12-decision-observations-goal-delivery-runner.json`.
  - Decision-observation boundary rerun: `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=28`, `final_pending_external_validation=3`, `final_failed=2`; output `/tmp/reachops-pr12-decision-observations-goal-status-report.json`.
  - Decision-observation boundary rerun: `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr12-decision-observations-package-check.json`.
  - Decision-observation boundary rerun: `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-decision-observations-final-gate.json`.
  - Decision-observation boundary rerun: `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-pr12-decision-observations-cleanliness.json`.
  - Decision-observation boundary rerun: `git diff --check`: passed; log `/tmp/reachops-pr12-decision-observations-diff-check.log`.
  - `/usr/bin/python3 -m py_compile ReachOps/intelligence/service.py ReachOps/intelligence/growth_task_router.py tests/test_campaign_run_observations.py`: passed, exit `0`; log `/tmp/reachops-pr12-workflow-run-trace-pycompile-full.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_campaign_run_observations`: passed, 11 tests, exit `0`; log `/tmp/reachops-pr12-workflow-run-trace-focused.log`.
  - `/usr/bin/python3 -m py_compile ReachOps/workbench/workflow_service.py ReachOps/intelligence/storage.py ReachOps/intelligence/schemas.py tests/test_campaign_run_observations.py`: passed, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_campaign_run_observations`: passed, 8 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_campaign_report_exports_current_customers_and_actions tests.test_reachops_campaign.ReachOpsCampaignTests.test_campaign_report_export_paths_do_not_overwrite_same_second_runs`: passed, 2 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-pr12-run-export-truth.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-pr12-run-scoped-unique-truth.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-pr12-run-export-campaign.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-pr12-run-scoped-unique-campaign.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-pr12-scoring-trace-campaign.log`.
  - `main` baseline at `origin/main`: `/tmp/reachops-main-baseline-pr12-run-export-campaign.log` failed with the same 14 failures and 1 error.
  - Baseline comparison result: `new_failures=[]`, `new_errors=[]`.
  - Baseline comparison artifact: `/tmp/reachops-pr12-scoring-trace-baseline-comparison.json`; `new_failures=[]`, `new_errors=[]`.
  - Baseline comparison artifact: `/tmp/reachops-pr12-run-scoped-unique-baseline-comparison.json`; `new_failures=[]`, `new_errors=[]`.
  - Baseline comparison artifact: `/tmp/reachops-pr12-run-export-baseline-comparison.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-pr12-scoring-trace-truth.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-pr12-event-trace-truth.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-pr12-action-evidence-run-trace-truth.log`.
  - Final pre-commit rerun: `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-pr12-action-evidence-run-trace-truth-final.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-pr12-workflow-run-trace-truth.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-pr12-event-trace-campaign.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-pr12-action-evidence-run-trace-campaign.log`.
  - Final pre-commit rerun: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-pr12-action-evidence-run-trace-campaign-final.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-pr12-workflow-run-trace-campaign.log`.
  - Baseline comparison artifact: `/tmp/reachops-pr12-event-trace-baseline-comparison.json`; `new_failures=[]`, `new_errors=[]`.
  - Baseline comparison artifact: `/tmp/reachops-pr12-action-evidence-run-trace-baseline-comparison.json`; `new_failures=[]`, `new_errors=[]`.
  - Final baseline comparison artifact: `/tmp/reachops-pr12-action-evidence-run-trace-baseline-comparison-final.json`; `new_failures=[]`, `new_errors=[]`.
  - Baseline comparison artifact: `/tmp/reachops-pr12-workflow-run-trace-baseline-comparison.json`; `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-pr12-event-trace-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-pr12-action-evidence-run-trace-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-pr12-workflow-run-trace-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-pr12-event-trace-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-pr12-action-evidence-run-trace-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-pr12-workflow-run-trace-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-event-trace-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-action-evidence-run-trace-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-workflow-run-trace-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=27`, `final_pending_external_validation=3`, `final_failed=3`; output `/tmp/reachops-pr12-event-trace-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=27`, `final_pending_external_validation=3`, `final_failed=3`; output `/tmp/reachops-pr12-action-evidence-run-trace-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=27`, `final_pending_external_validation=3`, `final_failed=3`; output `/tmp/reachops-pr12-workflow-run-trace-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr12-event-trace-package-check.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr12-action-evidence-run-trace-package-check.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr12-workflow-run-trace-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-event-trace-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-action-evidence-run-trace-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-workflow-run-trace-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`, `forbidden_count=0`; output `/tmp/reachops-pr12-event-trace-cleanliness.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`, `forbidden_count=0`; output `/tmp/reachops-pr12-action-evidence-run-trace-cleanliness.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`, `forbidden_count=0`; output `/tmp/reachops-pr12-workflow-run-trace-cleanliness.json`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-pr12-run-export-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-pr12-run-scoped-unique-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-pr12-scoring-trace-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-pr12-run-export-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-pr12-run-scoped-unique-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-pr12-scoring-trace-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-run-export-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; blocking scopes include `local_mvp`, `windows_final_artifacts`, and `external_authorized_execution`; output `/tmp/reachops-pr12-run-scoped-unique-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-scoring-trace-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=27`, `final_pending_external_validation=3`, `final_failed=3`; output `/tmp/reachops-pr12-run-export-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=27`, `final_pending_external_validation=3`, `final_failed=3`; output `/tmp/reachops-pr12-run-scoped-unique-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=27`, `final_pending_external_validation=3`, `final_failed=3`; output `/tmp/reachops-pr12-scoring-trace-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr12-run-export-package-check.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr12-run-scoped-unique-package-check.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr12-scoring-trace-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-run-export-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-run-scoped-unique-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-scoring-trace-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`, `forbidden_count=0`; output `/tmp/reachops-pr12-run-export-cleanliness.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`, `forbidden_count=0`; output `/tmp/reachops-pr12-run-scoped-unique-cleanliness.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`, `forbidden_count=0`; output `/tmp/reachops-pr12-scoring-trace-cleanliness.json`.
  - `git diff --check`: passed, exit `0`.
  - `git diff --check`: passed, exit `0`; log `/tmp/reachops-pr12-run-scoped-unique-diff-check.log`.
  - `git diff --check`: passed, exit `0`; log `/tmp/reachops-pr12-scoring-trace-diff-check.log`.
  - `git diff --check`: passed, exit `0`; log `/tmp/reachops-pr12-event-trace-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No customer data, credentials, cookies, real targets, or raw evidence were added.

## Non-blocking engineering work available

- P1 observation model and migration.
- LeadDecision versioning and unified scoring contract.
- Follow/DM evidence validators in no-submit fixtures.
- Windows Credential Manager abstraction and unit tests.
- Encrypted backup format and restore tests.
- License state machine and 7-day grace logic.
- Localization resource extraction for `zh-CN` and `en-US`.
- Public reply-monitor parser using redacted/replay fixtures.

## State-update rules

Codex must update this file at the end of each milestone with:

- status transition
- commit and PR
- tests executed and exact result
- evidence paths
- blockers
- next autonomous action

Do not write `COMPLETE` unless every exit condition is supported by evidence. Implementation completion and external live acceptance are separate states.
