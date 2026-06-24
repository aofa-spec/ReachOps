# 增长获客工作台产品架构

## 专业命名

中文名：增长获客工作台

英文名：ReachOps

定位：面向运营人员的自动获客执行系统。

## 交付目标

运营输入目标后，系统必须自动完成：

```text
找内容 → 采评论用户 → 识别意向 → 生成线索 → 生成动作
→ 账号执行/预检 → 失败换号 → 输出报告
```

页面上的每一个设置都必须是真实执行参数，不能是伪需求页面。

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

