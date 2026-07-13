# ReachOps Phase 2 Windows And Authorized Outreach Handoff

## Current Status

Mac local MVP is accepted. Final customer delivery is still pending.

Current final blockers:

- Windows final artifacts are missing.
- Authorized live submit evidence is missing.
- `acceptance_summary.json` is missing.
- Final acceptance gate is not ready.

Current safe handoff package:

- `reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_reachops_authorization_handoff.zip`
- Verification status: passed.
- Sensitive local files are excluded.

Current handoff readiness command:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_phase2_handoff_check.py --write --json
```

Current expected status before Windows execution is `ready_for_windows_execution`. This means the Mac-side handoff and Windows build inputs are prepared. It does not mean authorized live submit or final customer delivery is complete.

## Phase 2 Objective

Phase 2 signs off the final customer delivery, not the Mac MVP. It must prove:

- Windows `ReachOps.exe` exists and is a valid executable.
- Windows installer exists and is valid.
- Update manifest exists.
- Windows acceptance summary exists and passes.
- Authorized TikTok live submit evidence exists.
- Final gate reports `final_delivery_ready=true` and `failed_checks=[]`.

## Windows Build Steps

Run on a Windows machine with Python 3.11, PyInstaller dependencies, and Inno Setup 6 installed:

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_reachops_windows.ps1
```

Required output artifacts:

- `dist\ReachOps\ReachOps.exe`
- `dist\installer\ReachOps-Setup-0.4.0.exe`
- `dist\installer\reachops-update-manifest.json`

`-SkipInstaller` is not final delivery. It is only a non-final local build shortcut.

## Authorized Acceptance Inputs

Initialize the local input file:

```powershell
powershell -ExecutionPolicy Bypass -File tools\init_reachops_acceptance_inputs_windows.ps1 -Json
```

Then edit:

```text
tools\reachops_acceptance_inputs.local.ps1
```

Required fields:

- `ProfileIds`: numeric ixBrowser profile IDs approved for live validation.
- `CommentVideoUrl`: authorized TikTok video URL.
- `FollowProfileUrl`: authorized TikTok user profile URL.
- `DmProfileUrl`: authorized TikTok user profile URL for DM validation, if required.
- `TargetUsername`: authorized target username.
- `ActivationStatusPath`: path to a real activation status JSON with ready state.
- `ConfirmAuthorizedTargets`: `$true` only after all targets and copy are authorized.

Do not place real authorization values in the repository template.

## Live Acceptance Readiness

Before live submit, run:

```powershell
python tools\reachops_live_acceptance_status.py --local-inputs-path tools\reachops_acceptance_inputs.local.ps1 --write-report --json-report-path --json
```

Required ready state:

- local inputs usable.
- activation ready.
- authorized targets confirmed.
- profile IDs present.
- authorized target URLs present.

## Authorized Live Submit

Only after the readiness command is clean, run:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_reachops_acceptance_windows.ps1 -InputFile tools\reachops_acceptance_inputs.local.ps1 -RunLiveSubmit -ConfirmAuthorizedTargets
```

Required evidence:

- screenshot evidence for submitted action.
- sidecar metadata.
- `submitted_text`.
- `comment_visible_confirmed=true` for comment validation.
- `acceptance_summary.json` with status passed.

## Final Verification

Run:

```powershell
python tools\reachops_phase2_handoff_check.py --write --json
python tools\reachops_delivery_package_check.py --json
python tools\reachops_final_acceptance_gate.py --json
python tools\reachops_two_phase_acceptance_matrix.py --refresh --write --require-final --json
```

Final delivery is accepted only when:

- `final_delivery_ready=true`
- `failed_checks=[]`
- no pending external validation
- Windows artifacts are present
- authorized live submit evidence is present

## Current Mac Evidence

The Mac MVP pass is based on:

- batch: `gb_d2928a2643d64aba`
- selected group: `United States`
- candidates: 3
- preflight actions: 3
- preflight success: 3
- no-submit safety: `no_submit=true`

This proves the local Web controlled execution chain. It does not replace the Windows final package or authorized live submit evidence.
