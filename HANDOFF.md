# ReachOps Standalone Handoff

This directory is the clean standalone ReachOps development handoff.

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
```

Current delivery boundary:

- Stage 1/2 MVP is the active baseline: campaign creation, target recognition, source planning, comment-user collection, lead scoring, action generation, preflight, funnel, and report export.
- Real comment/follow/DM submission is stage 3 and must remain behind explicit authorization and evidence capture.
- Windows client delivery validation is complete for the non-live path: build, `ReachOps.exe`, installer, update manifest, installer smoke, UI startup smoke, and package check have passed in the Windows VM.
- The latest non-live Windows acceptance report is `reports\reachops_acceptance\20260624_190919\acceptance_summary.json` on the Windows VM and remains `ready_for_external_validation` because real TikTok submission is intentionally pending.
- Default client behavior must not submit real platform actions.
- GUI is mandatory for client delivery. If the local environment lacks Tkinter, continue headless core development and validate GUI in Windows VM or another Tkinter-capable environment.
- The next delivery focus is not UI decoration or broad feature expansion. Follow `ReachOps/docs/REACHOPS_DELIVERY_EXECUTION_PLAN.md`: run real ixBrowser/TikTok readiness and preflight, then run controlled live submit only after authorization and target confirmation.

Do not rely on historical logs or temporary Codex artifacts. They have been removed from this handoff.
