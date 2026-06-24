# ReachOps Delivery Execution Plan

This plan tracks the remaining work from the current MVP baseline to full client delivery.

The project is no longer in a broad feature-building phase. The priority is to freeze the working MVP, produce a Windows client artifact, and complete real-environment validation for ixBrowser and TikTok live submission.

## Delivery State

Current status:

- Stage 1: ReachOps MVP is implemented locally.
- Stage 2: Outreach plan MVP is implemented locally.
- Stage 3: Real execution is implemented behind authorization gates, but still needs external platform validation.
- Stage 4: AI/rules strategy enhancement is implemented locally.
- Stage 5: Standalone packaging has been validated in the Windows VM through build, installer, update manifest, installer smoke, and non-live acceptance. Final delivery still depends on real ixBrowser/TikTok external validation.

The project must not be called fully delivered until the Windows acceptance summary reaches `passed` with `effective_pending_external_validation = 0`.

## Milestone 1: Freeze MVP Baseline

Goal: confirm Stage 1, Stage 2, and Stage 4 are stable and form a regression baseline.

Deliverables:

- Stage 1 baseline:
  - Acquisition campaign creation.
  - Target recognition.
  - Audience persona generation.
  - Source planning.
  - Comment-user collection.
  - Dedupe.
  - Rule/AI-ready intent recognition.
  - Customer lead pool.
  - Current-campaign funnel.
  - CSV/JSON report export.
- Stage 2 baseline:
  - Comment action generation.
  - Follow action generation.
  - DM action generation.
  - Outreach templates.
  - Account assignment.
  - Execution preflight.
  - Failure reasons.
  - Action report export.
- Stage 4 baseline:
  - AI product analysis.
  - AI/rules audience persona.
  - AI/rules comment intent classification.
  - AI/rules outreach copy recommendation.
  - AI/rules source expansion.
  - Operator-editable strategy overrides.
- Initial git commit for the frozen baseline.
- Version recorded as `0.4.0` on the `mvp` channel unless a release decision changes it.

Validation commands:

```bash
python3 -m unittest tests.test_reachops_campaign
python3 tools/reachops_operator_pressure.py --json
python3 tools/reachops_delivery_audit.py --json
```

Acceptance criteria:

- Unit tests pass.
- Operator pressure status is `ok`.
- Delivery audit status is `ok`.
- Delivery audit has `0` failed checks.
- The only pending items are real-platform external validation items.

Current local evidence:

- `tests.test_reachops_campaign` passes locally.
- `reachops_operator_pressure.py --json` passes locally.
- `reachops_delivery_audit.py --json` passes locally with pending external validation for real platform submission.
- Initial baseline commit exists with subject `Freeze ReachOps MVP delivery baseline`; use `git log --oneline -1` for the current commit hash.

## Milestone 2: Windows Client Delivery Validation

Goal: prove ReachOps works as a standalone Windows client that can start, build, install, and preserve runtime data boundaries.

Required environment:

- Windows machine or Windows VM.
- Python.
- ixBrowser installed and reachable.
- Inno Setup installed for installer generation.
- Browser/runtime dependencies required by Selenium and ixBrowser.

Deliverables:

- UI startup smoke result.
- PyInstaller build artifact:
  - `dist\ReachOps\ReachOps.exe`
- Installer artifact:
  - `dist\installer\ReachOps-Setup-0.4.0.exe`
- Update manifest:
  - `reachops-update-manifest.json`
- Installer smoke result.

Validation commands:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_reachops_ui_startup_smoke_windows.ps1
powershell -ExecutionPolicy Bypass -File tools\build_reachops_windows.ps1
powershell -ExecutionPolicy Bypass -File tools\run_reachops_acceptance_windows.ps1
```

Acceptance criteria:

- UI launches.
- UI startup smoke reports a running interactive task.
- Windows build produces `ReachOps.exe`.
- Installer is generated or explicitly marked optional for a non-final validation run.
- Installer smoke passes.
- Runtime data is not written into the install directory.
- Independent config, data, logs, reports, and activation paths are preserved.
- Update manifest hash verification passes.

Current evidence:

- Windows VM build completed with `VersionInfoBuild: 1` for build `mvp-001`.
- `dist\ReachOps\ReachOps.exe` was generated.
- `dist\installer\ReachOps-Setup-0.4.0.exe` was generated.
- `dist\installer\reachops-update-manifest.json` was generated and hash-verified.
- Installer smoke returned `status=ok`, `exe_exists=true`, `data_in_install_dir=false`, and `hash_ok=true`.
- Non-live Windows acceptance wrote `reports\reachops_acceptance\20260624_190919\acceptance_summary.json` with status `ready_for_external_validation`.
- This milestone is complete for non-live Windows client delivery validation.

## Milestone 3: Real ixBrowser / TikTok Preflight

Goal: validate real account readiness without submitting comments, follows, or DMs.

Required environment:

- At least two or three real numeric ixBrowser profile IDs.
- Profiles are logged into TikTok.
- Proxies are working.
- One test video URL is reachable.
- One target profile URL is reachable.
- Message/profile pages are reachable where applicable.

Deliverables:

- Live readiness report.
- Live preflight report.
- Screenshot evidence and sidecar metadata for checked targets.
- Error-code coverage for unavailable accounts or blocked entry points.

Validation commands:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_reachops_live_readiness_windows.ps1 `
  -ProfileIds "123,456" `
  -CommentVideoUrl "https://www.tiktok.com/@creator/video/123" `
  -TargetProfileUrl "https://www.tiktok.com/@target_user" `
  -TargetUsername "target_user" `
  -ConfirmAuthorizedTargets

powershell -ExecutionPolicy Bypass -File tools\run_reachops_live_preflight_windows.ps1 `
  -ProfileIds "123,456" `
  -CommentVideoUrl "https://www.tiktok.com/@creator/video/123" `
  -FollowProfileUrl "https://www.tiktok.com/@target_user" `
  -DmProfileUrl "https://www.tiktok.com/@target_user" `
  -TargetUsername "target_user"
```

Acceptance criteria:

- At least one profile is ready.
- Login-required accounts are reported with `LOGIN_REQUIRED`.
- Captcha-gated accounts are reported with `CAPTCHA_DETECTED`.
- Proxy failures are reported with `PROXY_FAILED`.
- Missing comment/follow/DM entry points have explicit error codes.
- Preflight does not submit any real platform action.
- Evidence screenshots and sidecar files are generated.

Current evidence:

- Readiness and preflight scripts exist.
- Windows side currently has no `tools\reachops_acceptance_inputs.local.ps1`.
- `tools\run_reachops_live_readiness_windows.ps1` stops before opening a browser when `ProfileIds` is missing.
- With candidate profile IDs only, readiness stops before opening a browser because `CommentVideoUrl` is missing.
- This milestone still requires real ixBrowser profile IDs and authorized TikTok target evidence.

## Milestone 4: Controlled Real Execution Acceptance

Goal: complete Stage 3 by proving authorized real comments, follows, and DMs are controlled, limited, auditable, and protected by evidence requirements.

Required environment:

- Windows machine or VM.
- Real ixBrowser profiles.
- A valid activation status file.
- Low-risk authorized TikTok targets.
- Explicit operator confirmation.

Activation requirements:

- `active: true`
- Device binding matches the current machine.
- `live_submit: true`
- `comment_reply: true`
- `follow_review: true`
- `dm_review: true`
- Expiration is valid.

Validation command:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_reachops_acceptance_windows.ps1 `
  -ProfileIds "123,456" `
  -CommentVideoUrl "https://www.tiktok.com/@creator/video/123" `
  -FollowProfileUrl "https://www.tiktok.com/@target_user" `
  -DmProfileUrl "https://www.tiktok.com/@target_user" `
  -TargetUsername "target_user" `
  -ActivationStatusPath "C:\path\to\reachops_activation_status.json" `
  -RunLiveSubmit `
  -ConfirmAuthorizedTargets
```

Acceptance criteria:

- Acceptance summary status is `passed`.
- `effective_pending_external_validation = 0`.
- `真实 TikTok 平台提交` is no longer pending.
- Comment, follow, and DM attempts have execution records.
- Successful live actions have screenshot evidence and sidecar metadata.
- Missing evidence converts a claimed live success into a failure.
- Account failure triggers account switch where a replacement account is available.
- DM/follow failure can fall back to comment where policy allows.
- Rate limits, cooldown, and authorization failures are recorded with explicit error codes.

Current evidence:

- Local fixture validation proves authorization gate behavior and evidence enforcement.
- Real platform validation is still pending.

## Final Delivery Package

The final handoff should include:

- Source repository:
  - Initial commit exists.
  - Version is recorded.
  - `README.md`, `HANDOFF.md`, and this plan are current.
- Windows artifacts:
  - `ReachOps.exe`
  - Installer.
  - Update manifest.
- Validation reports:
  - Unit test output.
  - Operator pressure report.
  - Delivery audit report.
  - Windows acceptance summary.
  - Live readiness report.
  - Live preflight report.
  - Live submit report.
- Operator instructions:
  - How to start the app.
  - How to configure ixBrowser.
  - How to import activation.
  - How to run preflight.
  - How to enable real submit.
  - Safety statement that default behavior never submits real platform actions.

## Priority Order

1. Freeze and commit the current MVP baseline.
2. Run Windows UI, build, installer, and acceptance checks.
3. Run real ixBrowser readiness and preflight.
4. Run controlled live submit only after readiness passes and authorized targets are confirmed.
5. Mark the project fully delivered only after real platform pending validation reaches zero.
