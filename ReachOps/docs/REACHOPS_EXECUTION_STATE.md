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
| P2 | Windows local security, licensing, backup, device seats | `PLANNED` | Product contract locked | Windows Credential Manager, minimal license client, 7-day grace, encrypted backup/restore, tests |
| P3 | Public comment-reply monitoring and lead lifecycle | `PLANNED` | Product contract locked | Automatic public reply detection; action linkage; qualified-lead state; manual conversion/revenue capture |
| P4 | Bilingual UI, installer, update, Windows acceptance | `IN_PROGRESS` | Branch `codex/p4-operator-controls-ui-mapping` makes customer-visible operator controls map to execution evidence. Windows installer/update/live acceptance remain incomplete | Win10/11 installer, zh-CN/en-US UI, update flow, acceptance matrix, authorized live evidence |
| P5 | DM inbox monitoring | `DEFERRED` | Explicitly deferred behind public reply monitoring | Separate privacy/evidence contract and acceptance after P3/P4 |

## Next autonomous action

1. Review PR #10 evidence-truthfulness correction and merge only after accepting the known non-P0 baseline failures separately.
2. Do not expand PR #10 with P1.
3. After P0 merges, start P1 on a separate branch/PR:
   - add `campaign_runs`
   - add `source_observations`
   - add `content_observations`
   - add `comment_observations`
   - add `candidate_observations`
   - add versioned `lead_decisions`
   - keep existing global entities for compatibility
   - scope scoring and lead creation to run/batch observations
   - add idempotent migration and rollback evidence
   - add cross-campaign isolation tests

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

## Non-blocking engineering work available

- P1 observation model and migration.
- LeadDecision versioning and unified scoring contract.
- Follow/DM evidence validators in no-submit fixtures.
- Windows Credential Manager abstraction and unit tests.
- Encrypted backup format and restore tests.
- License state machine and 7-day grace logic.
- Localization resource extraction for `zh-CN` and `en-US`.
- Public reply-monitor parser using redacted/replay fixtures.

## Latest P4 operator-control UI verification snapshot

- Date: `2026-07-19`
- Branch: `codex/p4-operator-controls-ui-mapping`
- Draft PR: #18 `ReachOps P4: expose operator execution controls`
- Commit: latest branch head plus local PR #18 client-entry update; records operator controls, browser adapter binding, run-session checkpointing, and local-client-console entrypoint convergence.
- Scope: P4 local operator UI control visibility only. No Windows package, EXE, installer, ixBrowser runtime, or TikTok live-submit work was performed.
- Code evidence:
  - `ReachOps/workbench/console.py` now exposes customer-visible labels and controls for `每个目标最多视频`, `每条视频最多评论`, `参与账号数`, `任务间隔秒`, and `排除词`.
  - These controls already feed execution through `scan_max_videos_var`, `scan_max_comments_var`, `scan_profile_limit_var`, `scan_interval_var`, and `scan_exclude_keywords_var`; this slice closes the UI visibility/evidence mapping gap.
  - Added `tests/test_operator_controls_mapping.py` to lock the delivery-audit operator-control contract.
  - `ReachOps/workbench/tiktok_action_executor.py` now explicitly binds live action browser acquisition to the shared `WorkbenchBrowserAdapter` contract.
  - The action executor already acquired browsers through `get_workbench_browser_adapter().acquire(...)`; this update adds a typed adapter contract and focused test coverage so the Web/API acquisition-chain audit can verify actions use the same ixBrowser/Selenium adapter boundary as collection.
  - `tools/run_reachops_headless_macos.py` now explicitly advances the auditable run session to `COLLECTING` after the headless collection start and writes a no-AI-token checkpoint with log-line/progress/heartbeat metadata.
  - The Web/API acquisition-chain audit now verifies `headless_updates_run_session_checkpoints=true`; the false subchecks in that failed aggregate dropped from 5 to 4 in this branch.
  - `ReachOps/launcher.py`, `ReachOpsApp.py`, root/ReachOps READMEs, and Mac `.command` entrypoints now treat the local Web console as the default client surface.
  - Legacy Tk remains available only as an explicit diagnostic path through `--legacy-tk` or `REACHOPS_LEGACY_TK=1`; missing Web launcher failures no longer silently fall back to Tk.
  - `tools/reachops_web_ui.py` now satisfies the responsive toolbar/metric grid contract checked by delivery audit and runtime smoke.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/launcher.py tools/reachops_web_ui.py tests/test_launcher.py tests/test_operator_controls_mapping.py`: passed; log `/tmp/reachops-pr18-client-entry-pycompile.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_launcher tests.test_operator_controls_mapping`: passed, 11 tests; log `/tmp/reachops-pr18-client-entry-target-tests.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests.
  - Campaign regression comparison:
    - branch `codex/p4-operator-controls-ui-mapping`: 230 tests, 14 failures, 1 error; log `/tmp/reachops-pr18-client-entry-campaign.log`.
    - `origin/main`: 230 tests, 14 failures, 1 error; log `/tmp/reachops-main-baseline-pr18-client-entry-campaign.log`.
    - comparison `/tmp/reachops-pr18-client-entry-baseline-comparison.json`: `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`; output `/tmp/reachops-pr18-client-entry-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, summary `passed=48`, `pending_external_validation=3`, `failed=3`; client entrypoint and responsive toolbar checks now pass; output `/tmp/reachops-pr18-client-entry-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, `status=not_ready`, `final_delivery_ready=false`; blockers include Mac ixBrowser/API loop readiness, missing Windows artifacts, and pending authorized execution; output `/tmp/reachops-pr18-client-entry-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, `status=failed`; output `/tmp/reachops-pr18-client-entry-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed; missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-pr18-client-entry-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed; failed checks are `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-pr18-client-entry-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, `forbidden_count=0`; output `/tmp/reachops-pr18-client-entry-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-pr18-client-entry-diff-check.log`.
- Remaining blockers:
  - Delivery audit still has 3 failed local checks: campaign funnel isolation, Web panel runtime API smoke, and Web button JS/API feedback.
  - Current Mac goal-delivery runner also reports ixBrowser Local API / group freshness / latest run completion as not ready in this environment.
  - Windows final artifacts are still missing: `dist/ReachOps/ReachOps.exe`, `dist/installer/ReachOps-Setup-0.4.0.exe`, `dist/installer/reachops-update-manifest.json`, and `reports/reachops_acceptance/acceptance_summary.json`.
  - External authorized live TikTok validation remains pending and must not be fabricated on Mac.

## State-update rules

Codex must update this file at the end of each milestone with:

- status transition
- commit and PR
- tests executed and exact result
- evidence paths
- blockers
- next autonomous action

Do not write `COMPLETE` unless every exit condition is supported by evidence. Implementation completion and external live acceptance are separate states.
