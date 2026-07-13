# ReachOps 客户端方案生成与移机说明

## 获客方案生成链路

1. 运营在客户端输入推广目标。
   支持产品链接、关键词、达人主页、视频链接、话题和直播间链接。

2. 客户端调用 `GrowthIntelligenceService.create_campaign_plan()`。
   该方法先识别目标类型，再生成 campaign、persona、采集来源和执行策略。

3. 目标识别由 `CampaignAnalyzer` 完成。
   TikTok 达人主页会识别为 `creator_url`，TikTok 视频会识别为 `content_url`，电商/产品链接会识别为 `product_url`，普通文本会识别为 `keyword`。

4. 受众与关键词由两层生成。
   默认使用内置规则生成兴趣、痛点、购买触发词、意向词、排除词、搜索词和话题标签。
   如果配置了 `REACHOPS_AI_ENDPOINT`，会先请求外部 AI 接入点；AI 不可用时自动回退到规则生成。

5. 采集来源由 `SourcePlanner` 生成。
   系统会把产品词、评测词、使用场景词、话题标签等转换成可执行来源，并写入 `acquisition_sources`。

6. 客户端再叠加运营设置。
   `快速/标准/压测` 决定每来源视频数、每视频评论数、参与账号数和任务间隔。
   账号分组来自 ixBrowser 本地 API，默认会选择 United States 分组。

## 移机使用要求

客户换电脑后，必须满足以下条件：

1. 安装并启动 ixBrowser。
2. ixBrowser 已开通并启用本地 API。
3. 目标账号分组存在，例如 `United States`。
4. 分组内有已登录且可打开 TikTok 的账号。
5. 真实打包版本需要激活授权，授权绑定当前设备。
6. 如使用外部 AI，需要配置 AI Endpoint、模型和 Key。

## 客户端运行配置

客户端启动时会读取：

`config/reachops_client_config.json`

首次启动如果文件不存在，会自动生成模板：

```json
{
  "ixbrowser": {
    "api_target": "127.0.0.1",
    "api_port": "",
    "refresh_max_pages": 50
  },
  "ai": {
    "endpoint": "",
    "model": "reachops-default",
    "provider_name": "",
    "timeout_seconds": 20
  }
}
```

该文件用于移机后恢复本地 API 和 AI 接入配置，不依赖开发机环境变量。

## 运行时数据目录

默认数据目录：

- macOS/Linux: `~/.reachops`
- Windows: `%LOCALAPPDATA%\\ReachOps`

目录内保存数据库、日志、报告和授权状态。客户移机时不建议直接复制旧机器授权状态；真实授权应在新机器重新激活。

## 启动诊断日志

客户端启动会写入一条移机诊断日志：

`CONFIG portability ...`

该日志包含数据目录、配置文件路径、运行模式、是否需要激活、设备 ID 前缀、ixBrowser API 地址、AI 是否配置。验收时优先检查这条日志。
