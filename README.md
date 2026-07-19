# ReachOps

ReachOps 是独立增长获客客户端工程。

当前版本：`0.4.0` / `mvp`，基线 tag：`v0.4.0-mvp`。

PM 交付基线：`ReachOps/docs/REACHOPS_PM_DELIVERY_BASELINE.md`。目标模式执行说明：`ReachOps/docs/REACHOPS_GOAL_MODE_EXECUTION.md`。后续验收先看这两份文档；当前 2026-07-04 实时口径是“Mac MVP 账号阻断，最终客户交付未完成”。

当前交付状态：

- Stage 1 ReachOps MVP：本地链路已实现；当前实时验收 `blocked_by_accounts`，需 United States 至少 1 个内核匹配且 TikTok 已登录账号后复测。
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

客户端入口已统一到本地客户端控制台；以下命令会启动本地 127.0.0.1 控制台并打开浏览器：

```bash
python -m ReachOps
python ReachOpsApp.py
```

Mac 桌面推荐双击本地客户端入口：

```text
启动ReachOps本地客户端.command
启动ReachOps统一WebUI.command
```

旧 Tk 仅作为诊断入口保留，需要时显式开启：

```bash
python ReachOpsApp.py --legacy-tk
REACHOPS_LEGACY_TK=1 python ReachOpsApp.py
```

Web 控制台也可用开发命令直接启动，用于调试本机后端执行链路：

```bash
python tools/reachops_web_ui.py --web --host 127.0.0.1 --port 8769
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
python3 tools/reachops_goal_delivery_runner.py --json
python3 tools/reachops_goal_status_report.py --json
```

通过标准：

- 单测通过。
- operator pressure 返回 `status=ok`。
- delivery audit 返回 `status=ok` 且 `failed=0`。
- goal delivery runner 返回 `local_mvp_ready=true`，并用 `delivery_boundary` / `deliverable_index` 区分本地 MVP 与最终交付。
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

默认构建必须生成 `ReachOps.exe`、安装包和 update manifest；如果传 `-SkipInstaller`，只能作为非最终 EXE-only 构建，不可用于最终交付门禁。

非真实提交验收：

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_reachops_acceptance_windows.ps1
```

SSH 或远程桌面不稳定时，用后台模式启动，再重新连接查询结果：

```powershell
powershell -ExecutionPolicy Bypass -File tools\start_reachops_acceptance_background_windows.ps1 -ConfirmAuthorizedTargets
powershell -ExecutionPolicy Bypass -File tools\get_reachops_acceptance_background_status_windows.ps1 -Json
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
powershell -ExecutionPolicy Bypass -File tools\init_reachops_acceptance_inputs_windows.ps1
notepad tools\reachops_acceptance_inputs.local.ps1
powershell -ExecutionPolicy Bypass -File tools\reachops_acceptance_inputs.local.ps1
```

Mac 本地也可以先生成同一份本地验收输入文件，再复制/同步到 Windows 实机补齐真实授权参数：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/init_reachops_acceptance_inputs.py --json
```

已有本地文件时可以只更新已授权字段；确认所有 TikTok 目标已授权后再加 `--confirm-authorized-targets`：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/init_reachops_acceptance_inputs.py --update-existing --comment-video-url "https://www.tiktok.com/@creator/video/..." --follow-profile-url "https://www.tiktok.com/@target" --dm-profile-url "https://www.tiktok.com/@target" --target-username "target" --activation-status-path "/path/to/reachops_activation_status.json" --confirm-authorized-targets --json
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

`tools\reachops_live_acceptance_status.py` 只读状态，不打开浏览器、不提交动作，用来汇总当前还缺本地输入、有效授权、目标 URL、真实提交证据或客户端交付门禁。若已有 acceptance summary，它会在 `next_required_actions` 中展开具体待处理项。

客户端交付门禁可独立复测，不会打开浏览器或提交动作：

```powershell
python tools\reachops_client_delivery_check.py --json
python tools\reachops_client_delivery_check.py --base-dir "reports\reachops\mac_gui\runtime" --output "reports\reachops\mac_gui\runtime\reports\acceptance_remediation\latest_delivery_check.json" --json
```

最终交付不能只看 `contract_ok=true`；必须同时满足 `status=passed`、`final_delivery_ready=true`、`acceptance_ready=true`、`readiness=pass`、`failed_checks=[]`，并且 `delivery_check_path` 指向已落盘的 `latest_delivery_check.json`。网页端 `/api/acceptance` 会同步写出这份客户端门禁报告，便于运营和交付复核。若输出 `status=blocked_by_environment` 且 `failed_checks=["acceptance:ready"]`，说明启动入口、报告和 UI 合同可用，但真实客户端执行证据仍被账号/环境阻断。

当前工作区最终交付状态：

- `tools\reachops_goal_delivery_runner.py --json` 当前应以实时门禁为准；在最新 Mac 证据中客户端门禁为 `status=blocked_by_accounts`、`profile_available=0`，因此 Mac 本地 MVP 不能声明通过。Windows 最终包和授权真实提交仍然是最终交付阻断项。
- 目标模式总报告的 `deliverable_index` 是交付物索引；当前账号门禁失败时，`web_operator_panel.ready` 和 `local_mvp_acceptance.ready` 必须跟随实时门禁显示 blocked，不能用历史 ready 快照覆盖。`windows_final_package.ready=false`、`authorized_live_submit.ready=false`、`final_acceptance_gate.ready=false` 仍然阻断最终交付。
- 当前 `/Users/aofa/Documents/New project` 没有 Windows `dist\` 交付产物，也没有本地最终 `acceptance_summary.json`。
- `tools\reachops_client_delivery_check.py --json` 当前返回 `status=blocked_by_accounts`、`readiness=blocked_by_accounts`、`acceptance_ready=false`、`profile_available=0`；最新账号预检阻断为 `IXBROWSER_KERNEL_MISMATCH`、`LOGIN_REQUIRED` 和页面打开超时。
- `tools\reachops_delivery_package_check.py --allow-external-pending --json` 当前返回 `status=failed`、`final_delivery_ready=false`，缺失 `exe`、`installer`、`manifest`、`acceptance_summary`。
- `tools\reachops_final_acceptance_gate.py --json` 当前返回 `status=not_ready`、`final_delivery_ready=false`，失败项为 `goal_status:passed`、`delivery_package:passed`。
- 旧 Windows VM 验收记录只能作为诊断参考，不能作为当前工作区最终交付通过证据。

历史 Windows VM 诊断记录：

- 已识别数字 Profile ID：`27273`、`27240`、`27230`。
- readiness 报告：`reports\reachops_live_readiness\20260626_122513\live_readiness_payload.json`，状态 blocked，原因是授权文件仍为 template，错误码 `LIVE_SUBMIT_NOT_AUTHORIZED`，并确认 `no_browser_started=true`、`no_submit=true`。
- 历史 acceptance summary：`reports\reachops_acceptance\20260626_133256\acceptance_summary.json`，package check 为 `ready_for_external_validation`，`effective_pending_external_validation=3`，pending 包含 `external_platform_validation`、`live_preflight_environment_validation` 和客户端交付验收门禁。
- acceptance preflight 报告：`reports\reachops_acceptance\20260626_123159\live_preflight_payload.json`，状态 completed/no-submit，但 3 个 Profile 均在 ixBrowser `open_profile` 阶段失败，错误码 `PROFILE_START_FAILED`，原因是 `Socks5 Authentication failed`。
- 最新 standalone preflight 报告：`reports\reachops_live_preflight\20260626_124345\live_preflight_payload.json`，已包含 `environment_diagnostics`：`blocking_stage=ixbrowser_open_profile`，`failed_profile_ids=["27230","27240","27273"]`，真实 `open_profile` 失败 4 次，账号切换 2 次，分类为 `socks5_auth_failed`、`proxy_detection_failed`、`legacy_adapter_missing`。该报告确认 `no_submit=true`、`preflight_only=true`，并生成本地 JSON evidence sidecar。
- 在代理认证修复、目标 URL 替换为授权真实目标、激活文件变为有效状态前，不应运行 `-RunLiveSubmit`。

## 受控真实提交

真实提交只允许在 readiness/preflight 通过、目标被授权、激活文件有效后执行：

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_reachops_acceptance_windows.ps1 `
  -InputFile .\tools\reachops_acceptance_inputs.local.ps1 `
  -RunLiveSubmit `
  -ConfirmAuthorizedTargets
```

最终交付通过标准：

- `dist\ReachOps\ReachOps.exe` 存在。
- `dist\installer\ReachOps-Setup-0.4.0.exe` 存在。
- `dist\installer\reachops-update-manifest.json` hash 校验通过。
- `reports\reachops_acceptance\<timestamp>\acceptance_summary.json` 中 `status=passed`。
- `reports\reachops_acceptance\<timestamp>\repository_cleanliness_payload.json` 和 `windows_package_preflight.json` 存在，且 package `report_files.repository_cleanliness`、`report_files.windows_package_preflight` 通过。
- `effective_pending_external_validation=0`。
- 真实 comment/follow/DM 尝试都有执行记录、错误码或截图证据。

最终交付包检查：

```powershell
python tools\reachops_delivery_package_check.py --json
```

严格最终验收 gate：

```powershell
python tools\reachops_final_acceptance_gate.py --json
```

最终交付必须同时让 package check 返回 `status=passed`、`final_delivery_ready=true`，并让 final acceptance gate 返回 `status=passed`、`final_delivery_ready=true`。最终 package check 默认必须验证 `final_acceptance_gate.json`、`repository_cleanliness_payload.json` 和 `windows_package_preflight.json`；`--allow-missing-final-gate` 只允许 Windows acceptance 脚本首次 bootstrap 包检查使用，此时 JSON 会标记 `bootstrap_only=true`、`final_delivery_ready=false`，不能作为最终交付标准。`ready_for_external_validation`、`blocked_by_environment` 或缺少 `exe/installer/manifest/acceptance_summary/final_acceptance_gate/repository_cleanliness/windows_package_preflight` 都不是最终交付通过。

中间态检查允许外部真实平台 pending：

```powershell
python tools\reachops_delivery_package_check.py --allow-external-pending --json
```

中间态 package check 也要求 `live_readiness_payload.json` 和 `live_preflight_payload.json` 存在；缺真实参数时它们应为 blocked/no-submit 报告。

## 运行边界

- 配置目录、数据目录、授权状态使用 `ReachOps/runtime_paths.py` 管理。
- 客户端源码、启动、验收、构建都在本仓库内闭环。
- 运营主入口是网页端统一控制台；网页端通过本地 HTTP API (`/api/start`, `/api/logs`, `/api/snapshot`, `/api/acceptance`, `/api/control`) 调用本机服务端。
- 本机服务端启动 headless 执行层并复用 `GrowthIntelligenceService` / `GrowthWorkflowService`，由服务端调用 ixBrowser 本地 API 打开指纹浏览器 Profile，再通过 Selenium 采集和触达；核心获客执行不依赖运营手动操作桌面 GUI。
- 不提交运行数据库、报告、证据截图、日志或授权状态文件。
- 默认行为不得真实提交评论、关注或私信。
- 真实提交必须经过授权门、限频和可追溯报告；成功动作必须写出本地截图证据和 sidecar，不能用 `evidence://...` 作为真实提交成功证据。
- 启动 ixBrowser Profile 后如果 TikTok 出现登录/注册弹窗或强制登录页，系统必须立即记录 `LOGIN_REQUIRED`，停止该账号的获客采集流程，并进入账号不可用处理。
- 登录/注册弹窗（Login/signup dialogs）属于账号未登录状态，不应关闭配置列表后继续执行获客流程。
