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
- The latest non-live Windows acceptance report is `reports\reachops_acceptance\20260625_091523\acceptance_summary.json` on the Windows VM.
- The latest package check is `reports\reachops_acceptance\20260625_091523\delivery_package_check.json`, with `passed=true`, `status=ready_for_external_validation`, and `effective_pending_external_validation=2`.
- The latest acceptance package includes `live_acceptance_status_payload.json`, `activation_status_payload.json`, `live_validation_manifest.json`, `live_readiness_payload.json`, and `live_preflight_payload.json` as blocked/no-submit reports.
- Windows live validation can currently scan ixBrowser and select numeric profile IDs `27273`, `27240`, and `27230`.
- Live validation now checks activation readiness through the same activation gate used by readiness; `template_only` activation files are reported as blocked, not ready.
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
- Explicit operator confirmation: `-ConfirmAuthorizedTargets`; for final submit also `-RunLiveSubmit`.

Safe Windows next command pattern:

```powershell
Copy-Item tools\reachops_acceptance_inputs.example.ps1 tools\reachops_acceptance_inputs.local.ps1
notepad tools\reachops_acceptance_inputs.local.ps1
powershell -ExecutionPolicy Bypass -File tools\reachops_acceptance_inputs.local.ps1
```

`tools\reachops_acceptance_inputs.local.ps1` is ignored by git. Do not commit real profile IDs, target URLs, customer data, screenshots, evidence, logs, reports, or activation files.

Do not rely on historical logs or temporary Codex artifacts. They have been removed from this handoff.
