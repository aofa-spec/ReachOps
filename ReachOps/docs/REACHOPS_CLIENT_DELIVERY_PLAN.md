# ReachOps 客户端获客工作台完整开发计划

## 1. 项目目标

ReachOps 的验收标准不是“模块存在”，而是客户能否用客户端完成获客。

客户打开 ReachOps 后，只需要完成 4 步：

1. 输入获客目标：产品关键词、产品链接、达人链接、视频链接、话题、直播间。
2. 选择账号资源：选择 ixBrowser 账号分组，例如 Canada、US、BR。
3. 启动自动获客任务：系统自动分析目标、规划来源、采集互动用户、识别意向、生成客户线索和触达动作。
4. 查看结果和导出：看到本轮漏斗、日志、错误码、账号切换、成功失败统计，并导出 CSV/JSON。

一句话目标：

> 客户输入一个产品或目标人群，选择账号分组，点击开始，客户端自动帮他找到潜在买家、判断意向、生成触达动作，并把执行过程和结果清楚展示出来。

## 2. 产品定位

ReachOps 是一个独立获客客户端，不是普通数据采集器。

核心能力：

- 从推广目标自动生成社媒获客计划。
- 从 TikTok 相关内容评论区发现潜在买家。
- 对评论用户做去重、意向识别和评分。
- 生成评论、关注、私信动作计划。
- 在授权允许时执行真实触达。
- 用账号预检、失败换号、冷却、限频和降级评论保证账号可用性。

边界：

- 默认不真实提交评论、关注、私信。
- 真实执行必须经过授权门。
- 不绕过验证码、登录、平台风控或访问限制。
- 遇到登录失效、验证码、代理失败、页面打不开等状态，只记录错误码、证据和账号状态，并切换可用账号。

## 3. 运营控制台目标形态

### 3.1 首页：获客任务

首页必须是运营能直接理解的工作台，不是技术配置页。

必须保留：

- 推广目标输入框。
- 账号分组选择。
- 刷新账号分组。
- 开始获客。
- 导出报告。
- 采集范围设置。
- 自动采集方案。
- 本轮漏斗。
- 量化执行终端。

不应暴露给普通运营：

- `source_type`
- `campaign_id`
- `datasource`
- `candidate_user`
- `checkpoint`
- 其他内部技术对象名

### 3.2 自动采集方案

客户输入推广目标后，系统必须展示真实计划：

- 识别结果：商品页、关键词、达人主页、视频链接、标签、直播间。
- 推广对象：产品名、关键词或目标人群。
- 执行路径：分析目标 -> 规划来源 -> 找相关视频/达人/话题 -> 扫评论区 -> 去重 -> 意图识别 -> 客户线索 -> 触达动作预检。
- 采集来源：系统自动规划出的关键词、标签、话题、达人、视频。
- 来源分层：核心产品内容、评测/对比内容、效果验证内容、使用场景内容、话题标签内容。
- 本轮范围：账号分组、参与账号数、每来源视频数、每视频评论数、任务间隔。
- 意向判断词：购买、咨询、找链接、问价格、问效果、问产品名等。
- 排除规则：垃圾评论、娱乐评论、抽奖评论、机器人评论等。

示例：

输入：

```text
https://www.amazon.com/Retinol-Anti-Aging-Face-Serum/dp/B0ABC12345
```

系统应规划：

```text
keyword: Retinol Anti Aging Face Serum
keyword: Retinol Anti Aging Face Serum review
keyword: Retinol Anti Aging Face Serum before after
keyword: Retinol Anti Aging Face Serum routine
keyword: Retinol Anti Aging Face Serum tiktok shop
hashtag: retinolantiagingface
```

### 3.3 量化执行终端

终端必须按执行漏斗分区：

- 左侧：本轮漏斗结果。
- 右侧：总日志、采集、视频、评论、线索、触达、异常。

双击可最大化全屏。

日志必须实时显示：

- 目标识别。
- 来源规划。
- 账号分组读取。
- 账号登录态预检。
- 页面打开。
- 视频发现。
- 评论采集。
- 用户去重。
- 意图评分。
- 线索生成。
- 触达动作生成。
- 执行预检。
- 错误码和证据。
- 账号切换。

## 4. 总体架构

```text
ReachOps Client
  |
  |-- Workbench UI
  |     |-- 获客任务入口
  |     |-- 自动采集方案
  |     |-- 本轮漏斗
  |     |-- 量化执行终端
  |     |-- 线索池
  |     |-- 触达执行
  |     |-- 账号诊断
  |     |-- 报告中心
  |
  |-- Campaign Intelligence
  |     |-- AcquisitionCampaign
  |     |-- AudiencePersona
  |     |-- SourcePlanner
  |     |-- CampaignFunnel
  |     |-- StrategyBuilder
  |
  |-- Collection Runtime
  |     |-- ixBrowser Profile Adapter
  |     |-- TikTok Search Collector
  |     |-- TikTok Topic Collector
  |     |-- TikTok Profile Collector
  |     |-- TikTok Video Collector
  |     |-- TikTok Comment Collector
  |     |-- Live Room User Collector
  |
  |-- Lead Engine
  |     |-- CandidateUser
  |     |-- dedupe
  |     |-- intent classifier
  |     |-- scorer
  |     |-- operation lead pool
  |
  |-- Outreach Engine
  |     |-- comment action
  |     |-- follow action
  |     |-- dm action
  |     |-- templates
  |     |-- account allocation
  |     |-- preflight
  |     |-- authorization gate
  |     |-- execution evidence
  |
  |-- Safety / Account Control
  |     |-- login check
  |     |-- captcha detection
  |     |-- proxy check
  |     |-- account cooldown
  |     |-- failover
  |     |-- rate limits
  |     |-- fallback to comment
  |
  |-- Reporting
        |-- current campaign JSON
        |-- customer CSV
        |-- action CSV
        |-- execution report
```

## 5. 核心数据对象

### 5.1 AcquisitionCampaign

代表一次获客任务。

字段：

- id
- input_type
- input_value
- product_name
- category
- objective
- target_market
- target_language
- status
- created_at
- updated_at

### 5.2 AudiencePersona

代表系统对目标客户的理解。

字段：

- campaign_id
- demographics
- interests
- pain_points
- buying_triggers
- intent_keywords
- exclude_keywords
- search_keywords
- hashtags
- competitor_terms
- outreach_angles

### 5.3 AcquisitionSource

代表系统实际要执行的采集来源。

字段：

- campaign_id
- source_type
- source_value
- reason
- priority
- status

来源类型：

- keyword
- hashtag
- topic
- creator_url
- content_url
- live_room_url
- product_url
- shop_url

### 5.4 CampaignFunnel

代表本轮任务漏斗，不混历史累计。

字段：

- campaign_id
- batch_id
- target_sources
- profile_ok
- page_opened
- content_found
- comment_users
- dedup_users
- high_intent
- customer_leads
- outreach_actions
- preflight_ok
- execution_success
- failed
- account_switches
- error_counts

## 6. 执行流程

### 6.1 输入目标

用户输入：

- 产品关键词
- Amazon / Shopify / TikTok Shop / 其他商品链接
- TikTok 达人主页
- TikTok 视频链接
- TikTok 标签/话题
- 直播间链接

系统自动识别：

- 商品页
- 关键词
- 达人主页
- 视频链接
- 标签
- 直播间活跃用户

### 6.2 分析目标

系统生成：

- 产品名
- 品类
- 目标客户画像
- 痛点
- 购买触发词
- 咨询触发词
- 排除词

### 6.3 规划采集来源

按沙漏方式规划来源：

1. 核心产品词。
2. 评测词。
3. 效果对比词。
4. 使用场景词。
5. 社媒购物场景词。
6. 产品话题标签。
7. 行业话题标签。
8. 竞品/同类达人方向。

美妆示例：

```text
Retinol Anti Aging Face Serum
Retinol Anti Aging Face Serum review
Retinol Anti Aging Face Serum before after
Retinol Anti Aging Face Serum routine
Retinol Anti Aging Face Serum tiktok shop
#retinolantiagingface
#skincare
#beautyroutine
```

### 6.4 采集内容

系统按来源打开 TikTok：

- 搜索页
- 标签页
- 达人主页
- 视频详情页
- 直播间

采集：

- 视频链接
- 达人
- 标题/描述
- 播放量
- 点赞数
- 评论数
- 商品/店铺信号
- 相关性评分

### 6.5 扫评论区

对相关视频打开评论区，采集：

- 用户名
- 用户主页
- 评论内容
- 评论点赞数
- 回复数
- 评论语言
- 评论时间
- 来源视频

### 6.6 线索沉淀

系统执行：

- 用户去重。
- 评论去噪。
- 购买/咨询/兴趣/娱乐/垃圾分类。
- 线索评分。
- 高意向线索入池。

评分规则：

- 70-100：高价值线索。
- 40-69：可观察。
- 0-39：低价值。

加分项：

- 问购买链接。
- 问价格。
- 问产品名。
- 问效果。
- 问使用方式。
- 评论被点赞。
- 评论有回复。
- 来源视频播放量高。
- 来源视频评论数高。
- 用户多次出现在不同内容评论区。

### 6.7 生成触达动作

对线索生成动作：

- 评论回复。
- 关注。
- 私信。

动作必须包含：

- action_type
- target_username
- target_url
- suggested_text
- risk_level
- review_status
- recommended_profile_id
- block_reason

默认状态：

- 预检，不提交。
- 需要授权才能真实执行。

### 6.8 执行预检

执行前检查：

- 账号是否登录。
- 是否出现验证码。
- 代理是否失败。
- 页面是否可打开。
- 评论框是否存在。
- 关注按钮是否存在。
- 私信入口是否存在。
- 账号是否冷却。
- 日配额是否超限。
- 小时限频是否超限。

### 6.9 授权真实执行

真实提交必须满足：

- 客户显式开启授权。
- 动作通过复核。
- 账号通过预检。
- 未触发限频。
- 有证据记录。

执行策略：

- 私信可用则私信。
- 私信不可用则尝试关注。
- 关注失败或限制则降级评论。
- 账号失败自动换号。
- 连续失败进入冷却。

## 7. 错误码

必须进入日志和错误诊断，不允许弹窗卡死。

账号类：

- PROFILE_START_FAILED
- LOGIN_REQUIRED
- CAPTCHA_DETECTED
- PROXY_FAILED
- PROFILE_IN_COOLDOWN
- NO_LOGGED_IN_PROFILE_AVAILABLE

采集类：

- CREATOR_PAGE_OPEN_FAILED
- TOPIC_CONTENT_SCAN_FAILED
- VIDEO_SCAN_FAILED
- VIDEO_SCAN_EMPTY
- COMMENT_SCAN_FAILED
- COMMENT_SCAN_EMPTY
- COMMENT_ACCESS_GATED

触达类：

- ACTION_REQUIRES_REVIEW
- ACTION_REQUIRES_EXECUTION_CONFIRMATION
- COMMENT_BOX_NOT_FOUND
- COMMENT_SUBMIT_FAILED
- COMMENT_BLOCKED
- FOLLOW_BUTTON_MISSING
- FOLLOW_RATE_LIMITED
- DM_ENTRY_NOT_FOUND
- DM_NOT_ALLOWED
- DM_RATE_LIMITED

系统类：

- CHECKPOINT_WRITE_FAILED
- REPORT_EXPORT_FAILED
- ACTION_ROUTER_EXCEPTION
- DAILY_QUOTA_EXCEEDED
- VIDEO_HOURLY_LIMIT_EXCEEDED
- PROFILE_HOURLY_LIMIT_EXCEEDED

## 8. 账号资源管理

### 8.1 分组读取

刷新分组必须：

- 调用 ixBrowser 真实分组列表。
- 完整读取 Canada、US、BR 等分组。
- 显示分组名、group_id、账号数或待读取账号数。
- 保留上一次成功缓存，避免 API 空返回导致 UI 清空。

### 8.2 分组执行

选择哪个分组，就必须实际使用该分组。

不能出现：

- UI 显示 Canada，后台用了默认分组。
- UI 显示 BR，后台按缓存账号执行。
- 刷新后只显示部分分组。

### 8.3 登录态预检

开始采集前先做账号预检：

- 打开 TikTok 消息页或轻量页面判断登录态。
- 登录弹窗 -> LOGIN_REQUIRED。
- 验证码 -> CAPTCHA_DETECTED。
- 代理失败 -> PROXY_FAILED。
- 可用账号进入任务池。
- 不可用账号标记并可移动到封禁/异常分组。

## 9. UI 验收标准

页面必须满足：

- 首页就是“获客任务”。
- 没有技术语言干扰。
- 所有按钮都是真实功能。
- 设置项都进入任务配置。
- 采集范围说明清楚。
- 自动采集方案清楚。
- 终端日志实时滚动。
- 错误不弹窗卡死。
- 漏斗显示本轮 Campaign，不混历史。
- 导出只导出本轮 Campaign。

## 10. 阶段开发计划

### 阶段 1：ReachOps MVP

目标：

跑通产品/关键词到客户池。

交付：

- 获客任务入口。
- 输入类型识别。
- 基础受众画像。
- 来源规划。
- 评论用户采集。
- 去重。
- 规则意图识别。
- 客户池。
- 本轮实时漏斗。
- CSV/JSON 报告。

验收：

- 输入产品链接可创建 Campaign。
- 系统自动生成采集来源。
- 可采集评论用户。
- 可生成客户线索。
- 可导出客户 CSV 和 JSON。

### 阶段 2：触达计划 MVP

目标：

从客户池生成动作并预检。

交付：

- 评论动作生成。
- 关注动作生成。
- 私信动作生成。
- 话术模板。
- 账号分配。
- 执行前预检。
- 失败原因。
- 动作报告。

验收：

- 高意向线索能生成触达动作。
- 默认不提交真实动作。
- 预检能识别登录、验证码、代理、入口不可用。
- 动作 CSV 可导出。

### 阶段 3：真实执行

目标：

可控真实评论、关注、私信。

交付：

- 真实评论。
- 真实关注。
- 真实私信。
- 失败换号。
- 降级评论。
- 冷却机制。
- 限频。
- 授权门。
- 执行证据。

验收：

- 授权关闭时绝不提交。
- 授权开启且复核通过时可执行。
- 私信失败可降级评论。
- 关注失败可换号。
- 账号失败进入冷却。
- 所有执行有证据。

### 阶段 4：AI 增强

目标：

自动理解产品和客户。

交付：

- AI 产品分析。
- AI 受众画像。
- AI 评论意图分类。
- AI 话术推荐。
- AI 来源扩展。
- 人工可编辑策略。

验收：

- 商品链接能生成更准确产品名、品类、痛点、关键词。
- 评论能按购买、咨询、兴趣、垃圾分类。
- 运营能编辑 AI 策略。

### 阶段 5：独立打包

目标：

作为独立客户端交付。

交付：

- 独立 ixBrowser adapter。
- 独立配置目录。
- 独立数据目录。
- 授权绑定。
- Windows 打包。
- 安装包。
- 升级机制。

验收：

- Windows 客户端可独立启动。
- 数据目录独立。
- 授权绑定生效。
- 可升级。

## 11. 当前优先级

短期不要继续做 UI 装饰，优先做真实获客闭环：

1. 自动采集方案必须稳定展示真实来源规划。
2. 关键词/标签/话题来源必须真实进入执行任务。
3. 分组刷新必须完整读取 ixBrowser。
4. 开始任务必须先做登录态预检。
5. 评论采集失败必须换号或记录错误码。
6. 本轮漏斗必须按 Campaign 显示。
7. 导出报告必须只导出本轮。
8. 触达动作必须默认预检，不误提交。
9. 授权真实执行必须有证据和失败降级。

## 12. 测试计划

### Test 1：产品链接获客

输入 Amazon 商品链接。

要求：

- 自动识别商品页。
- 提取产品名。
- 生成关键词、评测词、效果词、场景词、标签。
- 采集相关视频。
- 扫评论。
- 生成客户线索。
- 导出报告。

### Test 2：关键词获客

输入：

```text
anti aging serum
```

要求：

- 自动识别关键词。
- 生成受众画像。
- 规划 TikTok 搜索来源。
- 采集评论用户。
- 输出客户池。

### Test 3：达人链接获客

输入 TikTok 达人主页。

要求：

- 扫描视频。
- checkpoint 去重。
- 采集新视频评论。
- 第二次运行不重复写视频和用户。

### Test 4：账号分组执行

选择 Canada 分组。

要求：

- 实际按 Canada group_id 拉取 Profile。
- 未登录账号被识别。
- 可用账号进入任务。
- 不可用账号被标记。

### Test 5：异常处理

模拟：

- 未登录。
- 验证码。
- 代理失败。
- 页面打不开。
- 无公开视频。
- 评论为空。

要求：

- 程序不中断。
- 不弹窗卡死。
- 有错误码。
- 有证据。
- 自动继续下一个任务或账号。

### Test 6：触达预检

对客户池生成评论、关注、私信动作。

要求：

- 默认不提交。
- 生成动作报告。
- 识别不可执行原因。
- 私信/关注不可用时生成降级评论。

### Test 7：授权真实执行

授权开启后小批量执行。

要求：

- 真实动作数量可控。
- 有账号、目标、动作、结果、证据。
- 失败自动换号。
- 超限进入冷却。

## 13. 完成交付定义

ReachOps 客户端最终交付必须同时满足：

- 输入产品/关键词即可创建获客任务。
- 系统能自动生成受众画像。
- 系统能自动规划来源。
- 系统能发现内容。
- 系统能采集互动用户。
- 系统能识别购买/咨询意向。
- 系统能生成客户线索。
- 系统能生成触达动作。
- 系统能执行预检。
- 授权允许时能真实执行。
- 账号失败能自动换号。
- 私信/关注失败能降级评论。
- 全程有实时漏斗。
- 全程有错误码和证据。
- 可导出客户名单和执行报告。

未满足真实执行授权验收前，不能宣称完整最终交付，只能宣称阶段 1/2 MVP 交付。
