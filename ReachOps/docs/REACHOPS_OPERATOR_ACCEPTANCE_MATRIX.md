# ReachOps 客户端运营验收矩阵

本文档定义 ReachOps 的客户端验收方式：按客户能不能完成获客验收，不按代码模块是否存在验收。

## 1. 客户完成获客的 4 步

1. 输入获客目标  
   支持产品关键词、产品链接、达人链接、视频链接、话题、直播间。客户不需要理解 `source_type`、`campaign_id`、`candidate_user` 等技术对象。

2. 选择账号资源  
   客户选择 ixBrowser 分组，例如 Canada、US、BR。刷新必须完整读取真实 Profile，再按 `group_id/group_name` 聚合分组。选择哪个分组，后台就只能使用哪个分组的账号。

3. 启动自动获客任务  
   系统自动执行：目标分析、受众画像、来源规划、内容发现、评论用户采集、去重、意图识别、客户线索、触达动作、执行预检或授权执行。

4. 查看结果和导出  
   客户能看到本轮漏斗、终端日志、错误码、账号切换、成功失败统计，并导出客户池和执行报告。

## 2. 可见控件必须是真功能

| 客户可见设置 | 后台必须执行 | 必须留下的证据 |
| --- | --- | --- |
| 推广目标 | 创建 AcquisitionCampaign，自动识别目标类型，生成获客来源 | `PLAN campaign` 日志、Campaign 报告 |
| 账号分组 | 全量刷新 ixBrowser Profile，按分组选择账号 | `CONFIG refresh_profiles`、`CONFIG selected_profiles` 日志 |
| 每个目标最多视频 | 限制每个来源/达人扫描的视频数 | `max_videos` 日志、Collection Batch 配置 |
| 每条视频最多评论 | 限制单视频评论采集数 | `max_comments` 日志、Collection Batch 配置 |
| 参与账号数 | 限制本轮使用的 Profile 数 | Profile preflight 日志、账号列表 |
| 任务间隔秒 | 写入任务节奏和限频配置 | `interval_seconds` 日志 |
| 意向词 | 进入意图识别和评分规则 | Campaign strategy、候选用户评分原因 |
| 排除词 | 进入过滤规则，降低垃圾评论进入客户池 | Campaign strategy、候选用户过滤结果 |
| 触达并发 | 控制预检/执行线程数 | Action router 日志、执行报告 |
| 开始获客 | 启动真实 WorkflowService 链路 | 漏斗、日志、客户池、动作队列 |
| 导出报告 | 导出当前 Campaign 的 JSON/CSV | 报告路径、`report_exported` 事件 |

任何新增 UI 控件，如果没有对应后台执行、日志证据和报告字段，应视为伪 UI，不能进入验收版本。

## 3. 账号资源验收

账号分组必须满足：

- 刷新时读取真实 ixBrowser Profile 列表。
- 从 Profile 的 `group_id/group_name` 聚合分组。
- 显示分组名、分组 ID 和账号数量。
- 选择 Canada 时，只能执行 Canada 的 Profile。
- 空响应不得覆盖上一次成功读取的分组。
- 未登录、验证码、代理失败、Profile 启动失败账号必须标记为不可用或冷却。
- `blocked_by_accounts` 且 `profile_available=0` 时，Web 面板必须显示“隔离坏账号”入口；命令行必须提供 `执行ReachOps账号修复.command`，先预览 `tools/reachops_apply_account_repair_plan.py --json`，确认后才把硬阻断账号移入 `封禁账号`。
- 账号修复后必须重新刷新分组并复跑 `tools/reachops_client_delivery_check.py --json`；只生成账号修复计划不算验收通过。
- 触达必须优先使用通过预检的登录账号。

必须记录的错误码：

- `LOGIN_REQUIRED`
- `CAPTCHA_DETECTED`
- `PROXY_FAILED`
- `PROFILE_START_FAILED`
- `CREATOR_PAGE_OPEN_FAILED`
- `COMMENT_SCAN_EMPTY`
- `COMMENT_SCAN_FAILED`
- `LIVE_SUBMIT_LICENSE_REQUIRED`
- `LIVE_SUBMIT_EVIDENCE_MISSING`

## 4. 漏斗验收

漏斗只显示本轮 Campaign 和本轮 Batch，不允许混入历史累计数据。

漏斗最少包含：

- 目标来源数
- 通过预检账号数
- 打开页面数
- 发现内容数
- 评论用户数
- 去重后用户数
- 意向客户数
- 生成触达动作数
- 本轮选中执行动作数
- 执行成功数
- 执行失败数
- 账号切换次数
- 首要错误码

## 5. 真实执行验收

默认模式必须是预检，不提交评论、关注、私信。

真实执行必须同时满足：

- 有效激活状态。
- 当前设备绑定通过。
- `live_submit/comment_reply/follow_review/dm_review` 能力开启。
- `executor_mode` 必须是 `platform_selenium`，fixture 或 dry-run 结果不能算真实平台提交。
- 目标链接和账号由操作者确认授权。
- Readiness 通过。
- Preflight 通过。
- 成功动作必须有本地截图证据和 sidecar 元数据；`evidence://...` 只能用于预检/fixture 记录，不能作为真实提交成功证据。
- sidecar 必须包含匹配截图文件的 `screenshot_sha256`、`action_type`、`profile_id`、`action_id` 和 `current_url`；评论提交还必须包含匹配话术的 `submitted_text` 且 `comment_visible_confirmed=true`。

私信或关注失败时，系统可以按策略降级评论；账号失败时必须自动换号或冷却，不得继续使用异常账号高频执行。

## 6. 导出验收

导出不能只证明文件存在，必须证明客户可继续运营。

JSON 报告必须包含：

- Campaign 信息
- 受众画像
- 来源规划
- 本轮漏斗
- 错误统计
- 客户线索池
- 运营线索
- 触达动作队列

客户 CSV 必须包含：

- username
- profile_url
- qualify_score
- intent_tags
- comment_text
- video_url
- batch_id

动作 CSV 必须包含：

- target_username
- action_type
- status
- risk_level
- suggested_text
- target_url
- batch_id

执行报告必须包含：

- 总动作数
- 成功数
- 失败数
- 错误统计

## 7. 当前状态判定

当前本地验收允许达到 `ready_for_external_validation`，表示：

- Stage 1 ReachOps MVP 已本地验证。
- Stage 2 触达计划 MVP 已本地验证。
- Stage 4 AI/规则增强已本地验证。
- Stage 5 非真实提交打包链路已有 Windows 中间态验证。
- Stage 3 真实平台提交仍需 Windows VM、真实 ixBrowser Profile、真实 TikTok 账号和授权目标证明。

运营和 PM 复核必须先看目标模式总报告：

- 执行入口：`tools/reachops_goal_delivery_runner.py --json`。
- `delivery_boundary.local_mvp_scope_ready=true` 只在当前 Mac 本地门禁实时通过时表示可验收；账号阻断时必须为 false。
- `delivery_boundary.overall_final_delivery_scope_ready=false` 表示整项目不能宣称最终交付。
- `deliverable_index.web_operator_panel.ready`、`deliverable_index.local_mvp_acceptance.ready` 必须跟随当前实时门禁，不能用历史 ready 快照覆盖；`deliverable_index.windows_build_inputs.ready=true` 表示 Windows 构建输入已具备交付条件。
- `deliverable_index.windows_final_package.ready=false`、`deliverable_index.authorized_live_submit.ready=false`、`deliverable_index.final_acceptance_gate.ready=false` 表示 Windows 最终包、授权真实提交和最终门禁仍未闭环。

最终交付不能只看 goal status。必须同时满足：

- `tools/reachops_goal_delivery_runner.py --json` 返回 `final_delivery_ready=true`，且 `delivery_boundary.overall_final_delivery_scope_ready=true`。
- `tools/reachops_goal_status_report.py --json` 返回 `passed`，且 `effective_pending_external_validation = 0`。
- `tools/reachops_client_delivery_check.py --json` 返回 `status=passed`、`final_delivery_ready=true`、`failed_checks=[]`。
- `tools/reachops_delivery_package_check.py --json` 返回 `status=passed`，并验证 Windows exe、installer、update manifest、acceptance summary、`repository_cleanliness_payload.json`、`windows_package_preflight.json`、`issue_closure_payload.json` 和 `final_acceptance_gate.json`。
- `tools/reachops_issue_closure_audit.py --json` 返回 Issues #1-#7 全部本地合同通过、`acceptance_criteria_external_pending=0`、`external_pending_count=0`、`closure_requires_external_validation=false`。
- `tools/reachops_final_acceptance_gate.py --json` 返回 `status=passed`、`final_delivery_ready=true`、`failed_checks=[]`，且包含通过的 `commercial_issue_closure:closed` 检查。
