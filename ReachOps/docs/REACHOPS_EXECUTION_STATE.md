# ReachOps Execution State

- Schema: `reachops.execution_state.v1`
- Contract: `REACHOPS_MASTER_EXECUTION_CONTRACT_V1.md`
- Last manually reconciled: `2026-07-17`
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
| P4 | Bilingual UI, installer, update, Windows acceptance | `IN_REVIEW` | Branch `codex/p4-web-runtime-smoke` hardens the unified Web client entry, strict live-comment activation gate, account-gate start blocking, group-count DOM evidence, and Python 3.9-compatible runtime smoke cleanup. Runtime smoke and DOM smoke now pass locally; delivery audit improved from 5 failed checks to 3 remaining failed checks. Final Windows package and authorized live acceptance are still incomplete. | Win10/11 installer, zh-CN/en-US UI, update flow, acceptance matrix, authorized live evidence |
| P5 | DM inbox monitoring | `DEFERRED` | Explicitly deferred behind public reply monitoring | Separate privacy/evidence contract and acceptance after P3/P4 |

## Next autonomous action

1. Finish reviewing Draft PR #12 for P1 immutable Campaign Run / Observation model; keep LeadDecision expansion split unless it is strictly required for P1 traceability.
2. Review Draft PR from branch `codex/p4-web-runtime-smoke`; accept only the Web runtime smoke slice and keep Windows/installer/live-submit validation out of scope.
3. Continue the remaining non-external delivery-audit failures as separate focused slices:
   - customer-visible settings need execution evidence mapping
   - funnel views must show only the current Campaign/Run
   - Web panel must prove the server-side local API path invokes the ixBrowser execution chain
4. After P1/P4 review, return to the final Windows delivery chain: `ReachOps.exe`, installer, update manifest, Windows acceptance, and authorized live evidence.

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

## Latest P4 Web runtime smoke snapshot

- Date: `2026-07-19`
- Branch: `codex/p4-web-runtime-smoke`
- Scope: Web runtime smoke, DOM smoke, launcher entry contract, and live-comment activation safety only.
- Code evidence:
  - `python ReachOpsApp.py` now starts the unified Web console by default.
  - Native Tk remains available only through `--legacy-tk` or `REACHOPS_LEGACY_TK=1`.
  - Missing Web launcher no longer silently falls back to native Tk.
  - `/api/activation` uses a strict Web activation payload and blocks live-comment readiness when no local activation status file exists.
  - `/api/start` blocks `live_comment` with human confirmation when activation status is missing or not ready.
  - Account-gate UI blocks repeated starts against a group whose latest profile preflight found no executable accounts until repair is explicitly confirmed.
  - Group detail rendering exposes per-group count status/source for DOM smoke evidence.
  - Web runtime smoke temporary directory cleanup is compatible with `/usr/bin/python3` 3.9.6.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/launcher.py tools/reachops_web_ui.py tools/reachops_web_panel_runtime_smoke.py tools/reachops_web_panel_dom_smoke.py tests/test_launcher.py tests/test_reachops_client_acceptance_status.py`: passed; log `/tmp/reachops-p4-web-runtime-smoke-pycompile.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_launcher`: passed; log `/tmp/reachops-p4-web-runtime-smoke-launcher-tests-final.log`.
  - `/usr/bin/python3 tools/reachops_web_panel_runtime_smoke.py --json`: passed; output `/tmp/reachops-p4-web-runtime-smoke-runtime.json`.
  - `/usr/bin/python3 tools/reachops_web_panel_dom_smoke.py --json`: passed; output `/tmp/reachops-p4-web-runtime-smoke-dom.json`.
  - `/usr/bin/python3 -m unittest -v tests.test_truthful_execution_semantics`: passed, 7 tests; log `/tmp/reachops-p4-web-runtime-smoke-truth.log`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed; output `/tmp/reachops-p4-web-runtime-smoke-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed with remaining non-slice blockers; summary changed from `passed=46,pending_external_validation=3,failed=5` to `passed=48,pending_external_validation=3,failed=3`; output `/tmp/reachops-p4-web-runtime-smoke-delivery-audit.json`.
  - Remaining delivery-audit failures: customer-visible settings execution evidence mapping, current Campaign funnel isolation, and Web-to-local-API-to-ixBrowser execution-chain proof.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with the existing baseline shape, 230 tests, 14 failures, 1 error; branch and `origin/main` comparison artifact `/tmp/reachops-p4-web-runtime-smoke-baseline-comparison.json` reports `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, `final_delivery_ready=false`; output `/tmp/reachops-p4-web-runtime-smoke-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed; output `/tmp/reachops-p4-web-runtime-smoke-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed because final Windows package artifacts are missing; output `/tmp/reachops-p4-web-runtime-smoke-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, `final_delivery_ready=false`; output `/tmp/reachops-p4-web-runtime-smoke-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed; output `/tmp/reachops-p4-web-runtime-smoke-cleanliness.json`.
  - `git diff --check`: passed; log `/tmp/reachops-p4-web-runtime-smoke-diff-check.log`.
- Safety:
  - No Windows build, EXE, installer, or TikTok live-submit was attempted on this macOS branch.
  - Web live-comment activation requires a local activation status file and activation ready state; development bypass is not accepted by the Web activation gate.

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
