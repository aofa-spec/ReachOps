# Hermes Development Guide for ReachOps

This guide is for the next agent continuing ReachOps development.

ReachOps is a standalone customer-acquisition client. The product goal is not to build isolated modules. The goal is that an operator can open the client, enter a target, choose an ixBrowser group, click start, and get customer leads plus outreach actions with clear logs and exportable reports.

## 1. Start Here

Read these files in order:

```text
HANDOFF.md
ReachOps/docs/REACHOPS_CLIENT_DELIVERY_PLAN.md
ReachOps/docs/REACHOPS_DELIVERY_EXECUTION_PLAN.md
ReachOps/docs/REACHOPS_WINDOWS_LIVE_ACCEPTANCE_RUNBOOK.md
HERMES_DEVELOPMENT_GUIDE.md
```

Main project directory:

```text
/Users/aofa/Documents/New project
```

Do not assume `/Users/aofa/projects/IntelliOps/ReachOps` is current. At the time of this handoff, the clean standalone project is under `/Users/aofa/Documents/New project`.

## 2. Current Delivery Status

Current baseline:

- Stage 1/2 MVP is the active baseline.
- Campaign creation, target recognition, audience/persona generation, source planning, comment-user collection, lead scoring, outreach action generation, preflight, funnel, and report export exist.
- The client defaults to preflight mode. It must not submit real comments, follows, or DMs unless stage 3 authorization is explicitly enabled and verified.
- Stage 3 real execution still requires external platform validation with evidence.

Do not mark the project fully delivered until real authorized comment/follow/DM execution, account failover, fallback comment behavior, limits, cooldown, and evidence are verified.

The active plan is `ReachOps/docs/REACHOPS_DELIVERY_EXECUTION_PLAN.md`. Use it as the delivery checklist from the current MVP baseline to final client handoff.

## 3. GUI Requirement

The GUI is mandatory. ReachOps is a client product, not only a headless automation library.

The GUI must support:

- Operator-friendly landing page named `获客任务`.
- Target input with automatic target recognition.
- ixBrowser group refresh and selection.
- Start acquisition.
- Report export.
- Real automatic acquisition plan display.
- Current-campaign funnel.
- Quant-style execution terminal.
- Lead pool.
- Outreach actions.
- Account diagnostics.
- Error diagnostics.

The GUI must not show confusing technical language to normal operators, such as:

- `source_type`
- `campaign_id`
- `datasource`
- `candidate_user`
- `checkpoint`

The GUI may contain technical IDs inside logs or diagnostics only when they are needed for debugging.

## 4. Tkinter / No-GUI Environment Policy

Some environments do not have Tkinter. If `import tkinter` fails, this does not block core development.

In a no-GUI environment, continue developing and testing:

- `ReachOps/intelligence/source_planner.py`
- `ReachOps/intelligence/service.py`
- `ReachOps/intelligence/growth_task_router.py`
- `ReachOps/intelligence/comment_intent.py`
- `ReachOps/intelligence/candidate_user_scorer.py`
- `ReachOps/intelligence/operation_lead_manager.py`
- `ReachOps/workbench/workflow_service.py`
- `ReachOps/workbench/profile_preflight.py`
- `ReachOps/workbench/action_router.py`
- collectors under `ReachOps/collectors/`
- tests under `tests/`
- scripts under `tools/`

Do not conclude that GUI is unnecessary because the current environment is headless.

GUI work must be validated in one of these environments:

- Windows VM with Tkinter.
- Local Python with Tkinter.
- A packaged Windows build.

If no GUI runtime is available, continue headless development and leave a clear note that GUI visual acceptance is pending.

## 5. Primary Commands

From project root:

```bash
cd "/Users/aofa/Documents/New project"
```

Run core regression tests:

```bash
python3 -m unittest tests.test_reachops_campaign
```

Run operator pressure flow:

```bash
python3 tools/reachops_operator_pressure.py --json
```

Run a targeted source-planning check:

```bash
python3 -m unittest tests.test_reachops_campaign.ReachOpsCampaignTests.test_amazon_product_link_becomes_executable_social_search_sources
```

Start GUI when Tkinter is available:

```bash
python3 ReachOpsApp.py
```

or:

```bash
python3 -m ReachOps
```

Windows VM start script:

```powershell
tools/start_reachops_ui_windows.ps1
```

## 6. Current Product Flow

The intended operator flow:

```text
Input target
  -> recognize target type
  -> create AcquisitionCampaign
  -> create AudiencePersona
  -> create SourcePlanner output
  -> display automatic acquisition plan
  -> select ixBrowser group
  -> profile preflight
  -> scan TikTok search/hashtag/creator/video/live sources
  -> collect comment users
  -> dedupe users
  -> classify intent
  -> score leads
  -> generate operation leads
  -> generate comment/follow/DM actions
  -> run action preflight
  -> show current campaign funnel
  -> export JSON/CSV
```

## 7. Source Planning Requirement

Source planning must behave like an acquisition funnel, not a simple scraper.

For a product target, the planner should generate layered sources:

- Core product keyword.
- Review keyword.
- Before/after or effect keyword where relevant.
- Usage scenario keyword.
- TikTok Shop / shopping context keyword.
- Product hashtag.
- Industry hashtags.
- Future: competitor creator/source expansion.

Example input:

```text
https://www.amazon.com/Retinol-Anti-Aging-Face-Serum/dp/B0ABC12345
```

Expected planned sources:

```text
keyword: Retinol Anti Aging Face Serum
keyword: Retinol Anti Aging Face Serum review
keyword: Retinol Anti Aging Face Serum before after
keyword: Retinol Anti Aging Face Serum routine
keyword: Retinol Anti Aging Face Serum tiktok shop
hashtag: retinolantiagingface
```

The automatic acquisition plan panel must explain:

- Recognition result.
- Promotion object.
- Execution path.
- Acquisition sources.
- Source layers.
- Range settings.
- Intent keywords.
- Exclusion rules.

## 8. ixBrowser Group Requirement

Group refresh must read real ixBrowser groups.

Acceptance requirements:

- Refresh shows full group list.
- Display includes readable name, group ID, and account count or pending count.
- Selection must use the actual selected group.
- Selecting Canada must execute Canada profiles, not a cached/default group.
- API empty response must not clear previously successful group data.
- Login-required, captcha, proxy-failed, and start-failed profiles must be identified and excluded or marked.

Relevant files:

```text
ReachOps/workbench/standalone_app.py
ReachOps/workbench/profile_preflight.py
ReachOps/adapters/ix_profile_group_manager.py
```

## 9. GUI Acceptance Checklist

Validate on Windows VM or Tkinter environment:

- Client launches without error.
- Window default size shows all key controls.
- Header tabs are readable.
- Start page is `获客任务`.
- Target input is visible.
- Account group combobox displays full group names.
- Refresh group button actually reloads ixBrowser groups.
- Current group label updates.
- Acquisition range controls are visible and real.
- Automatic acquisition plan updates after start.
- Start acquisition writes logs immediately.
- Funnel shows current Campaign only.
- Terminal has staged logs.
- Double-click terminal opens fullscreen log view.
- Export button exports current Campaign only.
- Errors enter terminal/log table, not blocking popups.

## 10. Headless Acceptance Checklist

Validate in no-GUI environments:

- Campaign can be created from product keyword.
- Campaign can be created from product URL.
- Amazon link extracts product name.
- SourcePlanner outputs layered acquisition sources.
- Collection can run with fixture collectors.
- Candidate users are generated.
- Leads are scored.
- Actions are generated.
- Preflight can run with fake/profile fixtures.
- JSON/CSV export works.
- Repeated collection does not duplicate already handled video/user data.
- Pressure script completes.

## 11. Stage 3 Real Execution Boundary

Real execution is not complete unless all are true:

- Operator explicitly enables real execution.
- Action review is approved.
- Profile preflight passes.
- Rate limits pass.
- Authorization gate passes.
- Real comment/follow/DM result is recorded.
- Evidence path exists.
- Failure can switch profile.
- DM/follow failure can fallback to comment.
- Cooldown works after repeated account failures.

Do not remove the authorization gate to make tests easier.

## 12. Files Most Likely To Change Next

GUI:

```text
ReachOps/workbench/console.py
ReachOps/workbench/standalone_app.py
ReachOps/workbench/view_models.py
```

Planning and strategy:

```text
ReachOps/intelligence/source_planner.py
ReachOps/intelligence/ai_strategy.py
ReachOps/intelligence/service.py
```

Collection:

```text
ReachOps/intelligence/growth_task_router.py
ReachOps/collectors/tiktok_search_collector.py
ReachOps/collectors/tiktok_topic_content_collector.py
ReachOps/collectors/tiktok_comment_collector.py
```

Leads and actions:

```text
ReachOps/intelligence/comment_intent.py
ReachOps/intelligence/candidate_user_scorer.py
ReachOps/intelligence/operation_lead_manager.py
ReachOps/workbench/action_router.py
ReachOps/workbench/workflow_service.py
```

Validation:

```text
tests/test_reachops_campaign.py
tools/reachops_operator_pressure.py
tools/reachops_visual_collection_preflight.py
```

## 13. Immediate Next Tasks

Recommended order:

1. Finish GUI acceptance pass in Windows VM.
2. Confirm the automatic acquisition plan panel is readable after entering product link/keyword.
3. Confirm account group refresh and selected group execution with real ixBrowser group.
4. Confirm current-campaign funnel does not mix historical data.
5. Confirm action generation and preflight remain visible in the client.
6. Add or fix tests for any GUI-linked behavior that can be tested headlessly.
7. Only then proceed to stage 3 authorized real execution.

## 14. What Not To Do

Do not:

- Treat no Tkinter as a reason to skip GUI development.
- Replace GUI acceptance with only unit tests.
- Claim final delivery before authorized real execution is verified.
- Remove safety gates for comment/follow/DM.
- Reintroduce popup error dialogs that block the operator.
- Use stale `/Users/aofa/projects/IntelliOps/ReachOps` as the source of truth unless it has been explicitly synced.

## 15. Current Clean Handoff Directory

The clean handoff directory should contain:

```text
ReachOps/
tests/
tools/
ico/
README.md
HANDOFF.md
HERMES_DEVELOPMENT_GUIDE.md
requirements.txt
GrowthIntelligenceApp.py
ReachOpsApp.py
```

Temporary logs, `.codex-tmp`, `.DS_Store`, `__pycache__`, and `.pyc` files should not be part of the handoff.
