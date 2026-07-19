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
| P2 | Windows local security, licensing, backup, device seats | `IN_REVIEW` | Draft PR #23, branch `codex/p2-windows-credential-manager`; local-security slice makes AI API key and license key resolution prefer Windows Credential Manager, keeps non-Windows runtimes explicitly non-persistent/session-only, structures native Credential Manager read/write/delete failures without leaking secret values, removes command-line license-key input from license refresh, adds a minimal license refresh client that sends only license/device/version metadata, adds a 7-day license grace state machine where app access can remain allowed while live-submit remains blocked, adds 24-hour license verification cadence evidence that blocks live-submit when declared verification is due, adds encrypted `.reachops-backup` create/inspect/restore preview/commit helpers that exclude activation files, Credential Manager secrets, cookies/sessions, proxy secrets, screenshots, and raw DOM evidence, adds device-seat evaluation for one-device default plus extra-seat activation evidence, and hardens Windows update manifest/preflight contracts so release manifests use portable installer paths and preserve runtime data/config/activation status; focused tests cover Windows target naming, read/write/delete flow, native failure redaction, oversized secret rejection, environment fallback, redaction status, default AI provider integration, license refresh secret-source precedence, license refresh request boundaries, license grace/expiry, 24-hour verification due/fresh states, activation reporting, live-submit blocking during grace/verification due, backup restore safety, seat enforcement, legacy compatibility, update manifest portability, and Windows package manifest-contract preflight | Review PR #23; continue Windows validation for Credential Manager, package persistence, activation refresh, and final package generation |
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
  - Credential Manager native read/write/delete failures now return structured `SecretLookup`/`SecretWriteResult` states instead of raising through the UI/provider path, and only expose exception class names, not secret values.
  - Oversized secret values are rejected before native Windows writes when the UTF-16 credential blob would exceed the Windows Credential Manager generic credential limit.
  - Non-Windows development runtimes return `unsupported_platform` for persistence and may only use environment variables as session-only compatibility.
  - AI API key resolution prefers Windows Credential Manager on Windows and falls back to `REACHOPS_AI_API_KEY` as non-persistent session input.
  - License key resolution now uses the same secret boundary: Windows Credential Manager `ReachOps:license_key` first, then `REACHOPS_LICENSE_KEY` as a non-persistent session fallback.
  - The Tk console writes a provided AI key through the credential store; on successful Windows storage it clears the process environment key path and keeps logs redacted to configured/source/persistence booleans.
  - The default acquisition intelligence provider now obtains the HTTP AI key through the credential resolver instead of reading only `REACHOPS_AI_API_KEY`.
  - Added `ReachOps.license_state.evaluate_license_state(...)` with active, grace, expired, inactive, template, and missing states.
  - License grace is 7 days after `expires_at`: local app access can remain allowed during grace, but `live_submit_allowed=false`.
  - `LiveSubmitAuthorizationGate` now includes `license_state` evidence and rejects grace-period live submit with `LIVE_SUBMIT_LICENSE_GRACE_PERIOD` instead of treating grace as live authorization.
  - `/api/activation`/activation status reporting now exposes license app-access and live-submit checks plus operator actions for grace/renewal.
  - Added `ReachOps.backup` helpers for encrypted `.reachops-backup` create, inspect, restore preview, and restore commit.
  - Backup manifests include schema version, backup variant, per-file SHA-256 hashes, encryption parameters, and explicit secret/data exclusions.
  - Backup manifest validation now requires the expected encryption contract, rejects unsupported KDF/cipher/MAC declarations, rejects duplicate archive paths, and blocks absolute or parent-traversal restore paths during preview before any file write.
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
  - License refresh request failures now return structured `request_failed` results with exception class names only, preserving the redacted request payload without echoing raw upstream exception strings.
  - License activation-status write failures now return structured `activation_status_write_failed` results with exception class names only, so filesystem diagnostics cannot leak a license key through UI/CLI JSON.
  - Added `tools/reachops_license_refresh.py` for redacted preview and explicit refresh; preview does not use network or write activation status.
  - `tools/reachops_license_refresh.py` no longer accepts `--license-key`; operators must use Windows Credential Manager or the session-only `REACHOPS_LICENSE_KEY` fallback, and the custom argument rejection does not echo the rejected secret value.
  - `tools/reachops_license_refresh.py` catch-all failures now report only the exception class name while preserving secret-source metadata and `secret_value_redacted=true`.
  - `LiveSubmitAuthorizationGate` now blocks declared stale verification with `LIVE_SUBMIT_LICENSE_VERIFICATION_REQUIRED` while keeping legacy activation payloads without verification timestamps compatible.
  - `tools/write_reachops_update_manifest.py` now writes a portable installer path instead of a build-machine absolute path.
  - `ReachOps.updater.ReachOpsUpdateManager.installer_path_from_manifest(...)` resolves relative manifest installer paths against the supplied base directory.
  - `tools/reachops_windows_package_preflight.py` now includes a `manifest_contract` fixture check for current version, Windows platform, installer hash/size, portable path, runtime config/data/activation preservation, and absence of customer-data fields.
  - Windows acceptance now runs `tools/reachops_license_refresh.py --preview --json` before activation status checks and records `acceptance_summary.license_refresh` as a no-browser/no-submit, customer-data-free, redacted request-boundary report.
  - Windows acceptance exposes `LicenseEndpoint` for preview routing but does not accept a command-line `LicenseKey`, avoiding command-line secret leakage.
  - `tools/verify_reachops_acceptance_summary.py` rejects unsafe license refresh evidence if the optional section starts a browser, attempts submit, uploads customer data, exposes an unredacted license key, or points its report outside the acceptance summary directory.
  - `tools/reachops_delivery_package_check.py` indexes the optional `license_refresh` report when an acceptance summary provides a `json_path`, without making it a substitute for activation readiness, live-submit evidence, or final delivery.
  - License refresh now sanitizes upstream `activation_status` responses before writing local activation status or returning CLI/report JSON.
  - Persisted activation status keeps only license status, license tier, capability flags, expiry, verification cadence, device-seat IDs, current device ID, client marker, and `customer_data_uploaded=false`.
  - Disallowed upstream response fields such as `license_key`, customer usernames, comment text, screenshot paths, database paths, cookies, proxy passwords, device secrets, operator names, and billing email are dropped before local persistence.
  - Nested device-seat rows keep only `device_id`, `id`, and `activated_at`; descriptive or secret-bearing device metadata is not persisted.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/credentials.py ReachOps/intelligence/ai_strategy.py ReachOps/workbench/console.py tests/test_credentials.py`: passed, exit `0`.
  - `/usr/bin/python3 -m py_compile ReachOps/credentials.py ReachOps/intelligence/ai_strategy.py tests/test_credentials.py`: passed, exit `0`.
  - `/usr/bin/python3 -m py_compile ReachOps/license_state.py ReachOps/workbench/authorization_gate.py ReachOps/intelligence/schemas.py tools/reachops_activation_status_check.py tools/reachops_live_acceptance_status.py tests/test_license_state.py`: passed, exit `0`.
  - `/usr/bin/python3 -m py_compile ReachOps/backup.py tests/test_backup.py`: passed, exit `0`.
  - `/usr/bin/python3 -m py_compile ReachOps/backup.py tests/test_backup.py`: passed, exit `0`; log `/tmp/reachops-p2-backup-manifest-pycompile.log`.
  - `/usr/bin/python3 -m py_compile ReachOps/device_seats.py ReachOps/workbench/authorization_gate.py tools/reachops_activation_status_check.py tools/reachops_live_acceptance_status.py tests/test_device_seats.py`: passed, exit `0`.
  - `/usr/bin/python3 -m py_compile ReachOps/license_verification.py tools/reachops_activation_status_check.py tools/reachops_live_acceptance_status.py tests/test_license_verification.py`: passed, exit `0`.
  - `/usr/bin/python3 -m py_compile ReachOps/license_client.py ReachOps/workbench/authorization_gate.py ReachOps/intelligence/schemas.py tests/test_license_client.py tests/test_license_verification.py tools/reachops_license_refresh.py`: passed, exit `0`.
  - `/usr/bin/python3 -m py_compile ReachOps/credentials.py ReachOps/license_client.py tools/reachops_license_refresh.py tests/test_license_client.py tests/test_credentials.py`: passed, exit `0`; log `/tmp/reachops-p2-license-key-secret-pycompile.log`.
  - `/usr/bin/python3 -m py_compile ReachOps/license_client.py tools/reachops_license_refresh.py tests/test_license_client.py`: passed, exit `0`; log `/tmp/reachops-p2-license-error-redaction-pycompile.log`.
  - `/usr/bin/python3 -m py_compile ReachOps/license_client.py tests/test_license_client.py`: passed, exit `0`; log `/tmp/reachops-p2-license-activation-sanitize-pycompile.log`.
  - `/usr/bin/python3 -m py_compile ReachOps/updater.py tools/write_reachops_update_manifest.py tools/reachops_windows_package_preflight.py tests/test_reachops_campaign.py`: passed, exit `0`.
  - `/usr/bin/python3 -m py_compile tools/verify_reachops_acceptance_summary.py tools/reachops_delivery_package_check.py tests/test_reachops_campaign.py`: passed, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_credentials`: passed, 5 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_credentials`: passed, 7 tests, exit `0`; log `/tmp/reachops-p2-credential-failure-credentials.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_license_state`: passed, 5 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_backup`: passed, 3 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_backup`: passed, 5 tests, exit `0`; log `/tmp/reachops-p2-backup-manifest-tests.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_device_seats`: passed, 6 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_license_verification`: passed, 5 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_license_client tests.test_license_verification`: passed, 11 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_license_client tests.test_credentials`: passed, 13 tests, exit `0`; log `/tmp/reachops-p2-license-key-secret-tests.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_license_client`: passed, 7 tests, exit `0`; log `/tmp/reachops-p2-license-error-redaction-tests.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_license_client`: passed, 8 tests, exit `0`; log `/tmp/reachops-p2-license-activation-sanitize-tests.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_update_manifest_contains_hash_and_preserve_policy tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_update_manager_validates_manifest_hash_and_install_args tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_windows_package_preflight_validates_build_inputs_without_claiming_final_delivery`: passed, 3 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_packaging_files_define_standalone_windows_artifacts tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_acceptance_summary_verifier_classifies_external_pending_and_failures tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_delivery_package_check_validates_artifacts_manifest_and_reports`: passed, 3 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_credentials tests.test_license_state`: passed, 10 tests, exit `0`; log `/tmp/reachops-p2-backup-security-tests.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_license_state tests.test_credentials tests.test_backup`: passed, 13 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_license_client tests.test_device_seats tests.test_license_verification tests.test_license_state tests.test_credentials tests.test_backup`: passed, 30 tests, exit `0`; log `/tmp/reachops-p2-license-client-security-tests.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_credentials tests.test_license_client tests.test_license_state tests.test_license_verification tests.test_device_seats tests.test_backup`: passed, 38 tests, exit `0`; log `/tmp/reachops-p2-backup-manifest-focused-tests.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_http_ai_provider_accepts_chat_style_json_response tests.test_reachops_campaign.ReachOpsCampaignTests.test_http_ai_provider_falls_back_to_rules_when_request_fails`: passed, 2 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_activation_status_check_reports_device_and_capabilities tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_activation_status_check_blocks_device_mismatch tests.test_reachops_campaign.ReachOpsCampaignTests.test_reachops_activation_status_template_is_not_authorization tests.test_reachops_campaign.ReachOpsCampaignTests.test_live_submit_rejects_expired_activation_status`: passed, 4 tests, exit `0`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-p2-license-verify-truth.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-p2-credential-failure-truth.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-p2-license-key-secret-truth.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-p2-license-error-redaction-truth.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-p2-license-activation-sanitize-truth.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests, exit `0`; log `/tmp/reachops-p2-backup-manifest-truth.log`.
  - `/usr/bin/python3 tools/reachops_windows_package_preflight.py --json`: passed, exit `0`, `ready_for_windows_build=true`, `manifest_contract.ok=true`; output `/tmp/reachops-p2-package-preflight-contract.json`.
  - `REACHOPS_LICENSE_KEY=<test-fixture> /usr/bin/python3 tools/reachops_license_refresh.py --preview --json --endpoint https://license.example.test/refresh`: passed as redaction fixture, exit `0`, wrote `/tmp/reachops-p2-license-refresh-preview.json`; verified `status=preview`, `refreshed=false`, `request_payload.license_key=***redacted***`, `no_browser_started=true`, `no_submit=true`, `customer_data_uploaded=false`.
  - `REACHOPS_LICENSE_KEY=<test-fixture> /usr/bin/python3 tools/reachops_license_refresh.py --preview --json --endpoint https://license.example.test/refresh`: passed as redaction fixture, exit `0`, wrote `/tmp/reachops-p2-license-key-secret-preview.json`; verified `status=preview`, `refreshed=false`, `license_key_source=environment_session`, `license_key_persistent=false`, `request_payload.license_key=***redacted***`, `no_browser_started=true`, `no_submit=true`, `customer_data_uploaded=false`.
  - `/usr/bin/python3 tools/reachops_windows_package_preflight.py --json`: passed, exit `0`, `ready_for_windows_build=true`, `manifest_contract.ok=true`; output `/tmp/reachops-p2-license-refresh-windows-package-preflight.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-p2-package-manifest-campaign.log`.
  - `origin/main` baseline: `/tmp/reachops-main-baseline-p2-license-verify-campaign.log` failed with the same 14 failures and 1 error.
  - Baseline comparison artifact: `/tmp/reachops-p2-package-manifest-baseline-comparison.json`; `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-p2-license-refresh-acceptance-campaign.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-p2-credential-failure-campaign.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-p2-license-key-secret-campaign.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-p2-license-error-redaction-campaign.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-p2-license-activation-sanitize-campaign.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-p2-backup-manifest-campaign.log`.
  - Baseline comparison artifact: `/tmp/reachops-p2-license-refresh-acceptance-baseline-comparison.json`; `new_failures=[]`, `new_errors=[]`.
  - Baseline comparison artifact: `/tmp/reachops-p2-credential-failure-baseline-comparison.json`; `new_failures=[]`, `new_errors=[]`.
  - Baseline comparison artifact: `/tmp/reachops-p2-license-key-secret-baseline-comparison.json`; `new_failures=[]`, `new_errors=[]`.
  - Baseline comparison artifact: `/tmp/reachops-p2-license-error-redaction-baseline-comparison.json`; `new_failures=[]`, `new_errors=[]`.
  - Baseline comparison artifact: `/tmp/reachops-p2-license-activation-sanitize-baseline-comparison.json`; `new_failures=[]`, `new_errors=[]`.
  - Baseline comparison artifact: `/tmp/reachops-p2-backup-manifest-baseline-comparison.json`; `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-p2-package-manifest-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-p2-license-refresh-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-p2-credential-failure-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-p2-license-key-secret-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-p2-license-error-redaction-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-p2-license-activation-sanitize-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-p2-review-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-p2-package-manifest-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-p2-license-refresh-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-p2-credential-failure-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-p2-license-key-secret-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-p2-license-error-redaction-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-p2-license-activation-sanitize-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, `status=failed`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-p2-backup-manifest-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-p2-package-manifest-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; delivery boundary blocks include `local_mvp`, `windows_final_artifacts`, and `external_authorized_execution`; output `/tmp/reachops-p2-license-refresh-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-p2-credential-failure-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-p2-license-key-secret-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-p2-license-error-redaction-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-p2-license-activation-sanitize-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; output `/tmp/reachops-p2-backup-manifest-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=27`, `final_pending_external_validation=3`, `final_failed=3`; output `/tmp/reachops-p2-package-manifest-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=27`, `final_pending_external_validation=3`, `final_failed=3`; output `/tmp/reachops-p2-license-refresh-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=27`, `final_pending_external_validation=3`, `final_failed=3`; output `/tmp/reachops-p2-credential-failure-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=27`, `final_pending_external_validation=3`, `final_failed=3`; output `/tmp/reachops-p2-license-key-secret-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=27`, `final_pending_external_validation=3`, `final_failed=3`; output `/tmp/reachops-p2-license-error-redaction-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`, summary `stages_passed=2`, `stages_pending_external_validation=2`, `stages_failed=1`, `final_passed=27`, `final_pending_external_validation=3`, `final_failed=3`; output `/tmp/reachops-p2-license-activation-sanitize-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`; output `/tmp/reachops-p2-backup-manifest-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p2-package-manifest-package-check.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; failures include `exe_missing`, `installer_missing`, `manifest_missing`, `acceptance_summary_missing`, and `acceptance_summary_not_passed`; output `/tmp/reachops-p2-license-refresh-package-check.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p2-credential-failure-package-check.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p2-license-key-secret-package-check.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p2-license-error-redaction-package-check.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p2-license-activation-sanitize-package-check.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p2-backup-manifest-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-p2-package-manifest-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-p2-license-refresh-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-p2-credential-failure-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-p2-license-key-secret-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-p2-license-error-redaction-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-p2-license-activation-sanitize-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-p2-backup-manifest-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`; output `/tmp/reachops-p2-package-manifest-cleanliness.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`; output `/tmp/reachops-p2-license-refresh-cleanliness.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`; output `/tmp/reachops-p2-credential-failure-cleanliness.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`; output `/tmp/reachops-p2-license-error-redaction-cleanliness.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`; output `/tmp/reachops-p2-license-activation-sanitize-cleanliness.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`; output `/tmp/reachops-p2-backup-manifest-cleanliness.json`.
  - `git diff --check`: passed, exit `0`.
  - `git diff --check`: passed, exit `0`; log `/tmp/reachops-p2-license-refresh-diff-check.log`.
  - `git diff --check`: passed, exit `0`; log `/tmp/reachops-p2-credential-failure-diff-check.log`.
  - `git diff --check`: passed, exit `0`; log `/tmp/reachops-p2-license-key-secret-diff-check.log`.
  - `git diff --check`: passed, exit `0`; log `/tmp/reachops-p2-license-error-redaction-diff-check.log`.
  - `git diff --check`: passed, exit `0`; log `/tmp/reachops-p2-license-activation-sanitize-diff-check.log`.
  - `git diff --check`: passed, exit `0`; log `/tmp/reachops-p2-backup-manifest-diff-check.log`.
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
