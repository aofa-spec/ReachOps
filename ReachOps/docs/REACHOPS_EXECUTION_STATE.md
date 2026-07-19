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
| P2 | Windows local security, licensing, backup, device seats | `IN_PROGRESS` | Windows Credential Manager secret-storage contract exists on branch `codex/p4-web-runtime-smoke`; license-state evaluator models active/current, revoked, expired, and 7-day grace while keeping grace out of live-submit readiness; encrypted `.reachops-backup` lightweight and full selected-evidence backup/restore contracts now cover customer password, manifest, integrity hashes, preview, wrong password, corrupted archive, interrupted restore rollback, unsafe path rejection, secret/cookie exclusions, lightweight raw-evidence exclusion, and full backup selected evidence inclusion; focused P2 tests passed on 2026-07-19 | Complete minimal external license refresh client and Windows Credential Manager validation on Windows |
| P3 | Public comment-reply monitoring and lead lifecycle | `PLANNED` | Product contract locked | Automatic public reply detection; action linkage; qualified-lead state; manual conversion/revenue capture |
| P4 | Bilingual UI, installer, update, Windows acceptance | `IN_REVIEW` | Branch `codex/p4-web-runtime-smoke` hardens the unified Web client entry, strict live-comment activation gate, account-gate start blocking, group-count DOM evidence, Python 3.9-compatible runtime smoke cleanup, customer-visible control evidence, campaign funnel isolation fixture truthfulness, and Web-to-local-API execution-chain evidence. Runtime smoke, DOM smoke, delivery audit, and goal status now pass locally; final Windows package and authorized live acceptance are still incomplete. | Win10/11 installer, zh-CN/en-US UI, update flow, acceptance matrix, authorized live evidence |
| P5 | DM inbox monitoring | `DEFERRED` | Explicitly deferred behind public reply monitoring | Separate privacy/evidence contract and acceptance after P3/P4 |

## Next autonomous action

1. Finish reviewing Draft PR #12 for P1 immutable Campaign Run / Observation model; keep LeadDecision expansion split unless it is strictly required for P1 traceability.
2. Review Draft PR from branch `codex/p4-web-runtime-smoke`; accept only the Web runtime smoke slice and keep Windows/installer/live-submit validation out of scope.
3. Continue P2 convergence with the next non-external slice: minimal external license refresh client contract, without storing secrets or customer business data outside the local device boundary.
4. After P1/P4 review, return to the final Windows delivery chain: `ReachOps.exe`, installer, update manifest, Windows acceptance, and authorized live evidence.
5. Keep live-submit external validation separate; do not mark final delivery until package check and final acceptance gate both return `final_delivery_ready=true`.

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

## Latest P4 local client validation refresh

- Date: `2026-07-19`
- Branch: `codex/p4-web-runtime-smoke`
- PR: Draft PR #26, comment `https://github.com/aofa-spec/ReachOps/pull/26#issuecomment-5015049709`
- Scope: Validate the current local client console and P4 Web runtime slice without entering Windows packaging, EXE generation, installer generation, or TikTok live-submit.
- Verified current UI:
  - Local client console is reachable at `http://127.0.0.1:8769/`.
  - `/api/version` returned `status=ok`, `display_version=客户端 v20`, `client_surface=local_client_console`, `loopback_host=127.0.0.1`, and `no_submit=true`.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/launcher.py ReachOps/workbench/console.py ReachOps/workbench/tiktok_action_executor.py tools/reachops_web_panel_runtime_smoke.py tools/reachops_web_panel_dom_smoke.py tools/reachops_web_ui.py tools/run_reachops_headless_macos.py tools/reachops_delivery_audit.py tools/reachops_delivery_package_check.py tools/verify_reachops_acceptance_summary.py tools/write_reachops_update_manifest.py tests/test_launcher.py tests/test_reachops_campaign.py`: passed; log `/tmp/reachops-pr26-pycompile-latest.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_launcher tests.test_truthful_execution_semantics`: passed, 13 tests; log `/tmp/reachops-pr26-launcher-truth-latest.log`.
  - `/usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed; output `/tmp/reachops-pr26-web-runtime-smoke-latest.json`.
  - `/usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed; output `/tmp/reachops-pr26-web-dom-smoke-latest.json`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-pr26-operator-pressure-latest.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-pr26-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed, `status=not_started`, `final_delivery_ready=false`, failed check `acceptance:ready`; blocker: `未看到 PLAN campaign，推广目标未进入任务规划。`
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-pr26-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, `status=failed`, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr26-package-check.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-pr26-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-pr26-diff-check.log`.
- Current blocker clarification:
  - The current Mac client-delivery evidence is `not_started` and must not be treated as current local MVP pass.
  - Final Windows delivery remains blocked by missing `dist/ReachOps/ReachOps.exe`, `dist/installer/ReachOps-Setup-0.4.0.exe`, `dist/installer/reachops-update-manifest.json`, and `reports/reachops_acceptance/acceptance_summary.json`.
  - Authorized Windows/TikTok live validation remains external and pending.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, or live-submit was attempted on macOS.
  - The local UI remains default no-submit.

## Latest P4 manifest installer binding hardening

- Date: `2026-07-19`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten final Windows package evidence validation without generating Windows artifacts on macOS.
- Code evidence:
  - `tools/reachops_delivery_package_check.py` now rejects update manifests that omit `installer.file_name` or `installer.path`, or whose `installer.file_name`, `installer.path`, or resolved installer path name does not match the expected versioned final installer `ReachOps-Setup-<VERSION>.exe`.
  - This prevents a final package from passing with a manifest that points at a stale or differently named installer while local expected artifacts happen to exist.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile tools/reachops_delivery_package_check.py tests/test_reachops_campaign.py`: passed; log `/tmp/reachops-p4-manifest-installer-name-pycompile.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_update_manifest_contains_hash_and_preserve_policy`: passed; log `/tmp/reachops-p4-manifest-installer-name-focused.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p4-manifest-installer-name-truth.log`.
  - `/usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed; output `/tmp/reachops-p4-manifest-installer-name-runtime-smoke.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-p4-manifest-installer-name-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p4-manifest-installer-name-goal-status.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p4-manifest-installer-name-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-manifest-installer-name-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-manifest-installer-name-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p4-manifest-installer-name-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p4-manifest-installer-name-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - Final delivery remains blocked until Windows artifacts and authorized live validation are produced and strict final gates pass.

## Latest P4 runtime cooldown hardening snapshot

- Date: `2026-07-19`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Runtime profile cooldown and profile-health convergence without entering Windows packaging or TikTok live-submit.
- Code evidence:
  - Empty collection retries now increment runtime profile failure counts before discarding the reusable session, so a single profile that repeatedly returns `EMPTY_RESULT_RETRY` reaches the configured runtime cooldown threshold and stops consuming remaining sources in the same run.
  - Profile-health recording now places profiles into cooldown after repeated failures even when the last error code is not in the hard-stop list; low health-score cooldown remains limited to hard-stop error codes.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py ReachOps/intelligence/growth_task_router.py tests/test_reachops_campaign.py`: passed; log `/tmp/reachops-p4-runtime-cooldown-pycompile.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_real_mode_retries_next_profile_when_page_has_empty_result tests.test_reachops_campaign.ReachOpsCampaignTests.test_real_mode_reports_comment_user_empty_when_content_was_discovered tests.test_reachops_campaign.ReachOpsCampaignTests.test_empty_result_failures_put_single_profile_into_runtime_cooldown tests.test_reachops_campaign.ReachOpsCampaignTests.test_profile_health_recording_is_safe_for_parallel_account_updates`: passed; log `/tmp/reachops-p4-runtime-cooldown-focused.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p4-runtime-cooldown-truth.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-p4-runtime-cooldown-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-p4-runtime-cooldown-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p4-runtime-cooldown-goal-status.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with known improved baseline shape, 230 tests, 3 failures, 0 errors; branch log `/tmp/reachops-p4-runtime-cooldown-campaign.log`; main baseline at `887f706` failed with 230 tests, 14 failures, 1 error; main log `/tmp/reachops-main-runtime-cooldown-campaign.log`; comparison artifact `/tmp/reachops-p4-runtime-cooldown-baseline-comparison.json`, `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p4-runtime-cooldown-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-runtime-cooldown-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; current blockers include `external_authorized_execution`, `client_delivery_gate`, and `windows_final_artifacts`; output `/tmp/reachops-p4-runtime-cooldown-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p4-runtime-cooldown-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p4-runtime-cooldown-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - Final delivery remains blocked until Windows artifacts, current client-delivery evidence, and authorized live validation are produced and strict final gates pass.

## Latest P4 ixBrowser group display compatibility snapshot

- Date: `2026-07-19`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Restore count-prefix compatibility for ixBrowser group display labels while preserving customer-readable localized group names.
- Code evidence:
  - `group_display_name(...)` now preserves the existing localized operator label for non-ASCII customer group names, such as `加拿大获客组 · 12 个账号 · ID: 281726`.
  - ASCII ixBrowser group names and the `全部配置` aggregate row also include the stable `[count]` prefix required by registry refresh and audit evidence, such as `[    2] Canada · 2 个账号 · ID: 281726`.
  - Existing `group_name_from_display(...)` parsing continues to strip the prefix before resolving the selected ixBrowser group name.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/workbench/standalone_app.py tests/test_reachops_campaign.py`: passed; log `/tmp/reachops-p4-group-display-pycompile.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_profile_group_display_keeps_operator_readable_group_name tests.test_reachops_campaign.ReachOpsCampaignTests.test_profile_registry_refresh_resolves_group_counts tests.test_reachops_campaign.ReachOpsCampaignTests.test_profile_registry_refresh_builds_groups_from_full_profile_list`: passed; log `/tmp/reachops-p4-group-display-focused.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p4-group-display-truth.log`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-p4-group-display-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-p4-group-display-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p4-group-display-goal-status.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with known current-environment PM boundary blocker only, 230 tests, 1 failure, 0 errors; branch log `/tmp/reachops-p4-group-display-campaign.log`; main baseline at `887f706` failed with 230 tests, 14 failures, 1 error; comparison artifact `/tmp/reachops-p4-group-display-baseline-comparison.json`, `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p4-group-display-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-group-display-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; current blockers include `external_authorized_execution`, `client_delivery_gate`, and `windows_final_artifacts`; output `/tmp/reachops-p4-group-display-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p4-group-display-cleanliness.json`.
  - `git diff --check`: passed after documentation update; log `/tmp/reachops-p4-group-display-diff-check-final.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - Final delivery remains blocked until Windows artifacts, current client-delivery evidence, and authorized live validation are produced and strict final gates pass.

## Latest P4 bilingual UI resource slice

- Date: `2026-07-19`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Start the `zh-CN` / `en-US` UI resource contract for the local client console without claiming full UI localization completion.
- Code evidence:
  - `tools/reachops_web_ui.py` now defines `DEFAULT_UI_LOCALE=zh-CN`, `SUPPORTED_UI_LOCALES=("zh-CN","en-US")`, and a core `UI_TEXT_RESOURCES` map for common local-client labels, actions, modes, final-gate labels, no-submit status, and report labels.
  - `/api/locales` returns `schema_version=reachops.web_ui_locales.v1`, both supported locales, resource key counts, and `no_browser_started=true` / `no_submit=true`.
  - `tools/reachops_web_panel_runtime_smoke.py` verifies the locale endpoint and required key coverage without side effects.
  - `tools/reachops_delivery_audit.py` now includes the Web UI locale API/resource contract in the Web-to-local-API evidence check.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile tools/reachops_web_ui.py tools/reachops_web_panel_runtime_smoke.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed; log `/tmp/reachops-p4-locales-pycompile.log`.
  - `/usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed; locale check `locales_endpoint_exposes_zh_cn_and_en_us_without_side_effects=true`; output `/tmp/reachops-p4-locales-runtime-smoke.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; locale source-contract check `web_ui_locales_api_exposes_zh_cn_en_us=true`; output `/tmp/reachops-p4-locales-delivery-audit.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_delivery_audit_reports_local_passes_and_external_pending`: passed; log `/tmp/reachops-p4-locales-focused.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p4-locales-truth.log`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p4-locales-goal-status.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p4-locales-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-locales-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-locales-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p4-locales-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p4-locales-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - This is a resource-contract slice only; full first-viewport UI language switching still remains future P4 work.

## Latest P4 first-viewport locale switching slice

- Date: `2026-07-19`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Make the first-viewport local client console controls switchable between `zh-CN` and `en-US` without changing runtime architecture or claiming full UI localization completion.
- Code evidence:
  - `tools/reachops_web_ui.py` now exposes a header language selector `localeSelect`, first-viewport `data-i18n` bindings, localStorage-backed locale persistence, and `applyLocale()` / `loadLocales()` client logic that reads `/api/locales`.
  - First-viewport bindings cover the app title/subtitle, navigation tabs, target/group/source/mode/volume controls, core mode and source options, runtime preview labels, and start/pause/resume/stop controls.
  - The locale switch remains local UI behavior only: it reads the local `/api/locales` endpoint and does not open browser profiles or submit platform actions.
  - `tools/reachops_web_panel_runtime_smoke.py` now verifies both the locale resource endpoint and the first-viewport switching wiring.
  - `tools/reachops_delivery_audit.py` now includes the first-viewport locale switching contract in the Web-to-local-API evidence check.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile tools/reachops_web_ui.py tools/reachops_web_panel_runtime_smoke.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - `/usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed; `first_viewport_locale_switching_is_wired_without_submit_side_effects=true`; output `/tmp/reachops-p4-first-viewport-locale-runtime-smoke.json`.
  - `/usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed; output `/tmp/reachops-p4-first-viewport-locale-dom-smoke.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-p4-first-viewport-locale-delivery-audit.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p4-first-viewport-locale-truth.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-p4-first-viewport-locale-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p4-first-viewport-locale-goal-status.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with known baseline shape, 230 tests, 11 failures, 1 error; branch log `/tmp/reachops-p4-first-viewport-locale-campaign.log`; `origin/main` baseline log `/tmp/reachops-main-first-viewport-locale-campaign.log`; comparison artifact `/tmp/reachops-p4-first-viewport-locale-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p4-first-viewport-locale-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-first-viewport-locale-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; output `/tmp/reachops-p4-first-viewport-locale-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p4-first-viewport-locale-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p4-first-viewport-locale-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - Final delivery remains blocked by missing Windows final artifacts, incomplete current client-delivery evidence, and external authorized live validation.

## Latest P4 locale DOM behavior proof

- Date: `2026-07-19`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Upgrade the first-viewport locale work from source wiring evidence to DOM behavior evidence without changing runtime architecture.
- Code evidence:
  - `tools/reachops_web_panel_dom_smoke.py` now simulates `/api/locales`, `localStorage`, `document.documentElement.lang`, and `[data-i18n]` nodes in the existing Node VM DOM harness.
  - The DOM smoke now triggers `localeSelect` to switch from `zh-CN` to `en-US` and back to `zh-CN`.
  - The new behavior check verifies that app title, promotion target label, start button, refresh button, and live-comment mode text change to English and then return to Chinese.
  - The smoke output includes `locale_debug` with initial, English, and Chinese snapshots for review.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile tools/reachops_web_panel_dom_smoke.py tools/reachops_web_panel_runtime_smoke.py tools/reachops_delivery_audit.py tools/reachops_web_ui.py tests/test_reachops_campaign.py`: passed.
  - `/usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed; `locale_selector_switches_first_viewport_text_in_dom=true`; output `/tmp/reachops-p4-locale-dom-behavior-smoke.json`.
  - `/usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed; output `/tmp/reachops-p4-locale-dom-behavior-runtime-smoke.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-p4-locale-dom-behavior-delivery-audit.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p4-locale-dom-behavior-truth.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-p4-locale-dom-behavior-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p4-locale-dom-behavior-goal-status.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with known baseline shape, 230 tests, 11 failures, 1 error; branch log `/tmp/reachops-p4-locale-dom-behavior-campaign.log`; `origin/main` baseline log `/tmp/reachops-main-locale-dom-behavior-campaign.log`; comparison artifact `/tmp/reachops-p4-locale-dom-behavior-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p4-locale-dom-behavior-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-locale-dom-behavior-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; output `/tmp/reachops-p4-locale-dom-behavior-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p4-locale-dom-behavior-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p4-locale-dom-behavior-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - Final delivery remains blocked by missing Windows final artifacts, incomplete current client-delivery evidence, and external authorized live validation.

## Latest P4 live activation readiness hardening

- Date: `2026-07-19`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten live readiness, live validation manifest, and live acceptance status so missing or placeholder activation evidence cannot be treated as ready during final/live acceptance.
- Code evidence:
  - `tools/reachops_activation_status_check.py` now supports `require_status_file=True`; callers using this mode receive `activation_status_file_exists=false` and `ready=false` when the local activation status file is absent, even if the development runtime would otherwise allow an activation bypass.
  - `tools/reachops_live_validation_manifest.py` and `tools/reachops_live_acceptance_status.py` now require a real activation status file for acceptance readiness.
  - `tools/reachops_live_readiness.py` now emits the strict `activation_status_file_exists` check and does not run authorization probes when the activation file is missing.
  - This preserves development compatibility for direct low-level activation checks while preventing live/final acceptance from counting missing activation as ready.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile tools/reachops_activation_status_check.py tools/reachops_live_validation_manifest.py tools/reachops_live_acceptance_status.py tools/reachops_live_readiness.py tests/test_reachops_campaign.py`: passed; log `/tmp/reachops-p4-activation-required-pycompile.log`.
  - Focused activation/readiness tests: passed, 6 tests covering missing activation, local input placeholders, template activation path handling, operator readiness report output, and live validation manifest blocking.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p4-activation-required-truth.log`.
  - `/usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed; output `/tmp/reachops-p4-activation-required-runtime-smoke.json`.
  - `/usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed; output `/tmp/reachops-p4-activation-required-dom-smoke.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-p4-activation-required-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, summary `customer_leads=27,submitted_unverified=0`; output `/tmp/reachops-p4-activation-required-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p4-activation-required-goal-status.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with improved known baseline shape, 230 tests, 6 failures, 0 errors; branch log `/tmp/reachops-p4-activation-required-campaign.log`.
  - `origin/main` campaign baseline at `887f706`: failed with 230 tests, 14 failures, 1 error; log `/tmp/reachops-main-activation-required-campaign.log`.
  - Baseline comparison artifact `/tmp/reachops-p4-activation-required-baseline-comparison.json`: `new_failures=[]`, `new_errors=[]`; resolved 8 failures and 1 error, including the activation/readiness failures.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p4-activation-required-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-activation-required-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-activation-required-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p4-activation-required-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p4-activation-required-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - Live/final acceptance now requires real local activation evidence; development bypass cannot satisfy the acceptance readiness checks.
  - Final delivery remains blocked by missing Windows final artifacts, incomplete current client-delivery evidence, and external authorized live validation.

## Latest P4 action-router live-submit authorization hardening

- Date: `2026-07-19`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Ensure the runtime action router itself cannot execute live submit with only a development activation bypass.
- Code evidence:
  - `ReachOps/workbench/action_router.py` now wraps live-submit authorization with an action-router strict check: when `dry_run=false`, `live_preflight_only=false`, and authorization is required, a missing local activation status file returns `LIVE_SUBMIT_NOT_AUTHORIZED`.
  - Missing activation is recorded as a skipped/blocked live action before template rendering, platform execution, evidence validation, quota increments, or lead/contact state advancement.
  - Dry-run and preflight paths remain unaffected; zero-limit dry-run comment routing still executes without quota writes.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/workbench/action_router.py tests/test_reachops_campaign.py`: passed; log `/tmp/reachops-p4-live-submit-auth-required-pycompile.log`.
  - Focused action-router live submit tests passed: missing activation blocks with `LIVE_SUBMIT_NOT_AUTHORIZED`; authorized-but-missing-evidence still fails with `LIVE_SUBMIT_EVIDENCE_MISSING`; expired activation and disabled capabilities remain blocked; zero-limit dry-run routing remains successful.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p4-live-submit-auth-required-truth.log`.
  - `/usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed; output `/tmp/reachops-p4-live-submit-auth-required-runtime-smoke.json`.
  - `/usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed; output `/tmp/reachops-p4-live-submit-auth-required-dom-smoke.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-p4-live-submit-auth-required-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, summary `customer_leads=27,submitted_unverified=0`; output `/tmp/reachops-p4-live-submit-auth-required-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p4-live-submit-auth-required-goal-status.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with improved known baseline shape, 230 tests, 5 failures, 0 errors; branch log `/tmp/reachops-p4-live-submit-auth-required-campaign.log`.
  - Baseline comparison artifact `/tmp/reachops-p4-live-submit-auth-required-baseline-comparison.json`: `new_failures=[]`, `new_errors=[]`; resolved 9 failures and 1 error compared with `origin/main` campaign baseline at `887f706`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p4-live-submit-auth-required-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-live-submit-auth-required-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-live-submit-auth-required-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p4-live-submit-auth-required-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p4-live-submit-auth-required-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - A live action without real activation now stops at authorization and is counted as skipped/blocked, not failed execution or live success.
  - Final delivery remains blocked by missing Windows final artifacts, incomplete current client-delivery evidence, and external authorized live validation.

## Latest P2 Windows Credential Manager secret-storage contract

- Date: `2026-07-19`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Establish the local secret-storage boundary required by the Windows client contract without entering Windows packaging, installer generation, or TikTok live-submit.
- Code evidence:
  - `ReachOps/security/credential_store.py` defines `reachops.credential_storage.v1`, `ReachOpsCredentialStore`, `credential_storage_status`, `redact_secret`, and `get_secret_if_available`.
  - Windows secret persistence requires `win32cred` and writes generic credentials through Windows Credential Manager using `CredWrite`, `CredRead`, and `CRED_TYPE_GENERIC`.
  - Non-Windows platforms return `backend=non_windows_unavailable`, `secret_persistence_allowed=false`, `status_includes_secret_values=false`, and refuse `set_secret`; this prevents macOS/Linux development paths from creating an alternate secret store.
  - `ReachOps/intelligence/ai_strategy.py` still accepts explicit env-provided API keys for process-local compatibility, but when no env key exists it reads `ai_api_key` through the credential contract instead of SQLite or JSON config.
  - `ReachOps/workbench/console.py` no longer assigns user-entered AI keys into `os.environ["REACHOPS_AI_API_KEY"]`; the legacy Tk settings path attempts to store keys through Windows Credential Manager and reports a non-Windows storage refusal without logging the key value.
  - `tools/reachops_delivery_audit.py` now includes the Windows Credential Manager secret-storage contract in its local architecture audit.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/security/__init__.py ReachOps/security/credential_store.py ReachOps/intelligence/ai_strategy.py ReachOps/workbench/console.py tools/reachops_delivery_audit.py tests/test_reachops_security.py tests/test_reachops_campaign.py`: passed.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_security`: passed, 7 tests; covers redaction, non-Windows persistence refusal, status payload not containing secrets, env-key compatibility without persistence, no-auth behavior when no secret is available, source contract, and legacy Tk no-env-write guard.
  - Focused AI provider compatibility tests passed: `test_campaign_plan_accepts_pluggable_ai_intelligence_provider`, `test_http_ai_provider_accepts_chat_style_json_response`, and `test_http_ai_provider_falls_back_to_rules_when_request_fails`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-p4-credential-store-delivery-audit.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p4-credential-store-truth.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-p4-credential-store-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p4-credential-store-goal-status.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with known improved branch shape, 230 tests, 1 failure, 0 errors; branch log `/tmp/reachops-p4-credential-store-campaign.log`.
  - `origin/main` campaign baseline: failed with 230 tests, 14 failures, 1 error; log `/tmp/reachops-main-credential-store-campaign.log`.
  - Baseline comparison artifact `/tmp/reachops-p4-credential-store-baseline-comparison.json`: `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p4-credential-store-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-credential-store-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-credential-store-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p4-credential-store-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p4-credential-store-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - No customer secret value, API key, cookie, screenshot, raw DOM, or customer SQLite database was committed.
  - Final delivery remains blocked by missing Windows final artifacts, incomplete current client-delivery evidence, and external authorized live validation.

## Latest P2 license-state and 7-day grace contract

- Date: `2026-07-19`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Add the minimal license-state model required by the Windows local client contract without creating a new licensing architecture or entering Windows packaging/live-submit.
- Code evidence:
  - `ReachOps/workbench/license_state.py` defines `reachops.license_state.v1`, `evaluate_license_state`, and `GRACE_PERIOD_DAYS=7`.
  - The evaluator classifies missing, template, inactive, revoked, expired, `active_current`, `grace`, and `grace_expired` states.
  - `grace` can keep `license_ready=true` for limited local availability, but deliberately keeps `live_submit_ready=false`; this prevents a stale or past-due local license cache from authorizing real TikTok comments.
  - `ReachOps/workbench/authorization_gate.py` now uses the shared license-state evaluator before live-submit capability checks; revoked licenses return `LIVE_SUBMIT_LICENSE_REVOKED`, expired licenses return `LIVE_SUBMIT_LICENSE_EXPIRED`, and grace states return `LIVE_SUBMIT_NOT_AUTHORIZED`.
  - `tools/reachops_activation_status_check.py` now reports `license_state` and adds `license_state_live_submit_ready` to its no-browser/no-submit activation checks.
  - `tools/reachops_delivery_audit.py` extends the authorization matrix to prove device mismatch, expiry, revocation, grace, and action-capability blocking.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/workbench/license_state.py ReachOps/workbench/authorization_gate.py ReachOps/workbench/__init__.py tools/reachops_activation_status_check.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused activation/license tests passed: `test_reachops_activation_status_check_reports_device_and_capabilities`, `test_reachops_license_state_grace_does_not_authorize_live_submit`, `test_reachops_activation_status_check_reports_grace_as_not_live_ready`, `test_reachops_activation_status_check_blocks_revoked_license`, `test_reachops_activation_status_check_blocks_device_mismatch`, and `test_reachops_activation_status_template_is_not_authorization`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_delivery_audit_reports_local_passes_and_external_pending`: passed.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p2-license-grace-truth.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-p2-license-grace-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-p2-license-grace-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p2-license-grace-goal-status.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with known improved branch shape, 230 tests, 1 failure, 0 errors; branch log `/tmp/reachops-p2-license-grace-campaign.log`.
  - `origin/main` campaign baseline: failed with 230 tests, 14 failures, 1 error; log `/tmp/reachops-main-p2-license-grace-campaign.log`.
  - Baseline comparison artifact `/tmp/reachops-p2-license-grace-baseline-comparison.json`: `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p2-license-grace-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p2-license-grace-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p2-license-grace-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p2-license-grace-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p2-license-grace-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - The 7-day grace state is explicitly not live-submit ready; only active/current activation can authorize real platform submission.
  - No customer business data, secret, cookie, screenshot, raw DOM, or customer SQLite database was committed.
  - Final delivery remains blocked by missing Windows final artifacts, incomplete current client-delivery evidence, and external authorized live validation.

## Latest P2 encrypted backup/restore contract

- Date: `2026-07-19`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Add the `.reachops-backup` lightweight backup/restore contract required by the Windows local-client customer-data boundary without entering the full evidence-file backup variant, Windows packaging, or live-submit.
- Code evidence:
  - `ReachOps/security/backup.py` defines `reachops.backup.v1`, `.reachops-backup`, password-derived encryption, HMAC authentication, versioned manifest, file hashes, restore preview, and atomic restore with rollback.
  - Lightweight backup includes the local SQLite runtime and non-secret config.
  - Backup excludes activation status, Windows Credential Manager secrets, AI/API/proxy/cookie/session/token paths, ixBrowser cookies/sessions/login state, and raw evidence screenshots.
  - Restore verifies password/authentication tag, manifest file hashes, and rejects unsafe absolute or `..` paths before writing.
  - Interrupted restore rolls back overwritten files and removes files newly created by the failed restore attempt.
  - All backup APIs report `customer_data_uploaded=false`, `no_browser_started=true`, and `no_submit=true`.
  - `tools/reachops_delivery_audit.py` now includes the encrypted backup/restore contract in the local architecture audit.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/security/backup.py ReachOps/security/__init__.py tools/reachops_delivery_audit.py tests/test_reachops_backup.py`: passed.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_backup`: passed, 6 tests covering secret/raw-evidence exclusion, preview, restore, wrong password, corrupted archive, interrupted rollback, invalid magic, and unsafe restore paths.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p2-backup-truth.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-p2-backup-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-p2-backup-delivery-audit-final.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p2-backup-goal-status.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with known improved branch shape, 230 tests, 1 failure, 0 errors; branch log `/tmp/reachops-p2-backup-campaign.log`.
  - `origin/main` campaign baseline: failed with 230 tests, 14 failures, 1 error; log `/tmp/reachops-main-p2-backup-campaign.log`.
  - Baseline comparison artifact `/tmp/reachops-p2-backup-baseline-comparison.json`: `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p2-backup-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p2-backup-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p2-backup-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p2-backup-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p2-backup-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - Backup tests used synthetic temp SQLite/config/evidence only; no customer data, secret, cookie, screenshot, raw DOM, or customer SQLite database was committed.
  - Final delivery remains blocked by missing Windows final artifacts, incomplete current client-delivery evidence, and external authorized live validation.

## Latest P2 full backup selected evidence contract

- Date: `2026-07-19`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Add the `.reachops-backup` full backup variant for explicitly selected evidence files without entering Windows packaging, EXE generation, installer generation, or TikTok live-submit.
- Code evidence:
  - `ReachOps/security/backup.py` keeps existing lightweight behavior compatible and adds `variant="full"` plus `include_evidence_files`.
  - Full backup includes lightweight SQLite/config content plus only explicitly selected files under the runtime `reports` directory.
  - Selected evidence files are stored under `data/growth_intelligence/reports/...`, so restore recreates them under the target runtime reports directory instead of an arbitrary filesystem path.
  - Full backup excludes selected evidence paths outside `reports_dir`, missing files, duplicate archive paths, and any selected evidence path containing secret/session/token/cookie/proxy/API-key/activation tokens.
  - Manifest now records supported variants, `selected_evidence_count`, `selected_evidence_file` categories, `unselected_evidence_files_excluded=true`, and full-backup selected-evidence exclusion reasons.
  - `tools/reachops_delivery_audit.py` now requires the full selected-evidence backup contract in the local architecture audit.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/security/backup.py tools/reachops_delivery_audit.py tests/test_reachops_backup.py`: passed.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_backup`: passed, 9 tests covering lightweight exclusion/restore plus full selected evidence inclusion, restore, outside-reports exclusion, and secret-path exclusion.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with known improved branch shape, 233 tests, 1 failure, 0 errors; branch log `/tmp/reachops-p2-full-backup-campaign.log`.
  - `origin/main` campaign baseline: failed with 230 tests, 14 failures, 1 error; log `/tmp/reachops-main-p2-full-backup-campaign.log`.
  - Baseline comparison artifact `/tmp/reachops-p2-full-backup-baseline-comparison.json`: `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p2-full-backup-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p2-full-backup-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p2-full-backup-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p2-full-backup-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p2-full-backup-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - Tests used synthetic temp SQLite/config/evidence only; no customer data, secret, cookie, screenshot, raw DOM, or customer SQLite database was committed.
  - Final delivery remains blocked by missing Windows final artifacts, incomplete current client-delivery evidence, and external authorized live validation.

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
