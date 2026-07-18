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
| P1 | Immutable Campaign Run / Observation model | `READY` | Architecture audit identified campaign/batch attribution overwrite risk | Idempotent migrations; run-scoped observations; historical decisions immutable; tests pass |
| P2 | Windows local security, licensing, backup, device seats | `PLANNED` | Product contract locked | Windows Credential Manager, minimal license client, 7-day grace, encrypted backup/restore, tests |
| P3 | Public comment-reply monitoring and lead lifecycle | `PLANNED` | Product contract locked | Automatic public reply detection; action linkage; qualified-lead state; manual conversion/revenue capture |
| P4 | Bilingual UI, installer, update, Windows acceptance | `IN_PROGRESS` | Branch `codex/p4-runtime-smoke-python39` makes the Web runtime API smoke runnable on Python 3.9, isolates activation-gate checks from development bypass, and makes the default Mac launcher enter the unified local Web console. Windows installer/update/live acceptance remain incomplete | Win10/11 installer, zh-CN/en-US UI, update flow, acceptance matrix, authorized live evidence |
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

## Latest P4 runtime-smoke launcher snapshot

- Date: `2026-07-19`
- Branch: `codex/p4-runtime-smoke-python39`
- Scope: P4 local Web runtime smoke and launcher-entry convergence only. No Windows package, EXE, installer, ixBrowser runtime, or TikTok live-submit work was performed.
- Code evidence:
  - `tools/reachops_web_panel_runtime_smoke.py` now works on Python 3.9 by avoiding unsupported `TemporaryDirectory(ignore_cleanup_errors=...)`.
  - The same runtime smoke forces `REACHOPS_REQUIRE_ACTIVATION=1` only inside the smoke and restores the caller environment, so the unauthorized live-comment check cannot pass through development bypass.
  - `ReachOps/launcher.py` now defaults `ReachOpsApp.py` to the unified Web console; Tk remains available only through `--legacy-tk` or `REACHOPS_LEGACY_TK=1` as a diagnostic path.
  - `启动ReachOps本地客户端.command` now delegates to `启动ReachOps统一WebUI.command`; `启动ReachOps原生MacUI.command` explicitly marks Tk as the legacy diagnostic entry.
  - `tests/test_launcher.py` locks the default Web-console launcher contract and the legacy diagnostic opt-in.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/launcher.py tools/reachops_web_panel_runtime_smoke.py tests/test_launcher.py`: passed; log `/tmp/reachops-p4-runtime-pycompile.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_launcher`: passed, 7 tests; log `/tmp/reachops-p4-runtime-launcher-tests.log`.
  - `/usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed, `status=passed`; output `/tmp/reachops-p4-runtime-smoke-final-probe.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_client_acceptance_status.ReachOpsWebUiContractTest.test_web_panel_runtime_smoke_proves_real_api_execution_chain`: passed; log `/tmp/reachops-p4-runtime-smoke-contract-test.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p4-runtime-truth.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-p4-runtime-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, but the previous `运营 Web 面板运行时 API 冒烟可真实启动和控制执行链` failure is no longer present; remaining failures are customer-visible controls, campaign-funnel isolation, web API acquisition-chain residual checks, and Web DOM button feedback; output `/tmp/reachops-p4-runtime-delivery-audit-probe.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with the same known baseline result as `origin/main`: 230 tests, 14 failures, 1 error; branch log `/tmp/reachops-p4-runtime-campaign.log`, comparison `/tmp/reachops-p4-runtime-baseline-comparison.json` has `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, `status=not_ready`, `final_delivery_ready=false`; output `/tmp/reachops-p4-runtime-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, `status=failed`; output `/tmp/reachops-p4-runtime-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed; missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p4-runtime-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed; failed checks are `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-p4-runtime-final-acceptance-gate.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-p4-runtime-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p4-runtime-diff-check.log`.
- Remaining blockers:
  - Delivery audit still has local UI/runtime failures on this main-based branch: customer-visible operator controls, campaign-funnel isolation, web API acquisition-chain residual checks, and Web DOM button feedback. PR #18 and PR #19 address part of this surface separately.
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
