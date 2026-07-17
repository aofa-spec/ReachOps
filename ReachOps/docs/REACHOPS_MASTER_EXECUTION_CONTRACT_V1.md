# ReachOps Master Execution Contract v1

- Contract ID: `REACHOPS-MASTER-EXECUTION-V1`
- Status: `ACTIVE`
- Effective date: `2026-07-17`
- Product owner: `AoFa`
- Engineering provider: `Codex`
- Repository: `aofa-spec/ReachOps`
- Canonical purpose: define the complete product target, engineering boundaries, autonomous execution order, truth semantics, safety gates, and acceptance contract for ReachOps.

## 1. Authority and precedence

This document is the canonical product and engineering target for ReachOps.

Precedence:

1. Latest explicit product-owner decision recorded in this contract.
2. This master execution contract.
3. `REACHOPS_EXECUTION_STATE.md` for current progress only.
4. Verified code, tests, runtime evidence, and current platform results.
5. Existing PM, goal-mode, Windows, and acceptance runbooks.
6. Historical reports and snapshots.

Existing `REACHOPS_GOAL_MODE_EXECUTION.md` and `REACHOPS_PM_DELIVERY_BASELINE.md` remain useful acceptance/runbook references, but they must not redefine the independent Windows client target or override this contract.

## 2. Product definition

ReachOps is an independent, sellable Windows local client for TikTok-oriented customer discovery and controlled outreach.

It is not:

- an OPC runtime module
- an Obsidian workflow
- a central SaaS holding all customer business data
- a fully automatic mass-outreach bot
- a system that bypasses login, CAPTCHA, rate limits, or platform restrictions

The customer installs ReachOps on Windows, connects the customer's own ixBrowser installation and logged-in profiles, imports a promotion target, collects public content/comments, identifies likely intent, reviews each proposed action, approves a small number of real public comments or replies, stores evidence locally, and monitors public replies.

## 3. Target customer and delivery form

First commercial delivery:

- Windows 10 22H2 x64
- Windows 11 x64
- installable EXE package
- local desktop client with local runtime service
- ixBrowser installed and logged in separately by the customer
- no Windows code-signing certificate in the current baseline; internal/test packages may show an unknown-publisher warning
- client checks for updates but does not silently force an update
- primary interface localized in `zh-CN` and `en-US`

Do not replatform the existing application wholesale. Preserve the existing Python/runtime/package baseline and refactor incrementally unless a separately approved technical decision proves that the current stack cannot satisfy a contract requirement.

## 4. Supported promotion inputs

The client accepts:

1. Public independent-site product URL.
2. TikTok product/content/video URL.
3. TikTok creator profile URL.
4. TikTok live-room URL.
5. Keyword or keyword list.
6. Hashtag or topic.

Input behavior:

### 4.1 Public product URL

```text
public product page
-> extract product name, public claims, price context, category, and audience clues
-> generate candidate keywords, hashtags, topics, competitor terms, intent terms, and exclusion terms
-> show editable strategy to the operator
-> require operator confirmation
-> generate executable TikTok sources
```

Private dashboards, authenticated administration pages, protected personal pages, and inaccessible URLs must be rejected with a clear reason. ReachOps must not attempt to acquire credentials or bypass access controls.

### 4.2 TikTok direct inputs

- Video/content URL: collect that content and its public comments.
- Creator URL: discover the creator's public content and then collect eligible comment areas.
- Live-room URL: collect only public interaction data that the current authorized session can lawfully read and that the collector contract supports.
- Keyword/hashtag/topic: search public content, rank sources, and enter eligible comment areas.

A product URL is not itself a TikTok comment source. It must be converted into TikTok-executable sources.

## 5. Country, group, timezone, and language

The customer manually chooses the ixBrowser group used for a run.

A group name alone is not authoritative country metadata. On first use, ReachOps must maintain an editable local group mapping:

```text
ixBrowser group ID/name
-> target country
-> timezone
-> default reply language
-> allowed action types
-> per-day and per-hour limits
```

The runtime also detects the actual language of each public comment.

Language rules:

- clear comment language: generate a proposal in that language
- uncertain language: require explicit operator confirmation
- comment language conflicts with group default: display a warning and prohibit automatic submission
- all live actions remain per-action human approved

Formally acceptance-tested languages for v1:

- English
- Spanish
- Portuguese
- Chinese

Other Unicode languages may be used through the model/provider architecture, but must be labeled architecture-supported and not formally acceptance-tested until evidence exists.

## 6. AI operating model

AI mode is hybrid.

### 6.1 Without a customer API key

ReachOps remains usable with deterministic local capabilities:

- rule-based input classification
- keyword and intent matching
- basic scoring
- exclusion rules
- editable templates
- human review
- no-submit and live-action safety gates

### 6.2 With a customer API key

The customer may configure a supported or OpenAI-compatible provider for:

- product-page analysis
- audience/persona suggestions
- keyword/topic/source expansion
- semantic intent classification
- multilingual reply suggestions
- reply qualification suggestions

Provider output is advisory. Deterministic code, operator approval, risk gates, evidence gates, and state machines remain authoritative.

### 6.3 Secret storage

Store AI API keys and other application secrets in Windows Credential Manager.

Do not store secrets in:

- SQLite
- logs
- reports
- screenshots
- support bundles
- backup archives
- Git

ixBrowser owns TikTok cookies and login sessions. ReachOps must not export, back up, or synchronize them.

## 7. Customer-data boundary

Each customer computer has an independent local SQLite runtime.

Local customer data includes:

- campaigns and runs
- source plans and observations
- public content/comment observations
- candidate users and lead decisions
- human review actions
- proposed and executed outreach
- public replies
- qualified-lead decisions
- manual conversion and revenue records
- evidence metadata and local evidence files
- local configuration and templates

There is no central server storing customer comments, usernames, leads, screenshots, conversations, or customer SQLite databases in v1.

### 7.1 Minimal external service

A minimal service may handle only:

- license activation
- subscription state
- device-seat state
- license revocation
- version/update metadata

It must not receive customer business data.

### 7.2 OPC boundary

OPC manages ReachOps as a company project. OPC may receive only:

- development mission state
- version and delivery state
- aggregated/redacted metrics
- redacted evidence summaries
- blockers and CEO decisions

OPC must not store customer databases, cookies, full comment data, real usernames, raw screenshots, or customer account state.

### 7.3 GitHub boundary

GitHub stores only:

- source code
- schemas and migrations
- tests
- redacted fixtures
- documentation
- non-sensitive build metadata

Real customer data, authorized targets, API keys, cookies, Profile secrets, screenshots, and local databases are prohibited.

## 8. Multi-device model

- Default license: one device.
- Additional device seats may be purchased.
- Every device has an independent runtime; devices do not share one SQLite database.
- No multi-device write access to iCloud SQLite, network-drive SQLite, OneDrive SQLite, or a shared NAS SQLite file.
- Data is moved through an explicit encrypted backup/export and restore process.

## 9. Backup and restore

Backup format: `.reachops-backup`.

The customer sets the backup password. ReachOps cannot recover a lost password.

Backup variants:

- lightweight: SQLite data, non-secret configuration, templates, and evidence index
- full: lightweight content plus selected evidence files

Always excluded:

- TikTok cookies and sessions
- ixBrowser login state
- AI API keys
- proxy credentials
- license secrets that must be reissued
- Windows Credential Manager secrets

Requirements:

- authenticated encryption
- versioned manifest
- integrity hashes
- schema/version compatibility check
- atomic restore
- restore preview
- rollback on failure
- tests for wrong password, corrupted archive, interrupted restore, and older supported schema

## 10. Licensing state machine

- First activation requires internet access.
- Client attempts license verification every 24 hours.
- Offline grace period is 7 days.
- During the 7-day grace period, licensed capabilities remain available under existing safety gates.
- After grace expiry, the customer may still view, search, export, and back up local data.
- After grace expiry, the customer may not start new real TikTok outreach.
- Reconnection and successful verification restore permitted live capabilities.
- License state must never delete or lock away customer-owned data.

## 11. Telemetry and support

Anonymous diagnostics are off by default.

When the customer opts in, allowed anonymous fields are limited to:

- ReachOps version
- Windows version
- error code
- failing module
- crash stack with secret redaction
- duration
- whether ixBrowser integration was active
- anonymous installation instance ID

Never collect through ordinary telemetry:

- TikTok usernames
- comment/reply content
- target URLs
- product information
- screenshots or DOM
- cookies or credentials
- proxy data
- SQLite files

A diagnostic support bundle may include broader evidence only when the customer explicitly generates it, previews its manifest, and chooses to share it. Redaction must be applied before packaging.

## 12. Core execution modes and truth semantics

Required `execution_mode` values:

- `simulated`
- `dry_run`
- `preflight`
- `live`

Required submission states:

- `not_attempted`
- `prepared`
- `submitted`
- `submitted_unverified`
- `verified_success`
- `failed`
- `blocked`

Required verification states:

- `not_required`
- `pending`
- `verified`
- `rejected`
- `expired`

A real success requires all of:

```text
execution_mode = live
submission_state = verified_success
verification_state = verified
evidence_verified = true
```

The following must never count as a live success:

- plan created
- UI button clicked
- runner process started
- process exit code zero
- Fixture/Mock success
- dry-run success
- preflight success
- screenshot existence alone
- evidence URI stub
- historical evidence from another run

## 13. v1 outreach scope

### 13.1 Live v1 capability

The first live-acceptance capability is a public TikTok comment or public reply to a user in a comment area.

Every real action requires:

- eligible candidate
- operator-visible source and original comment
- generated or edited proposed text
- selected ixBrowser Profile
- current readiness and risk gate pass
- explicit per-action operator approval
- final preview
- live execution
- action-specific evidence validation

There is no v1 one-click bulk live submission.

### 13.2 Follow and DM

Follow and DM may remain available as:

- proposal
- human review
- no-submit preflight
- evidence-contract development with fixtures

They are not required v1 live-delivery capabilities until their action-specific evidence and privacy contracts pass acceptance.

### 13.3 Public reply monitoring

v1 must automatically monitor public replies to ReachOps-originated public comments/replies:

```text
verified outreach action
-> persist target, source, text hash, author, and time
-> periodically revisit the public thread through authorized profiles
-> identify new public replies
-> link reply to original action_id and lead_id
-> store immutable reply observation
-> re-evaluate qualification
-> notify operator
```

DM inbox monitoring is a later milestone and must not block the public-reply v1.

## 14. Lead lifecycle

Canonical lifecycle:

```text
observed
-> scored
-> model_high_intent
-> human_reviewed
-> approved
-> contacted
-> reply_received
-> qualified
-> converted
-> won / lost / opted_out
```

Definitions:

- Candidate: a collected public user/comment that satisfies minimum data quality.
- Model High-Intent: model/rules infer likely need; not a customer and not qualified.
- Human-Approved Lead: operator confirms the candidate is worth contacting.
- Contacted: evidence-verified live public action completed.
- Reply Received: a public reply is observed and linked to the action.
- Qualified Lead: the reply content confirms a real need related to the offer.
- Converted: the customer records the configured target behavior.
- Won: the customer confirms a sale and may record amount/currency.

Keyword matching alone never creates a qualified lead.

## 15. Lead decision contract

Every scoring decision must be immutable and versioned:

- `lead_decision_id`
- `campaign_id`
- `run_id`
- `candidate_observation_id`
- `intent_type`
- `intent_score`
- `product_fit_score`
- `contactability_score`
- `source_quality_score`
- `total_lead_score`
- `confidence`
- `reason_codes`
- `feature_snapshot`
- `classifier/provider_version`
- `human_review_status`
- `created_at`

Rules:

- video popularity is source quality, not direct user purchase intent
- current campaign configuration cannot overwrite a historical decision
- human review is appended as an audit event, not used to erase the model decision
- source quality optimizes future collection; intent/product fit/contactability select lead candidates

## 16. Immutable observation model

Global stable entities and run observations must be separate.

Stable entities may include:

- `people`
- `contents`
- `sources`

Required run-scoped entities:

- `campaign_runs`
- `source_observations`
- `content_observations`
- `comment_observations`
- `candidate_observations`
- `lead_decisions`
- `contact_attempts`
- `contact_outcomes`
- `reply_observations`
- `conversion_events`
- `evidence_artifacts`

Every observation requires:

- `campaign_id`
- `run_id`
- `batch_id` where retained for compatibility
- stable entity reference
- source reference
- `observed_at`
- `evidence_id`
- collector/classifier version

A person may appear in multiple campaigns/runs without one run overwriting another.

## 17. Human-review surface

Each action-review row/page must show:

- original public comment
- source video/content
- public user profile
- matched intent and reasons
- score components and confidence
- detected language and group default language
- proposed reply
- selected ixBrowser Profile
- readiness/risk state
- evidence requirements

Operator actions:

- edit text
- approve and send
- reject
- add to exclusion list
- defer

Before live submission, show a final preview. Preserve:

- original suggestion
- final edited text
- editor/operator
- selected Profile
- approval time
- submission time
- target and source IDs
- execution result
- verification state
- evidence references

## 18. Evidence contracts

Evidence paths must be immutable and unique by run/action/attempt:

```text
evidence/{run_id}/{action_id}/{attempt_id}/
```

### 18.1 Comment/reply evidence

Required:

- target content URL/ID matches
- target username/context matches
- submitted text hash matches
- submitted text is visible after posting
- current page is not login/CAPTCHA/rate-limit/error state
- screenshot and structured sidecar
- complete streaming SHA-256
- submission and verification timestamps
- comment ID or stable DOM anchor when available

### 18.2 Follow evidence

Required before a future live release:

- target identity matches
- before state
- unambiguous after `Following` state
- before/after evidence
- page-state normal

Empty button text is not proof.

### 18.3 DM evidence

Required before a future live release:

- target conversation identity matches
- text hash matches
- sent message bubble is visible
- sent timestamp
- message ID or stable anchor when available
- page-state normal

No visible sent-message confirmation means `submitted_unverified`.

## 19. Fallback action contract

When an action changes channel, such as DM to public comment:

- create or select a separate target-channel action
- preserve `fallback_from_action_id`
- do not reuse source-channel rendered text
- regenerate using target-channel template and actual comment language
- recompute risk
- require a new approval if text or risk changes
- give the fallback action its own evidence lifecycle

## 20. Page-state and repair policy

There must be one canonical PageStateDetector and one canonical RepairPolicyEngine. Legacy paths may only forward to canonical implementations.

Every decision records:

- schema version
- detector version
- policy version
- decision ID
- page-state snapshot
- evidence references

### 20.1 Hard-stop enforcement

The following stop the current run/scope and prohibit account switching as a bypass:

- CAPTCHA or abnormal security verification
- login required/expired
- account restricted
- platform rate limiting/enforcement
- comment capability restricted

### 20.2 Bounded infrastructure retry

Only bounded infrastructure problems may retry or switch profiles:

- browser crash
- ixBrowser temporary startup/server failure
- proxy connectivity failure
- ordinary page timeout

Limits and backoff must be explicit and tested.

## 21. Runtime architecture

Target local architecture:

```text
Windows Desktop UI
-> Local Application Service
-> Campaign/Run Orchestrator
-> Local SQLite Runtime
-> Strategy and AI Provider Layer
-> ixBrowser Local API Adapter
-> Deterministic Collectors
-> Lead Decision Engine
-> Human Review Queue
-> Risk / Authorization / License Gates
-> Action Executor
-> Evidence Validator
-> Public Reply Monitor
-> Local Reports / Export / Backup
```

Supporting services:

- Windows Credential Manager adapter
- update client
- minimal license client
- local scheduler
- structured logging with redaction
- support-bundle builder

Local API must bind only to loopback unless a separately approved design changes this. POST actions reject non-local origins.

## 22. Autonomous Codex engineering loop

On every invocation, Codex must:

1. Read root `AGENTS.md`.
2. Read this contract.
3. Read and verify `REACHOPS_EXECUTION_STATE.md`.
4. Inspect Git/PR/test status.
5. Select the highest-priority unblocked item.
6. Produce one coherent, reversible milestone.
7. Run contract-relevant tests.
8. Update execution state.
9. Commit on a non-main branch and open/update a draft PR when supported.
10. Report evidence and the next action.

Codex must not ask the product owner to repeat decisions already recorded here. A new question is justified only when a missing decision would materially change customer-facing behavior, data custody, external risk, pricing/licensing policy, or irreversible architecture.

External blockers do not stop all engineering. Codex must continue non-blocked work while preserving the external gate as blocked.

## 23. Engineering roadmap

### P0 — Truthful execution semantics

Goal: prevent simulated, dry-run, preflight, and unverified outcomes from becoming business success.

Deliverables:

- explicit execution/submission/verification states
- live Fixture fail-closed
- hard-stop circuit breaker before switch/fallback
- truthful funnel aggregation
- simulated/preflight success does not advance contacted state
- channel fallback does not inherit wrong text
- regression tests

Current status: implementation exists in draft PR #10 and is not merged at contract activation time. Verify before trusting.

### P1 — Campaign Run / Observation model

Goal: eliminate campaign/batch cross-contamination and preserve historical decisions.

Deliverables:

- idempotent schema migration
- stable entities separated from observations
- run-scoped scoring and lead creation
- immutable LeadDecision
- compatibility reads for existing data
- rollback strategy
- cross-campaign isolation and migration tests

Exit criteria:

- the same user can be observed in multiple runs
- campaign B never overwrites campaign A decision
- every current-run candidate traces to campaign/run/evidence
- migration reruns safely

### P2 — Windows local security, license, seats, backup

Deliverables:

- Credential Manager abstraction
- secret-free SQLite/logging/backup
- minimal license state machine
- 24-hour verification and 7-day grace
- read/export/backup available after expiry; new live outreach disabled
- one-device default and extra-seat support
- encrypted lightweight/full backup
- atomic restore and compatibility tests
- telemetry default off and support-bundle redaction

### P3 — Public reply monitoring and business lifecycle

Deliverables:

- revisit verified public comment threads
- reply identity and action linkage
- immutable reply observations
- reply deduplication
- qualified-lead decision
- manual conversion, won/lost/opt-out, revenue/currency capture
- notifications and dashboard funnel
- redacted replay fixtures and tests

### P4 — Bilingual client, installer, update, final acceptance

Deliverables:

- `zh-CN` and `en-US` resource system
- Windows 10/11 installer and uninstall
- update manifest and user-confirmed update flow
- no silent forced update
- unsigned-build warning documented until certificate exists
- input/group/review/run/evidence/reply screens
- end-to-end local acceptance
- authorized Windows/ixBrowser/TikTok external validation

### P5 — DM monitoring

Deferred until public reply monitoring and privacy/evidence contracts are stable. It requires its own user-consent, retention, conversation identity, evidence, and deletion design.

## 24. Acceptance contract

Formal pilot:

- at least 100 real public comments collected
- manual audit of collection accuracy at least 90%
- at least 50 manually labeled intent samples
- model-high-intent precision at least 80% on the reviewed sample
- 10 individually approved authorized public comments/replies attempted
- at least 9 with complete evidence-verified success, unless platform/environment blocks are separately evidenced
- zero simulated/dry-run/preflight records counted as live success
- zero account switching used to bypass CAPTCHA/rate-limit/account restriction
- automatic public-reply association successfully validates at least 3 replies

If natural users do not reply, authorized test accounts may validate the technical reply-linking mechanism. Natural reply rate remains a separate business observation and must not be fabricated.

Every key metric must include scope, campaign/run, definition version, generation time, and evidence references.

## 25. Project-level Definition of Done

ReachOps v1 is customer-deliverable only when all are evidenced:

1. Windows 10/11 installer works on clean test machines.
2. Client operates with each device's independent local SQLite runtime.
3. Secrets remain outside SQLite, logs, backup, and Git.
4. Product inputs generate editable and executable source strategies.
5. ixBrowser group mapping and profile selection are explicit.
6. Collection and scoring are run-scoped and historically immutable.
7. Every live public action is individually approved.
8. Every live success has action-specific verified evidence.
9. Hard-stop platform states cannot be bypassed by account switching.
10. Public replies are automatically detected and linked.
11. Qualified lead requires reply-confirmed need.
12. Conversion and revenue can be recorded locally.
13. Backup/restore, licensing, 7-day grace, and extra device seats work.
14. `zh-CN` and `en-US` UI paths pass acceptance.
15. GitHub contains no customer data or secrets.
16. Existing baseline failures and new regressions are separately reported.
17. External authorized platform validation is passed; implementation alone is not called final delivery.

## 26. Required completion report

Each milestone report must include:

A. Verified facts  
B. Files and schema changed  
C. Migration and rollback  
D. Tests and exact results  
E. Evidence/artifact paths  
F. Privacy and secret scan  
G. External blockers  
H. Execution-state changes  
I. Branch, commit, and PR  
J. Next autonomous action

No report may say simply “completed” without supporting code, tests, records, or evidence.
