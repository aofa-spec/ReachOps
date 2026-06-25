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
- 成功动作必须有截图证据和 sidecar 元数据。

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

最终交付必须以 `tools/reachops_goal_status_report.py --json` 返回 `passed` 为准，并且 `effective_pending_external_validation = 0`。
