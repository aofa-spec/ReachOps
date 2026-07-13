# ReachOps PM / Architecture Delivery Standard

## Current Status As Of 2026-07-04

Current Mac local MVP acceptance is **blocked by accounts**, not passed.

Authoritative current gates:

- `tools/reachops_client_delivery_check.py --json`: `status=blocked_by_accounts`
- `contract_ok=true`
- `acceptance_ready=false`
- `final_delivery_ready=false`
- `failed_checks=["acceptance:ready"]`
- `tools/reachops_repository_cleanliness_check.py --json`: `status=passed`, `forbidden_count=0`

Current blocker:

- United States group inventory is readable, but latest preflight has `profile_available=0`.
- Account issues include `IXBROWSER_KERNEL_MISMATCH` and `LOGIN_REQUIRED`.
- Mac MVP can only pass after at least one United States profile has the required ixBrowser kernel, TikTok is logged in, and the latest retest produces `available>=1` plus collection/action-preflight evidence or a structured no-action reason.

The 2026-07-03 evidence below is retained as historical acceptance evidence and must not override the 2026-07-04 realtime gate.

## Delivery Scope

ReachOps is not delivered as a standalone page. The product is delivered as a local execution system controlled by an operator Web panel:

`Web operator panel -> local Web API -> ReachOps runner -> ixBrowser Local API -> fingerprint browser profile -> TikTok collection / outreach preflight / authorized live outreach -> logs, funnel, evidence, reports`

The Web UI is only accepted when it proves the backend execution chain above. A button click without runtime evidence is not accepted.

## What "Start Acquisition" Means

"Start acquisition" is valid only when the latest batch proves all of the following:

- Operator entered a target: product URL, keyword, creator URL, video URL, hashtag, or live room.
- The system classified the target type and generated executable sources.
- ixBrowser groups were refreshed through the Local API with fresh group names and counts.
- The selected profile group exists and `/api/start` uses that group.
- The local headless runner starts.
- Profile preflight checks login state, captcha/risk state, proxy/page availability, and profile startup.
- Usable profiles collect TikTok content and comment users.
- Candidates are deduplicated, scored, and classified for intent.
- Lead and outreach action data is produced, or a clear no-action reason is recorded.
- Default mode is no-submit. Real comments, follows, or DMs are not submitted unless live authorization gates pass.

Required evidence:

- `PLAN campaign`
- `START campaign`
- `CHECK profile_preflight`
- selected group / account queue evidence
- `DONE collection`
- `DONE action_preflight`, `DONE action_submit`, or `no_action_reason`
- no `HEADLESS_TIMEOUT` in the latest result

## Acquisition And Outreach States

`collect_only`: collection only. It can prove source scanning and candidate discovery, but does not prove outreach.

`preflight`: collection plus outreach preflight. This is the default Mac MVP mode. It can generate outreach actions and verify that the target page or entry point is executable without submitting comments, follows, or DMs.

`live_comment`: collection plus real comment submit. This is allowed only when the target is explicitly authorized, live confirmation is checked, activation is ready, the account is authorized, copy is confirmed, and evidence is written after execution.

## Effective Acquisition

Effective acquisition is not equal to a terminal batch. It requires:

- collection reached terminal state,
- candidate count is greater than zero,
- lead scoring or intent classification ran,
- report artifacts contain usable candidate data,
- no environment blocker invalidates the run.

If `candidates=0`, the state is `partial`, not `pass`. The system must show `no_action_reason.code=no_candidates`.

If candidates exist but no users meet the outreach threshold, the state is not live outreach success. The system must show `no_action_reason.code=low_intent_candidates`.

## Effective Outreach

Preflight outreach is effective when:

- an outreach action exists,
- the target page opens,
- the relevant entry point exists, such as comment box, follow button, or DM entry,
- the action is recorded as preflight-success or executable,
- no real submit occurs.

Live outreach is effective only when:

- a real action is submitted after authorization,
- evidence screenshot and sidecar metadata are written,
- submitted text is recorded,
- final result confirms visibility or completion, for example `comment_visible_confirmed=true`.

Invalid outreach includes low intent, inaccessible targets, login required, captcha/risk state, proxy failure, missing entry point, ixBrowser startup failure, or unapproved live submit.

## Mac Local MVP Gate

Mac local MVP is accepted only when these commands pass:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_mac_loop_acceptance.py --base-url http://127.0.0.1:8769 --json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_client_delivery_check.py --json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_repository_cleanliness_check.py --clean --json
```

The gate requires:

- Web UI reachable at `http://127.0.0.1:8769/`.
- ixBrowser Local API ready.
- group refresh returns a fresh group list from ixBrowser Local API, not cache-only data.
- all ixBrowser groups returned by the current refresh have verified account counts.
- selected group exists and has a verified account count from the same current refresh.
- `/api/start` launches the local runner.
- latest run is complete and not failed by timeout.
- `readiness=pass`.
- no-submit safety remains active by default.
- no-action reason is present whenever actions are zero.

Mac MVP now rejects start and acceptance when the current refresh cannot prove all returned group counts. Cached counts may be displayed to the operator, but they are not accepted as start evidence.

## Final Delivery Gate

Final customer delivery is stricter than Mac MVP. It additionally requires:

- Windows exe.
- Windows installer.
- update manifest.
- acceptance summary.
- same Web UI running on Windows.
- authorized real submit evidence.
- final gate reports `final_delivery_ready=true`.
- `failed_checks=[]`.
- no pending external validation.

Required final commands:

```bash
python tools/reachops_goal_delivery_runner.py --json
python tools/reachops_phase2_handoff_check.py --write --json
python tools/reachops_delivery_package_check.py --json
python tools/reachops_final_acceptance_gate.py --json
python tools/reachops_two_phase_acceptance_matrix.py --refresh --write --require-final --json
```

## Historical Mac Evidence As Of 2026-07-03

Latest observed batch:

- batch: `gb_d2928a2643d64aba`
- target: `https://www.tiktok.com/@aofacore/video/7656416339531205901`
- group: `United States`
- group inventory: 15 groups / 2910 profiles reported
- selected group inventory: `United States` has 698 verified profiles
- profile preflight: available 3 in the latest acceptance evidence
- collection terminal: yes
- candidates: 3
- preflight actions: 3
- preflight success: 3
- no submit: true
- no action reason: not required because actions > 0
- acceptance: `pass`

Historical conclusion: Mac local MVP acceptance passed on 2026-07-03. This proves the Web operator panel can control the local no-submit execution chain through ixBrowser profiles and TikTok preflight under that historical environment. It does not prove the current 2026-07-04 realtime Mac gate, and it does not prove final customer delivery; Windows final artifacts and authorized live submit evidence are still required.
