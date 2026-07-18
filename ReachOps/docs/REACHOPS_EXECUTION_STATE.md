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
| P0 | Truthful execution semantics | `IN_REVIEW` | Draft PR #10, branch `agent/reachops-truthful-execution-p0`; rebased on `origin/main`; evidence verification blocker fixed so live mode alone cannot set `evidence_verified`; unverified live submissions are tracked as `submitted_unverified` and do not increment generic success or `execution_success`; `tests.test_truthful_execution_semantics` 7/7 passed on 2026-07-17; exact campaign baseline comparison shows 230 tests on main and PR, both with 14 failures and 1 existing live-readiness error, `new_failures=0`, `new_errors=0` | Review and merge without new Evidence regressions; preserve no-live-action boundary; external Windows/TikTok acceptance remains separate |
| P1 | Immutable Campaign Run / Observation model | `READY` | Architecture audit identified campaign/batch attribution overwrite risk | Idempotent migrations; run-scoped observations; historical decisions immutable; tests pass |
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

## Latest P4 Web DOM start-gate snapshot

- Date: `2026-07-19`
- Branch: `codex/p4-web-dom-start-gate`
- Scope: Web operator panel DOM/start gate only. This does not enter Windows, EXE, installer, or TikTok live-submit scope.
- Code evidence:
  - The initial Start button is disabled until ixBrowser group refresh returns a real, non-stale group list with resolved group counts.
  - Account-preflight `blocked_by_accounts` now disables Start for the affected group and blocks programmatic `/api/start` until the operator repairs/isolates accounts and confirms re-preflight.
  - Stale account-repair results block Start and tell the operator to use the latest repair plan.
  - Refreshed ixBrowser groups render each group count and source in the first-screen group detail panel.
  - The toolbar grid uses stable responsive tracks for desktop and narrow screens.
- Tests and checks:
  - Re-verified on `2026-07-19`; no code changes were needed beyond commit `3259e9b`.
  - `/usr/bin/python3 -m py_compile tools/reachops_web_ui.py tools/reachops_web_panel_dom_smoke.py tests/test_reachops_client_acceptance_status.py`: passed.
  - `/usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed, including account-gate start blocking, stale repair blocking, cross-group unlock, and refreshed group count/source rendering.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_client_acceptance_status.ReachOpsWebUiContractTest.test_web_panel_dom_smoke_clicks_buttons_and_shows_api_feedback`: passed.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, summary `passed=47`, `pending_external_validation=3`, `failed=4`; output `/tmp/reachops-p4-dom-current-delivery-audit.json`. The DOM button-click feedback check is not failed. Remaining failed checks are outside this PR slice: `客户可见设置都有执行证据映射`, `漏斗只显示本轮 Campaign`, `网页端通过服务端本地 API 调用指纹浏览器执行获客`, and `运营 Web 面板运行时 API 冒烟可真实启动和控制执行链`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with the same baseline signature as `origin/main`, `230` tests, `14` failures and `1` error; branch log `/tmp/reachops-p4-dom-current-campaign.log`, main log `/tmp/reachops-main-baseline-current-campaign.log`, comparison `/tmp/reachops-p4-dom-current-baseline-comparison.json`, `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected for final delivery, `final_delivery_ready=false`; output `/tmp/reachops-p4-dom-current-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed as expected for final delivery, pending external validation remains `授权允许时能真实执行`, `真实 TikTok 平台提交`, and `客户端交付验收门禁不会把环境阻断当通过`; output `/tmp/reachops-p4-dom-current-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p4-dom-current-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-p4-dom-current-final-acceptance-gate.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-p4-dom-cleanliness.json`.
  - `git diff --check`: passed.
- Safety:
  - No real browser profile was opened by this slice.
  - No TikTok live-submit was executed.
  - No Windows/EXE/installer work was entered.

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
