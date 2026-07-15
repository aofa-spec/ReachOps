# ReachOps Standalone Handoff

This directory is the clean standalone ReachOps development handoff.

Version baseline: `0.4.0` / `mvp`, tag `v0.4.0-mvp`.

Start here:

```text
HERMES_DEVELOPMENT_GUIDE.md
ReachOps/docs/REACHOPS_CLIENT_DELIVERY_PLAN.md
ReachOps/docs/REACHOPS_DELIVERY_EXECUTION_PLAN.md
ReachOps/docs/REACHOPS_GOAL_MODE_EXECUTION.md
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
python3 tools/reachops_goal_delivery_runner.py --json
python3 tools/reachops_goal_status_report.py --json
```

Current delivery boundary:

- Stage 1 ReachOps MVP is implemented and passing: campaign creation, target recognition, persona, source planning, content/comment-user collection, dedupe, lead scoring, campaign funnel, and CSV/JSON export.
- The operator architecture is web-first and covered by delivery audit: operators use the unified Web UI, the local HTTP API handles `/api/start`, `/api/logs`, `/api/snapshot`, `/api/acceptance`, and `/api/control`, the server launches the headless service layer, and collection/outreach acquire ixBrowser profiles through `IxBrowserLocalAdapter` plus Selenium.
- Stage 2 outreach MVP is implemented and passing: action generation, templates, account assignment path, preflight, failure reasons, and action reports.
- Stage 4 AI/rules enhancement is implemented and passing: product analysis, audience persona, intent classification, copy/source recommendation, fallback rules, and editable strategy.
- Stage 5 standalone packaging is implemented and passing for the non-live path.
- Stage 3 is implemented locally for authorization gates, rate/cooldown behavior, account switch, fallback comment, and evidence enforcement, but real TikTok platform submission remains pending external validation.
- PM goal-mode status is authoritative through `tools\reachops_goal_delivery_runner.py --json`. Its `delivery_boundary` is the first field to read: `local_mvp_scope_ready=true` means Mac local MVP can be accepted, while `overall_final_delivery_scope_ready=false` means the whole project is not final-delivered. The top-level `blocking_scope_count` must match `delivery_boundary.blocking_scopes` so support can quickly confirm how many scopes still block acceptance.
- The same goal report exposes `deliverable_index`: current expected state is `web_operator_panel.ready=true`, `local_mvp_acceptance.ready=true`, `windows_build_inputs.ready=true`, but `windows_final_package.ready=false`, `authorized_live_submit.ready=false`, and `final_acceptance_gate.ready=false`. Do not treat a single child gate's `final_delivery_ready=true` as whole-project final delivery.
- Historical Windows client delivery validation exists for the non-live path, but it is not current final-delivery evidence for this worktree. The current `/Users/aofa/Documents/New project` checkout has Windows `dist\ReachOps\ReachOps.exe`, `dist\installer\ReachOps-Setup-0.4.0.exe`, and `dist\installer\reachops-update-manifest.json`, but still has no local final `reports\reachops_acceptance\*\acceptance_summary.json`.
- The current local final package check returns `status=failed`, `final_delivery_ready=false`, with `missing_artifacts=["acceptance_summary"]` and failures `["acceptance_summary_missing","acceptance_summary_not_passed"]`. Treat this as authoritative until Windows acceptance regenerates a passed summary into the current repo.
- Historical Windows evidence from 2026-06-26 may be useful for diagnosis only: build `m2-current-20260626`, acceptance report `reports\reachops_acceptance\20260626_133256\acceptance_summary.json`, package status `ready_for_external_validation`, `effective_pending_external_validation=3`, and pending `external_platform_validation`, `live_preflight_environment_validation`, plus the client delivery acceptance gate.
- Final delivery must also include `windows_package_preflight.json`, `issue_closure_payload.json`, `final_acceptance_gate.json`, and a strict `delivery_package_check.json` that validates all required report files. `--allow-missing-final-gate` is only for the Windows acceptance script bootstrap pass before `final_acceptance_gate.json` exists; that JSON is `bootstrap_only=true` and `final_delivery_ready=false`, so it is not a final delivery standard.
- Final delivery requires `tools\reachops_issue_closure_audit.py --json` to have zero external closure pending and `tools\reachops_final_acceptance_gate.py --json` to return `status=passed`, `final_delivery_ready=true`, `failed_checks=[]`, including `commercial_issue_closure:closed`.
- The client delivery gate must persist `latest_delivery_check.json`; `delivery_check_path` is part of the acceptance evidence, including the `/api/acceptance` Web UI path.
- The latest acceptance package includes `live_acceptance_status_payload.json`, `activation_status_payload.json`, `live_validation_manifest.json`, `live_readiness_payload.json`, and `live_preflight_payload.json` as blocked/no-submit reports.
- The skincare/beauty keyword-list customer promotion target has been validated through the non-live client flow; beauty-social terms such as `skintok`, `glassskin`, and `skinbarrier` now resolve to the beauty acquisition strategy instead of the generic strategy.
- Windows live validation can currently scan ixBrowser and select numeric profile IDs `27273`, `27240`, and `27230`.
- Live validation now checks activation readiness through the same activation gate used by readiness; `template_only` activation files are reported as blocked, not ready.
- The current local checkout intentionally does not include `tools\reachops_acceptance_inputs.local.ps1`; it is git-ignored because it contains environment-specific authorized targets and activation paths. On Windows, create it with `tools\init_reachops_acceptance_inputs_windows.ps1`, then replace every placeholder with authorized real TikTok targets before final validation.
- Windows activation template exists at `C:\Users\aofa\AppData\Local\ReachOps\config\reachops_activation_status.template.json` for device `1d3a691ec71f6a3356d1414ad8540f3e`. It is intentionally `template_only=true` and `active=false`; live submit remains blocked until a real activation status JSON replaces it.
- The latest no-browser readiness report is `reports\reachops_live_readiness\20260626_122513\live_readiness_payload.json`; it is blocked only by the template activation file, with `LIVE_SUBMIT_NOT_AUTHORIZED`, `no_browser_started=true`, and `no_submit=true`.
- The latest acceptance preflight report is `reports\reachops_acceptance\20260626_133256\live_preflight_payload.json`; it reached real ixBrowser profile startup for `27273`, `27240`, and `27230`, submitted nothing, and all profiles failed with `PROFILE_START_FAILED` because ixBrowser returned `Proxy detection failed: Connection Error: Socks5 Authentication failed`; `environment_diagnostics.blocking_stage=ixbrowser_open_profile`, `ready_profile_ids=[]`, and classifications include `socks5_auth_failed`, `proxy_detection_failed`, and `legacy_adapter_missing`.
- The latest standalone no-submit live preflight report is `reports\reachops_live_preflight\20260626_124345\live_preflight_payload.json`. It includes `environment_diagnostics` with `blocking_stage=ixbrowser_open_profile`, `failed_profile_ids=["27230","27240","27273"]`, four real `open_profile` failures, two account switches, and classifications `socks5_auth_failed`, `proxy_detection_failed`, and `legacy_adapter_missing`. It also generated local JSON evidence sidecars and kept `no_submit=true`.
- The Windows VM was resumed and reachable again on 2026-06-26; the verified no-submit acceptance run above used the skincare/beauty keyword-list target and explicit Profile IDs `27273,27240,27230`.
- Background acceptance recovery is verified through Windows ScheduledTask. Use `tools\start_reachops_acceptance_background_windows.ps1 -InputFile .\tools\reachops_acceptance_inputs.local.ps1` to launch acceptance input parsing safely and `tools\get_reachops_acceptance_background_status_windows.ps1 -RunDir <latest reports\reachops_acceptance_background\timestamp> -Json` to recover task state, log tails, `acceptance_summary.json` verification, `delivery_package_check`, `required_package_report_files`, `missing_package_report_files`, `windows_package_preflight`, `issue_closure`, `final_delivery_ready`, `final_delivery_blockers`, and `verification_commands` after reconnecting. A non-final package surfaces as `delivery_package_check_not_final_ready`; a missing or failed build preflight surfaces as `windows_package_preflight_missing` or `windows_package_preflight_not_ready`; incomplete Issues #1-#7 closure evidence surfaces as `issue_closure_not_closed` or `issue_closure_report_missing`; incomplete final package evidence surfaces as `<report>_report_missing` and non-JSON output prints `MISSING_PACKAGE_REPORT_FILES=...`.
- Remote sync validation now runs `tools\reachops_issue_closure_audit.py --json` and `tools\reachops_final_acceptance_gate.py --json` during `tools\sync_reachops_to_windows_vm.sh --run-tests`, writes `reachops_issue_closure_sync.json` and `reachops_final_acceptance_gate_sync.json`, and prints `SYNC_ISSUE_CLOSURE_STATUS`, `SYNC_FINAL_ACCEPTANCE_GATE_STATUS`, plus `SYNC_FINAL_DELIVERY_READY`.
- To summarize the current Milestone 3/4 blocker without opening a browser or submitting actions, run `python tools\reachops_live_environment_blocker_report.py --acceptance-summary reports\reachops_acceptance\20260626_133256\acceptance_summary.json --json`. The report now includes package `final_delivery_ready` / `bootstrap_only` details and emits a `final_delivery_package` blocker when package evidence is not final-ready. The current report is `status=blocked`, `milestone3_status=blocked`, `milestone4_status=blocked`, `ready_profile_ids=[]`, `failed_profile_ids=["27230","27240","27273"]`, and `blocking_stage=ixbrowser_open_profile`.
- To inspect selected ixBrowser profile/group/proxy metadata without opening a browser or submitting actions, run `python tools\reachops_ixbrowser_profile_metadata_report.py --profile-ids 27273,27240,27230 --json`. The report only calls list APIs, sets `safe_read_only=true`, and redacts proxy/account secrets by default.
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
