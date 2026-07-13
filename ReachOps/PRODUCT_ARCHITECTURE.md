# 增长获客工作台产品架构

## 专业命名

中文名：增长获客工作台

英文名：ReachOps

定位：面向运营人员的本地自治获客执行客户端。AI 是沟通窗口和计划生成器，程序是确定性执行主体。

## 交付目标

运营输入目标后，系统必须自动完成：

```text
找内容 → 采评论用户 → 识别意向 → 生成线索 → 生成动作
→ 账号执行/预检 → 失败换号 → 输出报告
```

页面上的每一个设置都必须是真实执行参数，不能是伪需求页面。

## 自治客户端目标

ReachOps 的目标形态不是“功能集合后台”，而是以下闭环：

```text
用户输入目标
→ AI/表单生成结构化 ExecutionPlan
→ 本地程序自动执行
→ 过程自动感知和自修复
→ 异常自动降级或阻断
→ 控制台实时解释
→ 执行结束生成证据和复盘
```

执行开始后默认不调用大模型，不消耗 token。AI 只在执行前生成计划、执行后复盘、未知错误离线分析时介入。

## ExecutionPlan 契约

整次运行必须先生成 `ExecutionPlan`，再启动 headless 执行器。Web UI、AI 对话区、命令行入口都必须收敛到同一份计划结构。

当前契约由 `ReachOps/execution_plan.py` 定义：

```json
{
  "schema_version": "reachops.execution_plan.v1",
  "target": "",
  "source_type": "keyword",
  "mode": "preflight|collect|live_comment",
  "profile_group": "",
  "volume": "quick|standard|stress",
  "limits": {
    "profile_limit": 3,
    "max_videos": 3,
    "max_comments": 20,
    "timeout_seconds": 900
  },
  "authorization": {
    "live_confirmed": false,
    "account_repair_confirmed": false,
    "live_submit_allowed": false
  },
  "repair_policy": {},
  "risk_policy": {
    "no_ai_token_during_execution": true,
    "never_bypass_login_or_captcha": true
  }
}
```

要求：

1. `/api/start-preview` 必须返回规范化后的 `execution_plan`。
2. `/api/start` 必须把计划写入 `reports/reachops/mac_gui/runtime/plans/`。
3. headless 执行器必须支持 `--execution-plan`，并以计划内容作为真实执行契约。
4. 控制台展示的目标、模式、分组、额度、授权和修复策略必须和计划一致。
5. 后续 RunSession、PageStateDetector、RepairPolicyEngine、EvidenceBundle 都必须挂接到 `plan_id`。
6. `/api/execution-plan` 必须只读返回最新计划快照，包含下载路径、摘要和 `no_browser_started=true`、`no_submit=true`。
7. `/api/snapshot` 的报告产物必须包含“本轮执行计划 JSON”，证明同一计划可下载、可复现、可审计。
8. `/api/start-preview` 必须返回 `preflight_decision`，包含 `start_allowed`、阻断原因、下一步动作、提交策略和 0 token 标记。

## RunSession 状态机

每次执行必须创建 `RunSession`，用于证明程序已经从“启动进程”升级为“可恢复、可审计的自治运行会话”。

当前契约由 `ReachOps/run_session.py` 定义：

```text
CREATED
PRECHECK
PROFILE_OPENING
COLLECTING
SCORING
ACTION_PLANNING
EXECUTING
REPAIRING
DEGRADED
BLOCKED
COMPLETED
```

要求：

1. `/api/start` 创建 `RunSession`，写入 `reports/reachops/mac_gui/runtime/runs/`。
2. headless 执行器支持 `--run-session`，执行中持续更新 checkpoint。
3. `/api/logs` 返回 `run_session` 和 `run_session_state`，控制台必须显示状态机状态。
4. 暂停、恢复、停止必须写入 `RunSession.control`。
5. 执行结果必须写入 `RunSession.result`，不能只依赖进程退出码。
6. `/api/run-session` 必须只读返回最新运行会话快照，包含下载路径、状态摘要、checkpoint、control、evidence、`ai_usage_ledger` 和 0 token 标记。
7. `/api/snapshot` 的报告产物必须包含“本轮运行会话 JSON”，证明本轮执行状态可下载、可恢复、可审计。
8. `RunSession.ai_usage_ledger` 必须记录执行期 AI 调用数、token 估算、允许 AI 介入的窗口和违规项；默认执行阶段 `ai_call_count=0`、`token_estimate=0`。

## RunRecovery 中断恢复

如果 Web 控制台重启、headless 进程消失或本地执行被系统中断，不能让会话长期停留在 running 状态。当前契约由 `ReachOps/run_recovery.py` 定义。

要求：

1. 运行态 `RunSession` 在本地进程不存在且没有终态结果时，必须归档为 `BLOCKED`。
2. 归档结果必须写入 `process_interrupted`、`PROCESS_INTERRUPTED` 和 recovery 证据。
3. `/api/logs` 必须触发恢复检查并返回 `recovery` 状态。
4. 新任务启动前必须先归档旧的中断会话，避免新旧 run 证据混淆。
5. 恢复过程是本地规则，不调用 AI，不消耗 token。
6. 暂停、继续、停止和中断恢复必须写入 `control_history`，并进入 EvidenceBundle 的 `control_summary`。
7. AI 操作台复盘必须解释运行控制事件，区分人工停止、系统恢复和执行阻断。

## PageStateDetector 页面状态感知

执行器不能只根据 Selenium 抛错判断成功或失败，必须持续采集页面状态，并把状态写入诊断和证据 sidecar。

当前契约由 `ReachOps/workbench/page_state_detector.py` 定义：

```text
READY
LOGIN_REQUIRED
CAPTCHA_DETECTED
RATE_LIMITED
PAGE_TIMEOUT
DOM_STALLED
MODAL_BLOCKED
COMMENT_BOX_MISSING
SUBMIT_BUTTON_MISSING
UNKNOWN_PAGE_STATE
```

要求：

1. 检测当前 URL、标题、页面文本摘要、按钮状态、弹窗状态和关键选择器数量。
2. 登录、注册、验证码、验证页、限频提示必须分类为阻断状态，不能继续硬执行。
3. 评论框缺失、提交按钮缺失、DOM 卡住必须进入标准页面状态，不能误判为成功。
4. TikTok Selenium 执行器必须把 `page_state` 写入 `page_diagnostics` 和截图 sidecar。
5. 页面状态分类必须是本地规则，不调用 AI，不消耗 token。
6. EvidenceBundle 必须生成 `page_state_summary`，统计页面状态快照、阻断状态、未知状态、登录、验证码、限频和 signals。
7. AI 操作台复盘必须引用 `page_state_summary`，解释页面层面为什么继续、降级或阻断。

## RepairPolicyEngine 自修复策略中心

页面状态和执行错误不能只停留在日志里，必须进入确定性修复策略。

当前契约由 `ReachOps/workbench/repair_policy_engine.py` 定义：

```text
LOGIN_REQUIRED / CAPTCHA_DETECTED / PROXY_FAILED
→ cooldown_profile_and_switch

PAGE_TIMEOUT / DOM_STALLED / MODAL_BLOCKED
→ retry_same_profile_with_backoff

COMMENT_BOX_MISSING / SUBMIT_BUTTON_MISSING
→ degrade_to_collect

UNKNOWN_PAGE_STATE
→ capture_unknown_state_bundle
```

要求：

1. 自修复策略必须是本地规则，不调用 AI，不消耗 token。
2. 登录、验证码、账号受限不能绕过，必须冷却或隔离账号并切换。
3. 页面卡住、超时、弹窗阻断先退避重试，重试耗尽后切换账号或阻断。
4. 评论框或提交按钮缺失不能硬提交，必须降级为只采集或等待人工复核。
5. 未知页面状态必须生成错误包，保留截图、页面状态和 URL。
6. ActionRouter 必须把修复决策写入执行结果和事件日志。

## RiskGate 账号池与风险门禁

真实动作执行前必须先经过统一风险门禁，不能让授权、额度、账号健康和高风险复核散落在不同模块里。

当前契约由 `ReachOps/workbench/risk_gate.py` 定义：

```text
账号健康 / 冷却 / 发布主账号阻断
→ PROFILE_IN_COOLDOWN / PUBLISH_PROFILE_BLOCKED

真实动作授权
→ LIVE_SUBMIT_NOT_AUTHORIZED / LIVE_SUBMIT_DEVICE_MISMATCH / LIVE_SUBMIT_LICENSE_EXPIRED

高风险动作
→ HIGH_RISK_REVIEW_NOTE_REQUIRED

日配额 / 小时限频
→ DAILY_QUOTA_EXCEEDED / RATE_LIMITED
```

要求：

1. 未授权不能真实评论、关注或私信。
2. 登录、验证码、账号受限、冷却账号不能绕过。
3. 发布主账号不能用于获客触达。
4. 高风险动作必须有复核说明。
5. 日配额和小时限频必须在执行前阻断。
6. 风险门禁决策必须写入执行结果，控制台和报告能解释“为什么不执行”。
7. 风险门禁是本地规则，不调用 AI，不消耗 token。
8. EvidenceBundle 必须生成 `risk_summary`，统计允许、阻断、授权阻断、额度阻断、限频阻断、高风险和账号冷却决策。
9. AI 操作台复盘必须引用 `risk_summary`，让运营能看到真实动作为什么被允许、降级或阻断。

## LocalAIConsole 社交式操作台

控制台需要像 AI 与人类互动一样交流，但产品执行不能依赖在线大模型。当前契约由 `ReachOps/ai_console.py` 定义。

职责边界：

1. 运营人员可以输入自然语言，例如“只采集不评论”“为什么停了”“切到真实评论”。
2. 本地规则控制台把自然语言转换为 `ExecutionPlan` 补丁，或从 `RunSession`、执行结果、验收状态中解释阻断原因。
3. `/api/ai-console` 必须返回 `no_ai_token_used=true`、`no_browser_started=true`、`no_submit=true`。
4. Web UI 可以把计划补丁同步到表单和预览，但不能自动点击开始执行。
5. 真实执行仍必须经过 `/api/start`、`ExecutionPlan`、`RunSession`、`RiskGate` 和 `RepairPolicyEngine`。
6. 真实评论、关注、私信等动作必须保留人工授权门禁；AI 控制台不能通过自然语言绕过授权确认。
7. “复盘这次执行”“执行结果报告”等请求必须基于本地 `EvidenceBundle` 生成 `run_recap`，不能依赖在线模型或消耗执行 token。
8. “分析未知错误”“分析未知状态”等请求必须基于本地 `OfflineLearningLedger` 生成 `unknown_state_analysis`，只输出候选分类和候选修复策略，不自动改变真实执行策略。
9. “为什么停了”“为什么卡住”等状态解释必须优先读取 `operator_summary`、`risk_summary`、`page_state_summary`、`repair_summary` 和 `control_summary`，再回退到运行日志或验收状态。

交互形态：

```text
人类自然语言
→ LocalAIConsole 意图解析
→ ExecutionPlan 预览
→ 人类点击开始
→ 本地自治执行
→ RunSession / RiskGate / RepairPolicyEngine 解释状态
→ 控制台以对话形式反馈
```

## EvidenceBundle 证据与复盘闭环

每次执行都必须生成一个统一证据包，证明“计划是什么、程序做了什么、结果是什么、为什么停止或阻断”。当前契约由 `ReachOps/evidence_bundle.py` 定义。

核心内容：

```json
{
  "schema_version": "reachops.evidence_bundle.v1",
  "plan_id": "",
  "session_id": "",
  "summary": {
    "status": "",
    "state": "",
    "target": "",
    "mode": "",
    "profile_group": "",
    "no_ai_token_during_execution": true
  },
  "artifacts": [],
  "timeline": []
}
```

要求：

1. 证据包必须索引 `ExecutionPlan`、`RunSession`、运行结果、运行日志和报告产物。
2. 证据包必须输出 JSON 和 Markdown 两种格式，便于程序读取和人类复盘。
3. `/api/evidence-bundle` 必须返回当前最新证据包。
4. `/api/logs` 和 `/api/snapshot` 必须暴露证据包摘要或路径，控制台报告区可下载。
5. headless 终态结果必须写入 `evidence_bundle` 路径。
6. 证据包只汇总证据，不伪造成功；缺失文件必须标记为 missing。
7. `/api/ai-console` 必须把当前证据包作为运行时上下文传给 `LocalAIConsole`，用于本地 0 token 执行复盘。
8. 证据包必须生成 `repair_summary`，统计修复决策、重试、换号、冷却、降级和修复阻断，证明自修复是否真的发生。
9. 证据包必须生成 `operator_summary` 作为报告首页，给出状态、首要阻断、下一步动作和证据计数。
10. AI 操作台复盘必须优先引用 `operator_summary`，确保对话解释和报告首页一致。
11. `/api/operator-summary` 必须只读返回报告首页、证据包下载路径和 0 token 标记，供控制台直接展示。
12. `/api/snapshot` 必须包含同一份 `operator_summary`，保证运行快照和报告首页一致。
13. 证据包必须生成 `ai_usage_summary`，从 `RunSession.ai_usage_ledger` 汇总执行期 AI 调用数、token 估算和审计状态；AI 操作台复盘必须显示该结果。

## OfflineLearningLedger 未知状态离线学习

未知页面状态不能只留在日志里，也不能自动放行继续硬跑。当前契约由 `ReachOps/workbench/offline_learning_ledger.py` 定义。

要求：

1. `UNKNOWN_PAGE_STATE`、未知执行错误和证据 sidecar 必须生成稳定 signature。
2. 相同未知状态重复出现时累计 `occurrence_count`，保留最近证据路径。
3. 本地规则可以给出候选分类和候选修复策略，例如登录、验证码、限频、评论框缺失。
4. 离线学习结果只能作为规则升级候选，不能自动绕过 `RiskGate` 或改变真实执行策略。
5. `/api/offline-learning` 只读返回学习账本，必须 `no_ai_token_used=true`、`no_browser_started=true`、`no_submit=true`。
6. EvidenceBundle 必须索引离线学习账本和记录数，便于复盘“未知问题是否重复出现”。
7. `/api/ai-console` 可以读取离线学习账本做本地未知状态分析，但分析结果只能作为规则升级候选，不能绕过 `RiskGate`。
8. 重复出现的未知状态必须生成 `policy_candidates` 队列，包含候选页面状态、候选修复动作、出现次数和证据路径。
9. `policy_candidates` 必须 `requires_human_review=true` 且 `auto_apply=false`，人工确认前不能自动写入 PageStateDetector 或 RepairPolicyEngine。

## 核心执行漏斗

本轮任务漏斗必须按 batch 统计：

```text
目标输入
→ 账号启动成功
→ 页面打开成功
→ 视频发现
→ 评论采集
→ 用户去重
→ 意向识别
→ 高意向用户
→ 动作队列
→ 执行前预检
→ 真实提交 / 跳过 / 失败
```

对应数据证据：

- `collection_batches`
- `collection_tasks`
- `growth_events`
- `growth_errors`
- `discovered_contents`
- `candidate_users`
- `operation_leads`
- `action_queue`
- `outreach_executions`

## 模块边界

```text
ReachOps
├── Client UI
├── Workflow Service
├── Collection Scheduler
├── Collector Adapters
├── Growth Storage
├── Lead Scorer
├── Action Router
├── Execution Guard
├── Outreach Executor
└── Report Builder
```

## 实盘功能要求

开始采集页只保留采集参数：

- 来源类型
- 目标输入
- 账号分组
- 每目标视频数
- 每视频评论数
- 最小播放量
- 最小评论数
- 采集并发账号数
- 意向关键词
- 排除关键词

触达执行页只保留触达参数：

- 执行模式
- 触达并发账号
- 单账号本轮上限
- 单账号每小时上限
- 同视频每小时上限
- 评论/关注/私信动作开关
- 失败自动换号
- 冷却阈值

## 验收标准

1. 独立目录可启动。
2. 所有 UI 设置均有真实逻辑。
3. 点击开始后必须创建本轮 batch。
4. 漏斗终端显示本轮实时结果。
5. 每个阶段必须写入事件日志。
6. 错误目标类型在启动前拦截。
7. 账号失败自动换号。
8. 评论、关注、私信有独立执行状态。
9. 私信/关注失败可降级评论。
10. 所有结果可导出 CSV/JSON/日报。
