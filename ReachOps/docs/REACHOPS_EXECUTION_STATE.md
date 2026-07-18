# ReachOps Execution State

- Schema: `reachops.execution_state.v1`
- Contract: `REACHOPS_MASTER_EXECUTION_CONTRACT_V1.md`
- Last manually reconciled: `2026-07-18`
- Rule: verify every status against the repository before acting.

## Current project state

ReachOps is an independent Windows 10/11 local client project. Product direction is locked. The project is in engineering convergence, not final customer delivery.

## Milestone status

| Priority | Milestone | Status | Verified evidence | Exit condition |
|---|---|---|---|---|
| P0 | Truthful execution semantics | `COMPLETE` | PR #10 squash-merged to `main` as `887f7068ad313c7d3cddf971362cdce42c555946`; live mode alone cannot set `evidence_verified`; unverified live submissions are tracked as `submitted_unverified` and do not increment generic success or `execution_success`; `tests.test_truthful_execution_semantics` 7/7 passed on 2026-07-18 for P2 license slice | Preserve no-live-action boundary; external Windows/TikTok acceptance remains separate |
| P1 | Immutable Campaign Run / Observation model | `IN_REVIEW` | Draft PR #12, branch `codex/p1-immutable-campaign-run-observations`; PR remains Draft/Open | Keep PR #12 Draft for review; continue collector/scoring/report wiring in follow-up PRs after review/merge |
| P2 | Windows local security, licensing, backup, device seats | `IN_PROGRESS` | Draft PR #13 covers Windows Credential Manager AI key foundation; branch `codex/p2-license-grace-state` adds local license state machine and 7-day grace semantics | Windows Credential Manager coverage for all customer secrets, minimal license client, 7-day grace, encrypted backup/restore, tests |
| P3 | Public comment-reply monitoring and lead lifecycle | `PLANNED` | Product contract locked | Automatic public reply detection; action linkage; qualified-lead state; manual conversion/revenue capture |
| P4 | Bilingual UI, installer, update, Windows acceptance | `PLANNED` | Existing packaging/runbook exists but final external acceptance is incomplete | Win10/11 installer, zh-CN/en-US UI, update flow, acceptance matrix, authorized live evidence |
| P5 | DM inbox monitoring | `DEFERRED` | Explicitly deferred behind public reply monitoring | Separate privacy/evidence contract and acceptance after P3/P4 |

## Next autonomous action

1. Keep Draft PR #12 under review; do not mix Windows/security work into that P1 PR.
2. Keep Draft PR #13 under review for Credential Manager AI key foundation.
3. Continue P2 in separate branches:
   - extend Windows Credential Manager storage beyond AI provider key
   - add minimal license client/server-sync contract around the local license state machine
   - add encrypted backup/restore format and tests
4. After PR #12 merges, continue P1 follow-up wiring for collector/scoring/report run-scoped reads.

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

## Latest P2 license snapshot

- Date: `2026-07-18 UTC`
- Branch: `codex/p2-license-grace-state`
- Scope: Local license state machine and 7-day grace semantics only; no Windows packaging, no live TikTok action, no Credential Manager PR #13 changes.
- Code evidence:
  - Added `ReachOps.workbench.license_state.LicenseStateEvaluator`.
  - License states distinguish `missing`, `template`, `inactive`, `invalid_expiry`, `active`, `grace`, and `expired`.
  - `client_access_allowed` and `live_submit_allowed` are separate outputs.
  - Expired licenses inside the 7-day grace window allow local client access but keep live platform submit blocked.
  - `LiveSubmitAuthorizationGate` now attaches `license_state` evidence and still returns `LIVE_SUBMIT_LICENSE_EXPIRED` for expired/grace live-submit attempts.
  - `tools/reachops_activation_status_check.py` now reports `license_state`, `license_client_access_allowed`, and `license_live_submit_allowed`.
- Tests and checks:
  - `set -o pipefail; /usr/bin/python3 -m py_compile ReachOps/workbench/license_state.py ReachOps/workbench/authorization_gate.py tools/reachops_activation_status_check.py tests/test_license_state.py tests/test_reachops_campaign.py 2>&1 | tee /tmp/reachops-p2-license-pycompile.log`: passed, exit `0`.
  - `set -o pipefail; /usr/bin/python3 -m unittest -v tests.test_license_state 2>&1 | tee /tmp/reachops-p2-license-tests.log`: passed, 4 tests, exit `0`.
  - `set -o pipefail; /usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_activation_status_check_reports_device_and_capabilities tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_activation_status_check_blocks_device_mismatch tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_activation_status_template_is_not_authorization tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_activation_status_grace_allows_client_but_not_live_submit tests.test_reachops_campaign.ReachOpsCampaignTests.test_live_submit_rejects_expired_activation_status 2>&1 | tee /tmp/reachops-p2-license-focused-campaign.log`: passed, 5 tests, exit `0`.
  - `set -o pipefail; /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics 2>&1 | tee /tmp/reachops-p2-license-truth.log`: passed, 7 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign 2>&1 | tee /tmp/reachops-p2-license-campaign.log`: failed with existing baseline shape, 231 tests, 14 failures and 1 error; the added grace test passed.
  - Baseline comparison artifact `/tmp/reachops-p2-license-baseline-comparison.json`: `new_failures=[]`, `new_errors=[]`, `resolved_failures=[]`, `resolved_errors=[]`.
  - `set -o pipefail; /usr/bin/python3 tools/reachops_operator_pressure.py --json 2>&1 | tee /tmp/reachops-p2-license-operator-pressure.json`: passed, `status=ok`, exit `0`.
  - `set -o pipefail; /usr/bin/python3 tools/reachops_delivery_audit.py --json 2>&1 | tee /tmp/reachops-p2-license-delivery-audit.json`: failed, exit `1`, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`.
  - `set -o pipefail; /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json 2>&1 | tee /tmp/reachops-p2-license-goal-delivery-runner.json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`.
  - `set -o pipefail; /usr/bin/python3 tools/reachops_goal_status_report.py --json 2>&1 | tee /tmp/reachops-p2-license-goal-status-report.json`: failed, exit `1`, `status=failed`, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`.
  - `set -o pipefail; /usr/bin/python3 tools/reachops_delivery_package_check.py --json 2>&1 | tee /tmp/reachops-p2-license-package-check.json`: failed, exit `1`; missing `exe`, `installer`, `manifest`, and `acceptance_summary`.
  - `set -o pipefail; /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json 2>&1 | tee /tmp/reachops-p2-license-final-acceptance-gate.json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`.
  - `set -o pipefail; /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json 2>&1 | tee /tmp/reachops-p2-license-cleanliness.json`: passed, exit `0`, `forbidden_count=0`.
  - `git diff --check`: passed, exit `0`.
- Safety:
  - No real TikTok action was executed.
  - No customer data, credentials, cookies, real targets, or raw evidence were added.
  - Grace mode does not authorize live platform submit.

## Non-blocking engineering work available

- P1 observation model and migration.
- LeadDecision versioning and unified scoring contract.
- Follow/DM evidence validators in no-submit fixtures.
- Extend Windows Credential Manager coverage beyond AI provider key.
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
