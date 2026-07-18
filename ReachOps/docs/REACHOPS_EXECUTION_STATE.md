# ReachOps Execution State

- Schema: `reachops.execution_state.v1`
- Contract: `REACHOPS_MASTER_EXECUTION_CONTRACT_V1.md`
- Last manually reconciled: `2026-07-17`
- Rule: verify every status against the repository before acting.

## Current project state

ReachOps is an independent Windows 10/11 local client project. Product direction is locked. The project is in engineering convergence, not final customer delivery.

## Milestone status

| Priority | Milestone | Status | Verified evidence | Exit condition |
|---|---|---|---|---|
| P0 | Truthful execution semantics | `COMPLETE` | PR #10 squash-merged to `main` as `887f7068ad313c7d3cddf971362cdce42c555946`; live mode alone cannot set `evidence_verified`; unverified live submissions are tracked as `submitted_unverified` and do not increment generic success or `execution_success`; `tests.test_truthful_execution_semantics` 7/7 passed on 2026-07-17; exact campaign baseline comparison before merge showed `new_failures=0`, `new_errors=0` | Preserve no-live-action boundary; external Windows/TikTok acceptance remains separate |
| P1 | Immutable Campaign Run / Observation model | `IN_REVIEW` | Draft PR #12, branch `codex/p1-immutable-campaign-run-observations`; review pass adds deterministic legacy run handling, run-scoped traceability for observations/executions/events/errors, and focused coverage for campaign isolation, run isolation, observation/evidence traceability, migration compatibility, and idempotency; `tests.test_campaign_run_observations` 5/5 passed on 2026-07-18 UTC; campaign regression comparison against `main` showed `new_failures=[]`, `new_errors=[]` | Keep PR #12 Draft for review; continue collector/scoring/report wiring in follow-up PRs |
| P2 | Windows local security, licensing, backup, device seats | `PLANNED` | Product contract locked | Windows Credential Manager, minimal license client, 7-day grace, encrypted backup/restore, tests |
| P3 | Public comment-reply monitoring and lead lifecycle | `PLANNED` | Product contract locked | Automatic public reply detection; action linkage; qualified-lead state; manual conversion/revenue capture |
| P4 | Bilingual UI, installer, update, Windows acceptance | `PLANNED` | Existing packaging/runbook exists but final external acceptance is incomplete | Win10/11 installer, zh-CN/en-US UI, update flow, acceptance matrix, authorized live evidence |
| P5 | DM inbox monitoring | `DEFERRED` | Explicitly deferred behind public reply monitoring | Separate privacy/evidence contract and acceptance after P3/P4 |

## Next autonomous action

1. Review Draft PR #12 from branch `codex/p1-immutable-campaign-run-observations`.
2. Keep PR #9 frozen until it is re-reviewed or split against the P0/P1 contract.
3. After the first P1 slice merges, continue P1 in a follow-up PR:
   - wire collectors to write `source_observations`, `content_observations`, and `comment_observations`
   - wire scoring to write `candidate_observations` and versioned `lead_decisions`
   - ensure reports and exports prefer run-scoped reads
   - add cross-campaign and cross-batch isolation tests at workflow level

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
- Scope: First P1 storage-contract slice only; no PR #9 changes and no real TikTok action.
- Code evidence:
  - Added `campaign_runs` as the immutable run ledger, one run per collection batch, with idempotent backfill for existing batches.
  - Added `source_observations`, `content_observations`, `comment_observations`, `candidate_observations`, and versioned `lead_decisions`.
  - Added `run_id` compatibility columns to collection tasks, discovered creators/content, shop content, candidates, leads, actions, outreach executions, events, and errors.
  - Added storage APIs to record run-scoped observations and append lead decisions without mutating prior decisions.
  - `comment_observations` now preserve distinct same-user comments in the same content/run by including `comment_text` in the idempotency key, while duplicate identical comments remain idempotent.
  - Added optional `run_id` filters for candidates, leads, actions, outreach executions, and execution counts.
  - Legacy migration now uses deterministic `legacy_run_<batch_id>` identifiers plus `legacy_backfill` metadata instead of random `run_*` IDs, and does not rewrite old candidate, lead, action, outreach execution, evidence-path, or error rows to claim a real run.
  - `list_observations_for_run(...)` now returns observation rows plus run-scoped outreach executions, events, and errors so evidence paths and error context are traceable by run.
  - LeadDecision remains scoped to immutable versioned decisions in this PR; broader scoring/lead lifecycle wiring is intentionally deferred to the follow-up P1 wiring PR.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py ReachOps/intelligence/schemas.py tests/test_campaign_run_observations.py`: passed, exit `0`; log `/tmp/reachops-pr12-comment-observation-pycompile.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_campaign_run_observations`: passed, 5 tests, exit `0`; log `/tmp/reachops-pr12-comment-observation-target.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-pr12-comment-observation-truth.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-pr12-comment-observation-campaign.log`.
  - `main` baseline at `887f706`: `/tmp/reachops-main-baseline-pr12-comment-observation-campaign.log` failed with the same 14 failures and 1 error.
  - Baseline comparison result: `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-pr12-comment-observation-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-pr12-comment-observation-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-comment-observation-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=27`, `final_pending_external_validation=3`, `final_failed=3`; output `/tmp/reachops-pr12-comment-observation-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr12-comment-observation-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr12-comment-observation-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`, `forbidden_count=0`; output `/tmp/reachops-pr12-comment-observation-cleanliness.json`.
  - `git diff --check`: passed, exit `0`; log `/tmp/reachops-pr12-comment-observation-diff-check.log`.
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
