# ReachOps Mac 本地 MVP 验收交付单

日期：2026-07-04

## 2026-07-04 实时验收状态

当前 Mac 本地 MVP **未通过实时验收**，状态为 `blocked_by_accounts`。

当前结论以本机最新门禁为准：

- `tools/reachops_client_delivery_check.py --json`：`status=blocked_by_accounts`
- `contract_ok=true`
- `acceptance_ready=false`
- `final_delivery_ready=false`
- `failed_checks=["acceptance:ready"]`
- United States 分组可读，当前缓存/只读元数据约 `694` 个配置。
- 最新账号预检 `profile_available=0`，不能进入真实采集/触达验收。
- 阻断原因：United States 分组内当前可检查账号存在 `IXBROWSER_KERNEL_MISMATCH`、`LOGIN_REQUIRED` 等账号状态问题。
- 最新修复清单：`reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_profile_remediation.csv`
- 项目结构清洁度：`tools/reachops_repository_cleanliness_check.py --json` 返回 `status=passed`、`forbidden_count=0`。

通过 Mac MVP 的下一步硬标准：

1. 点击 Web 面板的“刷新分组”，确认 United States 分组来自 ixBrowser 实时列表且显示账号数量。
2. 如果门禁仍为 `blocked_by_accounts`，点击 Web 面板“隔离坏账号”，或运行 `执行ReachOps账号修复.command`。
3. 账号修复必须使用固定最新账号修复计划，先预览 `tools/reachops_apply_account_repair_plan.py --json`，确认后再输入 `APPLY` 执行 `--apply`，把 `IXBROWSER_KERNEL_MISMATCH`、`LOGIN_REQUIRED`、验证码、代理失败等硬阻断账号移入 `封禁账号`。
4. 在 ixBrowser 的 United States 分组内保留至少 1 个账号。
5. 该账号内核版本匹配当前 ixBrowser 支持版本，当前错误提示要求 `138` 内核。
6. 该账号 TikTok 已登录，且可手动打开目标页面。
7. 再次刷新 Web 面板分组并运行 `复测ReachOps真实执行.command`。
8. 最新门禁达到 `acceptance_ready=true`，并出现 `available>=1`、`DONE collection`、`START action_preflight` 或结构化 `no_action_reason`。

以下 2026-07-03 内容保留为历史通过样例，不能替代 2026-07-04 的实时验收结论。

## 交付结论

第一阶段 Mac 本地 MVP 曾在 2026-07-03 达到本地循环验收条件。当前交付的是“运营网页端控制本地真实执行链路”，不是静态页面。

当前不可声明最终客户交付完成。最终交付仍需要 Windows 最终包和授权真实提交证据。

## 已交付链路

```text
Web 运营面板
  -> 本地 Web API
  -> ReachOps headless runner
  -> ixBrowser Local API
  -> 指纹浏览器 Profile
  -> TikTok 采集 / 触达预检
  -> 日志 / 漏斗 / 证据 / 验收报告
```

## 当前运行入口

- Web UI：`http://127.0.0.1:8769/`
- 目标模式入口：`tools/reachops_goal_delivery_runner.py --json`
- 两阶段验收矩阵：`tools/reachops_two_phase_acceptance_matrix.py --write --json`
- Mac 循环验收入口：`tools/reachops_mac_loop_acceptance.py --base-url http://127.0.0.1:8769 --json`
- 客户端门禁入口：`tools/reachops_client_delivery_check.py --json`
- 账号修复入口：`执行ReachOps账号修复.command`
- 项目清洁度入口：`tools/reachops_repository_cleanliness_check.py --clean --json`

## PM / 架构签收范围

第一阶段签收的是 Mac 本地 MVP：

- 运营通过网页端控制本地 API，而不是打开静态页面。
- 本地 API 调用 ReachOps headless runner，而不是前端模拟结果。
- runner 读取 ixBrowser Local API 的当前分组和账号数量。
- 选择分组后只使用该分组账号进入预检和采集。
- 默认执行 `preflight/no_submit`，不会真实评论、关注或私信。
- 日志、漏斗、账号预检、候选用户、触达预检或跳过原因都能追溯到最近批次。

第二阶段才签收最终客户交付：

- 授权真实触达完成。
- Windows exe、installer、update manifest、acceptance summary 齐全。
- `final_delivery_ready=true`、`failed_checks=[]`、无 pending external validation。

## 当前验收快照

| 项 | 当前值 |
| --- | --- |
| `status` | `passed` |
| `mac_loop_ready` | `true` |
| `ixbrowser_api_ready` | `true` |
| `groups_fresh` | `true` |
| `group_count` | `15` |
| `known_group_count` | `15` |
| `profile_count` | `2910` |
| 选中分组 | `United States` |
| 选中分组账号数 | `698` |
| 最新批次 | `gb_d2928a2643d64aba` |
| 最近执行状态 | `completed` |
| 候选用户 | `3` |
| 触达预检动作 | `3` |
| 触达预检成功 | `3` |
| 无触达原因 | 不适用，`actions>0` |
| `no_headless_timeout_in_current_result` | `true` |
| `start_contract_evidence_complete` | `true` |
| `no_action_reason_present_when_no_actions` | `true` |

当前最新批次已产生 3 个候选用户和 3 个触达预检动作，预检成功 3 个。系统按默认 no-submit/preflight 策略验证入口，不真实评论、关注或私信。

## 开始获客机器证据

`tools/reachops_mac_loop_acceptance.py --json` 必须输出：

```json
"start_contract_evidence": {
  "target_planned": true,
  "campaign_started": true,
  "profile_preflight_checked": true,
  "collection_done": true,
  "action_terminal_or_no_submit_reason": true,
  "scoped_log_lines": 97
}
```

并且 `checks.start_contract_evidence_complete=true`。这代表最近一次开始获客已经完成目标规划、批次启动、账号预检、采集完成，以及触达预检终态或可解释跳过原因。

## “开始获客”验收定义

“开始获客”必须完成：

1. 运营输入推广目标。
2. 系统识别目标类型并生成可执行来源。
3. 实时刷新 ixBrowser 分组和账号数量。
4. 选择真实存在的账号分组。
5. `/api/start` 启动本地 headless runner。
6. Profile 预检。
7. TikTok 内容和评论用户采集。
8. 候选用户去重、意向识别、评分。
9. 生成线索和触达动作。
10. 默认 `preflight/no_submit`，不真实评论、不关注、不私信。

可验收证据必须包含：`PLAN`、`START`、`CHECK profile_preflight`、`DONE collection`，以及触达预检结果或结构化可解释跳过原因。若 `actions=0`，`/api/acceptance`、`tools/reachops_client_delivery_check.py --json` 和 `tools/reachops_mac_loop_acceptance.py --json` 必须输出 `no_action_reason.code`。

## 有效触达边界

| 模式 | 是否真实提交 | 当前阶段是否交付 |
| --- | --- | --- |
| `collect_only` | 否 | 是 |
| `preflight` | 否 | 是 |
| `live_comment` | 是 | 否，进入第二阶段 |

当前阶段只允许默认 no-submit 预检。真实评论必须等到授权目标、激活状态 ready、人工确认和平台证据完整后才能进入最终验收。

有效触达不能只看动作队列数量：

- 预检有效触达：目标页面可打开，评论框、关注按钮或私信入口存在，动作没有真实提交，状态记录为 preflight 成功或可执行，证据标记 `preflight_only=true/no_submit=true`。
- 真实有效触达：动作真实提交成功，并有平台页面证据证明动作完成；评论必须包含截图、sidecar、`submitted_text` 和 `comment_visible_confirmed=true`。
- 无效触达：低意向、目标不可访问、账号未登录、验证码、风控、代理失败、Profile 启动失败、评论入口不存在、私信不允许，或缺少授权、激活、人工确认时尝试真实提交。

因此，`actions=0` 不是自动失败；只有缺少结构化原因才是失败。若系统输出 `low_intent_candidates`、`no_candidates`、`accounts_unavailable`、`page_unstable` 等明确原因，且 no-submit 策略生效，可以作为本地 MVP 的安全收口证据。

## 本地 MVP 签收标准

PM/架构签收第一阶段时，必须逐项核对：

| 验收项 | 签收标准 |
| --- | --- |
| Web 面板 | `http://127.0.0.1:8769/` 可访问，关键控件对应后端 API。 |
| ixBrowser 状态 | `/api/ixbrowser-status` 返回 `ready=true`。 |
| 分组刷新 | 点击刷新后实时读取全部分组和数量，`stale_cache=false`。 |
| 缓存保护 | 只有缓存或刷新失败时允许展示，但不能允许开始获客。 |
| 分组选择 | 选中分组必须存在于当前 ixBrowser 列表，启动时使用该分组。 |
| 本地执行 | `/api/start` 成功启动 headless runner。 |
| 执行证据 | 日志出现 `PLAN`、`START`、`CHECK profile_preflight`、`DONE collection`。 |
| 账号预检 | 能输出可用账号、不可用账号和跳过原因。 |
| 采集收口 | 最近批次完成，不存在 `HEADLESS_TIMEOUT`。 |
| 触达安全 | 默认 `no_submit=true`，未授权不会真实评论、关注或私信。 |
| 空动作解释 | `actions=0` 时必须输出 `no_action_reason.code`。 |
| 报告证据 | `latest_delivery_check.json`、目标模式总报告和本地 MVP 交付单可追溯。 |

## 验收命令

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_apply_account_repair_plan.py --json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_mac_loop_acceptance.py --base-url http://127.0.0.1:8769 --json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_client_delivery_check.py --json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_repository_cleanliness_check.py --clean --json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_two_phase_acceptance_matrix.py --write --json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_web_panel_dom_smoke.py --json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_web_panel_runtime_smoke.py --json
```

`tools/reachops_apply_account_repair_plan.py --json` 只预览，不移动账号；只有 Web 面板“隔离坏账号”确认后，或 `执行ReachOps账号修复.command` 中输入 `APPLY` 后，才允许调用 ixBrowser Local API 移动账号。修复后必须重新刷新分组并复跑客户端门禁，不能把“已生成修复计划”当成 Mac MVP 通过。

前三条和两阶段矩阵的 `local_mvp_ready=true` 同时成立时，第一阶段 Mac 本地 MVP 可交付。矩阵的 `final_delivery_ready=false` 代表第二阶段仍未签收，不影响第一阶段结论。

## 最终交付阻断

目标模式当前状态：

- `local_mvp_ready=true`
- `final_delivery_ready=false`
- `blocking_scopes=["windows_final_artifacts", "external_authorized_execution"]`

缺失最终产物：

- `dist/ReachOps/ReachOps.exe`
- `dist/installer/ReachOps-Setup-0.4.0.exe`
- `dist/installer/reachops-update-manifest.json`
- `reports/reachops_acceptance/acceptance_summary.json`
- Windows acceptance 目录中的 `authorization_handoff_payload.json`
- Windows acceptance 目录中的 `latest_reachops_authorization_handoff.zip`
- Windows acceptance 目录中的 `latest_live_acceptance_readiness.md/json`

缺失授权真实提交证据：

- 授权 TikTok 目标。
- 激活状态 ready。
- 确认后的评论内容。
- `acceptance_summary.authorization_handoff`。
- 平台提交截图和 sidecar。
- `submitted_text`。
- `comment_visible_confirmed=true`。

## 最终客户交付标准

第二阶段最终签收必须同时满足：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_goal_delivery_runner.py --json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_two_phase_acceptance_matrix.py --refresh --write --require-final --json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_delivery_package_check.py --json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_issue_closure_audit.py --json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_final_acceptance_gate.py --json
```

通过标准：

- 顶层 `final_delivery_ready=true`。
- 两阶段矩阵严格模式返回 0。
- `failed_checks=[]`。
- 无 pending external validation。
- Windows `ReachOps.exe`、安装包、update manifest、`acceptance_summary.json` 存在且校验通过。
- 授权真实触达证据完整，评论可见性已确认。
- Windows 上同一套 Web UI 和本地执行链路可运行。

## 禁止误判

- 不把缓存分组当作可启动依据。
- 不把 `client_delivery.final_delivery_ready=true` 当整项目最终交付完成。
- 不把 no-submit 预检当真实触达成功。
- 不把 Mac 本地 MVP 当 Windows 客户端最终交付。
