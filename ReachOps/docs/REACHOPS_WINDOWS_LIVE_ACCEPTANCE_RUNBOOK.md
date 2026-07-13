# ReachOps Windows Live Acceptance Runbook

Use this runbook to execute Milestone 2, Milestone 3, and Milestone 4 from `REACHOPS_DELIVERY_EXECUTION_PLAN.md`.

This document is intentionally operational. It tells the Windows operator what to prepare, which commands to run, which files prove success, and when to stop.

## Safety Rules

- Do not run `-RunLiveSubmit` until live readiness is `ready` and the test targets are explicitly authorized.
- Do not use production customer targets for first live acceptance.
- Default ReachOps behavior must remain dry-run/preflight. Real comment, follow, and DM submission must require:
  - `-RunLiveSubmit`
  - `-ConfirmAuthorizedTargets`
  - valid activation status
  - real profile IDs
  - explicit target URLs
- A claimed live success without local screenshot evidence and sidecar metadata is a failure; `evidence://...` is not valid evidence for real live-submit success.
- Live-submit sidecars must include `screenshot_sha256`, `action_type`, `profile_id`, `action_id`, and `current_url`. Comment sidecars must also include the submitted text and `comment_visible_confirmed=true`.

## Required Inputs

Fill these values before running live checks:

```powershell
$ProfileGroup = "BR"
$ProfileIds = "123,456,789"
$Target = "anti aging serum"
$CommentVideoUrl = "https://www.tiktok.com/@creator/video/123"
$FollowProfileUrl = "https://www.tiktok.com/@target_user"
$DmProfileUrl = "https://www.tiktok.com/@target_user"
$TargetUsername = "target_user"
$ActivationStatusPath = "C:\path\to\reachops_activation_status.json"
```

Recommended workflow:

```powershell
powershell -ExecutionPolicy Bypass -File tools\init_reachops_acceptance_inputs_windows.ps1
notepad tools\reachops_acceptance_inputs.local.ps1
powershell -ExecutionPolicy Bypass -File tools\reachops_acceptance_inputs.local.ps1
```

The local file is ignored by git. Keep real profile IDs, authorized targets, and activation paths out of source control.

The template runs readiness and preflight by default. It runs controlled live submit only if `$RunControlledLiveSubmit = $true`.

Profile requirements:

- Use numeric ixBrowser profile IDs.
- At least one profile must be logged into TikTok.
- Proxies must be healthy.
- The profiles must be allowed to open the test video and target profile.
- The target user/video must be low-risk and explicitly approved for testing.

Activation requirements:

Generate a local template first. This does not authorize live submit because the output contains `template_only: true`:

```powershell
python tools\reachops_activation_status_template.py `
  --bind-current-device `
  --enable-live-submit `
  --enable-comment-reply `
  --enable-follow-review `
  --enable-dm-review `
  --write `
  --output "$env:LOCALAPPDATA\ReachOps\config\reachops_activation_status.template.json"
```

```json
{
  "active": true,
  "template_only": false,
  "device_id": "must-match-current-device-when-bound",
  "expires_at": "2999-01-01T00:00:00Z",
  "license_tier": "enterprise",
  "capabilities": {
    "live_submit": true,
    "comment_reply": true,
    "follow_review": true,
    "dm_review": true
  }
}
```

Check the activation file before readiness or preflight:

```powershell
python tools\reachops_activation_status_check.py `
  --activation-status-path $ActivationStatusPath `
  --json
```

Check the whole live acceptance state without opening a browser:

```powershell
python tools\reachops_live_acceptance_status.py --json
```

Expected result:

- JSON contains `current_device_id`; use that value when preparing a device-bound activation file.
- JSON contains `ready = true` before controlled live submit.
- Validation manifests must show `activation_ready = true`; template-only or inactive activation files are blocked even when the file exists.
- Live acceptance status lists remaining gaps in `next_required_actions`; it is final proof only when `final_delivery_ready = true`.
- When an intermediate acceptance summary has pending items, `next_required_actions` expands them into concrete work: run readiness/preflight plus controlled live submit, complete `platform_selenium` live submit on authorized TikTok targets, and rerun the client delivery gate until `acceptance_ready=true` and `readiness=pass`.
- The client delivery gate can be rerun with `python tools\reachops_client_delivery_check.py --json`; final client acceptance requires `contract_ok=true`, `acceptance_ready=true`, `readiness=pass`, `failed_checks=[]`, and a persisted `latest_delivery_check.json` path in `delivery_check_path`.
- If blocked, fix `active`, `device_id`, `expires_at`, or the `live_submit/comment_reply/follow_review/dm_review` capabilities before continuing.

## Milestone 2: Windows Client Validation

Open PowerShell from the repository root:

```powershell
cd "C:\path\to\ReachOps"
```

Run UI startup smoke:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_reachops_ui_startup_smoke_windows.ps1
```

Expected result:

- Script exits successfully.
- UI process starts.
- Startup smoke JSON reports `status = ok`.
- Startup smoke JSON reports `process_running = true`.
- Startup smoke JSON reports `interactive_task = true`.

Build the Windows client:

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_reachops_windows.ps1 -Build "mvp-001"
```

Expected artifacts:

```text
dist\ReachOps\ReachOps.exe
dist\installer\ReachOps-Setup-0.4.0.exe
reachops-update-manifest.json
```

If Inno Setup is not installed, the script may skip installer generation. That is acceptable only for an intermediate validation run. It is not acceptable for final delivery.

Run full acceptance without live submit:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_reachops_acceptance_windows.ps1 `
  -InputFile .\tools\reachops_acceptance_inputs.local.ps1 `
  -ProfileGroup $ProfileGroup `
  -Target $Target `
  -AllowMissingInstaller
```

Expected result for this non-live pass:

- Acceptance summary status is `ready_for_external_validation`.
- Delivery audit has `failed = 0`.
- Operator pressure is `ok`.
- UI startup smoke is `ok`.
- Installer smoke is `ok` or `skipped_optional` only when `-AllowMissingInstaller` was intentionally used.
- Remaining pending items are real-platform validation only.

## Milestone 3: Live Readiness and Preflight

Run readiness without opening the browser:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_reachops_live_readiness_windows.ps1 `
  -ProfileGroup $ProfileGroup `
  -ProfileIds $ProfileIds `
  -CommentVideoUrl $CommentVideoUrl `
  -TargetProfileUrl $FollowProfileUrl `
  -TargetUsername $TargetUsername `
  -ActivationStatusPath $ActivationStatusPath `
  -ConfirmAuthorizedTargets
```

Expected result:

- `LIVE_READINESS_JSON` is printed.
- JSON contains `ready = true`.
- If blocked, JSON must explain why with explicit missing inputs or authorization/account errors.

Run preflight without submitting:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_reachops_live_preflight_windows.ps1 `
  -ProfileGroup $ProfileGroup `
  -ProfileIds $ProfileIds `
  -CommentVideoUrl $CommentVideoUrl `
  -TargetProfileUrl $FollowProfileUrl `
  -DmProfileUrl $DmProfileUrl `
  -TargetUsername $TargetUsername
```

Expected result:

- No comment/follow/DM is submitted.
- Login failures report `LOGIN_REQUIRED`.
- Captcha gates report `CAPTCHA_DETECTED`.
- Proxy failures report `PROXY_FAILED`.
- Missing page controls report explicit action-level errors.
- Evidence screenshots and sidecar files are written.
- At least one profile is usable for live acceptance.

Stop here if readiness is not `ready` or preflight cannot produce evidence.

## Milestone 4: Controlled Live Submit

Only run this after Milestone 3 passes and the target is approved.

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_reachops_acceptance_windows.ps1 `
  -InputFile .\tools\reachops_acceptance_inputs.local.ps1 `
  -RunLiveSubmit `
  -ConfirmAuthorizedTargets
```

Expected final result:

- `ACCEPTANCE_SUMMARY_JSON` is printed.
- Acceptance summary status is `passed`.
- `delivery_audit.effective_pending_external_validation = 0`.
- Goal status has no pending external validation.
- Live submit JSON exists.
- Comment, follow, and DM attempts have execution records.
- Successful live attempts have screenshot evidence and sidecar metadata.
- Failed live attempts have explicit error codes and evidence where possible.

Run the final package check:

```powershell
python tools\reachops_delivery_package_check.py --json
```

Expected result:

- Package check status is `passed`.
- `ReachOps.exe` exists and is non-empty.
- Installer exists and is non-empty.
- Update manifest exists.
- Manifest installer `sha256` matches the installer file.
- Acceptance summary verification passes.
- Required acceptance report JSON files exist.

Run the strict final acceptance gate:

```powershell
python tools\reachops_final_acceptance_gate.py --json
```

Expected result:

- Final gate status is `passed`.
- `final_delivery_ready` is `true`.
- `failed_checks` is empty.
- Client gate evidence includes `delivery_check_path`.
- Package gate evidence includes `artifacts` and `report_files`.

`tools\run_reachops_acceptance_windows.ps1` performs this as a strict sequence: bootstrap package check, final gate, write `final_acceptance_gate` back to `acceptance_summary.json`, package final evidence check, then final gate final evidence check. The bootstrap check is the only place that may use `--allow-missing-final-gate`; that interim package JSON is `bootstrap_only=true` and `final_delivery_ready=false`. The final evidence check must validate `final_acceptance_gate.json` before final delivery is accepted.

When recovering a background acceptance run, `tools\get_reachops_acceptance_background_status_windows.ps1 -Json` must show `final_delivery_ready=true` and an empty `final_delivery_blockers` list before the run can be treated as final delivery.

For an intermediate package before live submit, use:

```powershell
python tools\reachops_delivery_package_check.py --allow-external-pending --json
```

That command may return `ready_for_external_validation`. It is not final delivery.

## Failure Handling

If readiness fails:

- Fix missing profile IDs, target URLs, activation path, or confirmation flags first.
- Check ixBrowser profile IDs are numeric.
- Confirm the profiles are logged into TikTok.
- Confirm target URLs are reachable manually in the same profiles.

If preflight fails:

- Inspect generated screenshots and sidecar metadata.
- Separate account problems from target-page problems.
- Replace profiles that show login, captcha, or proxy failures.
- Do not proceed to live submit.

If live submit fails:

- Inspect `LIVE_SUBMIT_JSON`.
- Inspect `ACCEPTANCE_SUMMARY_JSON`.
- Verify whether failures are expected platform restrictions or implementation bugs.
- Do not rerun repeatedly against the same target if the failure is rate-limit or platform-risk related.

## Final Evidence Package

Collect these artifacts for final delivery:

```text
dist\ReachOps\ReachOps.exe
dist\installer\ReachOps-Setup-0.4.0.exe
reachops-update-manifest.json
reports\reachops_acceptance\<timestamp>\acceptance_summary.json
reports\reachops_acceptance\<timestamp>\goal_status_report.json
reports\reachops_acceptance\<timestamp>\delivery_audit_payload.json
reports\reachops_acceptance\<timestamp>\operator_pressure_payload.json
reports\reachops_acceptance\<timestamp>\activation_status_payload.json
reports\reachops_acceptance\<timestamp>\live_validation_manifest.json
reports\reachops_acceptance\<timestamp>\repository_cleanliness_payload.json
reports\reachops_acceptance\<timestamp>\windows_package_preflight.json
reports\reachops_acceptance\<timestamp>\live_readiness_payload.json
reports\reachops_acceptance\<timestamp>\live_preflight_payload.json
reports\reachops_acceptance\<timestamp>\live_submit_payload.json
reports\reachops_acceptance\<timestamp>\delivery_package_check.json
reports\reachops_acceptance\<timestamp>\final_acceptance_gate.json
reports\acceptance_remediation\latest_delivery_check.json
```

The project is fully delivered only when `acceptance_summary.json` says `passed`, the effective pending external validation count is zero, `tools\reachops_delivery_package_check.py --json` returns `passed`, the package `report_files` include `repository_cleanliness` and `windows_package_preflight`, and `tools\reachops_final_acceptance_gate.py --json` returns `passed` with `final_delivery_ready=true`.
