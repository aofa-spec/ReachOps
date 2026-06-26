# ReachOps

ReachOps 是独立增长获客客户端工程。

当前版本：`0.4.0` / `mvp`，基线 tag：`v0.4.0-mvp`。

当前交付状态：

- Stage 1 ReachOps MVP：本地已实现并通过验收。
- Stage 2 触达计划 MVP：本地已实现并通过验收。
- Stage 3 真实执行：授权门、限频、冷却、换号、降级和证据链路已实现；真实 TikTok 平台提交仍需 Windows + ixBrowser + 真实账号外部验收。
- Stage 4 AI 增强：AI/规则双通道、话术、来源扩展、人工可编辑策略已实现。
- Stage 5 独立打包：Windows `ReachOps.exe`、installer、update manifest、installer smoke 和非真实提交 acceptance 已在 Windows VM 验证通过；真实平台提交仍需外部验收。

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
python ReachOpsApp.py
```

兼容入口：

```bash
python GrowthIntelligenceApp.py
```

## 本地验收

```bash
python3 -m unittest tests.test_reachops_campaign
python3 tools/reachops_operator_pressure.py --json
python3 tools/reachops_delivery_audit.py --json
python3 tools/reachops_goal_status_report.py --json
```

通过标准：

- 单测通过。
- operator pressure 返回 `status=ok`。
- delivery audit 返回 `status=ok` 且 `failed=0`。
- goal status 可到 `ready_for_external_validation`；真实平台提交前不应宣称 `passed`。
- `tools/reachops_delivery_package_check.py` 需要 Windows 产物和 acceptance reports；本机没有这些产物时返回缺失是预期状态。

## Windows 客户端

启动 UI：

```powershell
powershell -ExecutionPolicy Bypass -File tools\start_reachops_ui_windows.ps1
```

UI 启动 smoke：

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_reachops_ui_startup_smoke_windows.ps1
```

构建：

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_reachops_windows.ps1
```

非真实提交验收：

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_reachops_acceptance_windows.ps1
```

Windows 真实交付验收请先阅读：

```text
ReachOps/docs/REACHOPS_OPERATOR_ACCEPTANCE_MATRIX.md
ReachOps/docs/REACHOPS_DELIVERY_EXECUTION_PLAN.md
ReachOps/docs/REACHOPS_WINDOWS_LIVE_ACCEPTANCE_RUNBOOK.md
```

## 真实账号 readiness / preflight

实机参数模板：

```powershell
Copy-Item tools\reachops_acceptance_inputs.example.ps1 tools\reachops_acceptance_inputs.local.ps1
notepad tools\reachops_acceptance_inputs.local.ps1
powershell -ExecutionPolicy Bypass -File tools\reachops_acceptance_inputs.local.ps1
```

`tools\reachops_acceptance_inputs.local.ps1` 已被 `.gitignore` 排除，不能提交真实账号、目标或授权路径。

缺少真实参数时，可以先运行 readiness / preflight 门控生成 blocked 报告；这些检查不会提交评论、关注或私信：

```powershell
python tools\reachops_activation_status_template.py --bind-current-device --enable-live-submit --enable-comment-reply --enable-follow-review --enable-dm-review --json
python tools\reachops_activation_status_check.py --activation-status-path "C:\path\to\reachops_activation_status.json" --json
python tools\reachops_live_acceptance_status.py --json
powershell -ExecutionPolicy Bypass -File tools\run_reachops_live_readiness_windows.ps1
powershell -ExecutionPolicy Bypass -File tools\run_reachops_live_preflight_windows.ps1
```

`tools\reachops_activation_status_template.py` 只生成授权状态模板；模板文件带有 `template_only=true`，不能作为真实授权通过。

`tools\reachops_live_acceptance_status.py` 只读状态，不打开浏览器、不提交动作，用来汇总当前还缺本地输入、有效授权、目标 URL 还是真实提交证据。

当前 Windows VM 最新实机状态：

- 已识别数字 Profile ID：`27273`、`27240`、`27230`。
- readiness 报告：`reports\reachops_live_readiness\20260626_122513\live_readiness_payload.json`，状态 blocked，原因是授权文件仍为 template，错误码 `LIVE_SUBMIT_NOT_AUTHORIZED`，并确认 `no_browser_started=true`、`no_submit=true`。
- 最新 acceptance summary：`reports\reachops_acceptance\20260626_123159\acceptance_summary.json`，package check 为 `ready_for_external_validation`，pending 包含 `external_platform_validation` 和 `live_preflight_environment_validation`。
- preflight 报告：`reports\reachops_acceptance\20260626_123159\live_preflight_payload.json`，状态 completed/no-submit，但 3 个 Profile 均在 ixBrowser `open_profile` 阶段失败，错误码 `PROFILE_START_FAILED`，原因是 `Socks5 Authentication failed`。报告包含账号切换记录、错误证据 URI 和本地 JSON evidence sidecar；后续 preflight/acceptance summary 会额外写入 `environment_diagnostics`，按 Profile 聚合 `ixbrowser_open_profile`、`socks5_auth_failed`、`proxy_detection_failed` 等环境 blocker。
- 在代理认证修复、目标 URL 替换为授权真实目标、激活文件变为有效状态前，不应运行 `-RunLiveSubmit`。

## 受控真实提交

真实提交只允许在 readiness/preflight 通过、目标被授权、激活文件有效后执行：

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_reachops_acceptance_windows.ps1 `
  -ProfileIds "123,456" `
  -CommentVideoUrl "https://www.tiktok.com/@creator/video/123" `
  -FollowProfileUrl "https://www.tiktok.com/@target_user" `
  -DmProfileUrl "https://www.tiktok.com/@target_user" `
  -TargetUsername "target_user" `
  -ActivationStatusPath "C:\path\to\reachops_activation_status.json" `
  -RunLiveSubmit `
  -ConfirmAuthorizedTargets
```

最终交付通过标准：

- `dist\ReachOps\ReachOps.exe` 存在。
- `dist\installer\ReachOps-Setup-0.4.0.exe` 存在。
- `dist\installer\reachops-update-manifest.json` hash 校验通过。
- `reports\reachops_acceptance\<timestamp>\acceptance_summary.json` 中 `status=passed`。
- `effective_pending_external_validation=0`。
- 真实 comment/follow/DM 尝试都有执行记录、错误码或截图证据。

最终交付包检查：

```powershell
python tools\reachops_delivery_package_check.py --json
```

中间态检查允许外部真实平台 pending：

```powershell
python tools\reachops_delivery_package_check.py --allow-external-pending --json
```

中间态 package check 也要求 `live_readiness_payload.json` 和 `live_preflight_payload.json` 存在；缺真实参数时它们应为 blocked/no-submit 报告。

## 运行边界

- 配置目录、数据目录、授权状态使用 `ReachOps/runtime_paths.py` 管理。
- 客户端源码、启动、验收、构建都在本仓库内闭环。
- 不提交运行数据库、报告、证据截图、日志或授权状态文件。
- 默认行为不得真实提交评论、关注或私信。
- 真实提交必须经过授权门、证据 sidecar、限频和可追溯报告。
- 启动 ixBrowser Profile 后如果 TikTok 出现登录/注册弹窗或强制登录页，系统必须立即记录 `LOGIN_REQUIRED`，停止该账号的获客采集流程，并进入账号不可用处理。
- 登录/注册弹窗（Login/signup dialogs）属于账号未登录状态，不应关闭配置列表后继续执行获客流程。
