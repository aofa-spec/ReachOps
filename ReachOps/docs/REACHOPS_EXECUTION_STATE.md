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
| P1 | Immutable Campaign Run / Observation model | `IN_PROGRESS` | Branch `codex/p1-campaign-funnel-isolation` aligns the campaign-funnel isolation audit with P0 truthful execution semantics and verifies funnel lead/action counts against current batch metrics. Broader immutable run/observation work remains separate | Idempotent migrations; run-scoped observations; historical decisions immutable; tests pass |
| P2 | Windows local security, licensing, backup, device seats | `PLANNED` | Product contract locked | Windows Credential Manager, minimal license client, 7-day grace, encrypted backup/restore, tests |
| P3 | Public comment-reply monitoring and lead lifecycle | `PLANNED` | Product contract locked | Automatic public reply detection; action linkage; qualified-lead state; manual conversion/revenue capture |
| P4 | Bilingual UI, installer, update, Windows acceptance | `PLANNED` | Existing packaging/runbook exists but final external acceptance is incomplete | Win10/11 installer, zh-CN/en-US UI, update flow, acceptance matrix, authorized live evidence |
| P5 | DM inbox monitoring | `DEFERRED` | Explicitly deferred behind public reply monitoring | Separate privacy/evidence contract and acceptance after P3/P4 |

## Next autonomous action

1. Keep P1 slices separate and reviewable; do not expand campaign-funnel isolation with Windows package, EXE, installer, or TikTok live-submit work.
2. Review and merge the campaign-funnel isolation audit correction only after accepting the known main baseline failures separately.
3. Continue P1 on separate branches/PRs:
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

## Latest P1 campaign-funnel isolation audit snapshot

- Date: `2026-07-19`
- Branch: `codex/p1-campaign-funnel-isolation`
- Scope: P1 campaign/batch funnel isolation audit only. No Windows package, EXE, installer, ixBrowser runtime, or TikTok live-submit work was performed.
- Code evidence:
  - `ReachOps/workbench/workflow_service.py` now prefers the current batch `total_sources` when a campaign funnel is scoped to a batch, so same-campaign historical sources do not inflate the current-run funnel.
  - `tools/reachops_delivery_audit.py` now records per-batch storage metrics and truth counts in the campaign-funnel isolation fixture.
  - The `漏斗只显示本轮 Campaign` check now requires candidate snapshots, action snapshots, `customer_leads`, and `outreach_actions` to match the current campaign batch.
  - The same check preserves P0 truthfulness: dry-run fixture execution must show `simulated_success>0`, while `old_execution_success`, `new_execution_success`, and `live_verified` remain `0`.
  - `tests/test_reachops_campaign.py` locks this contract in delivery-audit evidence assertions, the focused campaign-funnel batch-status regression test, and a same-campaign multi-batch `target_sources` regression.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/workbench/workflow_service.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed; log `/tmp/reachops-pr19-target-sources-pycompile.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-pr19-target-sources-truth.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_campaign_funnel_target_sources_prefers_current_batch tests.test_reachops_campaign.ReachOpsCampaignTests.test_campaign_funnel_counts_only_current_batch_execution_statuses`: passed; log `/tmp/reachops-pr19-target-sources-target.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with the same known failure/error set as `origin/main`; branch ran 231 tests with 14 failures and 1 error, main ran 230 tests with 14 failures and 1 error; branch log `/tmp/reachops-pr19-target-sources-campaign.log`, main log `/tmp/reachops-main-baseline-pr19-target-sources-campaign.log`.
  - Baseline comparison result: `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-pr19-target-sources-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, but `漏斗只显示本轮 Campaign` passed and the fixture evidence shows current-batch `target_sources=1`; remaining failures are UI/runtime checks from the current main-based branch; output `/tmp/reachops-pr19-target-sources-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, `status=not_ready`, `final_delivery_ready=false`; output `/tmp/reachops-pr19-target-sources-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, `status=failed`, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=28`, `final_pending_external_validation=3`, `final_failed=2`; output `/tmp/reachops-pr19-target-sources-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed; missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr19-target-sources-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed; failed checks are `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr19-target-sources-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-pr19-target-sources-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-pr19-target-sources-diff-check.log`.
- Remaining blockers:
  - Delivery audit still has local UI/runtime failures on this main-based branch: customer-visible operator controls, web API acquisition chain, web runtime API smoke, and web button JS/API feedback.
  - Windows final artifacts remain missing: `dist/ReachOps/ReachOps.exe`, `dist/installer/ReachOps-Setup-0.4.0.exe`, `dist/installer/reachops-update-manifest.json`, and `reports/reachops_acceptance/acceptance_summary.json`.
  - External authorized live TikTok validation remains pending and must not be fabricated on Mac.

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
