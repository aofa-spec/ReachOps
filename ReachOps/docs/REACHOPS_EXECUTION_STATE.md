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
| P2 | Windows local security, licensing, backup, device seats | `IN_REVIEW` | Draft PR #23, branch `codex/p2-windows-credential-manager`; local-security slice makes AI API key resolution prefer Windows Credential Manager, keeps non-Windows runtimes explicitly non-persistent/session-only, adds a minimal license refresh client that sends only license/device/version metadata, adds a 7-day license grace state machine where app access can remain allowed while live-submit remains blocked, adds 24-hour license verification cadence evidence that blocks live-submit when declared verification is due, adds encrypted `.reachops-backup` create/inspect/restore preview/commit helpers that exclude activation files, Credential Manager secrets, cookies/sessions, proxy secrets, screenshots, and raw DOM evidence, and adds device-seat evaluation for one-device default plus extra-seat activation evidence; focused tests cover Windows target naming, read/write/delete flow, environment fallback, redaction status, default AI provider integration, license refresh request boundaries, license grace/expiry, 24-hour verification due/fresh states, activation reporting, live-submit blocking during grace/verification due, wrong password/corruption rejection, atomic restore behavior, seat-limit exceeded, available-but-unbound seats, and legacy unbound compatibility | Review PR #23; continue Windows validation for Credential Manager, package persistence, activation refresh, and final package generation |
| P3 | Public comment-reply monitoring and lead lifecycle | `PLANNED` | Product contract locked | Automatic public reply detection; action linkage; qualified-lead state; manual conversion/revenue capture |
| P4 | Bilingual UI, installer, update, Windows acceptance | `PLANNED` | Existing packaging/runbook exists but final external acceptance is incomplete | Win10/11 installer, zh-CN/en-US UI, update flow, acceptance matrix, authorized live evidence |
| P5 | DM inbox monitoring | `DEFERRED` | Explicitly deferred behind public reply monitoring | Separate privacy/evidence contract and acceptance after P3/P4 |

## Next autonomous action

1. Keep PR #12 Draft for P1 review; do not expand it with P2.
2. Review the independent P2 Windows Credential Manager, license client, license grace, verification, backup, and device-seat slice on branch `codex/p2-windows-credential-manager`.
3. After the first P2 slice merges, continue P2:
   - Windows validation for Credential Manager, package persistence, and activation refresh
   - final package generation inputs

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

## Latest P2 verification snapshot

- Date: `2026-07-19`
- Branch: `codex/p2-windows-credential-manager`
- PR: Draft PR #23
- Commit: current P2 review commits on this branch; final SHA is reported in the completion report.
- Scope: First P2 local security slice only; no Windows build, installer, live TikTok action, customer data, credentials, cookies, or real target evidence.
- Code evidence:
  - Added `ReachOps.credentials.ReachOpsCredentialStore`.
  - Windows clients persist named secrets through Windows Credential Manager generic credentials with `ReachOps:<secret_name>` target names.
  - Non-Windows development runtimes return `unsupported_platform` for persistence and may only use environment variables as session-only compatibility.
  - AI API key resolution prefers Windows Credential Manager on Windows and falls back to `REACHOPS_AI_API_KEY` as non-persistent session input.
  - The Tk console writes a provided AI key through the credential store; on successful Windows storage it clears the process environment key path and keeps logs redacted to configured/source/persistence booleans.
  - The default acquisition intelligence provider now obtains the HTTP AI key through the credential resolver instead of reading only `REACHOPS_AI_API_KEY`.
  - Added `ReachOps.license_state.evaluate_license_state(...)` with active, grace, expired, inactive, template, and missing states.
  - License grace is 7 days after `expires_at`: local app access can remain allowed during grace, but `live_submit_allowed=false`.
  - `LiveSubmitAuthorizationGate` now includes `license_state` evidence and rejects grace-period live submit with `LIVE_SUBMIT_LICENSE_GRACE_PERIOD` instead of treating grace as live authorization.
  - `/api/activation`/activation status reporting now exposes license app-access and live-submit checks plus operator actions for grace/renewal.
  - Added `ReachOps.backup` helpers for encrypted `.reachops-backup` create, inspect, restore preview, and restore commit.
  - Backup manifests include schema version, backup variant, per-file SHA-256 hashes, encryption parameters, and explicit secret/data exclusions.
  - Backup collection includes local SQLite runtime data and non-secret config while excluding activation status files, Credential Manager secrets, TikTok cookies/sessions, proxy credentials, screenshots, and raw DOM evidence.
  - Restore preview validates archive authentication, manifest exclusions, and file hashes without writing files; restore commit writes through temporary files and atomically replaces targets.
  - Added `ReachOps.device_seats.evaluate_device_seat_state(...)` for one-device default and extra-seat activation payloads.
  - `LiveSubmitAuthorizationGate` now includes `device_seat_state` evidence and blocks live submit when the current device is not bound, even if an extra seat is available but not yet activated by the license service.
  - Activation status reporting now exposes `device_seat_allows_current_device` while keeping legacy unbound activation files compatible.
  - Added `ReachOps.license_verification.evaluate_license_verification_state(...)` for the required 24-hour local verification cadence.
  - Activation status reporting exposes `license_verification_state` and only enforces freshness when activation payloads declare verification timestamps, preserving legacy activation payload compatibility.
  - Live acceptance operator actions now distinguish a due 24-hour license verification refresh from live-submit authorization failure.
  - Added `ReachOps.license_client.ReachOpsLicenseClient` for minimal activation refresh.
  - License refresh sends only allowlisted license/device/version metadata to a configured endpoint and records `customer_data_uploaded=false`.
  - Added `tools/reachops_license_refresh.py` for redacted preview and explicit refresh; preview does not use network or write activation status.
  - `LiveSubmitAuthorizationGate` now blocks declared stale verification with `LIVE_SUBMIT_LICENSE_VERIFICATION_REQUIRED` while keeping legacy activation payloads without verification timestamps compatible.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/credentials.py ReachOps/intelligence/ai_strategy.py ReachOps/workbench/console.py tests/test_credentials.py`: passed, exit `0`.
  - `/usr/bin/python3 -m py_compile ReachOps/license_state.py ReachOps/workbench/authorization_gate.py ReachOps/intelligence/schemas.py tools/reachops_activation_status_check.py tools/reachops_live_acceptance_status.py tests/test_license_state.py`: passed, exit `0`.
  - `/usr/bin/python3 -m py_compile ReachOps/backup.py tests/test_backup.py`: passed, exit `0`.
  - `/usr/bin/python3 -m py_compile ReachOps/device_seats.py ReachOps/workbench/authorization_gate.py tools/reachops_activation_status_check.py tools/reachops_live_acceptance_status.py tests/test_device_seats.py`: passed, exit `0`.
  - `/usr/bin/python3 -m py_compile ReachOps/license_verification.py tools/reachops_activation_status_check.py tools/reachops_live_acceptance_status.py tests/test_license_verification.py`: passed, exit `0`.
  - `/usr/bin/python3 -m py_compile ReachOps/license_client.py ReachOps/workbench/authorization_gate.py ReachOps/intelligence/schemas.py tests/test_license_client.py tests/test_license_verification.py tools/reachops_license_refresh.py`: passed, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_credentials`: passed, 5 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_license_state`: passed, 5 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_backup`: passed, 3 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_device_seats`: passed, 6 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_license_verification`: passed, 5 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_license_client tests.test_license_verification`: passed, 11 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_credentials tests.test_license_state`: passed, 10 tests, exit `0`; log `/tmp/reachops-p2-backup-security-tests.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_license_state tests.test_credentials tests.test_backup`: passed, 13 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_license_client tests.test_device_seats tests.test_license_verification tests.test_license_state tests.test_credentials tests.test_backup`: passed, 30 tests, exit `0`; log `/tmp/reachops-p2-license-client-security-tests.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_http_ai_provider_accepts_chat_style_json_response tests.test_reachops_campaign.ReachOpsCampaignTests.test_http_ai_provider_falls_back_to_rules_when_request_fails`: passed, 2 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_activation_status_check_reports_device_and_capabilities tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_activation_status_check_blocks_device_mismatch tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_activation_status_template_is_not_authorization tests.test_reachops_campaign.ReachOpsCampaignTests.test_live_submit_rejects_expired_activation_status`: passed, 4 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-p2-license-verify-truth.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-p2-license-client-campaign.log`.
  - `origin/main` baseline: `/tmp/reachops-main-baseline-p2-license-verify-campaign.log` failed with the same 14 failures and 1 error.
  - Baseline comparison artifact: `/tmp/reachops-p2-license-client-baseline-comparison.json`; `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-p2-license-client-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-p2-license-client-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-p2-license-client-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=27`, `final_pending_external_validation=3`, `final_failed=3`; output `/tmp/reachops-p2-license-client-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p2-license-client-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-p2-license-client-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`; output `/tmp/reachops-p2-license-client-cleanliness.json`.
  - `git diff --check`: passed, exit `0`.
- Safety:
  - No real secret value was added to tests, logs, reports, or git-tracked files.
  - No real TikTok action was executed.

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
