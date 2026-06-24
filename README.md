# ReachOps

ReachOps 是独立增长获客客户端工程。

目标链路：

```text
产品/关键词/视频/达人/直播间
-> 获客任务
-> 受众画像
-> 来源规划
-> 内容与评论采集
-> 意向识别
-> 客户线索池
-> 触达动作队列
-> 执行前预检
-> 授权真实评论/关注/私信
-> 失败换号、降级评论、限频冷却
-> CSV/JSON 报告
```

## 启动

```bash
python -m ReachOps
```

正式脚本入口：

```bash
python ReachOpsApp.py
```

兼容入口：

```bash
python GrowthIntelligenceApp.py
```

## 测试

```bash
python -m unittest tests.test_reachops_campaign
```

## Windows

启动 UI：

```powershell
powershell -ExecutionPolicy Bypass -File tools\start_reachops_ui_windows.ps1
```

交付验收：

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_reachops_acceptance_windows.ps1
```

构建：

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_reachops_windows.ps1
```

## 独立边界

- 配置目录、数据目录、授权状态使用 `ReachOps/runtime_paths.py` 管理。
- 客户端源码、启动、验收、构建都在本仓库内闭环。
- 不提交运行数据库、报告、证据截图、日志或授权状态文件。
- 真实提交必须经过授权门、证据 sidecar、限频和可追溯报告。
