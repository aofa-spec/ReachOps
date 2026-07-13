# ReachOps ixBrowser API 修复后审计验收记录

日期：2026-07-13（Asia/Shanghai）

## 结论

ixBrowser API 会员开通后的复测确认：Local API 已可用，账号/分组只读读取恢复正常。

本轮未达到最终交付验收。当前阻塞不再是 “ixBrowser API 未开通”，而是：

- 本地验收输入仍是模板占位值，未填写授权目标、真实激活文件和授权确认。
- `United States` 分组虽然有 1 个账号通过登录态预检并能启动浏览器，但未采到评论用户，未生成 leads/outreach actions。
- `国老已改` 分组账号全部无法通过登录态/代理启动预检，已自动隔离 12 个不可用账号。
- Windows 最终交付仍缺本轮通过态 `acceptance_summary.json`。

## API 可用性

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_ixbrowser_profile_metadata_report.py --profile-limit 20 --max-pages 3 --json
```

结果：

- `status=ok`
- `safe_read_only=true`
- `open_profile_called=false`
- `profile_count=2377+`
- `group_count=15`
- 能读取 `United States`、`Canada`、`Brazil`、`国老已改` 等分组和配置数量。

说明：API 会员权限已经能支撑程序自动读取账号池和分组元数据。

## 本轮代码修复

修复文件：

- `tools/run_reachops_real_flow_macos.py`

修复内容：

- 将 `PROFILE_START_FAILED`、`PROFILE_PREFLIGHT_TIMEOUT`、`PAGE_OPEN_FAILED` 纳入不可用账号集合。
- 修复前：代理认证失败、启动失败账号不会被自动加入 blocked 列表，容易在后续场景中复用。
- 修复后：启动失败账号会被识别、隔离并跳过，程序继续筛选后续账号。

验证：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m py_compile tools/run_reachops_real_flow_macos.py
```

状态：通过。

## 真实执行复测

### United States 分组

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/run_reachops_real_flow_macos.py --profile-group "United States" --profile-limit 2 --profile-scan-limit 12 --max-attempt-batches 3 --max-videos 1 --max-comments 3 --profile-page-timeout 25 --profile-preflight-timeout 35 --scenario-timeout 240 --json
```

报告：

- `reports/reachops/mac_real_flow/20260712T213338Z/reachops_mac_real_flow_report.json`

结果：

- `acceptance.status=blocked`
- `profile_preflight_available=true`
- `browser_started=true`
- `collection_completed=false`
- `lead_pipeline=false`
- 可用账号：`23912`
- 已隔离账号：`23943`、`23936`、`23927`、`23923`、`23917`、`23911`、`23888`、`23886`

诊断：

- 程序已能自动筛选账号并启动真实浏览器。
- 采集入口能找到部分素材，但没有沉淀评论用户。
- 因没有 `comment_users/customer_leads/outreach_actions`，不能进入触达任务验收。

### 国老已改 分组

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/run_reachops_real_flow_macos.py --profile-group "国老已改" --profile-limit 2 --profile-scan-limit 12 --max-attempt-batches 4 --max-videos 1 --max-comments 5 --profile-page-timeout 25 --profile-preflight-timeout 35 --scenario-timeout 220 --json
```

报告：

- `reports/reachops/mac_real_flow/20260712T214003Z/reachops_mac_real_flow_report.json`

结果：

- `acceptance.status=blocked`
- `profile_preflight_available=false`
- `browser_started=false`
- `collection_completed=false`
- `lead_pipeline=false`
- 已隔离账号：`19826`、`18533`、`14417`、`14155`、`12555`、`12546`、`12489`、`12420`、`12382`、`12381`、`12375`、`11888`

诊断：

- 账号池可读取，但候选账号全部预检失败。
- 失败原因包括 `PROFILE_START_FAILED`，底层信息显示 socks5 代理认证失败或连接关闭。
- 修复后程序已自动隔离这些账号并停止继续消耗不可用账号。

## 门禁复跑

### 客户端交付门禁

报告：

- `reports/reachops_acceptance/client_delivery_after_ixbrowser_api_repair.json`

结果：

- `status=blocked_by_accounts`
- `final_delivery_ready=false`
- `profile_available=0`
- `failed_checks=["acceptance:ready"]`

主要阻塞：

- 账号预检没有可用账号，无法进入真实采集/触达。
- 存在内核不匹配账号，需要把配置内核改到 ixBrowser 当前支持版本。
- 本轮没有采集到候选用户，系统没有进入触达。

### Windows 交付包门禁

报告：

- `reports/reachops_acceptance/delivery_package_after_ixbrowser_api_repair.json`

结果：

- `status=failed`
- `final_delivery_ready=false`
- `missing_artifacts=["acceptance_summary"]`
- `failures=["acceptance_summary_missing","acceptance_summary_not_passed"]`

### 最终验收门禁

报告：

- `reports/reachops_acceptance/final_acceptance_after_ixbrowser_api_repair.json`

结果：

- `status=not_ready`
- `final_delivery_ready=false`
- `failed_checks=["goal_status:passed","client_delivery:final_ready","delivery_package:passed"]`

## 当前验收边界

可以确认：

- ixBrowser API 已恢复可用。
- 程序可以自动读取账号池、筛选账号、打开真实浏览器预检。
- 程序已经自动隔离部分不可用账号。
- Windows exe/installer 仍保留为已构建状态。

不能确认：

- 客户最终交付通过。
- 登录成功账号已完成采集触达任务。
- 真实 TikTok 评论/关注/私信已提交。
- `acceptance_summary.json` 已通过。

## 下一步要求

要达到最终交付，必须满足：

- 在 ixBrowser 中保留至少 1 个可手动打开 TikTok、已登录、内核匹配、代理可用的账号在执行分组内。
- 优先处理 `United States` 分组，因为当前交付门禁默认检查该分组。
- 把授权 TikTok 视频/主页/用户名和真实激活文件写入 `tools/reachops_acceptance_inputs.local.ps1`。
- 将 `ConfirmAuthorizedTargets` 设置为 `$true` 前，必须确认目标已授权。
- 复跑 `tools/run_reachops_real_flow_macos.py`，直到 `collection_completed=true` 且 `lead_pipeline=true`。
- 再运行 Windows acceptance，生成通过态 `reports/reachops_acceptance/acceptance_summary.json`。
- 最后确认 `tools/reachops_final_acceptance_gate.py --json` 返回 `status=passed` 且 `final_delivery_ready=true`。
