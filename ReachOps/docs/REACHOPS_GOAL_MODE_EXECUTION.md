# ReachOps 目标模式执行说明

本文是 PM、运营和交付复核的单文件入口。目标模式不是单个按钮测试，而是把 Web 面板、ixBrowser 分组读取、本地执行链路、Windows 包和最终门禁合并成一份可审计状态。

## 1. 执行入口

本地目标模式总控：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_goal_delivery_runner.py --json
```

两阶段 PM/架构验收矩阵：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_two_phase_acceptance_matrix.py --refresh --write --json
```

第二阶段 Windows / 授权触达交接检查：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_phase2_handoff_check.py --write --json
```

该命令会同时写出：

```text
reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_phase2_handoff_check.json
reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_phase2_handoff_check.md
```

其中 Markdown 报告会列出授权输入字段状态、占位字段、激活状态、Windows 实机执行命令和最终包缺失项。`ready_for_windows_execution=true` 只代表可以进入 Windows 实机阶段；只有 `final_delivery_ready=true` 才能算最终交付。

最终客户交付严格矩阵：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_two_phase_acceptance_matrix.py --refresh --write --require-final --json
```

该命令会写出：

```text
reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_goal_delivery_report.json
reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_goal_delivery_summary.md
reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_two_phase_acceptance_matrix.json
reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_two_phase_acceptance_matrix.md
reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_phase2_handoff_check.json
reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_phase2_handoff_check.md
```

Web 运营面板：

```text
http://127.0.0.1:8769/
```

第二阶段 Windows + 授权真实触达交接手册：

```text
ReachOps/docs/REACHOPS_PHASE2_WINDOWS_AUTH_HANDOFF.md
```

`latest_goal_delivery_report.json` 给自动化和 Web 面板读取，`latest_goal_delivery_summary.md` 给 PM/运营交接复核。Web 面板只做运营控制台；真实执行链路必须由本地服务 API 调用 ixBrowser 本地 API 和本地 runner 完成。
`latest_two_phase_acceptance_matrix.*` 把同一份目标证据拆成第一阶段 Mac 本地 MVP 和第二阶段最终客户交付两组逐条验收项，避免把本地通过误判为最终交付。

## 2. 当前验收口径

目标模式总报告的首读字段是 `delivery_boundary`：

- `delivery_boundary.local_mvp_scope_ready=true`：Mac 本地 MVP 可验收。
- `delivery_boundary.client_gate_scope_ready=true`：客户端门禁自身通过。
- `delivery_boundary.windows_build_input_scope_ready=true`：Windows 构建输入和脚本合同可验收；这不代表当前 Mac 本地 MVP 已通过。
- `delivery_boundary.overall_final_delivery_scope_ready=false`：整项目仍未达到最终客户交付。

目标模式总报告的交付物索引是 `deliverable_index`：

- `deliverable_index.web_operator_panel.ready`：跟随当前 Mac 本地门禁实时结果，账号阻断时为 false。
- `deliverable_index.local_mvp_acceptance.ready`：跟随当前 Mac 本地门禁实时结果，不能使用历史快照。
- `deliverable_index.windows_build_inputs.ready=true`
- `deliverable_index.windows_final_package.ready=false`
- `deliverable_index.authorized_live_submit.ready=false`
- `deliverable_index.final_acceptance_gate.ready=false`

因此当前状态只能验收本地 MVP，不能宣称最终交付。

注意：`local_mvp_scope_ready=true` 现在必须包含 `tools/reachops_mac_loop_acceptance.py --base-url http://127.0.0.1:8769 --json` 通过。历史成功批次、缓存分组或客户端门禁通过，都不能单独证明当前 Mac 本地执行链路可交付。

## 2.1 开始获客合同

“开始获客”必须证明完整执行链路，而不是只证明按钮可点击：

```text
输入推广目标
-> 目标类型识别
-> 生成可执行来源
-> 实时刷新 ixBrowser 分组和账号数量
-> 选择分组
-> /api/start 启动 headless runner
-> Profile 预检
-> TikTok 内容/评论用户采集
-> 候选用户去重和意向评分
-> 生成线索和触达动作
-> 默认 no-submit 触达预检
```

可启动条件：

- ixBrowser Local API 当前 ready。
- 分组不是缓存，且账号数量实时读取完整。
- 选中分组存在于当前 ixBrowser 分组列表。
- 最近一次执行日志能看到 `PLAN`、`START`、`CHECK profile_preflight`、`DONE collection`。
- 无触达动作时，报告必须解释原因。

## 2.2 有效触达定义

- `collect_only`：只采集，不提交平台动作。有效结果是候选用户、空结果原因或采集失败原因可解释。
- `preflight`：默认模式，采集 + 触达预检，不提交平台动作。有效结果是目标页面和评论/关注/私信入口可验证，证据标记 `preflight_only=true/no_submit=true`。
- `live_comment`：授权模式，真实评论提交。必须有授权目标、激活 ready、人工确认和平台证据；成功评论必须证明 `submitted_text` 和 `comment_visible_confirmed=true`。

## 3. 本地 MVP 验收标准

本地 MVP 可验收必须同时满足：

- Web 面板可访问并能展示最终交付状态。
- `/api/groups` 能读取 ixBrowser 分组列表和每个分组账号数量。
- `/api/groups` 不能只返回缓存结果作为启动依据；缓存只允许展示和提示阻断。
- Mac MVP 要求本次刷新返回的全部分组账号数量都可验证；只验证选中分组不再允许通过。
- 运营选择分组后，`/api/start` 使用该分组启动本地执行链路。
- 默认 no-submit，未授权或未确认时不能真实评论、关注或私信。
- `tools/reachops_client_delivery_check.py --json` 返回 `status=passed`、`readiness=pass`、`failed_checks=[]`。
- `tools/reachops_mac_loop_acceptance.py --json` 返回 `status=passed`、`mac_loop_ready=true`，用于确认最近一次 Mac Web UI 自动循环已稳定收口且没有 `HEADLESS_TIMEOUT` 残留。
- `tools/reachops_repository_cleanliness_check.py --json` 返回 `status=passed`。

## 4. 最终交付标准

最终交付不能只看 goal status，也不能只看客户端门禁。必须同时满足：

- `tools/reachops_goal_delivery_runner.py --json` 返回 `final_delivery_ready=true`。
- `tools/reachops_two_phase_acceptance_matrix.py --refresh --write --require-final --json` 返回 0，且 `final_delivery_ready=true`。
- `delivery_boundary.overall_final_delivery_scope_ready=true`。
- `tools/reachops_goal_status_report.py --json` 返回 `passed`，且 `effective_pending_external_validation=0`。
- `tools/reachops_client_delivery_check.py --json` 返回 `status=passed`、`final_delivery_ready=true`、`failed_checks=[]`。
- `tools/reachops_delivery_package_check.py --json` 返回 `status=passed`、`final_delivery_ready=true`。
- `tools/reachops_final_acceptance_gate.py --json` 返回 `status=passed`、`final_delivery_ready=true`、`failed_checks=[]`。
- Windows 最终包存在并可校验：`ReachOps.exe`、安装包、update manifest、`acceptance_summary.json`、`windows_package_preflight.json`、`authorization_handoff_payload.json`、`latest_reachops_authorization_handoff.zip`、`final_acceptance_gate.json`。
- Windows acceptance 必须生成授权交接证据：`latest_live_acceptance_readiness.md`、`latest_live_acceptance_readiness.json`、`authorization_handoff_payload.json`、`latest_reachops_authorization_handoff.zip`。
- 授权真实提交证据完整，评论动作必须证明 `submitted_text` 和 `comment_visible_confirmed`。

## 5. 当前最终交付阻断

当前阻断范围：

- `windows_final_artifacts`
- `external_authorized_execution`

当前缺失最终产物：

- `dist/ReachOps/ReachOps.exe`
- `dist/installer/ReachOps-Setup-0.4.0.exe`
- `dist/installer/reachops-update-manifest.json`
- `reports/reachops_acceptance/acceptance_summary.json`

当前应执行的 Windows 修复命令：

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_reachops_windows.ps1
powershell -ExecutionPolicy Bypass -File tools\init_reachops_acceptance_inputs_windows.ps1
powershell -ExecutionPolicy Bypass -File tools\run_reachops_acceptance_windows.ps1 -InputFile .\tools\reachops_acceptance_inputs.local.ps1 -RunLiveSubmit -ConfirmAuthorizedTargets
python tools\reachops_delivery_package_check.py --json
python tools\reachops_final_acceptance_gate.py --json
```

Mac 本地可以先生成同一份 git-ignored 验收输入文件，用于提前消除“本地输入文件缺失”阻断：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/init_reachops_acceptance_inputs.py --json
```

已有本地文件时可以增量写入授权字段：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/init_reachops_acceptance_inputs.py --update-existing --comment-video-url "https://www.tiktok.com/@creator/video/..." --follow-profile-url "https://www.tiktok.com/@target" --dm-profile-url "https://www.tiktok.com/@target" --target-username "target" --activation-status-path "/path/to/reachops_activation_status.json" --confirm-authorized-targets --json
```

生成后必须人工替换 `tools/reachops_acceptance_inputs.local.ps1` 中的真实授权字段：

- `ProfileIds`
- `CommentVideoUrl`
- `FollowProfileUrl`
- `DmProfileUrl`
- `TargetUsername`
- `ActivationStatusPath`
- `ConfirmAuthorizedTargets`

该文件存在不代表最终交付完成；只有所有占位值被授权真实目标替换、激活状态 ready、Windows acceptance 生成 passed summary 后，最终门禁才允许通过。

Windows acceptance 会把授权交接结果写入 `acceptance_summary.authorization_handoff`，并在同一验收目录生成：

- `authorization_handoff_payload.json`
- `latest_reachops_authorization_handoff.zip`
- `latest_live_acceptance_readiness.md`
- `latest_live_acceptance_readiness.json`

当前 Mac 侧已生成并验证通过的安全交接包：

```text
reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_reachops_authorization_handoff.zip
```

该包排除了 `tools/reachops_acceptance_inputs.local.ps1`、真实激活状态和授权目标值，只用于 Windows acceptance 准备，不等同于授权真实提交完成。

`tools/reachops_delivery_package_check.py --json` 会把 `authorization_handoff` 当作最终包必备报告项；缺失时最终包不能通过。

`--allow-missing-final-gate` 只能用于 Windows acceptance 脚本 bootstrap 阶段；带有 `bootstrap_only=true` 的结果不是最终交付证据。

## 6. 禁止误判

- 不把 Mac 本地验收当 Windows 客户端最终交付。
- 不把历史 Windows VM 记录当当前工作区最终交付证据。
- 不把 `client_delivery.final_delivery_ready=true` 当整项目最终交付完成。
- 不在缺少授权目标、有效激活和人工确认时运行真实评论、关注或私信。
- 不把 `ready_for_external_validation`、`blocked_by_environment` 或缺少最终产物的 package check 当最终交付通过。
