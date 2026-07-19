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
| P4 | Bilingual UI, installer, update, Windows acceptance | `IN_REVIEW` | Branch `codex/p4-web-runtime-smoke` hardens the unified Web client entry, strict live-comment activation gate, account-gate start blocking, group-count DOM evidence, Python 3.9-compatible runtime smoke cleanup, customer-visible control evidence, campaign funnel isolation fixture truthfulness, and Web-to-local-API execution-chain evidence. Runtime smoke, DOM smoke, delivery audit, and goal status now pass locally; final Windows package and authorized live acceptance are still incomplete. | Win10/11 installer, zh-CN/en-US UI, update flow, acceptance matrix, authorized live evidence |
| P5 | DM inbox monitoring | `DEFERRED` | Explicitly deferred behind public reply monitoring | Separate privacy/evidence contract and acceptance after P3/P4 |

## Next autonomous action

1. Finish reviewing Draft PR #12 for P1 immutable Campaign Run / Observation model; keep LeadDecision expansion split unless it is strictly required for P1 traceability.
2. Review Draft PR from branch `codex/p4-web-runtime-smoke`; accept only the Web runtime smoke slice and keep Windows/installer/live-submit validation out of scope.
3. After P1/P4 review, return to the final Windows delivery chain: `ReachOps.exe`, installer, update manifest, Windows acceptance, and authorized live evidence.
4. Keep live-submit external validation separate; do not mark final delivery until package check and final acceptance gate both return `final_delivery_ready=true`.

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

## Latest P4 Web runtime smoke snapshot

- Date: `2026-07-19`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Web runtime smoke, DOM smoke, launcher entry contract, and live-comment activation safety only.
- Code evidence:
  - `python ReachOpsApp.py` now starts the unified Web console by default.
  - Native Tk remains available only through `--legacy-tk` or `REACHOPS_LEGACY_TK=1`.
  - Missing Web launcher no longer silently falls back to native Tk.
  - `/api/activation` uses a strict Web activation payload and blocks live-comment readiness when no local activation status file exists.
  - `/api/start` blocks `live_comment` with human confirmation when activation status is missing or not ready.
  - Account-gate UI blocks repeated starts against a group whose latest profile preflight found no executable accounts until repair is explicitly confirmed.
  - Group detail rendering exposes per-group count status/source for DOM smoke evidence.
  - Web runtime smoke temporary directory cleanup is compatible with `/usr/bin/python3` 3.9.6.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/launcher.py tools/reachops_web_ui.py tools/reachops_web_panel_runtime_smoke.py tools/reachops_web_panel_dom_smoke.py tests/test_launcher.py tests/test_reachops_client_acceptance_status.py`: passed; log `/tmp/reachops-p4-web-runtime-smoke-pycompile.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_launcher`: passed; log `/tmp/reachops-p4-web-runtime-smoke-launcher-tests-final.log`.
  - `/usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed; output `/tmp/reachops-p4-web-runtime-smoke-runtime.json`.
  - `/usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed; output `/tmp/reachops-p4-web-runtime-smoke-dom.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p4-web-runtime-smoke-truth.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed; output `/tmp/reachops-p4-web-runtime-smoke-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed with remaining non-slice blockers; summary changed from `passed=46,pending_external_validation=3,failed=5` to `passed=48,pending_external_validation=3,failed=3`; output `/tmp/reachops-p4-web-runtime-smoke-delivery-audit.json`.
  - Remaining delivery-audit failures: customer-visible settings execution evidence mapping, current Campaign funnel isolation, and Web-to-local-API-to-ixBrowser execution-chain proof.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with the existing baseline shape, 230 tests, 14 failures, 1 error; branch and `origin/main` comparison artifact `/tmp/reachops-p4-web-runtime-smoke-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, `final_delivery_ready=false`; output `/tmp/reachops-p4-web-runtime-smoke-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed; output `/tmp/reachops-p4-web-runtime-smoke-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed because final Windows package artifacts are missing; output `/tmp/reachops-p4-web-runtime-smoke-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, `final_delivery_ready=false`; output `/tmp/reachops-p4-web-runtime-smoke-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p4-web-runtime-smoke-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p4-web-runtime-smoke-diff-check.log`.
- Safety:
  - No Windows build, EXE, installer, or TikTok live-submit was attempted on this macOS branch.
  - Web live-comment activation requires a local activation status file and activation ready state; development bypass is not accepted by the Web activation gate.

## Latest P4 delivery audit convergence snapshot

- Date: `2026-07-19`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Remove the remaining non-external delivery-audit blockers without entering Windows, EXE, installer, or TikTok live-submit.
- Code evidence:
  - Native compatibility console now exposes the existing execution-backed operator controls with customer-visible labels: participation account count, per-target video limit, per-video comment limit, task interval seconds, intent keywords, and exclusion keywords.
  - The campaign funnel isolation fixture now uses activation status plus local evidence sidecar to produce one verified live success for the old Campaign, while the new Campaign remains unexecuted; this preserves the rule that `execution_success` means evidence-verified live success.
  - The local client entry documentation now identifies the unified local client console as the default entry and keeps legacy Tk as diagnostics only.
  - Headless runtime records a `COLLECTING` run-session checkpoint after profile preflight begins.
  - TikTok action execution source explicitly proves use of `WorkbenchBrowserAdapter` and `manager.acquire`.
  - Update manifest generation now writes a portable installer path (`ReachOps-Setup-<version>.exe`) instead of a build-machine absolute path.
  - Final package checking now rejects update manifests whose `installer.path` is absolute, reporting `manifest_installer_path_not_portable`; this prevents Windows final packages from depending on a local build-machine path.
  - Acceptance-summary verification now treats a `comment_reply` live-submit evidence sidecar as invalid unless it includes non-empty `submitted_text` and `comment_visible_confirmed=true`, in addition to screenshot hash, profile, action, URL, and successful result identity checks.
  - Final package checking now rejects update manifests that omit or disable `runtime_policy.preserve_config`, `runtime_policy.preserve_data`, or `runtime_policy.preserve_activation_status`; this prevents a final update package from being accepted if it could overwrite customer-local config, SQLite data, or activation state.
  - Windows installer smoke now reports `preserve_config`, `preserve_data`, and `preserve_activation_status`, and fails with explicit `manifest_preserve_*_missing` codes when the update manifest does not preserve local customer state.
  - Acceptance-summary verification now rejects final passed summaries whose `live_readiness.no_browser_started` is false; readiness evidence must remain a no-browser/no-submit preparation check and cannot be replaced by an already-opened browser action.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/launcher.py ReachOps/workbench/console.py ReachOps/workbench/tiktok_action_executor.py tools/run_reachops_headless_macos.py tools/reachops_delivery_audit.py`: passed.
  - `/usr/bin/python3 -m unittest -v tests.test_launcher`: passed; log `/tmp/reachops-p4-delivery-audit-launcher-tests.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_delivery_audit_reports_local_passes_and_external_pending`: passed; log `/tmp/reachops-p4-delivery-audit-focused-test.log`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-p4-delivery-audit-zero.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed; log `/tmp/reachops-p4-delivery-audit-truth.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-p4-delivery-audit-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed; output `/tmp/reachops-p4-delivery-audit-runtime-smoke.json`.
  - `/usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed; output `/tmp/reachops-p4-delivery-audit-dom-smoke.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `stages_passed=3,stages_pending_external_validation=2,stages_failed=0,final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p4-delivery-audit-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`; output `/tmp/reachops-p4-delivery-audit-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, `final_delivery_ready=false`; output `/tmp/reachops-p4-delivery-audit-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`; output `/tmp/reachops-p4-delivery-audit-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p4-delivery-audit-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p4-delivery-audit-diff-check.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with known baseline shape, 230 tests, 11 failures, 1 error; branch/main comparison artifact `/tmp/reachops-p4-delivery-audit-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`, and resolved failures `test_reachops_delivery_audit_reports_local_passes_and_external_pending`, `test_reachops_goal_status_cli_uses_current_client_delivery_gate`, `test_reachops_goal_status_resolves_client_delivery_gate_independently`.
  - Portable manifest gate hardening: `/usr/bin/python3 -m py_compile tools/write_reachops_update_manifest.py tools/reachops_delivery_package_check.py tests/test_reachops_campaign.py`: passed, exit `0`; log `/tmp/reachops-p4-manifest-portable-pycompile.log`.
  - Portable manifest gate hardening: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_update_manifest_contains_hash_and_preserve_policy tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_update_manager_validates_manifest_hash_and_install_args tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed, exit `0`; log `/tmp/reachops-p4-manifest-portable-focused.log`.
  - Portable manifest gate hardening: `/usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed, exit `0`, `status=passed`; output `/tmp/reachops-p4-manifest-portable-runtime-smoke.json`.
  - Portable manifest gate hardening: `/usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed, exit `0`, `status=passed`; output `/tmp/reachops-p4-manifest-portable-dom-smoke.json`.
  - Portable manifest gate hardening: `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, exit `0`, `status=ok`, summary `passed=51`, `pending_external_validation=3`, `failed=0`; output `/tmp/reachops-p4-manifest-portable-delivery-audit.json`.
  - Portable manifest gate hardening: `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed, exit `0`, `status=ready_for_external_validation`, summary `final_passed=30`, `final_pending_external_validation=3`, `final_failed=0`; output `/tmp/reachops-p4-manifest-portable-goal-status-report.json`.
  - Portable manifest gate hardening: `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-p4-manifest-portable-truth.log`.
  - Portable manifest gate hardening: `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, exit `0`, `status=ok`; output `/tmp/reachops-p4-manifest-portable-operator-pressure.json`.
  - Portable manifest gate hardening: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with known improved baseline shape, 230 tests, 11 failures, 1 error; branch log `/tmp/reachops-p4-manifest-portable-campaign.log`; main baseline log `/tmp/reachops-main-p4-manifest-portable-campaign.log`; comparison artifact `/tmp/reachops-p4-manifest-portable-baseline-comparison.json`, `new_failures=[]`, `new_errors=[]`, resolved three existing delivery/goal-status failures.
  - Portable manifest gate hardening: `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, `final_delivery_ready=false`; missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p4-manifest-portable-package-check.json`.
  - Portable manifest gate hardening: `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-manifest-portable-goal-delivery-runner.json`.
  - Portable manifest gate hardening: `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-manifest-portable-final-gate.json`.
  - Portable manifest gate hardening: `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`, `forbidden_count=0`; output `/tmp/reachops-p4-manifest-portable-cleanliness.json`.
  - Portable manifest gate hardening: `git diff --check`: passed, exit `0`; log `/tmp/reachops-p4-manifest-portable-diff-check.log`.
  - Comment evidence hardening: `/usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tests/test_reachops_campaign.py`: passed, exit `0`; log `/tmp/reachops-p4-comment-evidence-pycompile.log`.
  - Comment evidence hardening: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_live_submit_acceptance_rejects_unconfirmed_comment_evidence`: passed, exit `0`; log `/tmp/reachops-p4-comment-evidence-focused.log`.
  - Comment evidence hardening: `/usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed, exit `0`, `status=passed`; output `/tmp/reachops-p4-comment-evidence-runtime-smoke.json`.
  - Comment evidence hardening: `/usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed, exit `0`, `status=passed`; output `/tmp/reachops-p4-comment-evidence-dom-smoke.json`.
  - Comment evidence hardening: `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, exit `0`, `status=ok`, summary `passed=51`, `pending_external_validation=3`, `failed=0`; output `/tmp/reachops-p4-comment-evidence-delivery-audit.json`.
  - Comment evidence hardening: `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed, exit `0`, `status=ready_for_external_validation`, summary `final_passed=30`, `final_pending_external_validation=3`, `final_failed=0`; output `/tmp/reachops-p4-comment-evidence-goal-status-report.json`.
  - Comment evidence hardening: `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-p4-comment-evidence-truth.log`.
  - Comment evidence hardening: `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, exit `0`, `status=ok`; output `/tmp/reachops-p4-comment-evidence-operator-pressure.json`.
  - Comment evidence hardening: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with known improved baseline shape, 230 tests, 11 failures, 1 error; branch log `/tmp/reachops-p4-comment-evidence-campaign.log`; main baseline log `/tmp/reachops-main-p4-comment-evidence-campaign.log`; comparison artifact `/tmp/reachops-p4-comment-evidence-baseline-comparison.json`, `new_failures=[]`, `new_errors=[]`, resolved three existing delivery/goal-status failures.
  - Comment evidence hardening: `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, `final_delivery_ready=false`; missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p4-comment-evidence-package-check.json`.
  - Comment evidence hardening: `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-comment-evidence-goal-delivery-runner.json`.
  - Comment evidence hardening: `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-comment-evidence-final-gate.json`.
  - Comment evidence hardening: `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`, `forbidden_count=0`; output `/tmp/reachops-p4-comment-evidence-cleanliness.json`.
  - Comment evidence hardening: `git diff --check`: passed, exit `0`; log `/tmp/reachops-p4-comment-evidence-diff-check.log`.
  - Runtime policy manifest hardening: `/usr/bin/python3 -m py_compile tools/reachops_delivery_package_check.py tests/test_reachops_campaign.py`: passed, exit `0`; log `/tmp/reachops-p4-runtime-policy-pycompile.log`.
  - Runtime policy manifest hardening: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_packaging_files_define_standalone_windows_artifacts`: passed, exit `0`; log `/tmp/reachops-p4-runtime-policy-focused.log`.
  - Runtime policy manifest hardening: `/usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed, exit `0`, `status=passed`; output `/tmp/reachops-p4-runtime-policy-runtime-smoke.json`.
  - Runtime policy manifest hardening: `/usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed, exit `0`, `status=passed`; output `/tmp/reachops-p4-runtime-policy-dom-smoke.json`.
  - Runtime policy manifest hardening: `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, exit `0`, `status=ok`, summary `passed=51`, `pending_external_validation=3`, `failed=0`; output `/tmp/reachops-p4-runtime-policy-delivery-audit.json`.
  - Runtime policy manifest hardening: `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed, exit `0`, `status=ready_for_external_validation`, summary `final_passed=30`, `final_pending_external_validation=3`, `final_failed=0`; output `/tmp/reachops-p4-runtime-policy-goal-status-report.json`.
  - Runtime policy manifest hardening: `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-p4-runtime-policy-truth.log`.
  - Runtime policy manifest hardening: `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, exit `0`, `status=ok`; output `/tmp/reachops-p4-runtime-policy-operator-pressure.json`.
  - Runtime policy manifest hardening: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with known improved baseline shape, 230 tests, 11 failures, 1 error; branch log `/tmp/reachops-p4-runtime-policy-campaign.log`; main baseline at `887f706` failed with 230 tests, 14 failures, 1 error; main log `/tmp/reachops-main-runtime-policy-campaign.log`; comparison artifact `/tmp/reachops-p4-runtime-policy-baseline-comparison.json`, `new_failures=[]`, `new_errors=[]`, resolved three existing delivery/goal-status failures.
  - Runtime policy manifest hardening: `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, `final_delivery_ready=false`; missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p4-runtime-policy-package-check.json`.
  - Runtime policy manifest hardening: `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-runtime-policy-goal-delivery-runner.json`.
  - Runtime policy manifest hardening: `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-runtime-policy-final-gate.json`.
  - Runtime policy manifest hardening: `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`, `forbidden_count=0`; output `/tmp/reachops-p4-runtime-policy-cleanliness.json`.
  - Runtime policy manifest hardening: `git diff --check`: passed, exit `0`; log `/tmp/reachops-p4-runtime-policy-diff-check.log`.
  - Live readiness no-browser hardening: `/usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tests/test_reachops_campaign.py`: passed, exit `0`; log `/tmp/reachops-p4-live-readiness-browser-pycompile.log`.
  - Live readiness no-browser hardening: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures`: passed, exit `0`; log `/tmp/reachops-p4-live-readiness-browser-focused.log`.
  - Live readiness no-browser hardening: `/usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed, exit `0`, `status=passed`; output `/tmp/reachops-p4-live-readiness-browser-runtime-smoke.json`.
  - Live readiness no-browser hardening: `/usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed, exit `0`, `status=passed`; output `/tmp/reachops-p4-live-readiness-browser-dom-smoke.json`.
  - Live readiness no-browser hardening: `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, exit `0`, `status=ok`, summary `passed=51`, `pending_external_validation=3`, `failed=0`; output `/tmp/reachops-p4-live-readiness-browser-delivery-audit.json`.
  - Live readiness no-browser hardening: `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed, exit `0`, `status=ready_for_external_validation`, summary `final_passed=30`, `final_pending_external_validation=3`, `final_failed=0`; output `/tmp/reachops-p4-live-readiness-browser-goal-status-report.json`.
  - Live readiness no-browser hardening: `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-p4-live-readiness-browser-truth.log`.
  - Live readiness no-browser hardening: `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, exit `0`, `status=ok`; output `/tmp/reachops-p4-live-readiness-browser-operator-pressure.json`.
  - Live readiness no-browser hardening: `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with known improved baseline shape, 230 tests, 11 failures, 1 error; branch log `/tmp/reachops-p4-live-readiness-browser-campaign.log`; main baseline at `887f706` failed with 230 tests, 14 failures, 1 error; main log `/tmp/reachops-main-live-readiness-browser-campaign.log`; comparison artifact `/tmp/reachops-p4-live-readiness-browser-baseline-comparison.json`, `new_failures=[]`, `new_errors=[]`, resolved three existing delivery/goal-status failures.
  - Live readiness no-browser hardening: `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, `final_delivery_ready=false`; missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p4-live-readiness-browser-package-check.json`.
  - Live readiness no-browser hardening: `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-live-readiness-browser-goal-delivery-runner.json`.
  - Live readiness no-browser hardening: `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-live-readiness-browser-final-gate.json`.
  - Live readiness no-browser hardening: `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`, `forbidden_count=0`; output `/tmp/reachops-p4-live-readiness-browser-cleanliness.json`.
  - Live readiness no-browser hardening: `git diff --check`: passed, exit `0`; log `/tmp/reachops-p4-live-readiness-browser-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, or update manifest was generated on macOS.
  - Fixture live success used local redacted evidence and `REACHOPS_ALLOW_TEST_FIXTURE_LIVE=1`, then restored the previous environment value.

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
