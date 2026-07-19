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
| P3 | Public comment-reply monitoring and lead lifecycle | `IN_REVIEW` | Branch `codex/p3-public-reply-observations`; storage foundation records immutable public reply observations linked to action/lead, only allows qualified-lead advancement from a linked reply-confirmed need decision, and preserves the verified-live-only rule for `contacted` | Automatic public reply detection; action linkage; qualified-lead state; manual conversion/revenue capture |
| P4 | Bilingual UI, installer, update, Windows acceptance | `PLANNED` | Existing packaging/runbook exists but final external acceptance is incomplete | Win10/11 installer, zh-CN/en-US UI, update flow, acceptance matrix, authorized live evidence |
| P5 | DM inbox monitoring | `DEFERRED` | Explicitly deferred behind public reply monitoring | Separate privacy/evidence contract and acceptance after P3/P4 |

## Next autonomous action

1. Keep PR #25 in Draft and review the public reply lifecycle storage contract; do not expand it into browser reply monitoring, Windows packaging, or live-submit.
2. Continue P3 with a separate public reply monitor/parser PR using redacted/replay fixtures:
   - detect public replies without submitting platform actions
   - link reply observations to existing action and lead IDs
   - preserve `reply_received` distinct from `qualified`
   - require reply-confirmed need decisions before `qualified`
3. Continue P1 immutable campaign-run observations as a separate PR:
   - preserve `campaign_runs`
   - preserve run-scoped source/content/comment/candidate observations
   - preserve legacy handling without fake `run_id`
   - keep LeadDecision versioning separate if it expands beyond the P1 runtime data model
   - keep cross-campaign/run isolation and traceability tests

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

## Latest P3 public reply lifecycle snapshot

- Date: `2026-07-19`
- Branch: `codex/p3-public-reply-observations`
- Scope: storage-layer public reply observation and qualified-lead foundation only.
- Code evidence:
  - Added local SQLite `reply_observations` with action/lead linkage, reply author/text/url, evidence path, raw payload, observed timestamp, and idempotency on `(action_id, reply_author, reply_text, reply_url)`.
  - Added local SQLite `lead_qualification_decisions` as append-only qualification evidence linked to a `reply_observation_id`.
  - `record_reply_observation(...)` requires an existing action, links the reply to the action's `lead_id`, logs a local event, and advances the lead to `reply_received`.
  - `record_lead_qualification_decision(...)` rejects missing reply observations and rejects `qualified=True` without a reply-confirmed need reason.
  - A keyword/high-intent candidate alone does not create `qualified`; only a linked public reply decision with confirmed need advances the lead to `qualified`.
  - Lead lifecycle no longer treats `action_queue.status in ('completed', 'success')` as `contacted`; `contacted` now requires a linked outreach execution with `execution_mode='live'`, `status='success'`, `submission_state='verified_success'`, `verification_state='verified'`, and `evidence_verified=1`.
  - This is not a public web collector yet; it is the local immutable data and lifecycle contract needed by the later reply monitor.
- Tests and checks:
  - `/usr/bin/python3 -m py_compile ReachOps/intelligence/storage.py tests/test_public_reply_lifecycle.py tests/test_truthful_execution_semantics.py`: passed, exit `0`; log `/tmp/reachops-p3-public-reply-verified-contact-pycompile.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_public_reply_lifecycle tests.test_truthful_execution_semantics`: passed, 12 tests, exit `0`; log `/tmp/reachops-p3-public-reply-verified-contact-focused.log`.
  - `/usr/bin/python3 -m unittest -v tests.test_reachops_campaign`: failed with existing baseline shape, 230 tests, 14 failures and 1 error; log `/tmp/reachops-p3-public-reply-verified-contact-campaign.log`.
  - `origin/main` campaign baseline in `/tmp/reachops-main-baseline-pr25-verified-contact`: failed with the same 230 tests, 14 failures and 1 error; log `/tmp/reachops-p3-public-reply-verified-contact-main-campaign.log`.
  - Baseline comparison artifact `/tmp/reachops-p3-public-reply-verified-contact-baseline-comparison.json`: `new_failures=[]`, `new_errors=[]`.
  - `/usr/bin/python3 tools/reachops_operator_pressure.py --json`: passed, `status=ok`, exit `0`; output `/tmp/reachops-p3-public-reply-verified-contact-operator-pressure.json`.
  - `/usr/bin/python3 tools/reachops_delivery_audit.py --json`: failed, exit `1`, summary `passed=46`, `pending_external_validation=3`, `failed=5`; output `/tmp/reachops-p3-public-reply-verified-contact-delivery-audit.json`.
  - `/usr/bin/python3 tools/reachops_goal_delivery_runner.py --json`: failed, exit `1`, `status=not_ready`, `final_delivery_ready=false`; output `/tmp/reachops-p3-public-reply-verified-contact-goal-delivery-runner.json`.
  - `/usr/bin/python3 tools/reachops_goal_status_report.py --json`: failed, exit `1`, `status=failed`; output `/tmp/reachops-p3-public-reply-verified-contact-goal-status-report.json`.
  - `/usr/bin/python3 tools/reachops_delivery_package_check.py --json`: failed, exit `1`, missing `exe`, `installer`, `manifest`, and `acceptance_summary`; output `/tmp/reachops-p3-public-reply-verified-contact-package-check.json`.
  - `/usr/bin/python3 tools/reachops_final_acceptance_gate.py --json`: failed, exit `1`; failed checks include `goal_status:passed`, `client_delivery:final_ready`, `delivery_package:passed`, and `delivery_audit:no_failed_checks`; output `/tmp/reachops-p3-public-reply-verified-contact-final-gate.json`.
  - `/usr/bin/python3 tools/reachops_repository_cleanliness_check.py --json`: passed, exit `0`; output `/tmp/reachops-p3-public-reply-verified-contact-cleanliness.json`.
  - `git diff --check`: passed, exit `0`; log `/tmp/reachops-p3-public-reply-verified-contact-diff-check.log`.
- Safety:
  - No public web monitoring or TikTok live action was executed.
  - No customer data, credentials, cookies, real targets, browser sessions, screenshots, raw DOM, or local acceptance inputs were added.
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
