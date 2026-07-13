# ReachOps PM 交付基线

日期：2026-07-04

## 2026-07-04 实时 PM 验收状态

当前项目按 PM 口径判定为：

- `Mac 本地 MVP：实时验收未通过`
- `当前状态：blocked_by_accounts`
- `代码/入口/报告/结构门禁：通过`
- `真实采集/触达门禁：未通过`

实时证据：

- `tools/reachops_client_delivery_check.py --json`
  - `status=blocked_by_accounts`
  - `contract_ok=true`
  - `acceptance_ready=false`
  - `final_delivery_ready=false`
  - `failed_checks=["acceptance:ready"]`
- `tools/reachops_repository_cleanliness_check.py --json`
  - `status=passed`
  - `forbidden_count=0`
- 最新账号修复清单：
  - `reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_profile_remediation.csv`
  - 当前为 42 个唯一账号问题，无重复 profile id。

阻断说明：

United States 分组可以读取，分组数量和验收报告文件可追溯；但最新账号预检 `profile_available=0`，主要问题为 `IXBROWSER_KERNEL_MISMATCH` 和 `LOGIN_REQUIRED`。在至少 1 个 United States 账号达到内核匹配、TikTok 已登录、可手动打开之前，不能宣称 Mac MVP 已通过，也不能进行真实采集/触达验收。

PM 账号修复闭环：

1. Web 面板点击“刷新分组”，确认分组列表和每组数量来自 ixBrowser 实时读取。
2. 当客户端门禁为 `blocked_by_accounts` 且 `profile_available=0` 时，运营可以点击 Web 面板“隔离坏账号”，或运行 `执行ReachOps账号修复.command`。
3. 账号修复只能基于固定最新账号修复计划执行；命令行先运行 `tools/reachops_apply_account_repair_plan.py --json` 预览，输入 `APPLY` 后才调用 ixBrowser Local API 把硬阻断账号移入 `封禁账号`。
4. 修复后必须重新刷新分组，确保 United States 至少保留 1 个内核匹配、TikTok 已登录、可手动打开目标页的账号。
5. 再运行 `复测ReachOps真实执行.command` 和 `tools/reachops_client_delivery_check.py --json`。只有 `status=passed`、`acceptance_ready=true`、`profile_available>=1` 时，Mac 本地 MVP 才能恢复验收。

以下 2026-07-03 内容保留为历史基线和历史验收样例，不能覆盖 2026-07-04 的实时状态。

本文档是当前项目的产品经理交付口径。后续开发、验收、审计都按本文档判断，不再用零散 UI 现象或单个脚本结果替代整体交付结论。

## 1. 产品目标

ReachOps 是给运营人员使用的网页端获客执行控制台。运营只需要在网页端完成：

1. 输入推广目标。
2. 刷新并选择 ixBrowser 账号分组。
3. 点击开始获客。
4. 查看本轮漏斗、日志、账号预检、采集结果和验收报告。

正确架构必须是：

```text
Web 运营面板
  -> 本地 Web API
  -> ReachOps Workflow / Headless Runner
  -> ixBrowser Local API
  -> 指纹浏览器 Profile
  -> TikTok 页面采集 / 预检 / 授权触达
```

运营面板不能是静态演示页；页面上的每一个关键控件都必须对应后端真实参数、运行日志和报告证据。

## 2. 当前交付状态

2026-07-03 历史项目状态曾按 PM 口径判定为：

- `本地 MVP：已通过 2026-07-03 Mac 本地循环验收`
- `最终客户交付：未完成`
- `原因：本地 MVP 需要当前 ixBrowser Local API 实时连通并通过 mac_loop_acceptance；真实授权提交和 Windows 客户端包仍未闭环`

2026-07-04 当前实时证据：

- Web UI：`http://127.0.0.1:8769/`
- 目标模式总报告：`tools/reachops_goal_delivery_runner.py`，自动化读取使用 `--json`
- MVP 汇总：`status=blocked_by_accounts`、`mvp_local_ready=false`；当前账号门禁未通过时，历史本地 MVP 快照不能作为实时验收结论。
- 最终交付：`final_delivery_ready=false`
- 客户端门禁：`status=blocked_by_accounts`、`acceptance_ready=false`、`profile_available=0`
- 交付边界：当前先被账号可用性阻断；整项目最终交付仍以目标总报告顶层 `final_delivery_ready` 和 `final_acceptance_gate` 为准。
- ixBrowser 分组：15 个分组
- ixBrowser 配置总数：2910
- United States 分组：694 个配置
- 最新 Mac 自动循环验收批次：`gb_1f48981b903b4b35`
- 最新批次结论：账号预检可执行，但 `available=0`，主要阻断为 `IXBROWSER_KERNEL_MISMATCH`、`LOGIN_REQUIRED`、页面打开超时；系统没有进入真实采集/触达。
- 最新无触达原因：`no_candidates` / `accounts_unavailable`；当前必须先补齐至少 1 个已登录、内核匹配、可打开 TikTok 的 United States 账号。
- 产品链接识别合同已覆盖 Amazon、Walmart、Etsy、Shop.app、无协议商品链接、query title 商品链接和 TikTok product 路径；商品页只会转成可执行关键词/话题来源，不会把商品页 URL 本身当评论采集源。

2026-07-03 Mac 本地循环验收快照：

| 字段 | 当前值 |
| --- | --- |
| `mac_loop_ready` | `true` |
| `ixbrowser_api_ready` | `true` |
| `groups_fresh` | `true` |
| `group_count / known_group_count` | `15 / 15` |
| `profile_count` | `2910` |
| `last_run_completed` | `true` |
| `acceptance_pass` | `true` |
| `loop_terminal_evidence` | `true` |
| `start_contract_evidence_complete` | `true` |
| `no_headless_timeout_in_current_result` | `true` |
| `no_action_reason_present_when_no_actions` | `true` |
| 候选用户 / 触达动作 | `2 / 0` |
| 无触达原因 | `low_intent_candidates` |

当前本地 MVP 是否可验收必须以实时 `mac_loop_acceptance` 为准：ixBrowser Local API 不在线、分组只来自缓存、或最近一次开始获客链路未完成时，不能宣称 Mac 本地 MVP 当前可交付。

`mac_loop_acceptance` 还必须输出 `start_contract_evidence`：

- `target_planned=true`
- `campaign_started=true`
- `profile_preflight_checked=true`
- `collection_done=true`
- `action_terminal_or_no_submit_reason=true`
- `scoped_log_lines>0`

## 2.1 开始获客产品合同

“开始获客”不是静态按钮，也不是单次 API 调用成功。它必须完成以下链路：

1. 运营输入推广目标：产品链接、关键词、达人主页、视频链接、话题或直播间。
2. 系统识别目标类型，并生成 TikTok 可执行来源。
3. 刷新 ixBrowser 分组，实时读取全部分组列表和每组账号数量。
4. 选择账号分组，后端确认该分组来自当前 ixBrowser 实时列表。
5. 启动本地 headless runner。
6. 账号预检：检查登录态、验证码、代理、页面可打开性和 Profile 启动失败。
7. 用可用账号采集 TikTok 内容和评论用户。
8. 候选用户去重、意向识别和评分。
9. 生成线索和触达动作。
10. 默认 `preflight/no_submit`，不真实评论、不关注、不私信。

“开始获客可用”必须满足：

- ixBrowser Local API 当前 `ready=true`。
- 分组数量实时读取完整，不能只使用缓存分组。
- 选中分组真实存在。
- `/api/start` 能启动本地执行器。
- 日志出现 `PLAN`、`START`、`CHECK profile_preflight`、`DONE collection`。
- 如果没有触达动作，必须说明原因：无候选、低意向、账号不可用、页面失败或策略跳过。该原因必须以结构化 `no_action_reason.code` 出现在 `/api/acceptance`、`tools/reachops_client_delivery_check.py --json`、`tools/reachops_mac_loop_acceptance.py --json` 和目标模式 `local_mvp_evidence` 中。

## 2.2 有效触达定义

触达分三层：

| 模式 | 中文名 | 是否提交平台 | 有效定义 |
| --- | --- | --- | --- |
| `collect_only` | 只采集 | 否 | 产生可解释的候选用户、空结果原因或采集失败原因。 |
| `preflight` | 采集 + 触达预检 | 否 | 目标页面可打开，评论框/关注按钮/私信入口存在，动作状态记录为 preflight 成功或可执行，证据标记 `preflight_only=true/no_submit=true`。 |
| `live_comment` | 采集 + 真实评论 | 是 | 仅在授权目标、激活 ready、人工确认后执行；成功必须有截图、sidecar、`submitted_text` 和 `comment_visible_confirmed=true`。 |

无效触达包括：低意向策略跳过、目标不可访问、账号未登录、验证码、风控、代理失败、评论入口不存在、私信不允许、缺少授权/激活/人工确认时尝试真实提交。

## 3. 本轮必须交付

### 3.1 Web 运营面板

必须交付：

- 推广目标输入。
- 目标类型自动识别。
- ixBrowser 分组刷新按钮。
- 分组列表和每组账号数量。
- 当前选中分组数量。
- 开始获客按钮。
- 暂停、继续、停止。
- 本轮执行漏斗。
- 本轮配置启动列表。
- 运行日志。
- 验收状态。
- 报告下载入口。

验收要求：

- 点击“刷新分组”后必须真实调用 ixBrowser Local API。
- 分组数量必须来自 ixBrowser `profile-list(group_id)` 的真实 `total`，不能用假数据或静态配置。
- ixBrowser 不可用时必须显示明确错误，不能显示 0 个分组误导运营。
- 选择某个分组启动时，后台只能使用该分组账号。

### 3.2 本地执行服务

必须交付：

- `/api/groups`：只读刷新 ixBrowser 分组和数量。
- `/api/start`：启动获客任务。
- `/api/control`：暂停、继续、停止任务。
- `/api/logs`：读取当前运行日志。
- `/api/acceptance`：读取客户端验收状态。
- `/api/final-status`：读取最终交付门禁。
- `/api/ixbrowser-status`：只读检查 ixBrowser API 状态。

验收要求：

- Web API 只绑定 `127.0.0.1`。
- POST 接口必须拒绝非本机来源。
- 默认模式必须是 `preflight/no_submit`。
- 未勾选真实评论确认时，不能提交任何 TikTok 评论、关注或私信。
- 真实执行必须经过激活授权和显式确认。

### 3.3 ixBrowser 配置读取

必须交付：

- 自动读取全部分组列表。
- 显示每个分组账号数量。
- `blocked_by_accounts` 时提供“隔离坏账号”受控入口，避免反复启动同一批硬失败 Profile 占用启动次数。
- 保存最近一次成功读取结果，避免临时失败覆盖有效数据。
- 支持按分组直接读取账号，不依赖全量扫描数千个 Profile。
- 账号预检必须标记登录失效、验证码、代理失败、启动失败等异常。

当前已验证真实数据：

| 分组 | 数量 |
| --- | ---: |
| United States | 700 |
| Canada | 470 |
| Brazil | 593 |
| United Kingdom | 314 |
| 封禁账号 | 86 |

### 3.4 获客 MVP 链路

必须交付：

- 目标识别。
- 来源规划。
- 视频或内容发现。
- 评论用户采集。
- 用户去重。
- 意向识别。
- 线索生成。
- 触达动作预检。
- 执行报告。

验收要求：

- 每个阶段必须有日志。
- 每个批次必须有 batch id。
- 报告必须能追溯到本轮运行。
- 空结果必须解释原因，例如没有候选用户、账号不可用、目标类型不匹配、页面跳转不稳定。

## 4. 最小验收标准

本地 MVP 验收必须全部满足：

| 验收项 | 标准 | 当前状态 |
| --- | --- | --- |
| Web 面板可启动 | `http://127.0.0.1:8769/` 可访问 | 桌面启动入口已具备；当前 Codex 沙箱 `LOCAL_PORT_BIND_BLOCKED`，需以 Mac 桌面 Terminal 实测为准 |
| ixBrowser 实时连通 | `/api/ixbrowser-status ready=true` | 以当前机器状态为准 |
| 分组刷新 | 实时读取 ixBrowser 分组和数量；缓存只展示，不允许启动 | 以当前机器状态为准 |
| 分组选择 | 选择分组后可启动该分组任务 | 以 `mac_loop_acceptance` 为准 |
| 本地任务启动 | `/api/start` 启动 headless runner | 当前账号门禁阻断，不能判定为通过 |
| 账号预检 | 能检查并筛选可用 Profile | 未通过：`profile_available=0`，主要为 `IXBROWSER_KERNEL_MISMATCH`、`LOGIN_REQUIRED` |
| 采集链路 | 出现 `DONE collection` | 未通过：账号不可用导致没有进入有效采集 |
| 默认安全 | no-submit，不真实评论 | 通过 |
| 审计脚本 | `reachops_delivery_audit.py --json` 无失败项 | 未通过：当前默认 audit 有失败项 |
| 项目清洁 | `reachops_repository_cleanliness_check.py --clean --json` 通过 | 通过 |
| 客户端门禁 | `reachops_client_delivery_check.py --json` passed | 未通过：`status=blocked_by_accounts` |
| Mac 自动循环验收 | `reachops_mac_loop_acceptance.py --base-url http://127.0.0.1:8769 --json` passed | 未通过，必须补齐可用账号后复测 |

当前本地 MVP 和客户端交付门禁是否可验收必须以目标模式总报告和 Mac 自动循环验收为准；真实授权提交和 Windows 客户端包仍未闭环，所以不能对外宣称最终交付完成。

## 5. 最终交付验收标准

最终客户交付必须全部满足：

1. `tools/reachops_client_delivery_check.py --json`
   - `status=passed`
   - `final_delivery_ready=true`
   - `failed_checks=[]`

2. `tools/reachops_delivery_package_check.py --json`
   - Windows exe 存在。
   - Installer 存在。
   - update manifest 存在。
   - acceptance summary 存在。
   - `authorization_handoff_payload.json` 存在。
   - `latest_reachops_authorization_handoff.zip` 存在且校验通过，不能包含本地授权输入或激活文件。
   - `latest_live_acceptance_readiness.md/json` 存在。
   - repository cleanliness payload 存在。

3. `tools/reachops_final_acceptance_gate.py --json`
   - `status=passed`
   - `final_delivery_ready=true`
   - 无 pending external validation。

4. 真实授权执行证据
   - 用户明确授权目标链接、账号分组和评论内容。
   - 激活状态有效。
   - Windows acceptance summary 写入 `authorization_handoff`。
   - TikTok 真实提交成功必须有截图和 sidecar 元数据。
   - 不能用 fixture、dry-run、no-submit 结果冒充真实平台提交。

## 6. 边界限制

本项目明确不承诺：

- 不绕过 TikTok 登录、验证码、风控、地域限制或平台权限。
- 不保证每个账号都可用，账号可用性由 ixBrowser Profile 登录态、代理和平台状态决定。
- 不在未授权情况下提交评论、关注或私信。
- 不把 no-submit 预检结果当真实触达成功。
- 不把 Mac 本地验收当 Windows 客户端最终交付。
- 不保证输入任何链接都一定能采集到候选用户；页面无评论、跳转异常、内容不可访问时必须给出错误原因。
- 不把静态 UI、模拟数据、fixture 数据作为客户交付证据。

## 7. 立即收敛任务

为了尽快完成程序，后续只推进以下任务：

1. 产品链接自动识别复测。
   - 状态：已完成。
   - 证据：批次 `gb_3f0656c002024e6b` 日志出现 `input_type=product_url`、产品名 `Owala FreeSip Sway Stainless 30 oz`、可执行关键词来源、账号预检 `available=2`、`DONE collection` 和 `DONE action_preflight skipped ... no_submit=true`。
   - 单元合同：`test_common_product_links_extract_readable_product_names` 覆盖 Amazon、Walmart、Etsy、Shop.app、无协议 URL、query title 和 TikTok product 链接；`test_amazon_product_link_becomes_executable_social_search_sources` 确认商品页会生成 TikTok 可执行搜索/话题来源。

2. 固化 Web 面板分组体验。
   - 刷新按钮必须有可见日志。
   - 分组列表必须显示数量。
   - 当前选中分组必须显示数量和 group id。
   - 页面不能出现控件压缩到不可读。

3. 完成 Windows 交付包。
   - exe、installer、启动脚本、验收脚本、manifest 必须齐全。
   - Windows 端能启动同一套 Web UI。
   - Windows 验收报告必须可复现。

4. 做一次授权真实提交验收。
   - 仅在用户明确授权后执行。
   - 只对授权目标和授权账号执行。
   - 成功或失败都必须产出证据。

## 8. 停止新增范围

在最终交付通过前，暂停新增以下内容：

- 新获客平台。
- 新 AI 策略大改。
- 新仪表盘大屏。
- 新营销文案系统。
- 新多租户权限。
- 新云端同步。

当前优先级只有一个：让现有 Web 面板、ixBrowser 分组、TikTok 采集预检、报告和 Windows 包形成可验收闭环。

## 9. 交付物清单

| 交付物 | 路径或入口 | 状态 |
| --- | --- | --- |
| Web 运营面板 | `http://127.0.0.1:8769/` | 启动入口已具备；当前沙箱不可验证，需 Mac 桌面实测 |
| Mac Web UI 启动脚本 | `启动ReachOps统一WebUI.command` | 已有 |
| 原生 Mac UI 启动脚本 | `启动ReachOps原生MacUI.command` | 已有 |
| 真实执行复测脚本 | `复测ReachOps真实执行.command` | 已有 |
| 验收包入口 | `打开ReachOps验收包.command` | 已有 |
| PM 交付基线 | `ReachOps/docs/REACHOPS_PM_DELIVERY_BASELINE.md` | 当前文档 |
| 真实压力测试报告 | `ReachOps/docs/REACHOPS_REAL_PRESSURE_AUDIT_ACCEPTANCE_REPORT.md` | 已有 |
| 客户端交付计划 | `ReachOps/docs/REACHOPS_CLIENT_DELIVERY_PLAN.md` | 已有 |
| 运营验收矩阵 | `ReachOps/docs/REACHOPS_OPERATOR_ACCEPTANCE_MATRIX.md` | 已有 |
| 目标模式总报告 | `tools/reachops_goal_delivery_runner.py` / `tools/reachops_goal_delivery_runner.py --json` | 可生成；当前状态 `not_ready` |
| Windows 打包前置门禁 | `tools/reachops_windows_package_preflight.py --json` | 通过 |
| Windows 交付包 | exe / installer / manifest / acceptance_summary | 待最终验收 |

Windows 构建合同：`tools\build_reachops_windows.ps1` 默认必须生成 EXE、安装包和 update manifest；只有显式传 `-SkipInstaller` 才允许非最终 EXE-only 构建。`-SkipInstaller` 产物不能通过最终交付门禁。

最终验收包合同：Windows acceptance 必须写出 `windows_package_preflight.json` 并将 `windows_package_preflight` 写入 `acceptance_summary.json`；`delivery_package_check.py` 和 `final_acceptance_gate.py` 会把该报告作为最终 `report_files` 必备证据。

目标模式执行合同：直接运行 `tools/reachops_goal_delivery_runner.py` 会输出 PM 可读摘要，包括执行入口、验收门、交付物、阻断项和下一步命令；加 `--json` 会输出同一份结构化报告，供 Web 面板、自动化验收和最终门禁读取。两种模式都会写出 `reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_goal_delivery_report.json`。

目标模式总报告中的 `delivery_boundary` 是 PM 验收的首读字段：`local_mvp_scope_ready=true` 只在当前 Mac 本地门禁实时通过时才表示可验收；当前 2026-07-04 账号阻断状态下应为 false。`client_gate_scope_ready=true` 表示客户端门禁自身通过，`overall_final_delivery_scope_ready=false` 表示整项目仍未达到最终客户交付。

目标模式总报告中的 `deliverable_index` 是交付物索引：`web_operator_panel.ready`、`local_mvp_acceptance.ready` 必须跟随当前 Mac 本地门禁实时结果，不能沿用历史 ready 快照；`windows_build_inputs.ready=true` 只代表 Windows 构建输入合同可验收。`windows_final_package.ready=false`、`authorized_live_submit.ready=false`、`final_acceptance_gate.ready=false` 代表最终客户交付仍未完成。PM 复核时必须优先看该索引的 ready/missing/blocking_scope，而不是只看单个子门禁的 `final_delivery_ready`。

## 10. PM 结论

当前不要再把问题定义为“页面再美化一下”或“脚本再多跑一次”。项目现在的关键是交付闭环：

```text
真实分组读取
  -> 选中分组启动
  -> 账号预检
  -> 采集完成
  -> 触达预检 / 授权触达
  -> 报告导出
  -> 客户端门禁实时通过
  -> Windows 包交付
```

本地 MVP 和 Mac 客户端目标模式门禁具备验收基础，但当前 2026-07-04 实时账号门禁未通过；最终交付只在 Mac MVP、授权真实提交和 Windows 包全部闭环后才能宣布完成。
