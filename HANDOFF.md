# ReachOps Standalone Handoff

This directory is the clean standalone ReachOps development handoff.

Version baseline: `0.4.0` / `mvp`, tag `v0.4.0-mvp`.

Start here:

```text
HERMES_DEVELOPMENT_GUIDE.md
ReachOps/docs/REACHOPS_CLIENT_DELIVERY_PLAN.md
ReachOps/docs/REACHOPS_DELIVERY_EXECUTION_PLAN.md
ReachOps/docs/REACHOPS_WINDOWS_LIVE_ACCEPTANCE_RUNBOOK.md
```

Project layout:

```text
ReachOps/        application code
tests/           regression tests
tools/           smoke, pressure, VM, and packaging scripts
requirements.txt Python dependencies
HERMES_DEVELOPMENT_GUIDE.md next-agent development instructions
README.md        basic project notes
```

Primary validation commands:

```bash
python3 -m unittest tests.test_reachops_campaign
python3 tools/reachops_operator_pressure.py --json
python3 tools/reachops_delivery_audit.py --json
python3 tools/reachops_goal_status_report.py --json
```

Current delivery boundary:

- Stage 1 ReachOps MVP is implemented and passing: campaign creation, target recognition, persona, source planning, content/comment-user collection, dedupe, lead scoring, campaign funnel, and CSV/JSON export.
- Stage 2 outreach MVP is implemented and passing: action generation, templates, account assignment path, preflight, failure reasons, and action reports.
- Stage 4 AI/rules enhancement is implemented and passing: product analysis, audience persona, intent classification, copy/source recommendation, fallback rules, and editable strategy.
- Stage 5 standalone packaging is implemented and passing for the non-live path.
- Stage 3 is implemented locally for authorization gates, rate/cooldown behavior, account switch, fallback comment, and evidence enforcement, but real TikTok platform submission remains pending external validation.
- Windows client delivery validation is complete for the non-live path: build, `ReachOps.exe`, installer, update manifest, installer smoke, UI startup smoke, and package check have passed in the Windows VM.
- The latest Windows rebuild completed on 2026-06-26 with build `m2-current-20260626`; `dist\ReachOps\ReachOps.exe`, `dist\installer\ReachOps-Setup-0.4.0.exe`, and `dist\installer\reachops-update-manifest.json` exist, and installer smoke returned `status=ok`, `hash_ok=true`, `data_in_install_dir=false`.
- The latest Windows acceptance report is `reports\reachops_acceptance\20260626_123159\acceptance_summary.json` on the Windows VM.
- The latest package check is `reports\reachops_acceptance\20260626_123159\delivery_package_check.json`, with `passed=true`, `status=ready_for_external_validation`, `effective_pending_external_validation=2`, and pending `live_preflight_environment_validation` because all selected ixBrowser profiles currently fail proxy authentication.
- The latest acceptance package includes `live_acceptance_status_payload.json`, `activation_status_payload.json`, `live_validation_manifest.json`, `live_readiness_payload.json`, and `live_preflight_payload.json` as blocked/no-submit reports.
- The skincare/beauty keyword-list customer promotion target has been validated through the non-live client flow; beauty-social terms such as `skintok`, `glassskin`, and `skinbarrier` now resolve to the beauty acquisition strategy instead of the generic strategy.
- Windows live validation can currently scan ixBrowser and select numeric profile IDs `27273`, `27240`, and `27230`.
- Live validation now checks activation readiness through the same activation gate used by readiness; `template_only` activation files are reported as blocked, not ready.
- Windows `tools\reachops_acceptance_inputs.local.ps1` has been prepared with Profile IDs `27273,27240,27230` and the skincare/beauty keyword-list target. `CommentVideoUrl`, `FollowProfileUrl`, `DmProfileUrl`, and `TargetUsername` currently contain sample placeholder targets (`creator/video/123`, `target_user`) and must be replaced with authorized real targets before final validation.
- Windows activation template exists at `C:\Users\aofa\AppData\Local\ReachOps\config\reachops_activation_status.template.json` for device `1d3a691ec71f6a3356d1414ad8540f3e`. It is intentionally `template_only=true` and `active=false`; live submit remains blocked until a real activation status JSON replaces it.
- The latest no-browser readiness report is `reports\reachops_live_readiness\20260626_122513\live_readiness_payload.json`; it is blocked only by the template activation file, with `LIVE_SUBMIT_NOT_AUTHORIZED`, `no_browser_started=true`, and `no_submit=true`.
- The latest no-submit live preflight report is `reports\reachops_acceptance\20260626_123159\live_preflight_payload.json`; it reached real ixBrowser profile startup for `27273`, `27240`, and `27230`, submitted nothing, and all profiles failed with `PROFILE_START_FAILED` because ixBrowser returned `Proxy detection failed: Connection Error: Socks5 Authentication failed`. Account switch evidence and local JSON evidence sidecars were generated under `reports\reachops_acceptance\20260626_123159\live_preflight\evidence\preflight`. Future preflight and acceptance summaries include `environment_diagnostics` so this blocker is classified per profile as `ixbrowser_open_profile` with `socks5_auth_failed`/`proxy_detection_failed` instead of only appearing as generic action failure.
- Default client behavior must not submit real platform actions.
- If TikTok shows a login/signup dialog or forced login page after an ixBrowser Profile opens, treat that account as `LOGIN_REQUIRED` immediately. Do not continue discovery, collection, comment scan, or customer acquisition with that Profile.
- GUI is mandatory for client delivery. If the local environment lacks Tkinter, continue headless core development and validate GUI in Windows VM or another Tkinter-capable environment.
- The next delivery focus is not UI decoration or broad feature expansion. Follow `ReachOps/docs/REACHOPS_DELIVERY_EXECUTION_PLAN.md`: run real ixBrowser/TikTok readiness and preflight, then run controlled live submit only after authorization and target confirmation.

Remaining external inputs before live readiness can pass:

- Authorized TikTok video URL for comment preflight/submit.
- Authorized TikTok profile URL for follow.
- Authorized TikTok profile URL or message entry for DM.
- Target username matching the authorized profile URLs.
- Activation status JSON with `active=true`, current device binding, and `live_submit`, `comment_reply`, `follow_review`, `dm_review` enabled.
- Working proxy/SOCKS5 credentials on the selected ixBrowser profiles; current profiles fail before page checks with `PROFILE_START_FAILED`.
- Explicit operator confirmation: `-ConfirmAuthorizedTargets`; for final submit also `-RunLiveSubmit`.

Safe Windows next command pattern:

```powershell
notepad tools\reachops_acceptance_inputs.local.ps1
powershell -ExecutionPolicy Bypass -File tools\reachops_acceptance_inputs.local.ps1
```

`tools\reachops_acceptance_inputs.local.ps1` is ignored by git. Do not commit real profile IDs, target URLs, customer data, screenshots, evidence, logs, reports, or activation files.

Do not rely on historical logs or temporary Codex artifacts. They have been removed from this handoff.
