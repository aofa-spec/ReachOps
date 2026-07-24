# ReachOps Execution State

- Schema: `reachops.execution_state.v1`
- Contract: `REACHOPS_MASTER_EXECUTION_CONTRACT_V1.md`
- Last manually reconciled: `2026-07-24`
- Rule: verify every status against the repository before acting.

## Current project state

ReachOps is an independent Windows 10/11 local client project. Product direction is locked. The project is in engineering convergence, not final customer delivery.

## Milestone status

| Priority | Milestone | Status | Verified evidence | Exit condition |
|---|---|---|---|---|
| P0 | Truthful execution semantics | `IN_REVIEW` | Draft PR #10, branch `agent/reachops-truthful-execution-p0`; rebased on `origin/main`; evidence verification blocker fixed so live mode alone cannot set `evidence_verified`; unverified live submissions are tracked as `submitted_unverified` and do not increment generic success or `execution_success`; `tests.test_truthful_execution_semantics` 7/7 passed on 2026-07-17; exact campaign baseline comparison shows 230 tests on main and PR, both with 14 failures and 1 existing live-readiness error, `new_failures=0`, `new_errors=0` | Review and merge without new Evidence regressions; preserve no-live-action boundary; external Windows/TikTok acceptance remains separate |
| P1 | Immutable Campaign Run / Observation model | `IN_REVIEW` | P1 runtime ledger storage, runtime/lead-pipeline wiring, and scoped report/export surfacing exist on branch `codex/p4-web-runtime-smoke`: `campaign_runs`, `source_observations`, `content_observations`, `comment_observations`, `candidate_observations`, `evidence_artifacts`, and immutable/versioned `lead_decisions`; collection batches bind to campaign runs; collection task/content/comment/lead/action/execution rows can carry `run_id`; reports expose `runtime_scope` and `runtime_traceability`; JSON/CSV/Markdown exports include campaign/run traceability; legacy migration keeps old `run_id` empty instead of fabricating run attribution; P1 focused tests and full campaign regression passed on 2026-07-23 | Review P1 PR slice and merge without expanding LeadDecision lifecycle beyond traceability |
| P2 | Windows local security, licensing, backup, device seats | `IN_PROGRESS` | Windows Credential Manager secret-storage contract exists on branch `codex/p4-web-runtime-smoke`; secret redaction now fully masks values when `visible_tail=0`, closing a local reporting edge case; `tools/reachops_windows_credential_manager_check.py` now provides a Windows-only set/read/delete validation entry that reports non-Windows as `blocked_external_validation` without leaking secret values; Windows acceptance now runs that validation and final acceptance summary/package verification require the `windows_credential_manager_validation` report before any final passed package can be accepted; license-state evaluator models active/current, revoked, expired, and 7-day grace while keeping grace out of live-submit readiness; encrypted `.reachops-backup` lightweight and full selected-evidence backup/restore contracts now cover customer password, manifest, integrity hashes, preview, wrong password, corrupted archive, interrupted restore rollback, unsafe path rejection, secret/cookie exclusions, lightweight raw-evidence exclusion, and full backup selected evidence inclusion; minimal external license refresh client contract now refreshes only license/device/version metadata over HTTPS and writes local activation status atomically without browser start, submit, or customer-data upload; focused P2 tests passed on 2026-07-20 | Run `python tools\reachops_windows_credential_manager_check.py --json` on Windows 10/11 and require `status=passed`; complete Windows Credential Manager validation on Windows |
| P3 | Public comment-reply monitoring and lead lifecycle | `IN_PROGRESS` | Public reply replay parser, local `public_reply_events` storage, idempotent reply ingestion, qualified-lead lifecycle promotion, campaign report/export traceability, and local client UI/API surfacing now exist on branch `codex/p4-web-runtime-smoke`; local `conversion_events` storage now records manual conversion/won/lost/opt-out/revenue/currency capture with campaign/run/batch/lead/action/reply traceability and idempotency; a lead is promoted to `qualified` only when a public reply confirms need and is linked to an evidence-verified live contact, and conversion/revenue records advance the lifecycle without fabricating legacy run attribution; focused P3 tests and delivery audit passed on 2026-07-20 | Automatic platform reply detection |
| P4 | Bilingual UI, installer, update, Windows acceptance | `IN_REVIEW` | Branch `codex/p4-web-runtime-smoke` hardens the unified Web client entry, strict live-comment activation gate, account-gate start blocking, group-count DOM evidence, editable local ixBrowser group mapping, Python 3.9-compatible runtime smoke cleanup, customer-visible control evidence, campaign funnel isolation fixture truthfulness, Web-to-local-API execution-chain evidence, and goal delivery boundary reporting. Runtime smoke, DOM smoke, delivery audit, goal status, and campaign regression now pass locally; group-count resolution is configurable for large ixBrowser libraries; a fresh no-submit Web start produced PLAN/START/profile-preflight evidence and correctly blocked on `profile_available=0`; final Windows package and authorized live acceptance are still incomplete. | Win10/11 installer, zh-CN/en-US UI, update flow, acceptance matrix, authorized live evidence |
| P5 | DM inbox monitoring | `DEFERRED` | Explicitly deferred behind public reply monitoring | Separate privacy/evidence contract and acceptance after P3/P4 |

## Next autonomous action

1. Review the P1 immutable Campaign Run / Observation model slice now that storage, collection/content/comment pipeline wiring, and report/export traceability are implemented; keep unrelated LeadDecision lifecycle expansion split unless required for traceability.
2. Review Draft PR from branch `codex/p4-web-runtime-smoke`; keep Windows/installer/live-submit validation out of scope.
3. Continue P2 convergence only where non-external work remains; minimal external license refresh client contract is complete, and the remaining P2 exit gate is Windows Credential Manager validation on Windows.
4. Repair the current `United States` ixBrowser account pool: fix `IXBROWSER_KERNEL_MISMATCH`, complete TikTok login for `LOGIN_REQUIRED`, and keep at least one logged-in, kernel-compatible, page-openable profile in the execution group; then rerun the no-submit client acceptance loop.
5. Keep live-submit external validation separate; do not mark final delivery until package check and final acceptance gate both return `final_delivery_ready=true`.

## Known external blockers

- Authorized Windows + ixBrowser + logged-in TikTok environment is required for final platform validation.
- Real targets and activation inputs must remain local and git-ignored.
- Windows code-signing certificate is not currently available; internal builds may show an unknown-publisher warning.
- Natural user replies cannot be guaranteed; authorized test accounts may validate reply-linking mechanics, while natural reply rate remains a business observation.

## Product-owner minimum MVP freeze decision

- Date: `2026-07-24`
- Status: `ACTIVE`
- Decision: ReachOps is now in minimum MVP delivery freeze mode. Stop expanding P1/P2/P3/P4 product surface; keep existing stable code, but do not make post-MVP capabilities a `minimum_mvp_ready` blocker.
- Minimum MVP delivery focus:
  - Mac real ixBrowser no-submit acceptance against the real `United States` group, bounded profile scan, at least one `READY` profile, five consecutive real no-submit acquisition runs, 100% EvidenceBundle completeness, zero unauthorized submit, zero orphan processes, and explicit terminal state.
  - Windows minimum package acceptance: `ReachOps.exe`, installer, update manifest, hash verification, clean VM install, first launch, basic activation, default no-submit, uninstall, and `acceptance_summary.json`.
- Frozen / POST_MVP for minimum readiness: real comments, Follow, DM, public reply monitoring, qualified lead, conversion, revenue, CRM, Workspace, RBAC, multi-device seats, telemetry, encrypted backup, and formal multilingual acceptance.
- Important boundary: `minimum_mvp_ready=true` will represent only the minimum MVP; it must not be equated with `final_delivery_ready=true`, which remains false until full commercial and external platform acceptance is complete.

## Latest Windows VM client-gate convergence snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Use the available Windows 11 VM as a real engineering validation surface for the customer-client delivery path without claiming final Windows/TikTok acceptance. This slice fixes Windows-only test/build blockers that hid real package and Credential Manager state.
- Verified environment:
  - Mac ixBrowser app exists at `/Applications/ixBrowser.app`; local status endpoint returned `ready=true`, `base_url=http://127.0.0.1:53200/api/v2/`, `no_browser_started=true`, `no_submit=true`.
  - Windows 11 VM is reachable through `windows-vm`; Windows ixBrowser install directory exists at `C:\Program Files\ixBrowser`.
  - Windows Python is `C:\Python311-x64\python.exe`; Inno Setup is installed; ReachOps source is synced to `C:\Users\aofa\ReachOps_client`.
- Code evidence:
  - Windows sync/package preflight now include `tools/reachops_windows_credential_manager_check.py` and `tools/reachops_execution_acceptance_audit.py`, so Windows build input validation catches missing acceptance helpers before the build/test stage.
  - Python subprocess capture points used by launcher, goal delivery runner, MVP summary, delivery audit, Mac self-check, web UI process checks, and execution acceptance audit now use explicit `encoding="utf-8", errors="replace"` to avoid Windows GBK decode thread crashes when child tools emit UTF-8/Chinese output.
  - `tools/reachops_windows_credential_manager_check.py` now reports Windows CredWrite session failures as structured `blocked_external_validation` without tracebacks or secret leaks.
  - `tools/reachops_web_ui.py` now explicitly closes the SQLite connection used by `build_operations_payload`, fixing Windows temp database file-lock cleanup errors in public-reply/conversion payload tests.
  - `tools/reachops_goal_delivery_runner.py` now keeps `windows_final_artifacts` blocking when package status/final readiness is not passed, even if stale historical EXE/installer files exist; `deliverable_index.windows_final_package.failures` exposes the reason.
  - Tests were adjusted to avoid POSIX-only path assumptions and stale-artifact assumptions on Windows.
- Tests and checks:
  - Windows `py_compile` for changed Python files: passed.
  - Windows focused regression for subprocess encoding, package preflight, packaging sync, and Credential Manager session failure: passed, 4 tests.
  - Windows full campaign regression: passed, 259 tests; log `/tmp/reachops-win-campaign-after-all-fixes.log`. Earlier in this slice the same Windows run exposed `2 failures, 4 errors`; after fixes it is `0 failures, 0 errors`.
  - Local `py_compile` for changed Python files: passed.
  - Local `tests.test_truthful_execution_semantics`: passed, 7 tests.
  - Local `tests.test_reachops_security`: passed, 16 tests.
  - Local `tests.test_reachops_campaign`: passed, 259 tests; log `/tmp/reachops-local-campaign-after-windows-fixes.log`.
  - `tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-after-windows-fixes-operator-pressure.json`.
  - `tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-after-windows-fixes-delivery-audit.json`.
  - `tools/reachops_goal_status_report.py --json`: passed, `status=ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-after-windows-fixes-goal-status-report.json`.
  - `tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-after-windows-fixes-cleanliness.json`.
  - `git diff --check`: passed; output `/tmp/reachops-after-windows-fixes-diff-check.log`.
  - Baseline comparison: `origin/main` campaign regression ran 230 tests with 14 failures and 1 error; current branch ran 259 tests with 0 failures and 0 errors, so `new_failures=[]`, `new_errors=[]`; main log `/tmp/reachops-main-campaign-compare.log`.
- Windows VM evidence:
  - `tools\reachops_windows_package_preflight.py --json` on Windows returned `status=ready_for_windows_build` and confirmed `execution_acceptance_audit` plus `windows_credential_manager_check` exist; output `/tmp/reachops-win-package-preflight-after-utf8-sync.json`.
  - `tools\reachops_windows_credential_manager_check.py --json` on Windows returned `status=blocked_external_validation`, `backend=windows_credential_manager`, `windows_credential_manager_available=true`, but `CredWrite` failed with Windows error 1312: login session does not exist or has ended; output `/tmp/reachops-win-credential-manager-after-utf8-sync.json`.
  - `tools\reachops_final_acceptance_gate.py --json` on Windows remains `status=not_ready`, as expected, because final acceptance summary/package evidence and external authorized execution are not complete; output `/tmp/reachops-win-final-gate-after-utf8-sync.json`.
- Safety:
  - No TikTok live-submit was attempted.
  - No browser profile launch was performed by the Credential Manager/package checks; reported `no_browser_started=true`, `no_submit=true`.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - Existing untracked `ReachOps-1/` remains outside the work and was not modified.
- Remaining blockers:
  - Mac/client MVP remains blocked by current account readiness: latest goal runner reports `status=not_ready`, `client_delivery.status=blocked_by_accounts`, `profile_available=0`, and requires at least one READY logged-in/kernel-compatible profile before the five-run real no-submit client loop.
  - Windows Credential Manager validation requires an interactive Windows login/session where CredWrite succeeds; current VM SSH session returns error 1312 and is correctly classified as `blocked_external_validation`.
  - Final Windows delivery still requires current `ReachOps.exe`, installer, portable update manifest, root `reports/reachops_acceptance/acceptance_summary.json`, Windows acceptance reports, and final gate `final_delivery_ready=true`.
  - Authorized live-submit evidence remains separate and must not be attempted without explicit authorization.

## Latest P4 freeze safe-landing snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Complete the already-started final-artifact evidence-plan alignment and then stop feature expansion under the product-owner minimum MVP freeze decision.
- Code evidence:
  - `tools/reachops_final_acceptance_gate.py` now centralizes the Windows final required artifact list and includes package preflight, authorization handoff payload/zip, Windows Credential Manager validation, and final acceptance gate evidence in the final-delivery evidence plan/blocker output.
  - `tests/test_reachops_campaign.py` verifies those required evidence paths are surfaced in the final delivery evidence plan and blocker.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/reachops_final_acceptance_gate.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_final_acceptance_gate_requires_client_and_package_final_ready` and `test_reachops_final_acceptance_gate_passes_only_when_all_final_evidence_is_ready`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-freeze-safe-landing-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-freeze-safe-landing-campaign.log`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-freeze-safe-landing-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-freeze-safe-landing-diff-check.log`.
- Safety:
  - No Windows build, EXE, installer, update manifest, Windows VM access, ixBrowser profile launch, real TikTok page open, or TikTok live-submit was attempted in this safe-landing slice.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - `minimum_mvp_ready` is not implemented or claimed in this slice; next work must add/report that minimum-MVP-specific gate instead of continuing full-scope feature expansion.

## Latest P4 final-gate required report alignment snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Minimal-MVP final gate consistency hardening. The strict final acceptance gate now requires the same critical final package report evidence that package check already produces for Windows Credential Manager validation and authorization handoff.
- Code evidence:
  - `tools/reachops_final_acceptance_gate.py` now includes `authorization_handoff` and `windows_credential_manager_validation` in `REQUIRED_PACKAGE_REPORT_FILES`.
  - `tests/test_reachops_campaign.py` updates the final package fixture and verifies final gate rejection when `authorization_handoff`, `windows_credential_manager_validation`, or `live_submit` report evidence is missing and when `live_preflight` evidence is empty.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/reachops_final_acceptance_gate.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_final_acceptance_gate_passes_only_when_all_final_evidence_is_ready` and `test_reachops_final_acceptance_gate_rejects_package_missing_required_report_file`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-final-gate-required-reports-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-final-gate-required-reports-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-final-gate-required-reports-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch worktree ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-final-gate-required-reports-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-final-gate-required-reports-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-final-gate-required-reports-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-final-gate-required-reports-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`, failed check `acceptance:ready`; output `/tmp/reachops-final-gate-required-reports-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-final-gate-required-reports-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-final-gate-required-reports-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-final-gate-required-reports-final-gate.json`.
- Safety:
  - No Windows build, EXE, installer, update manifest, Windows VM access, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by current account readiness/local MVP, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 authorization-handoff bundle content verification snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Minimal-MVP final package evidence hardening. Final passed acceptance summaries now require the authorization handoff zip to pass the existing safe-bundle verifier, not merely exist as a non-empty file.
- Code evidence:
  - `tools/verify_reachops_acceptance_summary.py` now calls the existing `verify_handoff_bundle` check for `authorization_handoff.bundle_path` when validating a final passed summary.
  - Final passed summaries now fail with `authorization_handoff_bundle_verification_failed` when the bundle is missing required files, contains forbidden sensitive files, lacks safe commands, or does not declare no-browser/no-submit safety.
  - The verifier result now exposes bundle verification status, failures, forbidden files, and missing files under `authorization_handoff`.
  - `tests/test_reachops_campaign.py` now uses a minimal valid authorization handoff bundle fixture and covers the invalid-bundle case where sensitive local inputs are included.
  - `tools/reachops_delivery_audit.py` now audits that authorization-handoff bundle content verification exists.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures` and `test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-handoff-bundle-content-contract-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-handoff-bundle-content-contract-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-handoff-bundle-content-contract-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch worktree ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-handoff-bundle-content-contract-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-handoff-bundle-content-contract-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-handoff-bundle-content-contract-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-handoff-bundle-content-contract-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`, failed check `acceptance:ready`; output `/tmp/reachops-handoff-bundle-content-contract-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-handoff-bundle-content-contract-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-handoff-bundle-content-contract-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-handoff-bundle-content-contract-final-gate.json`.
- Safety:
  - No Windows build, EXE, installer, update manifest, Windows VM access, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by current account readiness/local MVP, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 authorization-handoff bundle verification snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten final Windows acceptance summary verification so `latest_reachops_authorization_handoff.zip` cannot merely be named in `acceptance_summary.authorization_handoff`; for a final passed summary, the bundle file must exist, be non-empty, and stay inside the acceptance summary directory.
- Code evidence:
  - `tools/verify_reachops_acceptance_summary.py` now resolves `authorization_handoff.bundle_path` relative to the acceptance summary, reports bundle existence/size/directory containment, and fails final passed summaries with `authorization_handoff_bundle_file_missing`, `authorization_handoff_bundle_file_empty`, or `authorization_handoff_bundle_outside_summary_dir`.
  - The verifier still enforces `authorization_handoff_payload.json` path existence, JSON validity, no-browser/no-submit safety, and payload-vs-summary mismatch checks.
  - `tools/reachops_delivery_audit.py` now audits that authorization-handoff bundle file and directory-containment enforcement exists.
  - `tests/test_reachops_campaign.py` covers valid bundle evidence, missing bundle file, empty bundle file, and outside-summary-directory bundle path.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures` and `test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-handoff-bundle-contract-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-handoff-bundle-contract-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-handoff-bundle-contract-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch worktree ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-handoff-bundle-contract-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-handoff-bundle-contract-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-handoff-bundle-contract-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-handoff-bundle-contract-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`, failed check `acceptance:ready`; output `/tmp/reachops-handoff-bundle-contract-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-handoff-bundle-contract-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-handoff-bundle-contract-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-handoff-bundle-contract-final-gate.json`.
- Safety:
  - No Windows build, EXE, installer, update manifest, Windows VM access, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by current account readiness/local MVP, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 live-validation payload verification snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten final Windows acceptance summary verification so `live_validation_manifest.json` cannot merely exist while contradicting `acceptance_summary.live_validation`, preserving the no-browser/no-submit live-input and selected-profile validation chain before any final passed package can be accepted.
- Code evidence:
  - `tools/verify_reachops_acceptance_summary.py` now reads `live_validation.json_path` for final passed summaries when `summary_path` is supplied.
  - Final passed summaries now fail with `live_validation_missing`, `live_validation_not_ready`, `live_validation_missing_inputs`, or `live_validation_profile_ids_missing` when live validation is absent, blocked, still has missing inputs, or lacks selected profile IDs.
  - Final passed summaries now fail with `live_validation_json_path_missing`, `live_validation_json_missing`, `live_validation_json_empty`, `live_validation_json_outside_summary_dir`, or `live_validation_json_invalid` when the referenced live validation manifest is absent, empty, outside the summary directory, or unreadable.
  - Final passed summaries now fail with `live_validation_json_mismatch:<field>` when payload values for `status`, `no_browser_started`, `no_submit`, `missing_inputs`, or `selected_profile_ids` disagree with `acceptance_summary.live_validation`.
  - The verifier result now exposes JSON path, existence, size, inside-summary-dir, loaded, and error detail for `live_validation`.
  - `tools/reachops_delivery_audit.py` now audits that live-validation payload invalid/mismatch enforcement exists.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures` and `test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-live-validation-payload-contract-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-live-validation-payload-contract-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-live-validation-payload-contract-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch worktree ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-live-validation-payload-contract-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-live-validation-payload-contract-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-live-validation-payload-contract-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-live-validation-payload-contract-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`, failed check `acceptance:ready`; output `/tmp/reachops-live-validation-payload-contract-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-live-validation-payload-contract-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, `acceptance_summary`, and final passed summary evidence; output `/tmp/reachops-live-validation-payload-contract-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-live-validation-payload-contract-final-gate.json`.
- Safety:
  - No Windows build, EXE, installer, update manifest, Windows VM access, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by current account readiness/local MVP, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 activation-status payload verification snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten final Windows acceptance summary verification so `activation_status_payload.json` cannot merely exist while contradicting `acceptance_summary.activation_status`, preserving the license/device activation-ready evidence chain before any final passed package can be accepted.
- Code evidence:
  - `tools/verify_reachops_acceptance_summary.py` now reads `activation_status.json_path` for final passed summaries when `summary_path` is supplied.
  - Final passed summaries now fail with `activation_status_missing`, `activation_status_not_ready`, `activation_status_ready_false`, `activation_status_file_missing`, `activation_status_started_browser`, `activation_status_submitted_action`, or `activation_status_device_id_missing` when activation readiness is absent, unsafe, or not device-attributed.
  - Final passed summaries now fail with `activation_status_json_path_missing`, `activation_status_json_missing`, `activation_status_json_empty`, `activation_status_json_outside_summary_dir`, or `activation_status_json_invalid` when the referenced activation status payload is absent, empty, outside the summary directory, or unreadable.
  - Final passed summaries now fail with `activation_status_json_mismatch:<field>` when payload values for `status`, `ready`, `no_browser_started`, `no_submit`, `activation_status_exists`, or `current_device_id` disagree with `acceptance_summary.activation_status`.
  - The verifier result now exposes JSON path, existence, size, inside-summary-dir, loaded, and error detail for `activation_status`.
  - `tools/reachops_delivery_audit.py` now audits that activation-status payload invalid/mismatch enforcement exists.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures` and `test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-activation-status-payload-contract-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-activation-status-payload-contract-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-activation-status-payload-contract-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch worktree ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-activation-status-payload-contract-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-activation-status-payload-contract-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-activation-status-payload-contract-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-activation-status-payload-contract-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`, failed check `acceptance:ready`; output `/tmp/reachops-activation-status-payload-contract-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-activation-status-payload-contract-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, `acceptance_summary`, and final passed summary evidence; output `/tmp/reachops-activation-status-payload-contract-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-activation-status-payload-contract-final-gate.json`.
- Safety:
  - No Windows build, EXE, installer, update manifest, Windows VM access, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by current account readiness/local MVP, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 goal-status payload verification snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten final Windows acceptance summary verification so `goal_status_report.json` cannot merely exist while contradicting `acceptance_summary.goal_status`, preventing a final passed package from hiding stale pending-external validation or mismatched goal-stage counts.
- Code evidence:
  - `tools/verify_reachops_acceptance_summary.py` now reads `goal_status.json_path` for final passed summaries when `summary_path` is supplied.
  - Final passed summaries now fail with `goal_status_json_path_missing`, `goal_status_json_missing`, `goal_status_json_empty`, `goal_status_json_outside_summary_dir`, or `goal_status_json_invalid` when the referenced goal status report is absent, empty, outside the summary directory, or unreadable.
  - Final passed summaries now fail with `goal_status_json_mismatch:<field>` when payload values for `status`, `pending_external_validation`, `summary.stages_passed`, `summary.stages_pending_external_validation`, or `summary.stages_failed` disagree with `acceptance_summary.goal_status`.
  - The verifier result now exposes JSON path, existence, size, inside-summary-dir, loaded, and error detail for `goal_status`.
  - `tools/reachops_delivery_audit.py` now audits that goal-status payload invalid/mismatch enforcement exists.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures` and `test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-goal-status-payload-contract-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-goal-status-payload-contract-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-goal-status-payload-contract-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch worktree ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-goal-status-payload-contract-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-goal-status-payload-contract-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-goal-status-payload-contract-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-goal-status-payload-contract-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`, failed check `acceptance:ready`; output `/tmp/reachops-goal-status-payload-contract-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-goal-status-payload-contract-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-goal-status-payload-contract-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-goal-status-payload-contract-final-gate.json`.
- Safety:
  - No Windows build, EXE, installer, update manifest, Windows VM access, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by current account readiness/local MVP, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 live preflight/submit payload verification snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten final Windows acceptance summary verification so `live_preflight_payload.json` and `live_submit_payload.json` cannot merely exist while contradicting `acceptance_summary.live_preflight` or `acceptance_summary.live_submit`, preserving the no-submit preflight and evidence-verified live-submit chain before any final passed package can be accepted.
- Code evidence:
  - `tools/verify_reachops_acceptance_summary.py` now reads `live_preflight.json_path` and `live_submit.json_path` for final passed summaries when `summary_path` is supplied.
  - Final passed summaries now fail with `live_preflight_json_path_missing`, `live_preflight_json_missing`, `live_preflight_json_empty`, `live_preflight_json_outside_summary_dir`, or `live_preflight_json_invalid` when the referenced live preflight payload is absent, empty, outside the summary directory, or unreadable.
  - Final passed summaries now fail with `live_preflight_json_mismatch:<field>` when payload values for `status`, `no_submit`, or `missing_preflight_action_types` disagree with `acceptance_summary.live_preflight`.
  - Final passed summaries now fail with `live_submit_json_path_missing`, `live_submit_json_missing`, `live_submit_json_empty`, `live_submit_json_outside_summary_dir`, or `live_submit_json_invalid` when the referenced live submit payload is absent, empty, outside the summary directory, or unreadable.
  - Final passed summaries now fail with `live_submit_json_mismatch:<field>` when payload values for `status`, `executor_mode`, `platform_validation`, `passed`, `live_submit`, `activation_status_loaded`, `summary.selected_actions`, `summary.success`, `summary.failed`, `summary.skipped`, `missing_evidence_action_types`, or `missing_local_evidence_file_action_types` disagree with `acceptance_summary.live_submit`.
  - The verifier result now exposes JSON path, existence, size, inside-summary-dir, loaded, and error detail for both `live_preflight` and `live_submit`.
  - `tools/reachops_delivery_audit.py` now audits that live preflight and live submit payload invalid/mismatch enforcement exists.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures` and `test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-live-preflight-submit-payload-contract-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-live-preflight-submit-payload-contract-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-live-preflight-submit-payload-contract-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch worktree ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-live-preflight-submit-payload-contract-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-live-preflight-submit-payload-contract-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-live-preflight-submit-payload-contract-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-live-preflight-submit-payload-contract-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`, failed check `acceptance:ready`; output `/tmp/reachops-live-preflight-submit-payload-contract-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; blocking scopes `local_mvp`, `windows_final_artifacts`, and `external_authorized_execution`; output `/tmp/reachops-live-preflight-submit-payload-contract-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-live-preflight-submit-payload-contract-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-live-preflight-submit-payload-contract-final-gate.json`.
- Safety:
  - No Windows build, EXE, installer, update manifest, Windows VM access, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by current account readiness/local MVP, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 audit/pressure payload verification snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten final Windows acceptance summary verification so `delivery_audit_payload.json` and `operator_pressure_payload.json` cannot merely exist while contradicting `acceptance_summary.delivery_audit` or `acceptance_summary.operator_pressure`, preserving the delivery-audit and operator-pressure evidence chain before any final passed package can be accepted.
- Code evidence:
  - `tools/verify_reachops_acceptance_summary.py` now reads `delivery_audit.json_path` and `operator_pressure.json_path` for final passed summaries when `summary_path` is supplied.
  - Final passed summaries now fail with `delivery_audit_json_path_missing`, `delivery_audit_json_missing`, `delivery_audit_json_empty`, `delivery_audit_json_outside_summary_dir`, or `delivery_audit_json_invalid` when the referenced delivery audit payload is absent, empty, outside the summary directory, or unreadable.
  - Final passed summaries now fail with `delivery_audit_json_mismatch:<field>` when payload values for `status`, `passed`, `pending_external_validation`, or `failed` disagree with `acceptance_summary.delivery_audit`.
  - Final passed summaries now fail with `operator_pressure_json_path_missing`, `operator_pressure_json_missing`, `operator_pressure_json_empty`, `operator_pressure_json_outside_summary_dir`, or `operator_pressure_json_invalid` when the referenced operator pressure payload is absent, empty, outside the summary directory, or unreadable.
  - Final passed summaries now fail with `operator_pressure_json_mismatch:<field>` when payload values for `status`, `campaign_count`, `content_found`, `comment_users`, `customer_leads`, `outreach_actions`, `execution_success`, or `account_switched` disagree with `acceptance_summary.operator_pressure`.
  - The verifier result now exposes JSON path, existence, size, inside-summary-dir, loaded, and error detail for both `delivery_audit` and `operator_pressure`.
  - `tools/reachops_delivery_audit.py` now audits that delivery audit and operator pressure payload invalid/mismatch enforcement exists.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures` and `test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-audit-pressure-payload-contract-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-audit-pressure-payload-contract-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-audit-pressure-payload-contract-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch worktree ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-audit-pressure-payload-contract-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-audit-pressure-payload-contract-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-audit-pressure-payload-contract-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-audit-pressure-payload-contract-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`, failed check `acceptance:ready`; output `/tmp/reachops-audit-pressure-payload-contract-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; blocking scopes `local_mvp`, `windows_final_artifacts`, and `external_authorized_execution`; output `/tmp/reachops-audit-pressure-payload-contract-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-audit-pressure-payload-contract-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-audit-pressure-payload-contract-final-gate.json`.
- Safety:
  - No Windows build, EXE, installer, update manifest, Windows VM access, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by current account readiness/local MVP, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 installer smoke payload verification snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten final Windows acceptance summary verification so `installer_smoke_payload.json` cannot merely exist while contradicting `acceptance_summary.installer_smoke`, preserving the ReachOps.exe/install-dir/hash smoke evidence chain before any final passed package can be accepted.
- Code evidence:
  - `tools/verify_reachops_acceptance_summary.py` now reads `installer_smoke.json_path` for final passed summaries when `summary_path` is supplied.
  - Final passed summaries now fail with `installer_smoke_json_path_missing`, `installer_smoke_json_missing`, `installer_smoke_json_empty`, `installer_smoke_json_outside_summary_dir`, or `installer_smoke_json_invalid` when the referenced installer smoke payload is absent, empty, outside the summary directory, or unreadable.
  - Final passed summaries now fail with `installer_smoke_json_mismatch:<field>` when payload values for `status`, `exe_exists`, `data_in_install_dir`, `hash_ok`, or `optional` disagree with `acceptance_summary.installer_smoke`.
  - The verifier result now exposes `installer_smoke.json_path`, `json_exists`, `json_size`, `json_inside_summary_dir`, `json_loaded`, and `json_error`.
  - `tools/reachops_delivery_audit.py` now audits that installer smoke payload invalid/mismatch enforcement exists.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures` and `test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-installer-smoke-payload-contract-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-installer-smoke-payload-contract-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-installer-smoke-payload-contract-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-installer-smoke-payload-contract-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-installer-smoke-payload-contract-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-installer-smoke-payload-contract-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-installer-smoke-payload-contract-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`, failed check `acceptance:ready`; output `/tmp/reachops-installer-smoke-payload-contract-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-installer-smoke-payload-contract-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-installer-smoke-payload-contract-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-installer-smoke-payload-contract-final-gate.json`.
- Mac ixBrowser observation:
  - `/Applications/ixBrowser.app` exists and ixBrowser is currently running on macOS, but this is not a complete effective validation.
  - `http://127.0.0.1:8769/api/ixbrowser-status` returned `status=blocked`, `ready=false`, with ixBrowser Local API error `code=1008 message=Server busy, please try again later.`
  - `http://127.0.0.1:8769/api/groups?refresh=1` returned 16 groups, including `United States` group id `257999` count `397`, but group counts were sourced from `cached_known_count_after_live_group_list`; this does not satisfy final live group/profile validation.
- Safety:
  - No Windows build, EXE, installer, update manifest, Windows VM access, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by current account readiness/local MVP, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 live readiness payload verification snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten final Windows acceptance summary verification so `live_readiness_payload.json` cannot merely exist while contradicting `acceptance_summary.live_readiness`, preserving the no-browser/no-submit authorization-readiness evidence chain before any final passed package can be accepted.
- Code evidence:
  - `tools/verify_reachops_acceptance_summary.py` now reads `live_readiness.json_path` for final passed summaries when `summary_path` is supplied.
  - Final passed summaries now fail with `live_readiness_json_missing`, `live_readiness_json_empty`, `live_readiness_json_outside_summary_dir`, or `live_readiness_json_invalid` when the referenced payload is absent, empty, outside the summary directory, or unreadable.
  - Final passed summaries now fail with `live_readiness_json_mismatch:<field>` when payload values for `status`, `ready`, `no_browser_started`, or `no_submit` disagree with `acceptance_summary.live_readiness`.
  - The verifier result now exposes `live_readiness.json_path`, `json_exists`, `json_size`, `json_inside_summary_dir`, `json_loaded`, and `json_error`.
  - `tools/reachops_delivery_audit.py` now audits that live readiness payload invalid/mismatch enforcement exists.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures` and `test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-live-readiness-payload-contract-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-live-readiness-payload-contract-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-live-readiness-payload-contract-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-live-readiness-payload-contract-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-live-readiness-payload-contract-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-live-readiness-payload-contract-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-live-readiness-payload-contract-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`, failed check `acceptance:ready`; output `/tmp/reachops-live-readiness-payload-contract-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-live-readiness-payload-contract-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-live-readiness-payload-contract-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-live-readiness-payload-contract-final-gate.json`.
- Safety:
  - No Windows build, EXE, installer, update manifest, Windows VM access, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by current account readiness/local MVP, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 repository cleanliness payload verification snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten final Windows acceptance summary verification so `repository_cleanliness_payload.json` cannot merely exist while contradicting `acceptance_summary.repository_cleanliness`, preserving the privacy/safety cleanliness gate before final package acceptance.
- Code evidence:
  - `tools/verify_reachops_acceptance_summary.py` now reads `repository_cleanliness.json_path` for final passed summaries when `summary_path` is supplied.
  - Final passed summaries now fail with `repository_cleanliness_json_invalid` when the repository cleanliness payload is unreadable or not a JSON object.
  - Final passed summaries now fail with `repository_cleanliness_json_mismatch:<field>` when payload values for `status`, `passed`, or `forbidden_count` disagree with `acceptance_summary.repository_cleanliness`.
  - The verifier result now exposes `repository_cleanliness.json_loaded` and `repository_cleanliness.json_error`.
  - `tools/reachops_delivery_audit.py` now audits that repository cleanliness payload invalid/mismatch enforcement exists.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures` and `test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-cleanliness-payload-contract-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-cleanliness-payload-contract-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-cleanliness-payload-contract-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-cleanliness-payload-contract-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-cleanliness-payload-contract-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-cleanliness-payload-contract-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-cleanliness-payload-contract-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`, failed check `acceptance:ready`; output `/tmp/reachops-cleanliness-payload-contract-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-cleanliness-payload-contract-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-cleanliness-payload-contract-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-cleanliness-payload-contract-final-gate.json`.
- Safety:
  - No Windows build, EXE, installer, update manifest, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by account readiness/local MVP, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 Windows package preflight payload verification snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten final Windows acceptance summary verification so `windows_package_preflight.json` cannot merely exist while contradicting `acceptance_summary.windows_package_preflight`, preserving the build-input evidence chain before Windows final package generation.
- Code evidence:
  - `tools/verify_reachops_acceptance_summary.py` now reads `windows_package_preflight.json_path` for final passed summaries when `summary_path` is supplied.
  - Final passed summaries now fail with `windows_package_preflight_json_invalid` when the Windows package preflight payload is unreadable or not a JSON object.
  - Final passed summaries now fail with `windows_package_preflight_json_mismatch:<field>` when payload values for `status`, `ready_for_windows_build`, or `final_delivery_ready` disagree with `acceptance_summary.windows_package_preflight`.
  - Final passed summaries now fail with `windows_package_preflight_json_mismatch:build_contract.<field>` when payload build-contract values for `default_build_requires_installer` or `skip_installer_is_non_final` disagree with the summary.
  - The verifier result now exposes `windows_package_preflight.json_loaded` and `windows_package_preflight.json_error`.
  - `tools/reachops_delivery_audit.py` now audits that Windows package preflight payload invalid/mismatch enforcement exists.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures` and `test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-windows-preflight-payload-contract-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-windows-preflight-payload-contract-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-windows-preflight-payload-contract-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-windows-preflight-payload-contract-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-windows-preflight-payload-contract-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-windows-preflight-payload-contract-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-windows-preflight-payload-contract-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`, failed check `acceptance:ready`; output `/tmp/reachops-windows-preflight-payload-contract-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-windows-preflight-payload-contract-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-windows-preflight-payload-contract-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-windows-preflight-payload-contract-final-gate.json`.
- Safety:
  - No Windows build, EXE, installer, update manifest, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by account readiness/local MVP, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 authorization handoff payload verification snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten final Windows acceptance summary verification so `authorization_handoff_payload.json` cannot merely exist while contradicting `acceptance_summary.authorization_handoff`, preserving the final authorized-handoff evidence chain for Windows acceptance.
- Code evidence:
  - `tools/verify_reachops_acceptance_summary.py` now reads `authorization_handoff.json_path` for final passed summaries when `summary_path` is supplied.
  - Final passed summaries now fail with `authorization_handoff_json_invalid` when the authorization handoff payload is unreadable or not a JSON object.
  - Final passed summaries now fail with `authorization_handoff_json_mismatch:<field>` when payload values for `status`, `exists`, `final_delivery_ready`, `no_browser_started`, `no_submit`, `bundle_path`, or `readiness_status` disagree with `acceptance_summary.authorization_handoff`.
  - The verifier result now exposes `authorization_handoff.json_loaded` and `authorization_handoff.json_error`.
  - `tools/reachops_delivery_audit.py` now audits that authorization handoff payload invalid/mismatch enforcement exists.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures` and `test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-auth-handoff-payload-contract-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-auth-handoff-payload-contract-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-auth-handoff-payload-contract-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-auth-handoff-payload-contract-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-auth-handoff-payload-contract-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-auth-handoff-payload-contract-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-auth-handoff-payload-contract-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`, failed check `acceptance:ready`; output `/tmp/reachops-auth-handoff-payload-contract-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-auth-handoff-payload-contract-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-auth-handoff-payload-contract-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-auth-handoff-payload-contract-final-gate.json`.
- Safety:
  - No Windows build, EXE, installer, update manifest, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by account readiness/local MVP, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 live acceptance status payload verification snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten final Windows acceptance summary verification so `live_acceptance_status_payload.json` cannot contradict `acceptance_summary.live_acceptance_status`, preventing a passed final summary from hiding unusable authorization inputs, activation blockers, selected-profile mismatches, failed checks, browser-start side effects, or submit side effects.
- Code evidence:
  - `tools/verify_reachops_acceptance_summary.py` now requires `live_acceptance_status.json_path` for final passed summaries and checks that the payload exists, is non-empty, and stays inside the acceptance summary directory.
  - Final passed summaries now fail with `live_acceptance_status_json_invalid` when the live acceptance status payload is unreadable or not a JSON object.
  - Final passed summaries now fail with `live_acceptance_status_json_mismatch:<field>` when payload values for `status`, `final_delivery_ready`, `ready_for_live_submit`, `no_browser_started`, `no_submit`, or `failed_checks` disagree with `acceptance_summary.live_acceptance_status`.
  - Final passed summaries now fail with nested mismatch codes when `local_inputs.usable`, `activation.ready`, `live_validation.missing_inputs`, or `live_validation.selected_profile_ids` disagree between the payload and the summary.
  - `tools/reachops_delivery_audit.py` now audits that live acceptance payload invalid/mismatch enforcement exists.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures` and `test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-live-acceptance-payload-contract-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-live-acceptance-payload-contract-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-live-acceptance-payload-contract-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-live-acceptance-payload-contract-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-live-acceptance-payload-contract-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-live-acceptance-payload-contract-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-live-acceptance-payload-contract-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`, failed check `acceptance:ready`; output `/tmp/reachops-live-acceptance-payload-contract-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`, blocking scopes `local_mvp`, `windows_final_artifacts`, and `external_authorized_execution`; output `/tmp/reachops-live-acceptance-payload-contract-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-live-acceptance-payload-contract-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-live-acceptance-payload-contract-final-gate.json`.
- Safety:
  - No Windows build, EXE, installer, update manifest, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by account readiness/local MVP, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 final acceptance gate payload verification snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten final Windows acceptance summary verification so `final_acceptance_gate.json` cannot contradict `acceptance_summary.final_acceptance_gate`, preventing a passed final summary from hiding failed final gate checks or a not-ready final delivery state.
- Code evidence:
  - `tools/verify_reachops_acceptance_summary.py` now reads the final `final_acceptance_gate.json_path` payload when `acceptance_summary.status=passed` and a summary path is supplied.
  - Final passed summaries now fail with `final_acceptance_gate_json_invalid` when the final gate payload is unreadable or not a JSON object.
  - Final passed summaries now fail with `final_acceptance_gate_json_mismatch:<field>` when payload values for `status`, `final_delivery_ready`, or `failed_checks` disagree with `acceptance_summary.final_acceptance_gate`.
  - Final passed summaries now fail with `final_acceptance_gate_json_checks_missing` or `final_acceptance_gate_json_checks_failed` when the payload omits or fails required final gate checks: `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, `delivery_audit:no_failed_checks`, and `operator_pressure:leads_and_actions`.
  - `tools/reachops_delivery_package_check.py` keeps the existing `allow_final_gate_convergence` bootstrap exception scoped to the self-referential package-check convergence case, while strict final package checks still require a passed final gate payload.
  - `tools/reachops_delivery_audit.py` now audits that final gate payload invalid/mismatch/check enforcement exists.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tools/reachops_delivery_package_check.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures` and `test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-final-gate-payload-contract-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-final-gate-payload-contract-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-final-gate-payload-contract-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-final-gate-payload-contract-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-final-gate-payload-contract-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-final-gate-payload-contract-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-final-gate-payload-contract-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`, failed check `acceptance:ready`; output `/tmp/reachops-final-gate-payload-contract-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, blocking scopes `local_mvp`, `windows_final_artifacts`, and `external_authorized_execution`; output `/tmp/reachops-final-gate-payload-contract-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-final-gate-payload-contract-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-final-gate-payload-contract-final-gate.json`.
- Safety:
  - No Windows build, EXE, installer, update manifest, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by account readiness/local MVP, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 client delivery payload verification snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten final Windows acceptance summary verification so `client_delivery.json` cannot contradict `acceptance_summary.client_delivery`, preventing a passed final summary from hiding account/client readiness blockers.
- Code evidence:
  - `tools/verify_reachops_acceptance_summary.py` now reads the final `client_delivery.json_path` payload when `acceptance_summary.status=passed` and a summary path is supplied.
  - Final passed summaries now fail with `client_delivery_json_invalid` when the client delivery payload is unreadable or not a JSON object.
  - Final passed summaries now fail with `client_delivery_json_mismatch:<field>` when payload values for `status`, `readiness`, `contract_ok`, `acceptance_ready`, or `final_delivery_ready` disagree with `acceptance_summary.client_delivery`.
  - Final passed summaries now fail with `client_delivery_json_mismatch:failed_checks` when payload failed checks disagree with the summary, preserving the `blocked_by_accounts` / `acceptance:ready` blocker instead of allowing it to be summarized away.
  - `tools/reachops_delivery_audit.py` now audits that client delivery payload invalid/mismatch enforcement exists.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures` and `test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-client-delivery-payload-contract-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-client-delivery-payload-contract-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-client-delivery-payload-contract-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-client-delivery-payload-contract-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-client-delivery-payload-contract-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-client-delivery-payload-contract-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-client-delivery-payload-contract-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`; output `/tmp/reachops-client-delivery-payload-contract-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-client-delivery-payload-contract-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-client-delivery-payload-contract-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`; output `/tmp/reachops-client-delivery-payload-contract-final-gate.json`.
- Safety:
  - No Windows build, EXE, installer, update manifest, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by current Mac/local account readiness, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P2/P4 Windows Credential Manager payload verification snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten final Windows acceptance summary verification so Windows Credential Manager validation cannot pass merely because a report file exists; the payload content must match the summarized secret-storage facts and safety flags.
- Code evidence:
  - `tools/verify_reachops_acceptance_summary.py` now reads the final `windows_credential_manager_validation.json_path` payload when `acceptance_summary.status=passed` and a summary path is supplied.
  - Final passed summaries now fail with `windows_credential_manager_validation_json_invalid` when the credential validation payload is unreadable or not a JSON object.
  - Final passed summaries now fail with `windows_credential_manager_validation_json_mismatch:<field>` when payload values for `status`, `passed`, `backend`, `no_browser_started`, `no_submit`, `customer_data_uploaded`, or `secret_value_included` disagree with `acceptance_summary.windows_credential_manager_validation`.
  - Final passed summaries now fail with `windows_credential_manager_validation_json_mismatch:checks.<name>` when payload check values disagree with the summary checks, including Windows Credential Manager availability, set/read/delete, and output redaction.
  - `tools/reachops_delivery_audit.py` now audits that invalid and mismatched Windows Credential Manager payload enforcement exists.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures` and `test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-credential-payload-contract-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-credential-payload-contract-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-credential-payload-contract-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-credential-payload-contract-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-credential-payload-contract-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-credential-payload-contract-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-credential-payload-contract-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`; output `/tmp/reachops-credential-payload-contract-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-credential-payload-contract-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-credential-payload-contract-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`; output `/tmp/reachops-credential-payload-contract-final-gate.json`.
- Safety:
  - No Windows build, EXE, installer, update manifest, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by current Mac/local account readiness, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 Windows UI startup payload verification snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten final Windows acceptance summary verification so UI startup evidence cannot pass merely because a payload file exists; the payload content must match the summarized local-client facts.
- Code evidence:
  - `tools/verify_reachops_acceptance_summary.py` now reads the final `ui_startup.json_path` payload when `acceptance_summary.status=passed` and a summary path is supplied.
  - Final passed summaries now fail with `ui_startup_json_invalid` when the UI startup payload is unreadable or not a JSON object.
  - Final passed summaries now fail with `ui_startup_json_mismatch:<field>` when payload values for `status`, `process_running`, `interactive_task`, `client_surface`, `loopback_host`, `no_browser_started`, or `no_submit` disagree with `acceptance_summary.ui_startup`.
  - `tools/reachops_delivery_audit.py` now audits that invalid and mismatched UI startup payload enforcement exists.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures`, `test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`, `test_reachops_final_acceptance_gate_passes_only_when_all_final_evidence_is_ready`, and `test_reachops_packaging_files_define_standalone_windows_artifacts`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-ui-startup-payload-contract-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-ui-startup-payload-contract-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-ui-startup-payload-contract-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-ui-startup-payload-contract-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-ui-startup-payload-contract-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-ui-startup-payload-contract-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-ui-startup-payload-contract-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`; output `/tmp/reachops-ui-startup-payload-contract-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-ui-startup-payload-contract-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-ui-startup-payload-contract-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`; output `/tmp/reachops-ui-startup-payload-contract-final-gate.json`.
- Safety:
  - No Windows build, EXE, installer, update manifest, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by current Mac/local account readiness, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 Windows UI startup acceptance contract snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Harden final Windows acceptance so `acceptance_summary.json` cannot pass with weak or ambiguous local UI startup evidence, without entering Windows build, EXE, installer, ixBrowser profile launch, or TikTok live-submit scope.
- Code evidence:
  - `tools/run_reachops_ui_startup_smoke_windows.ps1` now marks UI startup evidence as `no_browser_started=true` and `no_submit=true`.
  - `tools/run_reachops_acceptance_windows.ps1` now carries `client_surface`, `loopback_host`, `no_browser_started`, and `no_submit` from UI startup smoke into `acceptance_summary.ui_startup`, including the `-ReuseExistingUiStartup` path.
  - `tools/verify_reachops_acceptance_summary.py` now rejects passed summaries unless UI startup evidence proves `status=ok`, `process_running=true`, `interactive_task=true`, `client_surface=local_client_console`, local loopback host, `no_browser_started=true`, `no_submit=true`, and a final-status `json_path` inside the acceptance summary directory.
  - `tools/reachops_delivery_audit.py` now audits the startup smoke and acceptance summary verifier contract for local-console, loopback, no-browser, no-submit, and UI payload-file enforcement.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures`, `test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`, and `test_reachops_packaging_files_define_standalone_windows_artifacts`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-ui-startup-contract-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-ui-startup-contract-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-ui-startup-contract-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-ui-startup-contract-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-ui-startup-contract-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-ui-startup-contract-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-ui-startup-contract-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`; output `/tmp/reachops-ui-startup-contract-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-ui-startup-contract-goal-delivery-runner.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-ui-startup-contract-package-check.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`; output `/tmp/reachops-ui-startup-contract-final-gate.json`.
- Safety:
  - No Windows build, EXE, installer, update manifest, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by current Mac/local account readiness, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 bilingual language-gate UI snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten the operator language-gate UI so safety warnings for comment/group language conflicts are available in both `zh-CN` and `en-US`, without entering Windows, EXE, installer, ixBrowser profile launch, or TikTok live-submit scope.
- Code evidence:
  - Web operator outreach rows now include `language_gate_summary_i18n` and `next_step_i18n` alongside the existing Chinese-compatible `language_gate_summary` and `next_step` fields.
  - The outreach risk/failure column uses `localizedRowText(...)` to choose the current UI locale before falling back to the Chinese/default field.
  - Language conflict, uncertain language, and not-formally-acceptance-tested language next steps now have explicit English and Chinese text.
  - Delivery audit now checks both backend language-gate summaries and locale-aware UI rendering hooks.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/reachops_web_ui.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused test `test_operator_outreach_rows_surface_language_gate_warning`: passed and verifies both `zh-CN` and `en-US` language-gate warnings.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed; output `/tmp/reachops-language-i18n-dom-smoke.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed; output `/tmp/reachops-language-i18n-runtime-smoke.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, summary `execution_success=9`, `submitted_unverified=0`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-language-i18n-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-language-i18n-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-language-i18n-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-language-i18n-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, blocker scopes `local_mvp`, `windows_final_artifacts`, and `external_authorized_execution`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`.
- Safety:
  - No Windows build, EXE, installer, update manifest, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by account readiness/local MVP, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 operator language-gate UI snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Surface the runtime language gate to operators in the local Web client without entering Windows, EXE, installer, ixBrowser profile launch, or TikTok live-submit scope.
- Runtime/UI evidence:
  - Local Web client was started at `http://127.0.0.1:8769/`; `/api/version` returned `status=ok`, `display_version=客户端 v20`, `client_surface=local_client_console`, `loopback_host=127.0.0.1`, `no_browser_started=true`, and `no_submit=true`.
  - `build_operator_outreach_rows(...)` now emits `language_gate_summary` for non-ready language-gate states.
  - The outreach table risk/failure column now prioritizes `language_gate_summary` before generic risk-gate summary so queued/reviewed actions can show language warnings before execution.
  - `outreach_next_step(...)` now tells operators that group/comment language conflicts must be resolved before any real submit, and that uncertain or not-formally-tested languages require human confirmation.
  - Delivery audit now checks that the Web operator outreach rows explain language-gate warnings, not only backend risk-gate blocks.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/reachops_web_ui.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused tests `test_operator_outreach_rows_surface_language_gate_warning`, `test_action_queue_records_language_gate_and_localized_reply_copy`, and `test_action_queue_language_conflict_and_uncertain_language_require_operator_confirmation`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed; output `/tmp/reachops-language-ui-dom-smoke.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed; output `/tmp/reachops-language-ui-runtime-smoke.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, summary `execution_success=9`, `submitted_unverified=0`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 258 tests; log `/tmp/reachops-language-ui-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch ran 258 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-language-ui-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-language-ui-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-language-ui-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected, exit `1`, `status=blocked_by_accounts`, `profile_available=0`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, blocker scopes `local_mvp`, `windows_final_artifacts`, and `external_authorized_execution`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`.
- Safety:
  - No Windows build, EXE, installer, update manifest, ixBrowser profile launch, or TikTok live-submit was attempted.
  - The UI startup and smoke checks were loopback-only and reported `no_browser_started=true` / `no_submit=true`.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by account readiness/local MVP, Windows final artifacts, Windows Credential Manager validation on Windows, and authorized live evidence.

## Latest P4 language gate snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Close the master-contract country/group/language runtime gap without creating a new architecture and without entering Windows, EXE, installer, or TikTok live-submit scope.
- Code evidence:
  - `ActionQueueItem` and local SQLite `action_queue` now persist `comment_language`, `group_default_language`, `language_gate_status`, and `language_gate_note`.
  - Existing persisted action rows migrate conservatively: missing language-gate fields default to `requires_operator_confirmation`; no legacy action is treated as safe for automatic live submission merely because the column was absent.
  - `OperationLeadManager` records detected comment language and configured group default language on every proposed action, escalates non-ready language gates to high risk, and distinguishes `requires_operator_confirmation`, `language_conflict_with_group_default`, and `architecture_supported_requires_operator_confirmation`.
  - Rule-based comment reply suggestions now localize deterministic v1 copy for acceptance-tested languages `en`, `es`, `pt`, and `zh`; other languages remain architecture-supported only and require operator confirmation before live submit.
  - `RiskGate` blocks live submit when the language gate is not `ready`, including explicit reason codes for group-language conflict, untested language, and generic operator confirmation.
  - `ExecutionGuard` includes a lower-level `LANGUAGE_CONFIRMATION_REQUIRED` block so unsafe language-gate state cannot bypass the higher-level risk gate.
  - The standalone client reads the editable local ixBrowser group mapping and passes the group default reply language into collection/action generation.
  - Delivery audit now verifies language-gate storage, action-generation, risk-gate, execution-guard, and standalone wiring.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile ReachOps/intelligence/schemas.py ReachOps/intelligence/storage.py ReachOps/intelligence/outreach_copy.py ReachOps/intelligence/operation_lead_manager.py ReachOps/workbench/risk_gate.py ReachOps/workbench/execution_guard.py ReachOps/workbench/standalone_app.py tests/test_reachops_campaign.py tools/reachops_delivery_audit.py`: passed.
  - New focused language-gate tests: `test_action_queue_records_language_gate_and_localized_reply_copy` and `test_action_queue_language_conflict_and_uncertain_language_require_operator_confirmation`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, summary `execution_success=9`, `submitted_unverified=0`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 257 tests; log `/tmp/reachops-language-gate-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch ran 257 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-language-gate-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-language-gate-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-language-gate-diff-check.log`.
- Expected final-delivery blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; blocker scopes `local_mvp`, `windows_final_artifacts`, and `external_authorized_execution`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`.
- Safety:
  - No Windows build, EXE, installer, update manifest, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
  - Final delivery remains blocked by Windows final artifacts, Windows Credential Manager validation on Windows, current local MVP/ixBrowser readiness, and authorized live evidence.

## Latest P4 ixBrowser group mapping snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Close the non-external country/group/timezone/language gap from the master contract without entering Windows, EXE, installer, or TikTok live-submit scope.
- Code evidence:
  - Local SQLite now has `ixbrowser_group_mappings` with `group_id`, `group_name`, `target_country`, `timezone`, `default_reply_language`, allowed action types, per-day/per-hour limits, status, source, and schema version.
  - `ensure_ixbrowser_group_mappings(...)` creates first-use local placeholders from ixBrowser groups without deriving country, timezone, or language from the group name.
  - `upsert_ixbrowser_group_mapping(...)` preserves operator-edited local mapping, filters allowed action types to `comment_reply`, `follow_review`, and `dm_review`, clamps negative limits, and marks rows `ready` only after country, timezone, and language are configured.
  - `/api/groups` attaches local mapping status to each refreshed group; `/api/group-mappings` lists mappings; `/api/group-mapping` saves operator edits.
  - The Web client exposes the group mapping panel beside group selection and states that the group name is not country authority.
  - All group-mapping APIs report `no_browser_started=true` and `no_submit=true`; saving a mapping does not launch ixBrowser and does not submit platform actions.
- Browser evidence:
  - Temporary local UI `http://127.0.0.1:8770/` loaded with title `ReachOps 统一控制台`.
  - DOM contained `保存分组映射`; `#groupMappingPanel` was visible; exactly one `#saveGroupMapping` button was present.
  - Console `error/warn` logs were empty.
  - Manual interaction filled `目标国家=US` and `时区=America/New_York`; the save control was clickable and did not fabricate a group selection when no fresh selected group was available.
  - Local API round trip saved `qa-curl-group-1` as `ready`; unsupported action types were filtered; `/api/group-mappings` returned `configured_count=1`, `group_name_is_not_country_authority=true`, `no_browser_started=true`, and `no_submit=true`.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py tools/reachops_web_ui.py tools/reachops_delivery_audit.py tests/test_reachops_runtime_model.py tests/test_reachops_campaign.py`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 11 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, blockers `local_mvp`, `windows_final_artifacts`, and `external_authorized_execution`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, exit `1`, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`, failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 255 tests; log `/tmp/reachops-group-mapping-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch ran 255 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-group-mapping-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`.
  - `git diff --check`: passed.
- Safety:
  - No Windows build, EXE, installer, update manifest, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this commit and was not modified.
  - Final delivery remains blocked by Windows final artifacts, Windows Credential Manager validation on Windows, current account readiness, and authorized live evidence.

## Latest P1 Runtime observation ledger snapshot

- Date: `2026-07-23`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Review and tighten Draft PR #12 runtime data-model slice without merging the old branch or entering Windows, EXE, installer, or TikTok live-submit scope.
- PR #12 scope review:
  - CampaignRun coverage is present through `campaign_runs`, collection-batch binding, active run context, scoped report/export traceability, and run-scoped lead/action/execution rows.
  - Observation coverage now includes `source_observations`, `content_observations`, `comment_observations`, `candidate_observations`, `evidence_artifacts`, and `lead_decisions`.
  - Traceability coverage includes `runtime_traceability_summary(...)`, `list_observations_for_run(...)`, report/export `runtime_scope`, and explicit campaign/run IDs.
  - LeadDecision traceability has been pulled into the P1 Runtime data-model closeout only at the storage/versioned-observation boundary: decisions are immutable/versioned, tied to campaign/run/candidate observation, fingerprinted by normalized decision payload, and exposed through `list_lead_decisions(...)`.
  - Broader LeadDecision lifecycle/product behavior remains outside this P1 slice unless it is required for runtime traceability.
- Code evidence:
  - Local SQLite migrations add `source_observations`, `content_observations`, and `comment_observations` with campaign/run/batch scope and idempotency keys.
  - `create_collection_task(...)` records source observations when a real campaign run is bound to the batch.
  - `upsert_content(...)` records content observations for active campaign runs.
  - `upsert_candidate(...)` records comment observations for active campaign runs, preserving distinct same-user comments in the same content/run while making duplicate identical comments idempotent.
  - New observation methods require an existing campaign run; legacy rows with empty `run_id` are not backfilled and no fabricated `run_id` is assigned.
  - `lead_decisions` migration adds `decision_version`, `decision_schema_version`, `decision_source`, `rule_version`, `base_decision_key`, `decision_fingerprint`, and `decision_json` without rewriting legacy rows.
  - Exact duplicate LeadDecision payloads are idempotent by fingerprint; changed same-provider/same-key decisions append `#vN` versions instead of overwriting or colliding with the older unique key.
  - Migrated legacy LeadDecision rows with empty new fingerprint fields remain readable/idempotent when the same payload is observed again, and changed payloads append a new version without fabricating history.
  - Delivery audit P1 contract now requires the source/content/comment ledger tables and APIs.
  - The activation grace test fixture now uses a current in-grace timestamp instead of the stale `2026-07-15T00:00:00Z`, preserving the intended P2 grace/no-live-submit assertion after July 22, 2026.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py tools/reachops_delivery_audit.py tests/test_reachops_runtime_model.py tests/test_reachops_campaign.py`: passed.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 10 tests. Coverage includes campaign isolation, run isolation, source/content/comment/candidate observation traceability, evidence traceability, LeadDecision traceability/versioning, legacy LeadDecision append compatibility, migration compatibility, no-run legacy handling, and idempotency.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, exit `1`, `status=not_ready`, `final_delivery_ready=false`; blockers are `local_mvp`, `client_delivery_gate`, `windows_final_artifacts`, and `external_authorized_execution`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 254 tests.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch ran 254 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-p1-runtime-ledger-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`.
  - `git diff --check`: passed.
- Safety:
  - No Windows build, EXE, installer, update manifest, ixBrowser profile launch, or TikTok live-submit was attempted.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or acceptance input files were committed.
  - Final delivery remains blocked by Windows final artifacts, Windows Credential Manager validation on Windows, current account readiness, and authorized live evidence.

## Latest P3 manual conversion and revenue capture snapshot

- Date: `2026-07-20`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Complete the local business-lifecycle capture after public replies without entering Windows packaging, installer, EXE generation, or TikTok live-submit.
- Code evidence:
  - Local SQLite now has `conversion_events` with campaign/run/batch/lead/action/public-reply traceability, conversion state, amount/currency, operator source, notes, recorded time, created_by, and an explicit idempotency key.
  - Manual conversion records resolve scope only from existing lead/action/reply/batch rows or explicit caller fields; legacy leads with empty `run_id` and `batch_id` remain empty and do not inherit the active runtime context.
  - Lead lifecycle refresh now prioritizes terminal business states `won`, `lost`, and `opted_out`, and advances `converted` / `revenue_recorded` to `converted` without weakening the reply-qualified rule.
  - Campaign JSON exports, CSV exports, GrowthReporter summaries, Web operations payload, and the local Web API `/api/conversion-event` now surface conversion and revenue records with `no_submit=true`.
  - Delivery audit now requires conversion JSON/CSV traceability and revenue summary evidence alongside public reply evidence.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py ReachOps/intelligence/growth_reporter.py ReachOps/workbench/workflow_service.py tools/reachops_web_ui.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed.
  - Focused P3 conversion tests: 8 tests passed, covering conversion traceability, campaign/run isolation, idempotency, legacy migration compatibility, legacy no-run handling, Web payload surfacing, Web legacy compatibility, and campaign artifact export.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`; missing `exe`, `installer`, `manifest`, and `acceptance_summary`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`.
  - `git diff --check`: passed.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 254 tests; log `/tmp/reachops-p3-conversion-campaign.log`.
  - Main comparison: `origin/main` at `887f706` ran 230 tests with 14 failures and 1 error; current branch ran 254 tests with 0 failures and 0 errors; comparison artifact `/tmp/reachops-p3-conversion-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - Conversion/revenue capture is local SQLite-only and does not upload customer data.

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

## Latest P2 minimal license refresh client contract

- Date: `2026-07-20`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Add the minimal external license refresh client contract without entering Windows packaging, EXE generation, installer generation, Windows Credential Manager real-machine validation, ixBrowser execution, or TikTok live-submit.
- Code evidence:
  - `ReachOps/workbench/license_refresh_client.py` defines `reachops.license_refresh.v1`, a strict request allow-list, and forbidden customer-data tokens.
  - License refresh requests contain only `schema_version`, `license_id`, `device_id`, `app_version`, `platform`, and `requested_at`.
  - The default transport requires `https://`, posts JSON explicitly, and has no import-time network action.
  - A successful refresh normalizes the server response into local activation status with `reachops.license_state.v1`, evaluates the local license state, and writes the activation status atomically with `os.replace`.
  - Refresh results and written activation status carry `customer_data_uploaded=false`, `no_browser_started=true`, and `no_submit=true`.
  - `ReachOps/workbench/__init__.py` exports the refresh schema and refresh entry point.
  - `tools/reachops_delivery_audit.py` now requires the minimal license refresh client contract in the local architecture audit.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/workbench/license_refresh_client.py ReachOps/workbench/license_state.py ReachOps/workbench/__init__.py tests/test_reachops_security.py tools/reachops_delivery_audit.py`: passed; log `/tmp/reachops-p2-license-refresh-pycompile-final.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_security`: passed, 12 tests; log `/tmp/reachops-p2-license-refresh-security-final.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p2-license-refresh-truth-final.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-p2-license-refresh-operator-pressure-final.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-p2-license-refresh-delivery-audit-final.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p2-license-refresh-goal-status-final.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with known improved branch shape, 233 tests, 1 failure, 0 errors; branch log `/tmp/reachops-p2-license-refresh-campaign-final.log`.
  - `origin/main` campaign baseline: failed with 230 tests, 14 failures, 1 error; log `/tmp/reachops-main-p2-license-refresh-campaign-final.log`.
  - Baseline comparison artifact `/tmp/reachops-p2-license-refresh-baseline-comparison-final.json`: `new_failures=[]`, `new_errors=[]`; branch still has existing `test_reachops_goal_delivery_report_summarizes_pm_boundary` failure.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p2-license-refresh-package-check-final.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p2-license-refresh-final-gate-final.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p2-license-refresh-goal-delivery-runner-final.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p2-license-refresh-cleanliness-final.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p2-license-refresh-diff-check-final.log`.
- Safety:
  - No customer business data is sent to the license refresh endpoint by the client contract.
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - Final delivery remains blocked by missing Windows final artifacts, incomplete current client-delivery evidence, Windows Credential Manager validation on Windows, and external authorized live validation.

## Latest P4 goal delivery boundary report cleanup

- Date: `2026-07-20`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Remove the last current-branch campaign regression failure in the goal delivery PM boundary report without entering Windows packaging, EXE generation, installer generation, ixBrowser execution, or TikTok live-submit.
- Code evidence:
  - `tools/reachops_goal_delivery_runner.py` now separates current Mac loop execution evidence from PM contract-definition evidence.
  - When the local UI/loop is not running, the report keeps `local_mvp_ready=false` and `final_delivery_ready=false`, but still emits complete, auditable start-acquisition contract fields.
  - The report now emits `start_contract_current_evidence_complete=false` when current runtime evidence is incomplete, and `start_contract_evidence_complete=true` only for the PM contract structure.
  - Zero-action reports now include structured `no_action_reason.code=current_local_loop_not_ready`, so no action is inferred as submitted when the current local loop is not ready.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile tools/reachops_goal_delivery_runner.py tests/test_reachops_campaign.py`: passed; log `/tmp/reachops-goal-report-boundary-pycompile.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_goal_delivery_report_summarizes_pm_boundary`: passed; log `/tmp/reachops-goal-report-boundary-focused.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-goal-report-boundary-truth.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 233 tests; log `/tmp/reachops-goal-report-boundary-campaign.log`.
  - `origin/main` campaign baseline: failed with 230 tests, 14 failures, 1 error; log `/tmp/reachops-main-goal-report-boundary-campaign.log`.
  - Baseline comparison artifact `/tmp/reachops-goal-report-boundary-baseline-comparison.json`: `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-goal-report-boundary-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-goal-report-boundary-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-goal-report-boundary-goal-status.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-goal-report-boundary-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-goal-report-boundary-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-goal-report-boundary-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-goal-report-boundary-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-goal-report-boundary-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - The report explicitly keeps current local MVP and final delivery not ready when current runtime evidence is incomplete.
  - Final delivery remains blocked by missing Windows final artifacts, incomplete current client-delivery evidence, Windows Credential Manager validation on Windows, and external authorized live validation.

## Latest P1 runtime ledger storage slice

- Date: `2026-07-20`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Add the first P1 storage-level runtime ledger without replacing the existing GrowthStorage architecture or entering Windows packaging, EXE generation, installer generation, ixBrowser execution, or TikTok live-submit.
- Code evidence:
  - `ReachOps/intelligence/storage.py` now creates `campaign_runs`, `evidence_artifacts`, `candidate_observations`, and `lead_decisions`.
  - New storage APIs create idempotent campaign runs, record evidence artifacts, record candidate observations, record immutable/versioned lead decisions, and summarize runtime traceability by campaign/run.
  - New runtime writes require a real `campaign_id` and `run_id`; missing run attribution raises `ValueError` with the explicit rule that legacy rows must not be assigned a fabricated `run_id`.
  - Legacy-compatible `run_id` columns are added with empty defaults to existing runtime tables, so old rows remain unattributed instead of being backfilled into a fake run.
  - New lead/action/execution writes capture active `run_id`; existing lead and outreach execution queries can filter by `run_id` while preserving default compatibility.
  - `ReachOps/intelligence/schemas.py` accepts the empty `run_id` compatibility column on existing dataclasses.
  - `tools/reachops_delivery_audit.py` now checks the P1 runtime observation ledger contract.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py ReachOps/intelligence/schemas.py tests/test_reachops_runtime_model.py tools/reachops_delivery_audit.py`: passed; log `/tmp/reachops-p1-runtime-model-pycompile-final.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 6 tests; log `/tmp/reachops-p1-runtime-model-focused-final.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p1-runtime-model-truth-final.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 233 tests; log `/tmp/reachops-p1-runtime-model-campaign.log`.
  - `origin/main` campaign baseline: failed with 230 tests, 14 failures, 1 error; log `/tmp/reachops-main-p1-runtime-model-campaign.log`.
  - Baseline comparison artifact `/tmp/reachops-p1-runtime-model-baseline-comparison.json`: `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-p1-runtime-model-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-p1-runtime-model-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p1-runtime-model-goal-status.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p1-runtime-model-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p1-runtime-model-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p1-runtime-model-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p1-runtime-model-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p1-runtime-model-diff-check.log`.
- Safety:
  - No old data is assigned a fabricated `run_id`; legacy compatibility columns default to empty attribution.
  - Tests use synthetic temp SQLite data only; no customer data, screenshots, cookies, TikTok state, secrets, or customer runtime database was committed.
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - P1 remains incomplete until live collection/scoring/report paths write through the runtime ledger end to end.

## Latest P1 runtime ledger pipeline wiring

- Date: `2026-07-20`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Wire the existing collection/scoring/lead pipeline into the P1 runtime ledger without replacing GrowthStorage, changing the product architecture, entering Windows packaging, or attempting live TikTok submit.
- Code evidence:
  - `GrowthTaskConfig` now carries `active_run_id`.
  - `GrowthTaskRouter.run()` creates an idempotent `campaign_run` for campaign-scoped runs, binds the collection batch to that run, sets active batch/run context, records the run id in pipeline events, and completes the run ledger at terminal collection status.
  - `collection_batches` now has a compatibility `run_id` column and stores the bridge from legacy batch to immutable run.
  - New creator/content/candidate/topic-content rows created during an active run carry `run_id`; existing stable rows are not overwritten to avoid cross-run contamination.
  - `OperationLeadManager.build_from_scored_candidates()` records local evidence artifacts, candidate observations, and immutable/versioned lead decisions for each run-scoped candidate when campaign/run attribution is available.
  - Existing lead/action/execution writes continue to capture active `run_id`, and query APIs preserve default compatibility while allowing run filtering.
  - `tools/reachops_delivery_audit.py` now checks that the runtime router and lead pipeline are wired to the P1 ledger, not only that storage tables exist.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py ReachOps/intelligence/schemas.py ReachOps/intelligence/growth_task_router.py ReachOps/intelligence/operation_lead_manager.py tests/test_reachops_runtime_model.py tools/reachops_delivery_audit.py`: passed; log `/tmp/reachops-p1-runtime-ledger-wiring-pycompile-final.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 8 tests; log `/tmp/reachops-p1-runtime-ledger-wiring-focused-final.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p1-runtime-ledger-wiring-truth.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 233 tests; log `/tmp/reachops-p1-runtime-ledger-wiring-campaign.log`.
  - `origin/main` campaign baseline: failed with 230 tests, 14 failures, 1 error; log `/tmp/reachops-main-p1-runtime-ledger-wiring-campaign.log`.
  - Baseline comparison artifact `/tmp/reachops-p1-runtime-ledger-wiring-baseline-comparison.json`: `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-p1-runtime-ledger-wiring-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-p1-runtime-ledger-wiring-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p1-runtime-ledger-wiring-goal-status.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p1-runtime-ledger-wiring-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p1-runtime-ledger-wiring-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p1-runtime-ledger-wiring-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p1-runtime-ledger-wiring-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p1-runtime-ledger-wiring-diff-check.log`.
- Safety:
  - No old data is assigned a fabricated `run_id`; stable entities are not overwritten to force run attribution.
  - Tests use synthetic temp SQLite data only; no customer data, screenshots, cookies, TikTok state, secrets, or customer runtime database was committed.
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - P1 remains incomplete until runtime ledger traceability is surfaced in user-facing reports/exports and PR review is complete.

## Latest P1 runtime ledger report/export surfacing

- Date: `2026-07-20`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Surface P1 runtime ledger traceability in existing GrowthReporter reports and exports without creating new architecture, entering Windows packaging, EXE generation, installer generation, ixBrowser execution, or TikTok live-submit.
- Code evidence:
  - `ReachOps/intelligence/growth_reporter.py` now accepts optional `campaign_id`, `run_id`, and `batch_id` when building a report.
  - Reports include `runtime_traceability_schema_version=reachops.runtime_traceability_report.v1`, `runtime_scope`, and `runtime_traceability` from `GrowthStorage.runtime_traceability_summary(...)`.
  - Scoped reports filter candidates, contents, topic contents, operation actions, operation leads, and outreach executions by the current batch/run rather than exporting a global view.
  - JSON exports persist the runtime traceability summary; high-value-user CSV and action CSV exports now include `campaign_id`, `run_id`, and `batch_id`; Markdown daily briefs show the runtime scope and traceability counts.
  - `GrowthTaskRouter.run()` exports the current `campaign_id/run_id/batch_id` report at the end of the lead pipeline.
  - Storage list helpers preserve default compatibility while adding optional `run_id` filters for report use.
  - `tools/reachops_delivery_audit.py` now checks the report/export portion of the P1 runtime observation ledger contract.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py ReachOps/intelligence/growth_reporter.py ReachOps/intelligence/growth_task_router.py tests/test_reachops_runtime_model.py tools/reachops_delivery_audit.py`: passed.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_runtime_model`: passed, 9 tests.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 233 tests; log `/tmp/reachops-p1-report-surfacing-campaign.log`.
  - `origin/main` campaign baseline: failed with 230 tests, 14 failures, 1 error; log `/tmp/reachops-main-p1-report-surfacing-campaign.log`.
  - Baseline comparison artifact `/tmp/reachops-p1-report-surfacing-baseline-comparison.json`: `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p1-report-surfacing-goal-status.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`; missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p1-report-surfacing-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p1-report-surfacing-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; blockers include external authorized execution, client delivery gate not started, and Windows final artifacts; output `/tmp/reachops-p1-report-surfacing-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p1-report-surfacing-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p1-report-surfacing-diff-check.log`.
- Safety:
  - No old data is assigned a fabricated `run_id`; legacy rows remain unattributed through empty `run_id`.
  - Tests use synthetic temp SQLite data only; no customer data, screenshots, cookies, TikTok state, secrets, or customer runtime database was committed.
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - LeadDecision lifecycle expansion beyond immutable/versioned traceability remains split out of this P1 slice.
  - Final delivery remains blocked by missing Windows final artifacts, incomplete current client-delivery evidence, Windows Credential Manager validation on Windows, and external authorized live validation.

## Latest P4 client-delivery next-action correction

- Date: `2026-07-20`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Correct the current client-delivery handoff guidance for the `not_started` state without entering Windows packaging, EXE generation, installer generation, ixBrowser execution, or TikTok live-submit.
- Code evidence:
  - `tools/reachops_client_acceptance_status.py` now distinguishes `readiness=not_started` from `blocked_by_accounts` when building operator next actions.
  - When no current `PLAN campaign` evidence exists, `tools/reachops_client_delivery_check.py --json` now instructs the operator to launch the ReachOps local client, enter a promotion target, start acquisition, and wait for `PLAN campaign` / `START campaign` evidence.
  - Account-repair guidance remains limited to `blocked_by_accounts` runs where a current started batch has `available<=0`.
  - `tests/test_reachops_client_acceptance_status.py` adds a regression test proving that `not_started` does not ask the operator to repair the United States group before a run exists.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile tools/reachops_client_acceptance_status.py tests/test_reachops_client_acceptance_status.py`: passed.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_client_acceptance_status.ReachOpsClientAcceptanceStatusTest.test_not_started_next_actions_start_client_not_account_repair`: passed.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_client_acceptance_status.ReachOpsClientAcceptanceStatusTest.test_blocked_by_accounts_uses_real_profile_group tests.test_reachops_client_acceptance_status.ReachOpsClientAcceptanceStatusTest.test_not_started_next_actions_start_client_not_account_repair tests.test_reachops_client_acceptance_status.ReachOpsClientAcceptanceStatusTest.test_pass_requires_collection_and_action_in_scoped_batch tests.test_reachops_client_acceptance_status.ReachOpsClientAcceptanceStatusTest.test_restart_after_latest_batch_requires_new_run`: passed.
  - `/usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected with `status=not_started`, `readiness=not_started`, `failed_checks=["acceptance:ready"]`, blocker `未看到 PLAN campaign，推广目标未进入任务规划。`; output `/tmp/reachops-client-next-actions-after-fix.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_client_acceptance_status`: failed with 121 tests, 5 failures, 1 error; failing tests are Web UI contract/HTTP endpoint checks outside this next-action branch; log `/tmp/reachops-next-actions-client-acceptance.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-next-actions-truth.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-next-actions-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-next-actions-delivery-audit.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 233 tests; log `/tmp/reachops-next-actions-campaign.log`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-next-actions-goal-status.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-next-actions-package.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-next-actions-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; blocking scopes are `local_mvp`, `windows_final_artifacts`, and `external_authorized_execution`; output `/tmp/reachops-next-actions-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-next-actions-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-next-actions-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - No customer data, cookies, screenshots, raw DOM, credentials, local acceptance inputs, or SQLite customer runtime data was committed.
  - Final delivery remains blocked until fresh local client UI acceptance evidence, Windows final artifacts, Windows Credential Manager validation, and authorized live validation are produced and strict final gates pass.

## Latest P4 account-gate and evidence-bundle convergence

- Date: `2026-07-20`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Restore strict local-client start gates and runtime evidence-bundle smoke without entering Windows packaging, EXE generation, installer generation, ixBrowser execution, or TikTok live-submit.
- Code evidence:
  - `tools/reachops_web_ui.py` now rejects same-group `blocked_by_accounts` starts unless the operator explicitly confirms account repair/recheck, preserving the contract that repeated starts must not consume profiles before repair handling.
  - `tools/reachops_web_ui.py` now rejects stale cached ixBrowser group lists at `/api/start`; cached groups remain display-only and cannot be used as startup authority.
  - `/api/logs` falls back to recent log lines when a stale run-log offset would otherwise hide terminal evidence such as `HEADLESS_TIMEOUT`.
  - `ReachOps/run_session.py` no longer infers `REPAIRING` from the normal startup field `account_repair_confirmed=false`; repair inference now requires explicit repair/account-gate markers, keeping PRECHECK state transitions valid.
  - The native Tk compatibility console renders `page_subtitle_var` again and keeps the current six-tab operator navigation, including `信息沙漏`.
  - `tools/reachops_web_panel_runtime_smoke.py` now records evidence-bundle diagnostics for `/api/logs` and `/api/evidence-bundle` checks, making future bundle regressions auditable.
  - Tests isolate launch-path fixtures from real ixBrowser state by mocking the profile-group gate where the test intent is startup error handling, timeout normalization, or start serialization.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/run_session.py ReachOps/workbench/console.py tools/reachops_web_ui.py tools/reachops_web_panel_runtime_smoke.py tools/reachops_client_acceptance_status.py tests/test_run_recovery.py tests/test_reachops_client_acceptance_status.py`: passed.
  - `/usr/bin/python3 -m unittest -v tests.test_run_recovery`: passed, 8 tests; log `/tmp/reachops-gate-fix-run-recovery.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_client_acceptance_status`: passed, 121 tests; log `/tmp/reachops-client-acceptance-full-final.log`.
  - `/usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed, `failed_checks=[]`; output `/tmp/reachops-gate-fix-runtime-smoke-final.json`.
  - `/usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed; output `/tmp/reachops-account-gate-dom-smoke.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-account-gate-truth.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-account-gate-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-account-gate-delivery-audit.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 233 tests; log `/tmp/reachops-account-gate-campaign.log`.
  - `/usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected with `status=not_started`, `readiness=not_started`, `failed_checks=["acceptance:ready"]`; output `/tmp/reachops-account-gate-client-delivery.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-account-gate-goal-status.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-account-gate-package.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-account-gate-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; blocking scopes are `local_mvp`, `windows_final_artifacts`, and `external_authorized_execution`; output `/tmp/reachops-account-gate-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-account-gate-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-account-gate-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - No customer data, cookies, screenshots, raw DOM, credentials, local acceptance inputs, or SQLite customer runtime data was committed.
  - Final delivery remains blocked until a fresh local UI no-submit acceptance run exists, Windows artifacts are generated on Windows, Windows Credential Manager validation is completed, and authorized live evidence passes strict final gates.

## Latest P2 secret-redaction boundary hardening

- Date: `2026-07-20`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Harden the local secret-redaction boundary without creating new architecture, entering Windows packaging, EXE generation, installer generation, ixBrowser execution, or TikTok live-submit.
- Code evidence:
  - `ReachOps/security/credential_store.py` now treats `visible_tail=0` as a full-redaction request and returns only `*` characters with a minimum masked length.
  - This closes the Python `text[-0:]` edge case where a zero visible tail could append the full secret to the masked prefix.
  - `tests/test_reachops_security.py` adds a regression test proving the full secret and its tail are absent when zero visible characters are requested.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/security/credential_store.py tests/test_reachops_security.py`: passed.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_security`: passed, 13 tests.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 233 tests; log `/tmp/reachops-p2-redact-campaign.log`.
  - Branch/main comparison: branch campaign regression has no failures or errors; therefore `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected with `status=not_started`, `readiness=not_started`, `failed_checks=["acceptance:ready"]`; output `/tmp/reachops-p2-redact-client-delivery.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p2-redact-goal-status.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p2-redact-package.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p2-redact-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; blocking scopes are `local_mvp`, `windows_final_artifacts`, and `external_authorized_execution`; output `/tmp/reachops-p2-redact-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`.
  - `git diff --check`: passed; log `/tmp/reachops-p2-redact-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - No customer data, cookies, screenshots, raw DOM, credentials, local acceptance inputs, or SQLite customer runtime data was committed.
  - P2 remains `IN_PROGRESS` until Windows Credential Manager behavior is validated on Windows.
  - Final delivery remains blocked until a fresh local UI no-submit acceptance run exists, Windows artifacts are generated on Windows, Windows Credential Manager validation is completed, and authorized live evidence passes strict final gates.

## Latest P2 Windows Credential Manager validation entry

- Date: `2026-07-20`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Add an explicit Windows Credential Manager validation entry for the remaining P2 external gate without creating new architecture, entering Windows packaging, EXE generation, installer generation, ixBrowser execution, or TikTok live-submit.
- Code evidence:
  - `tools/reachops_windows_credential_manager_check.py` validates the existing `ReachOpsCredentialStore` through a set/read/delete round trip on Windows.
  - The tool returns `blocked_external_validation` on non-Windows instead of reporting success.
  - The validation output includes `no_browser_started=true`, `no_submit=true`, `customer_data_uploaded=false`, and `secret_value_included=false`.
  - The tool deletes its temporary credential in a `finally` block and does not print the generated secret value.
  - `tools/reachops_delivery_audit.py` now includes the validation entry in the Windows Credential Manager secret-storage contract check.
  - `tests/test_reachops_security.py` covers non-Windows blocking and a fake Windows set/read/delete round trip with secret-output exclusion.
- Local UI evidence:
  - `/usr/bin/python3 tools/reachops_mac_self_check.py --start-web --json`: started/verified the local client console at `http://127.0.0.1:8769/`; `/api/version` returned `client_surface=local_client_console`, `display_version=客户端 v20`, `loopback_host=127.0.0.1`, `no_browser_started=true`, and `no_submit=true`; output `/tmp/reachops-continue-self-check.json`.
  - `curl http://127.0.0.1:8769/api/ixbrowser-status`: returned `status=blocked`, `ready=false`, and `ixBrowser Local API 未启动或端口不可连接`; no ixBrowser profile was opened.
  - `/usr/bin/python3 tools/reachops_mac_loop_acceptance.py --base-url http://127.0.0.1:8769 --json`: failed as expected with `mac_loop_ready=false`, `ixbrowser_api_ready=false`, `groups_available=false`, and `client_delivery.status=not_started`; output `/tmp/reachops-continue-mac-loop.json`.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile tools/reachops_windows_credential_manager_check.py tools/reachops_delivery_audit.py tests/test_reachops_security.py`: passed.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_security`: passed, 15 tests.
  - `/usr/bin/python3 tools/reachops_windows_credential_manager_check.py --json`: failed as expected on macOS with `status=blocked_external_validation`, `backend=non_windows_unavailable`, `no_browser_started=true`, `no_submit=true`, `customer_data_uploaded=false`; output `/tmp/reachops-windows-credential-manager-check-local.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-credential-check-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-credential-check-delivery-audit.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 233 tests; log `/tmp/reachops-credential-check-campaign.log`.
  - Branch/main comparison: branch campaign regression has no failures or errors; therefore `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected with `status=not_started`, `readiness=not_started`, `failed_checks=["acceptance:ready"]`; output `/tmp/reachops-credential-check-client-delivery.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-credential-check-goal-status.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-credential-check-package.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-credential-check-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; blocking scopes are `local_mvp`, `windows_final_artifacts`, and `external_authorized_execution`; output `/tmp/reachops-credential-check-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-credential-check-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-credential-check-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - No customer data, cookies, screenshots, raw DOM, credentials, local acceptance inputs, or SQLite customer runtime data was committed.
  - P2 remains `IN_PROGRESS` until the new credential-manager check passes on Windows.
  - Final delivery remains blocked until ixBrowser Local API is available for fresh no-submit client acceptance, Windows artifacts are generated on Windows, Windows Credential Manager validation passes on Windows, and authorized live evidence passes strict final gates.

## Latest P2 final package Credential Manager evidence gate

- Date: `2026-07-20`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Make Windows Credential Manager validation a required final acceptance/package evidence section without creating new architecture, entering Windows packaging, EXE generation, installer generation, ixBrowser execution, or TikTok live-submit.
- Code evidence:
  - `tools/run_reachops_acceptance_windows.ps1` now runs `tools\reachops_windows_credential_manager_check.py --json`, writes `windows_credential_manager_validation.json`, prints `WINDOWS_CREDENTIAL_MANAGER_JSON`, and includes `windows_credential_manager_validation` in `acceptance_summary.json`.
  - `tools/verify_reachops_acceptance_summary.py` now rejects final passed summaries when the credential-manager validation is missing, not passed, not backed by `windows_credential_manager`, lacks set/read/delete proof, leaks a secret, starts a browser, submits an action, uploads customer data, or points at a missing/empty/out-of-summary report file.
  - `tools/reachops_delivery_package_check.py` now requires the `windows_credential_manager_validation` report section for final package validation.
  - `tests/test_reachops_campaign.py` covers the new acceptance-summary happy path, missing section, unsafe/failed validation, report-path compatibility, package report presence, package missing-report failure, and Windows acceptance script source contract.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_package_check.py tests/test_reachops_campaign.py`: passed.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed, 2 tests.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_packaging_files_define_standalone_windows_artifacts`: passed.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-credential-artifact-truth.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-credential-artifact-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-credential-artifact-delivery-audit.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 233 tests; log `/tmp/reachops-credential-artifact-campaign.log`.
  - Main comparison: `origin/main` at `887f706` also passed `tests.test_reachops_campaign`, 233 tests; log `/tmp/reachops-main-credential-campaign.log`; therefore `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_windows_credential_manager_check.py --json`: failed as expected on macOS with `status=blocked_external_validation`, `backend=non_windows_unavailable`, `no_browser_started=true`, `no_submit=true`, `customer_data_uploaded=false`, `secret_value_included=false`; output `/tmp/reachops-credential-artifact-credential-manager.json`.
  - `/usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected with `status=not_started`, `readiness=not_started`, `failed_checks=["acceptance:ready"]`; output `/tmp/reachops-credential-artifact-client-delivery.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-credential-artifact-goal-status.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-credential-artifact-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-credential-artifact-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; blocking scopes are `local_mvp`, `windows_final_artifacts`, and `external_authorized_execution`; output `/tmp/reachops-credential-artifact-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-credential-artifact-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-credential-artifact-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - No customer data, cookies, screenshots, raw DOM, credentials, local acceptance inputs, or SQLite customer runtime data was committed.
  - P2 remains `IN_PROGRESS` until `windows_credential_manager_validation.status=passed` is produced on Windows 10/11 and accepted by the strict final package gates.
  - Final delivery remains blocked until fresh local UI no-submit acceptance evidence exists, Windows artifacts are generated on Windows, Windows Credential Manager validation passes on Windows, and authorized live evidence passes strict final gates.

## Latest P4 local UI manual-test refresh and repair-summary cleanup

- Date: `2026-07-20`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Keep the local client available for manual testing and remove a misleading operator-facing account-repair summary error without entering Windows packaging, EXE generation, installer generation, ixBrowser profile execution, or TikTok live-submit.
- Verified current UI:
  - Local client console is reachable at `http://127.0.0.1:8769/`.
  - `/api/version` returned `status=ok`, `display_version=客户端 v20`, `client_surface=local_client_console`, `pid=10613`, `loopback_host=127.0.0.1`, `no_browser_started=true`, and `no_submit=true`.
  - `/api/acceptance` now reports `account_repair_summary.status=not_available` with `reason=account_repair_plan_not_generated` when no account-repair plan exists, instead of exposing `[Errno 21] Is a directory: '.'`.
  - `/api/ixbrowser-status` reports `status=blocked`, `ready=false`, `base_url=http://127.0.0.1:53200/api/v2/`, and connection refused; fresh local MVP/client acceptance cannot pass until ixBrowser Local API is started and a no-submit PLAN/START run is completed.
- Code evidence:
  - `tools/reachops_web_ui.py` now treats empty, missing, and directory account-repair plan paths as structured `not_available` states before attempting JSON parsing.
  - `tests/test_reachops_campaign.py` covers directory-path handling so operator UI state does not regress to a filesystem exception.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile tools/reachops_web_ui.py tests/test_reachops_campaign.py`: passed; log `/tmp/reachops-p4-account-repair-summary-pycompile.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_web_account_repair_summary_treats_directory_path_as_not_available tests.test_reachops_campaign.ReachOpsCampaignTests.test_web_group_refresh_normalizes_ixbrowser_local_api_connection_error`: passed, 2 tests; log `/tmp/reachops-p4-account-repair-summary-focused.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p4-account-repair-summary-truth.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-p4-account-repair-summary-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-p4-account-repair-summary-delivery-audit.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 234 tests; log `/tmp/reachops-p4-account-repair-summary-campaign.log`.
  - Main comparison: `origin/main` at `887f706` failed `tests.test_reachops_campaign`, 230 tests, 14 failures and 1 error; log `/tmp/reachops-main-account-repair-summary-campaign.log`. Comparison artifact `/tmp/reachops-p4-account-repair-summary-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected with `status=not_started`, `readiness=not_started`, `failed_checks=["acceptance:ready"]`, blocker `未看到 PLAN campaign，推广目标未进入任务规划。`; output `/tmp/reachops-p4-account-repair-summary-client-delivery.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p4-account-repair-summary-goal-status.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p4-account-repair-summary-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-account-repair-summary-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`; blocking scopes are `external_authorized_execution`, `client_delivery_gate`, and `windows_final_artifacts`; output `/tmp/reachops-p4-account-repair-summary-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-p4-account-repair-summary-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p4-account-repair-summary-diff-check.log`.
- Safety:
  - No real TikTok action was executed.
  - No ixBrowser profile was opened by this slice because Local API is not reachable.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - Final delivery remains blocked until ixBrowser Local API is available for fresh no-submit client acceptance, Windows artifacts are generated on Windows, Windows Credential Manager validation passes on Windows, and authorized live evidence passes strict final gates.

## Latest P2 backup symlink boundary hardening

- Date: `2026-07-20`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Harden `.reachops-backup` local customer-data boundary so backup discovery does not follow symlinked runtime files to content outside the independent local runtime, without entering Windows packaging, EXE generation, installer generation, ixBrowser execution, or TikTok live-submit.
- Code evidence:
  - `ReachOps/security/backup.py` now excludes symlinked SQLite runtime and non-secret config files with manifest reason `symlink_file_excluded`.
  - This prevents a config path such as `config/display_settings.json` from exporting the target content of a symlink that points outside the ReachOps runtime.
  - `tools/reachops_delivery_audit.py` now requires `symlink_file_excluded` and `.is_symlink()` in the encrypted backup/restore contract check.
  - `tests/test_reachops_backup.py` proves that symlinked config and SQLite paths are not exported and that outside target content is absent from backup preview output.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/security/backup.py tools/reachops_delivery_audit.py tests/test_reachops_backup.py tests/test_reachops_campaign.py`: passed; log `/tmp/reachops-p2-backup-symlink-pycompile.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_backup`: passed, 10 tests; log `/tmp/reachops-p2-backup-symlink-backup-tests.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p2-backup-symlink-truth.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-p2-backup-symlink-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-p2-backup-symlink-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p2-backup-symlink-goal-status.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 234 tests; log `/tmp/reachops-p2-backup-symlink-campaign.log`.
  - Main comparison: `origin/main` at `887f706` failed `tests.test_reachops_campaign`, 230 tests, 14 failures and 1 error; log `/tmp/reachops-main-backup-symlink-campaign.log`. Comparison artifact `/tmp/reachops-p2-backup-symlink-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected with `status=not_started`, `readiness=not_started`, `failed_checks=["acceptance:ready"]`, blocker `未看到 PLAN campaign，推广目标未进入任务规划。`; output `/tmp/reachops-p2-backup-symlink-client-delivery.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p2-backup-symlink-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p2-backup-symlink-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`; blocking scopes are `external_authorized_execution`, `client_delivery_gate`, and `windows_final_artifacts`; output `/tmp/reachops-p2-backup-symlink-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-p2-backup-symlink-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p2-backup-symlink-diff-check.log`.
- Safety:
  - Tests used synthetic temp SQLite/config/symlink data only.
  - No customer data, cookies, screenshots, raw DOM, credentials, local acceptance inputs, or SQLite customer runtime data was committed.
  - No real TikTok action was executed.
  - No ixBrowser profile was opened by this slice.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - Final delivery remains blocked until ixBrowser Local API is available for fresh no-submit client acceptance, Windows artifacts are generated on Windows, Windows Credential Manager validation passes on Windows, and authorized live evidence passes strict final gates.

## Latest P4 follow/DM evidence hardening

- Date: `2026-07-20`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Tighten live-submit evidence truthfulness for follow and DM actions without entering Windows packaging, EXE generation, installer generation, ixBrowser execution, or TikTok live-submit.
- Code evidence:
  - `ReachOps/workbench/tiktok_action_executor.py` now writes `follow_state_confirmed`, `dm_entry_confirmed`, and `dm_submitted_text` into local screenshot sidecars. These fields are true/non-empty only for non-preflight, no-error action evidence.
  - `ReachOps/workbench/action_router.py` rejects successful live follow evidence unless `follow_state_confirmed=true`.
  - `ReachOps/workbench/action_router.py` rejects successful live DM evidence unless `dm_entry_confirmed=true`, and rejects mismatched `dm_submitted_text` when expected DM text is available.
  - `tools/reachops_live_submit_acceptance.py` and `tools/verify_reachops_acceptance_summary.py` now apply the same action-specific sidecar checks for final acceptance evidence details.
  - `tools/reachops_delivery_audit.py` fixture evidence now includes the stricter follow/DM confirmation metadata so the local audit keeps proving the same evidence contract it requires.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/workbench/tiktok_action_executor.py ReachOps/workbench/action_router.py tools/reachops_live_submit_acceptance.py tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed; log `/tmp/reachops-p4-follow-dm-evidence-pycompile.log`.
  - Focused follow/DM evidence tests passed, 6 tests; log `/tmp/reachops-p4-follow-dm-evidence-focused.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p4-follow-dm-evidence-truth.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-p4-follow-dm-evidence-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=51,pending_external_validation=3,failed=0`; output `/tmp/reachops-p4-follow-dm-evidence-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p4-follow-dm-evidence-goal-status.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 238 tests; log `/tmp/reachops-p4-follow-dm-evidence-campaign.log`.
  - Main comparison: `origin/main` at `887f706` failed `tests.test_reachops_campaign`, 230 tests, 14 failures and 1 error; log `/tmp/reachops-main-follow-dm-campaign.log`. Comparison artifact `/tmp/reachops-p4-follow-dm-evidence-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected with `status=not_started`, `readiness=not_started`, `failed_checks=["acceptance:ready"]`, blocker `未看到 PLAN campaign，推广目标未进入任务规划。`; output `/tmp/reachops-p4-follow-dm-evidence-client-delivery.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p4-follow-dm-evidence-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p4-follow-dm-evidence-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`; blocking scopes are `external_authorized_execution`, `client_delivery_gate`, and `windows_final_artifacts`; output `/tmp/reachops-p4-follow-dm-evidence-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-p4-follow-dm-evidence-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p4-follow-dm-evidence-diff-check.log`.
- Safety:
  - Tests used synthetic temp PNG sidecars only.
  - No customer data, cookies, screenshots, raw DOM, credentials, local acceptance inputs, or SQLite customer runtime data was committed.
  - No real TikTok action was executed.
  - No ixBrowser profile was opened by this slice.
  - No Windows build, EXE, installer, update manifest, or live-submit was attempted on macOS.
  - Final delivery remains blocked until ixBrowser Local API is available for fresh no-submit client acceptance, Windows artifacts are generated on Windows, Windows Credential Manager validation passes on Windows, and authorized live evidence passes strict final gates.

## Latest P3 public reply lifecycle foundation

- Date: `2026-07-20`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Add redacted/replay public-reply monitoring foundation and lead lifecycle qualification rules without entering Windows packaging, EXE generation, installer generation, ixBrowser execution, or TikTok live-submit.
- Code evidence:
  - `ReachOps/intelligence/public_reply_monitor.py` now parses caller-provided public reply replay rows with deterministic multilingual purchase/need signals and explicit negative-interest guards.
  - `ReachOps/intelligence/storage.py` now creates and migrates local `public_reply_events`, preserving campaign/run/batch/action/execution linkage without fabricating run or batch IDs for legacy rows.
  - Public replies are idempotent by `(lead_id, action_id, reply_text, replied_at)`.
  - Lead lifecycle now distinguishes `reply_received` from `qualified`: a lead becomes `qualified` only when the reply content confirms need and the reply is linked to an evidence-verified live contact (`submission_state=verified_success`, `verification_state=verified`, `evidence_verified=1`); an unverified live submission can record intent but cannot increment the stored qualified count.
  - `tools/reachops_delivery_audit.py` now includes a redacted public-reply fixture proving qualified lifecycle promotion and replay idempotency.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py ReachOps/intelligence/public_reply_monitor.py ReachOps/intelligence/__init__.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed; log `/tmp/reachops-p3-public-reply-pycompile.log`.
  - Focused P3 public-reply tests passed, 6 tests; log `/tmp/reachops-p3-public-reply-focused.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p3-public-reply-truth.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-p3-public-reply-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=52,pending_external_validation=3,failed=0`; output `/tmp/reachops-p3-public-reply-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p3-public-reply-goal-status.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 244 tests; log `/tmp/reachops-p3-public-reply-campaign.log`.
  - Main comparison: `origin/main` at `887f706` failed `tests.test_reachops_campaign`, 230 tests, 14 failures and 1 error; log `/tmp/reachops-main-p3-public-reply-campaign.log`. Comparison artifact `/tmp/reachops-p3-public-reply-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected with `status=not_started`, `readiness=not_started`, `failed_checks=["acceptance:ready"]`; output `/tmp/reachops-p3-public-reply-client-delivery.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p3-public-reply-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p3-public-reply-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p3-public-reply-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-p3-public-reply-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p3-public-reply-diff-check.log`.
- Safety:
  - Tests used synthetic redacted public reply rows only.
  - No real TikTok action was executed.
  - No ixBrowser profile was opened by this slice.
  - No customer data, cookies, screenshots, raw DOM, credentials, local acceptance inputs, or SQLite customer runtime data was committed.
  - P3 remains incomplete until public reply detection is connected to real authorized platform replay/monitoring evidence, surfaced in UI/reports, and manual conversion/revenue capture is implemented.
  - Final delivery remains blocked until ixBrowser Local API is available for fresh no-submit client acceptance, Windows artifacts are generated on Windows, Windows Credential Manager validation passes on Windows, and authorized live evidence passes strict final gates.

## Latest P3 public reply report traceability export

- Date: `2026-07-20`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Surface public reply lifecycle evidence in existing local campaign reports and exports without entering Windows packaging, EXE generation, installer generation, ixBrowser execution, or TikTok live-submit.
- Code evidence:
  - `ReachOps/workbench/workflow_service.py` now exports `public_reply_events` and `public_reply_summary` in campaign JSON artifacts.
  - Campaign export now writes `reachops_public_replies_*.csv` and returns `public_replies_csv_path`.
  - Public reply JSON/CSV export includes campaign, run, batch, lead, action, execution, intent, qualification, verified-contact, evidence, and classifier traceability fields.
  - `ReachOps/intelligence/growth_reporter.py` now includes `public_reply_count` and `qualified_reply_count` in report summaries and Markdown briefs.
  - `tools/reachops_delivery_audit.py` now verifies exported public reply JSON/CSV traceability and qualified reply summary counts using synthetic redacted fixture data.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py ReachOps/intelligence/growth_reporter.py ReachOps/workbench/workflow_service.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed; log `/tmp/reachops-p3-public-reply-export-pycompile.log`.
  - Focused public-reply export tests passed, 2 tests; log `/tmp/reachops-p3-public-reply-export-focused.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p3-public-reply-export-truth.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-p3-public-reply-export-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=52,pending_external_validation=3,failed=0`; output `/tmp/reachops-p3-public-reply-export-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p3-public-reply-export-goal-status.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 244 tests; log `/tmp/reachops-p3-public-reply-export-campaign.log`.
  - Main comparison: `origin/main` at `887f706` failed `tests.test_reachops_campaign`, 230 tests, 14 failures and 1 error; log `/tmp/reachops-main-p3-public-reply-campaign.log`. Comparison artifact `/tmp/reachops-p3-public-reply-export-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected with `status=not_started`, `readiness=not_started`, `failed_checks=["acceptance:ready"]`; output `/tmp/reachops-p3-public-reply-export-client-delivery.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p3-public-reply-export-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p3-public-reply-export-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p3-public-reply-export-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-p3-public-reply-export-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p3-public-reply-export-diff-check.log`.
- Safety:
  - Tests used synthetic redacted public reply rows only.
  - No real TikTok action was executed.
  - No ixBrowser profile was opened by this slice.
  - No customer data, cookies, screenshots, raw DOM, credentials, local acceptance inputs, or SQLite customer runtime data was committed.
  - P3 remains incomplete until public reply detection is connected to real authorized platform replay/monitoring evidence and manual conversion/revenue capture is implemented.
  - Final delivery remains blocked until ixBrowser Local API is available for fresh no-submit client acceptance, Windows artifacts are generated on Windows, Windows Credential Manager validation passes on Windows, and authorized live evidence passes strict final gates.

## Latest P3 public reply UI surfacing

- Date: `2026-07-20`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Surface public reply lifecycle state in the existing local Web client UI/API without entering Windows packaging, EXE generation, installer generation, ixBrowser execution, or TikTok live-submit.
- Code evidence:
  - `/api/acceptance` operations payload now includes `counts.public_replies`, `counts.qualified_replies`, and scoped `public_reply_events` for the latest batch.
  - Web lead rows now include `public_reply_count`, `qualified_reply_count`, `latest_reply_*`, `reply_summary`, and lifecycle status `reply_received` or `qualified`.
  - Legacy SQLite runtimes without `public_reply_events` keep public reply counts at zero and still render existing lead rows instead of failing or inventing runtime attribution.
  - The local client dashboard now displays `公开回复` and `合格回复` KPI tiles.
  - The lead table now includes a `公开回复` column and maps `reply_received` to `收到回复`, `qualified` to `合格线索`.
  - `tools/reachops_delivery_audit.py` now verifies that public reply counts, status labels, lead summary, and operations payload are exposed in the local client surface.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile tools/reachops_web_ui.py tools/reachops_delivery_audit.py tests/test_reachops_campaign.py`: passed; log `/tmp/reachops-p3-public-reply-ui-pycompile.log`.
  - Focused public-reply UI/API tests passed, 3 tests; log `/tmp/reachops-p3-public-reply-ui-focused.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p3-public-reply-ui-truth.log`.
  - `/usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed, `status=passed`; output `/tmp/reachops-p3-public-reply-ui-runtime-smoke.json`.
  - `/usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed, `status=passed`; output `/tmp/reachops-p3-public-reply-ui-dom-smoke.json`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-p3-public-reply-ui-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-p3-public-reply-ui-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-p3-public-reply-ui-goal-status.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 246 tests; log `/tmp/reachops-p3-public-reply-ui-campaign.log`.
  - Main comparison: `origin/main` at `887f706` failed `tests.test_reachops_campaign`, 230 tests, 14 failures and 1 error; log `/tmp/reachops-main-p3-public-reply-campaign.log`. Comparison artifact `/tmp/reachops-p3-public-reply-ui-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected with `status=not_started`, `readiness=not_started`, `failed_checks=["acceptance:ready"]`; output `/tmp/reachops-p3-public-reply-ui-client-delivery.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p3-public-reply-ui-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p3-public-reply-ui-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-p3-public-reply-ui-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-p3-public-reply-ui-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p3-public-reply-ui-diff-check.log`.
- Safety:
  - Tests used synthetic redacted public reply rows only.
  - No real TikTok action was executed.
  - No ixBrowser profile was opened by this slice.
  - No customer data, cookies, screenshots, raw DOM, credentials, local acceptance inputs, or SQLite customer runtime data was committed.
  - P3 remains incomplete until public reply detection is connected to real authorized platform replay/monitoring evidence and manual conversion/revenue capture is implemented.
  - Final delivery remains blocked until ixBrowser Local API is available for fresh no-submit client acceptance, Windows artifacts are generated on Windows, Windows Credential Manager validation passes on Windows, and authorized live evidence passes strict final gates.

## Latest P4 current client no-submit acceptance attempt

- Date: `2026-07-20`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Reduce the current local-client acceptance blocker without entering Windows packaging, EXE generation, installer generation, or TikTok live-submit.
- Code evidence:
  - `tools/reachops_web_ui.py` now makes ixBrowser group-count resolution tunable with `REACHOPS_GROUP_COUNT_RESOLVE_TIMEOUT_SECONDS` and `REACHOPS_GROUP_COUNT_RESOLVE_WORKERS`.
  - Default group-count resolution is now `45s` and `3` workers instead of the previous fixed `20s` and single worker.
  - The strict start gate still requires all live group counts to be known; this change does not allow partial or stale group counts to start a run.
- Runtime evidence:
  - Existing Web UI on `http://127.0.0.1:8769/` was reachable, but its previous hardcoded count resolver returned `known_group_count=11` of `group_count=16`, causing `/api/start` to reject with `profile_group_counts_incomplete`, `no_browser_started=true`, `no_submit=true`.
  - A current-code Web UI was started on `http://127.0.0.1:8770/` with `REACHOPS_GROUP_COUNT_RESOLVE_TIMEOUT_SECONDS=90` and `REACHOPS_GROUP_COUNT_RESOLVE_WORKERS=4`; `/api/groups?refresh=1` returned `group_count=16`, `known_group_count=16`, `live_all_group_counts_known=true`, `counts_resolved=true`.
  - `/api/start` then launched a default `preflight` / no-submit run for `United States`, target `https://www.amazon.com/APRILSKIN-Pore-Care-Long-lasting-Duo/dp/B0GXKPKRW6?ref_=ast_sto_dp`; response `status=started`, `execution_plan_id=plan_679fcb64e509cc1c`, `run_session_id=run_f8d67ae37aac456a`.
  - Logs contain `PLAN campaign`, `START campaign`, selected group profile-list evidence, and profile preflight evidence for batch `gb_243e48e31aef4254`.
  - The run terminated without live submission: `BLOCK campaign failed reason=无可用账号 required=1 available=0 checked=24 auto_limit=24 error=INSUFFICIENT_LOGGED_IN_PROFILES`.
  - Current account blockers: `IXBROWSER_KERNEL_MISMATCH=14`, `LOGIN_REQUIRED=4`, `PROFILE_PREFLIGHT_TIMEOUT=5`, `PAGE_OPEN_FAILED=1`; `profile_available=0`.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile tools/reachops_web_ui.py tests/test_reachops_campaign.py`: passed.
  - Focused tests for group-count tunability and ixBrowser connection-error normalization: passed, 2 tests.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-group-count-truth.log`.
  - `/usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed, `status=passed`; output `/tmp/reachops-group-count-runtime-smoke.json`.
  - `/usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed, `status=passed`; output `/tmp/reachops-group-count-dom-smoke.json`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-group-count-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-group-count-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-group-count-goal-status.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 247 tests; log `/tmp/reachops-group-count-campaign.log`.
  - Main comparison: `origin/main` at `887f706` failed `tests.test_reachops_campaign`, 230 tests, 14 failures and 1 error; log `/tmp/reachops-main-p3-public-reply-campaign.log`. Comparison artifact `/tmp/reachops-group-count-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_client_delivery_check.py --json`: failed as expected with `status=blocked_by_accounts`, `readiness=blocked_by_accounts`, `profile_available=0`, `failed_checks=["acceptance:ready"]`; output `/tmp/reachops-group-count-client-delivery.json`.
  - `/usr/bin/python3 tools/reachops_mac_loop_acceptance.py --base-url http://127.0.0.1:8770 --json`: failed as expected with `mac_loop_ready=false`; it confirms Web UI reachable, ixBrowser ready, all group counts known, latest run completed, and blocks on account availability / no collection terminal evidence; output `/tmp/reachops-group-count-mac-loop.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed as expected, `final_delivery_ready=false`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-group-count-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`; failed checks are `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-group-count-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed as expected, `status=not_ready`, `final_delivery_ready=false`, `blocking_scopes=["local_mvp","windows_final_artifacts","external_authorized_execution"]`; output `/tmp/reachops-group-count-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-group-count-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-group-count-diff-check.log`.
- Safety:
  - The current client run was `preflight` / no-submit only.
  - No TikTok live-submit, follow, DM, or comment was authorized or attempted.
  - The system hard-blocked on unavailable accounts instead of bypassing login, kernel mismatch, page timeout, or page-open failure.
  - Runtime evidence and account/profile data remain under git-ignored local reports; no customer runtime database or raw evidence is committed.
  - Final delivery remains blocked until at least one execution-group profile is logged in, kernel-compatible, and page-openable; Windows artifacts, Windows Credential Manager validation, and authorized live evidence remain external final gates.

## Latest minimum-MVP client calibration

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Re-check the product-owner minimum MVP freeze gate from the customer-visible local client boundary without starting live submit, Windows packaging, EXE acceptance, installer acceptance, or account repair.
- Runtime evidence:
  - The Mac ixBrowser application is installed at `/Applications/ixBrowser.app` and ixBrowser processes are running.
  - `GET http://127.0.0.1:8769/api/ixbrowser-status` returned `status=ready`, `ready=true`, `base_url=http://127.0.0.1:53200/api/v2/`, `no_browser_started=true`, and `no_submit=true`; output `/tmp/reachops-current-ixbrowser-status.json`.
  - `GET http://127.0.0.1:8769/api/groups?refresh=1` returned `group_count=16`, `known_group_count=16`, `live_all_group_counts_known=true`, `profile_count=2910`, and `United States` group `257999` with `397` known accounts. Count source is still reported as `cached_known_count_after_live_group_list`, so it is display/supporting evidence and not sufficient by itself to prove an executable READY profile.
  - `tools/reachops_client_delivery_check.py --json` failed as expected with `status=blocked_by_accounts`, `readiness=blocked_by_accounts`, `acceptance_ready=false`, `final_delivery_ready=false`, `profile_available=0`, and `failed_checks=["acceptance:ready"]`; output `/tmp/reachops-current-client-delivery.json`.
  - `tools/reachops_mac_loop_acceptance.py --base-url http://127.0.0.1:8769 --json` failed as expected with `status=failed`, `mac_loop_ready=false`, `client_delivery.status=blocked_by_accounts`, `client_delivery.readiness=blocked_by_accounts`, `final_delivery_ready=false`, and `failed_checks=["acceptance:ready"]`; output `/tmp/reachops-current-mac-loop.json`.
  - Continuation re-checks kept the same result: `/tmp/reachops-cont-ixbrowser-status.json` reports ixBrowser API `ready=true`; `/tmp/reachops-cont-groups.json` reports `United States` group `257999`, `397` known accounts, and `us_count_source=cached_known_count_after_live_group_list`; `/tmp/reachops-cont-client-delivery.json` reports `status=blocked_by_accounts`, `acceptance_ready=false`, and `profile_available=0`.
  - Windows package input preflight is ready for a Windows build: `/tmp/reachops-cont-windows-package-preflight.json` reports `status=ready_for_windows_build`, `ready_for_windows_build=true`, and no build-contract failures.
  - Windows final artifacts are still absent: `/tmp/reachops-cont-package-check.json` reports `status=failed`, `final_delivery_ready=false`, and missing `exe`, `installer`, `manifest`, and `acceptance_summary`.
  - Strict final gate remains not ready: `/tmp/reachops-cont-final-gate.json` reports `status=not_ready`, `final_delivery_ready=false`, and failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`.
- Blocker classification:
  - Current blocker is external account/environment readiness, not a new software defect: `profile_available=0` in the `United States` execution group.
  - Existing remediation evidence continues to show hard account blockers: `IXBROWSER_KERNEL_MISMATCH`, `LOGIN_REQUIRED`, `PROFILE_PREFLIGHT_TIMEOUT`, and `PAGE_OPEN_FAILED`.
  - The client correctly refuses to treat this as a passed no-submit run and keeps `minimum_mvp_ready=false`.
- Windows boundary:
  - Windows 11 VM, Windows ixBrowser, installed `ReachOps.exe`, installer, manifest, and Windows acceptance summary were not accessed or validated in this calibration.
  - Mac ixBrowser Local API readiness does not prove Windows client readiness.
  - Current Mac-side package checks prove that Windows build inputs exist, but they do not generate or validate the installed Windows client; the next Windows step must run `tools\build_reachops_windows.ps1` and `tools\run_reachops_acceptance_windows.ps1` inside Windows.
- Safety:
  - No TikTok live-submit, follow, DM, or comment was authorized or attempted.
  - No ixBrowser profile was opened by this calibration beyond read-only Local API status/group checks.
  - No customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or local acceptance input files were committed.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
- Next action:
  - On Mac, repair or supply at least one `United States` profile that is TikTok logged-in, ixBrowser-kernel compatible, proxy/page-open stable, and eligible for automatic selection; then rerun the same customer-visible no-submit client calibration until five consecutive runs pass.
  - For final Windows delivery, enter the Windows 11 environment and validate installed `ReachOps.exe` with Windows ixBrowser; Mac-side verification remains insufficient for Windows acceptance.

## Latest client plan-replay account-gate snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Close a customer-visible Web client interaction gap discovered during minimum-MVP calibration: the backend already rejected `/api/start-from-plan` when the account gate was blocked, but the UI still presented `重放计划执行` as enabled. This slice aligns the customer-visible plan replay entrypoint with the same account gate as `开始获客`.
- Code evidence:
  - `tools/reachops_web_ui.py` now disables `startFromPlan` when the current selected group is account-gate blocked and account repair has not been confirmed for that group.
  - `previewPlanReplay` remains enabled and its title explicitly states that, under account blocking, preview only explains the gate and does not start a browser.
  - `startFromPlan()` now has a client-side guard that returns a structured `account_repair_required` notice with `no_browser_started=true` and `no_submit=true` if a disabled replay button is invoked.
  - `tests/test_reachops_client_acceptance_status.py` now verifies that `/api/start-from-plan` rejects `account_repair_required` without launching `subprocess.Popen`, and that the rendered Web UI disables plan replay execution under an account gate.
- Client-visible verification:
  - The ReachOps local Web client was restarted from the current workspace on `http://127.0.0.1:8769/`.
  - Browser DOM verification returned `acceptanceState="验收状态：账号阻断 / blocked_by_accounts / 目标：not_ready / 客户端门禁：blocked_by_accounts"`.
  - Browser DOM verification returned `accountGateState="United States 账号阻断"`, `startDisabled=true`, `startFromPlanDisabled=true`, `previewPlanReplayDisabled=false`, and `previewPlanReplayTitle="United States 账号阻断；预检只会解释阻断原因，不会启动浏览器。"`
  - No start button, plan replay execution button, ixBrowser profile launch, or TikTok page action was clicked during this verification.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/reachops_web_ui.py tests/test_reachops_client_acceptance_status.py`: passed.
  - Targeted plan-replay/account-gate tests: passed, 3 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_client_acceptance_status`: passed, 123 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-client-plan-replay-gate-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-client-plan-replay-gate-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-client-plan-replay-gate-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 259 tests; log `/tmp/reachops-client-plan-replay-gate-campaign.log`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-client-plan-replay-gate-cleanliness.json`.
  - `git diff --check`: passed.
- Expected blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json` failed as expected with `status=blocked_by_accounts`, `readiness=blocked_by_accounts`, `acceptance_ready=false`, `final_delivery_ready=false`, `profile_available=0`, and `failed_checks=["acceptance:ready"]`; output `/tmp/reachops-client-plan-replay-gate-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json` failed as expected with `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`, and failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-client-plan-replay-gate-goal-delivery-runner.json`.
- Safety:
  - No TikTok live-submit, follow, DM, or comment was authorized or attempted.
  - No account repair plan was applied and no ixBrowser profile was launched by this slice.
  - Current Mac and Windows ixBrowser installations are visible, but effective real validation still requires at least one READY, logged-in, kernel-compatible, page-openable profile selected automatically from the customer-visible client flow.
  - The untracked `ReachOps-1/` directory remains outside this work and was not modified.
- Next action:
  - Repair or provide at least one usable `United States` profile, then rerun the same customer-visible no-submit client path. Only after five consecutive real client no-submit runs pass can the minimum-MVP readiness gate be considered for `minimum_mvp_ready=true`.

## Latest acquisition-test-group client calibration snapshot

- Date: `2026-07-24`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Product owner directed the Mac client calibration to continue with ixBrowser group `获客分组测试` instead of the prior `United States` group. This was executed only from the customer-visible local Web client at `http://127.0.0.1:8769/` in `preflight` / no-submit mode.
- Real client execution evidence:
  - `/api/groups?refresh=1` read `获客分组测试` from ixBrowser Local API with `group_id=308389`, `count=11`, `count_known=true`, and `count_source=cached_known_count_after_live_group_list`; output `/tmp/reachops-groups-refresh-acq-test.json`.
  - The browser UI was changed to `group=获客分组测试`, `target=APRILSKIN Pore Care Long lasting Duo`, and `mode=preflight`; the start preview showed `可启动`.
  - First real client start created ExecutionPlan `plan_bfd0df71e4834cfe` and RunSession `run_fdd747b548c73b9b`, but watchdog blocked it as `HEARTBEAT_STALE` after reading a stale heartbeat from old RunSession `run_f8d67ae37aac456a`. This was classified as a software defect, not an account blocker.
  - After fixing watchdog heartbeat ownership, the same client-visible path started RunSession `run_7a4f809975441992` and batch `gb_498320c756f54b92` for `获客分组测试`.
  - The fixed run reached `PROFILE_PREFLIGHT`, selected 3 initial profiles from 11 candidates, then backfilled. Heartbeat stayed fresh for the current run and watchdog did not mis-block.
  - The run checked 9 profiles and ended with `BLOCK campaign failed reason=无可用账号 required=1 available=0 checked=9 auto_limit=24 error=INSUFFICIENT_LOGGED_IN_PROFILES`.
  - Current `获客分组测试` profile errors are `PAGE_OPEN_FAILED=4` and `PROFILE_PREFLIGHT_TIMEOUT=5`; no READY profile was found.
  - The client then correctly marked the selected group account gate blocked: a repeat page start showed `accountGateState="获客分组测试 账号阻断"`, `previewGate="账号修复后启动"`, and `startDisabled=true`, so the system did not keep reopening the same failed profile pool.
- Code evidence:
  - `tools/reachops_web_ui.py` now ignores runtime heartbeat files whose `run_session_path`/session id does not match the current RunSession, and cleans stale heartbeat/progress files before starting a new runner.
  - `tools/run_reachops_headless_macos.py` now treats `BLOCK campaign failed` / `BLOCK campaign not_started` terminal logs as `status=blocked`, final RunSession `BLOCKED`, and non-zero exit instead of `completed`.
  - `tools/run_reachops_headless_macos.py` now marks `PROFILE_PREFLIGHT` before launching the collection flow, avoiding the observed backward `COLLECTING->PROFILE_PREFLIGHT` RunSession transition.
  - `ReachOps/run_session.py` now infers `BLOCKED` from blocked campaign terminal logs.
  - Tests cover stale heartbeat ownership, blocked campaign terminal classification, and RunSession blocked-state inference.
- Tests and checks:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m py_compile tools/reachops_web_ui.py tools/run_reachops_headless_macos.py ReachOps/run_session.py tests/test_reachops_client_acceptance_status.py tests/test_run_recovery.py`: passed.
  - Targeted tests for stale heartbeat, blocked terminal classification, and blocked RunSession inference: passed, 3 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_client_acceptance_status`: passed, 125 tests; log `/tmp/reachops-acq-test-client-acceptance.log`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_run_recovery`: passed, 9 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, `submitted_unverified=0`; output `/tmp/reachops-acq-test-operator-pressure.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_delivery_audit.py --json`: passed, `status=ok`, summary `passed=53,pending_external_validation=3,failed=0`; output `/tmp/reachops-acq-test-delivery-audit.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_status_report.py --json`: passed as `ready_for_external_validation`, summary `final_passed=30,final_pending_external_validation=3,final_failed=0`; output `/tmp/reachops-acq-test-goal-status-report.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: passed, 259 tests; log `/tmp/reachops-acq-test-campaign.log`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-acq-test-cleanliness.json`.
  - `git diff --check`: passed.
- Expected blockers:
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_client_delivery_check.py --json` failed as expected with `status=blocked_by_accounts`, `readiness=blocked_by_accounts`, `profile_available=0`, `failed_checks=["acceptance:ready"]`, selected group `获客分组测试`, `selected_group_id=308389`, and `selected_profile_count=11`; output `/tmp/reachops-acq-test-client-delivery.json`.
  - `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 tools/reachops_goal_delivery_runner.py --json` failed as expected with `status=not_ready`, `local_mvp_ready=false`, `final_delivery_ready=false`, and failed checks `goal_status:passed`, `client_delivery:final_ready`, and `delivery_package:passed`; output `/tmp/reachops-acq-test-goal-delivery-runner.json`.
- Safety:
  - No TikTok live-submit, follow, DM, or comment was authorized or attempted.
  - The only real browser/profile work was bounded no-submit profile preflight from the customer-visible client.
  - The run stopped after circuit breaker `browser_start_instability` with 9 failed profiles, leaving 2 untried profiles instead of repeatedly reopening failed profiles.
  - No `run_reachops_headless_macos.py` process remained after terminal state.
  - Runtime evidence and screenshots remain in git-ignored local reports; no customer SQLite database, cookies, credentials, raw DOM evidence, screenshots, or local acceptance input files were committed.
- Next action:
  - Fix `获客分组测试` account environment: at least one profile must be logged in, kernel-compatible, proxy/page-open stable, and able to open TikTok manually. Then rerun the same Web client no-submit flow. Until then, `minimum_mvp_ready` must remain false.

## Non-blocking engineering work available

- LeadDecision versioning and unified scoring contract.
- Windows Credential Manager validation on Windows.
- Encrypted backup format and restore tests.
- License state machine and 7-day grace logic.
- Localization resource extraction for `zh-CN` and `en-US`.

## State-update rules

Codex must update this file at the end of each milestone with:

- status transition
- commit and PR
- tests executed and exact result
- evidence paths
- blockers
- next autonomous action

Do not write `COMPLETE` unless every exit condition is supported by evidence. Implementation completion and external live acceptance are separate states.
