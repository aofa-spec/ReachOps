# ReachOps 真实压力测试与审计验收报告

日期：2026-07-10

## 2026-07-10 实时复测结论

当前项目 **不能验收为最终交付通过**。本地运营压测、交付审计、Web 面板 DOM/运行时冒烟和仓库清洁度通过；但全量单测失败，客户端交付门禁被账号阻断，最终交付包缺失 Windows 产物和通过的 acceptance summary。

### 2026-07-11 ixBrowser 重启后真实复测

用户确认已重新启动 ixBrowser 指纹浏览器后，重新执行真实验收检查。

执行结果：

- `tools/reachops_ixbrowser_profile_metadata_report.py --group-name "United States" --profile-limit 20 --max-pages 3 --json`
  - `status=ok`
  - `safe_read_only=true`
  - `open_profile_called=false`
  - `profile_count=2910`
  - `group_count=15`
  - `known_group_count=15`
  - `selected_group_id=257999`
  - `selected_profile_count=577`
  - 结论：ixBrowser App / Local API 已可连通，United States 分组可读。
- `tools/reachops_live_acceptance_status.py --json`
  - `status=blocked`
  - `ready_for_live_preflight=false`
  - `ready_for_live_submit=false`
  - `no_browser_started=true`
  - `no_submit=true`
  - 阻断：本地验收输入仍有占位字段，缺 ProfileIds、授权 TikTok 目标、目标用户名、激活状态文件和授权确认；激活状态文件不存在。
  - 结论：不得执行真实评论/关注/私信提交。
- `tools/reachops_visual_collection_preflight.py --base-dir reports/reachops/mac_real_flow/manual_probe_20260711_batch_a --target "https://www.tiktok.com/@tiktok" --source-type creator_url --profile-group "United States" --profile-limit 8 --profile-ids "18795,18798,18800,18802,18803,18804,18806,18809" --max-videos 1 --max-comments 5 --profile-page-timeout 30 --profile-preflight-timeout 40 --no-quarantine-failed-profiles --allow-fail --json`
  - `mode=visual_browser_read_only_preflight`
  - `no_submit=true`
  - `dry_run_actions=true`
  - `requested=8`
  - `checked=8`
  - `available=0`
  - `unavailable=8`
  - errors：`LOGIN_REQUIRED=2`、`PROFILE_PREFLIGHT_TIMEOUT=6`
  - `customer_leads=0`
  - `outreach_actions=0`
  - 报告：`reports/reachops/mac_real_flow/manual_probe_20260711_batch_a/reachops_visual_collection_preflight_report.json`
  - 截图证据：
    - `reports/reachops/mac_real_flow/manual_probe_20260711_batch_a/evidence/20260710T162021Z/profile_preflight/18795_profile_preflight_LOGIN_REQUIRED.png`
    - `reports/reachops/mac_real_flow/manual_probe_20260711_batch_a/evidence/20260710T162021Z/profile_preflight/18798_profile_preflight_LOGIN_REQUIRED.png`
- `tools/reachops_client_delivery_check.py --json`
  - `status=blocked_by_accounts`
  - `profile_available=0`
  - `acceptance_ready=false`
  - `final_delivery_ready=false`
  - `failed_checks=["acceptance:ready"]`
- `tools/reachops_mvp_acceptance_summary.py --json`
  - `status=blocked_by_accounts`
  - `mvp_local_ready=false`
  - `final_delivery_ready=false`

2026-07-11 判定：

- ixBrowser 启动和 Local API：通过。
- United States 分组读取：通过。
- 真实 no-submit 预检：未通过，当前抽测账号无可用 TikTok 登录态。
- Mac MVP 验收：未通过，`blocked_by_accounts`。
- 真实提交验收：未执行，授权输入和激活状态未满足。

下一步仍是账号侧处理：在 United States 分组中保留至少 1 个内核匹配、TikTok 已登录、能打开目标页面且不会预检超时的 Profile 后，再复跑本节命令。

### 2026-07-10 真实 ixBrowser 启动验收补充

已按真实 Mac 验收路径连接本机 ixBrowser App 和 Local API，不只跑 fixture。

本次真实环境证据：

- `tools/reachops_ixbrowser_profile_metadata_report.py --group-name "United States" --profile-limit 10 --max-pages 3 --json`
  - `status=ok`
  - `safe_read_only=true`
  - `open_profile_called=false`
  - `profile_count=2910`
  - `group_count=15`
  - `known_group_count=15`
  - `selected_group_id=257999`
  - `selected_profile_count=582`
  - 说明：本步只读 ixBrowser 分组和账号元数据，不打开 Profile。
- `tools/run_reachops_real_flow_macos.py --profile-group "United States" --profile-limit 2 --profile-scan-limit 30 --max-attempt-batches 2 --max-videos 1 --max-comments 5 --profile-page-timeout 25 --profile-preflight-timeout 30 --scenario-timeout 180 --json`
  - `mode=mac_real_browser_flow_no_submit`
  - `no_submit=true`
  - 从 United States 选出 30 个候选 Profile。
  - 4 个真实入口场景均执行：`keyword_product`、`hashtag_topic`、`creator_profile`、`live_room`。
  - 每个场景 2 次 attempt，均失败。
  - 失败原因：`no_logged_in_profile_available`、`browser_not_started`、`evidence_screenshot_missing`、`collection_not_completed`、`effective_acquisition_not_completed`。
  - 具体错误：前排账号 `24927`、`24925`、`24830`、`24828` 均返回 `IXBROWSER_KERNEL_MISMATCH`，ixBrowser API 原始信息为 `code=2014 message=当前版本仅支持 138 内核打开，请修改内核版本`。
  - 报告：`reports/reachops/mac_real_flow/20260710T151104Z/reachops_mac_real_flow_report.json`
- 由于 `run_reachops_real_flow_macos.py` 当前没有把 `IXBROWSER_KERNEL_MISMATCH` 纳入 retry 的硬阻断集合，它在多场景中重复使用前 4 个坏账号。为避免该脚本缺陷影响判断，额外做了 targeted 真实启动探针。
- 直接 ixBrowser `open_profile` 探针：
  - Profile `45` 真实启动成功，返回 `debugging_address=127.0.0.1:31590`、`debugging_port=31590`、`webdriver=/Users/aofa/Library/Application Support/ixBrowser-Resources/chrome/142-0004/chromedriver.app/Contents/MacOS/chromedriver`。
  - 随后 `close_profile(45)` 成功。
  - 报告：`reports/reachops/mac_real_flow/direct_open_profile_probe_20260710T1516.json`
- `tools/reachops_visual_collection_preflight.py ... --profile-ids "45" ... --json`
  - Profile `45` 进入真实页面预检后失败：`LOGIN_REQUIRED`。
  - 已生成截图证据：`reports/reachops/mac_real_flow/manual_probe_45/evidence/20260710T151634Z/profile_preflight/45_profile_preflight_LOGIN_REQUIRED.png`
  - 该账号按安全策略被移入 `封禁账号`，`quarantine_move.ok=true`。
  - 报告：`reports/reachops/mac_real_flow/manual_probe_45/reachops_visual_collection_preflight_report.json`
- `tools/reachops_visual_collection_preflight.py ... --profile-ids "240,477,1090,1226,1860,5185" --no-quarantine-failed-profiles ... --json`
  - 6 个账号全部不可用。
  - 错误分布：`IXBROWSER_KERNEL_MISMATCH=1`、`LOGIN_REQUIRED=2`、`PROFILE_PREFLIGHT_TIMEOUT=3`。
  - `no_submit=true`，未评论、未关注、未私信。
  - 报告：`reports/reachops/mac_real_flow/manual_probe_low_batch/reachops_visual_collection_preflight_report.json`

本次真实启动验收判定：

- ixBrowser App 与 Local API：通过，可读分组，可真实打开至少一个 Profile。
- 项目真实 no-submit 执行链路：未通过，原因是当前抽测账号无法形成至少 1 个已登录且可通过页面预检的 TikTok Profile。
- 真实采集/线索/触达预检：未进入，`customer_leads=0`、`outreach_actions=0`。
- 真实平台提交：未执行，且当前授权输入/激活状态仍不满足 live submit 条件。
- 安全边界：通过，所有真实启动和预检均保持 `no_submit=true`。

本次真实验收后的门禁复核：

- `tools/reachops_client_delivery_check.py --json`
  - `status=blocked_by_accounts`
  - `profile_available=0`
  - `acceptance_ready=false`
  - `final_delivery_ready=false`
  - `failed_checks=["acceptance:ready"]`
- `tools/reachops_mvp_acceptance_summary.py --json`
  - `status=blocked_by_accounts`
  - `mvp_local_ready=false`
  - `final_delivery_ready=false`
- `tools/reachops_final_acceptance_gate.py --json`
  - `status=not_ready`
  - `final_delivery_ready=false`
  - failed：`goal_status:passed`、`client_delivery:final_ready`、`delivery_package:passed`

下一步必须先在 ixBrowser 中准备验收账号：

1. United States 分组至少保留 1 个可打开 TikTok 的账号。
2. Profile 内核版本必须符合当前 ixBrowser 支持版本。当前错误要求 `138` 内核；部分可启动账号使用 `chrome/142-0004`，但仍需 TikTok 登录态。
3. 账号必须已登录 TikTok，打开 `https://www.tiktok.com/@tiktok` 或授权目标时不出现登录要求。
4. 复跑 `tools/reachops_visual_collection_preflight.py` 或 `复测ReachOps真实执行.command`，直到至少 1 个 Profile 预检 `available>0`，并出现真实 `DONE collection` 或结构化 no-action reason。

本次实际执行命令和结果：

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_operator_pressure.py --max-campaigns 5 --max-sources-per-campaign 5 --max-videos 5 --max-comments 4 --collect-profile-count 4 --execute-profile-count 4 --action-limit 250 --json`
  - `status=ok`
  - `campaign_count=3`
  - `target_sources=13`
  - `content_found=63`
  - `comment_users=99`
  - `customer_leads=99`
  - `outreach_actions=198`
  - `selected_actions=24`
  - `execution_success=15`
  - `execution_failed=12`
  - `account_switched=6`
  - `workers=2`
  - `available_profiles=4`
  - 说明：该压测使用 fixture/dry-run 路径，不进行真实 TikTok 提交。
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_delivery_audit.py --json`
  - `status=ok`
  - `passed=51`
  - `pending_external_validation=3`
  - `failed=0`
  - `processed_sources=2`
  - `action_selected=24`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_goal_status_report.py --json`
  - `status=ready_for_external_validation`
  - `stages_passed=3`
  - `stages_pending_external_validation=2`
  - `final_pending_external_validation=3`
  - pending：`授权允许时能真实执行`、`真实 TikTok 平台提交`、`客户端交付验收门禁不会把环境阻断当通过`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_client_delivery_check.py --json`
  - `status=blocked_by_accounts`
  - `readiness=blocked_by_accounts`
  - `profile_available=0`
  - `contract_ok=true`
  - `acceptance_ready=false`
  - `final_delivery_ready=false`
  - `failed_checks=["acceptance:ready"]`
  - blocker：账号预检没有可用账号、存在 `IXBROWSER_KERNEL_MISMATCH`、本轮未采集到候选用户
  - 本批次内核不匹配账号样例：`24919`、`24922`、`24923`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_final_acceptance_gate.py --json`
  - `status=not_ready`
  - `final_delivery_ready=false`
  - failed：`goal_status:passed`、`client_delivery:final_ready`、`delivery_package:passed`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_delivery_package_check.py --json`
  - `status=failed`
  - `final_delivery_ready=false`
  - 缺失：`exe`、`installer`、`manifest`、`acceptance_summary`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_web_panel_dom_smoke.py --json`
  - `status=passed`
  - `failed_checks=[]`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_web_panel_runtime_smoke.py --json`
  - `status=passed`
  - `failed_checks=[]`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_repository_cleanliness_check.py --json`
  - `status=passed`
  - `forbidden_count=0`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_mvp_acceptance_summary.py --json`
  - `status=blocked_by_accounts`
  - `mvp_local_ready=false`
  - `final_delivery_ready=false`
  - `failed_checks=["client_delivery:acceptance:ready"]`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests`
  - `Ran 435 tests`
  - `FAILED (failures=6, errors=4)`
  - 主要失败集中在 `tests.test_reachops_client_acceptance_status.ReachOpsWebUiContractTest` 的 `/api/start` HTTP 合同用例：当前服务端会先校验 ixBrowser 分组列表和账号修复门禁，测试仍直接只传 `target` 并期望进入 `subprocess.Popen` 分支，合同不一致。
  - `tests.test_reachops_campaign.ReachOpsCampaignTests.test_ixbrowser_group_loader_accepts_wrapped_api_response` 在全量测试中曾失败，但单项复跑通过。

本次审计判定：

- 本地能力路径：可承压，审计通过。
- Web 面板：DOM 和真实 HTTP runtime smoke 通过。
- 当前 Mac 客户端验收：不通过，阻断于账号可用性。
- 最终交付验收：不通过，阻断于真实授权外部验证、客户端门禁、Windows 最终产物。
- 自动化测试基线：不通过，需要修复或更新 `/api/start` 门禁合同相关单测后才能作为可交付 CI 基线。

下一步必须完成：

1. 在 ixBrowser 中修复 United States 分组账号：至少 1 个账号可手动打开 TikTok、已登录、内核版本匹配当前 ixBrowser 支持版本。
2. 处理 `IXBROWSER_KERNEL_MISMATCH` 账号：将 `24919`、`24922`、`24923` 等账号内核改到当前支持版本，或移出执行分组。
3. 用真实可采集目标复跑客户端门禁，直到 `tools/reachops_client_delivery_check.py --json` 返回 `status=passed`、`final_delivery_ready=true`、`failed_checks=[]`。
4. 在 Windows 实机生成 `dist/ReachOps/ReachOps.exe`、`dist/installer/ReachOps-Setup-0.4.0.exe`、`dist/installer/reachops-update-manifest.json`，并生成通过的 `reports/reachops_acceptance/acceptance_summary.json`。
5. 完成授权真实提交验收，补齐真实截图、sidecar、`submitted_text` 和 `comment_visible_confirmed=true`。
6. 修复或更新 Web UI `/api/start` HTTP 合同测试，使测试合同与当前启动前门禁一致。

## 2026-07-04 实时验收状态

以下内容为历史记录，不能替代 2026-07-10 本次实时复测结论。

当前 Mac MVP 实时验收 **未通过**，状态为 `blocked_by_accounts`。

实时门禁证据：

- `tools/reachops_client_delivery_check.py --json`：`status=blocked_by_accounts`
- `contract_ok=true`
- `acceptance_ready=false`
- `final_delivery_ready=false`
- `failed_checks=["acceptance:ready"]`
- 项目清洁度：`tools/reachops_repository_cleanliness_check.py --json` 返回 `status=passed`、`forbidden_count=0`

阻断原因：

- United States 分组可读，分组数量和报告文件可追溯。
- 最新账号预检 `profile_available=0`。
- 主要账号问题为 `IXBROWSER_KERNEL_MISMATCH` 和 `LOGIN_REQUIRED`。
- 最新唯一账号修复清单：`reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_profile_remediation.csv`。

以下 2026-07-03 压测内容保留为历史通过样例，不能替代 2026-07-04 的实时 Mac MVP 验收结论。

## 结论

以产品经理最小 MVP 口径验收，2026-07-03 历史代码、自动化测试、本地压力路径、Web 运营面板、架构审计和客户端门禁逻辑曾达到本地 MVP 审计验收标准；当前实时状态必须以 2026-07-04 门禁为准。

最终交付仍不能标记为完成，因为真实 Windows 客户端交付包和授权 TikTok/ixBrowser 外部环境验证尚未在当前工作区完成。系统已正确把这些项目归类为 `pending_external_validation` 或 `blocked_by_environment`，不会把环境阻断误判为通过。

当前运行态注意事项：`http://127.0.0.1:8769/` 已启动为当前 Web UI 验收入口。当前 Mac 已连通 ixBrowser Local API 默认端口 `127.0.0.1:53200`，网页端“刷新分组”已真实读取 15 个 ixBrowser 配置分组，并解析出 15 个分组的账号数量；当前自动循环验收快照显示 `United States（700账号）`、`group_count=15`、`known_group_count=15`、`profile_count=2910`，“开始获客”按钮只在实时分组列表就绪后解除禁用。若 ixBrowser Local API 未开启、端口不一致或只能读取缓存分组，面板会显示可读错误，并阻止用未验证分组启动采集。

## 架构验收

运营执行入口必须是网页端，浏览器动作必须由本地服务 API 调用指纹浏览器执行。当前审计通过的链路为：

```text
web_ui_http_api
  -> local server subprocess
  -> headless service layer
  -> workflow/router
  -> ixBrowser local API
  -> Selenium
```

已验证的关键点：

- Web UI 提供 `/api/start` 作为运营启动入口。
- Web UI “刷新分组”先读取 ixBrowser 配置分组列表，再按每个 `group_id` 调用 `profile-list(group_id, limit=1)` 读取 ixBrowser 返回的 `client.total`，将账号数量回填到分组下拉框和分组详情区；只有全部可计数组都拿到数量时才标记 `counts_resolved=true`。该方式避免先全量扫描数千个 Profile 造成刷新超时，也避免把采样结果误显示为精确数量。
- 若 ixBrowser SDK 返回 `None` 或 Local API 连接失败，后端会把它归一为可读错误，例如 `ixBrowser Local API 未启动或端口不可连接`，并把原始连接异常写入 `error_detail` 和 `refresh_groups` 日志；UI 不会再把连接失败误显示成 0 个分组。
- Web UI 提供只读 `/api/ixbrowser-status`，面板“执行方案”区域会显示 `ixBrowser API` 状态；该接口只调用分组列表的一页只读检查，返回 `no_browser_started=true`、`no_submit=true`，不会打开指纹浏览器或提交平台动作。
- Web UI 提供 `/api/ixbrowser-config`，运营可在网页端填写 ixBrowser Local API 端口并点击“应用”；服务端会更新当前进程的 `REACHOPS_IXBROWSER_API_PORT`、清空分组缓存，并把端口保存到 runtime 配置 `config/reachops_web_settings.json`，重启 Web UI 后自动恢复。该接口继续保持 `no_browser_started=true`、`no_submit=true`。非默认端口不再要求运营进入终端设置环境变量。
- `/api/start` 在服务端拒绝空目标并返回 `target_required`，避免无效执行被误记为运营任务。
- Web UI 提供 `/api/control`、`/api/logs`、`/api/snapshot`、`/api/acceptance`、`/api/final-status` 作为运行控制和验收观察入口。
- `/api/acceptance` 暴露客户端交付门禁：`status`、`final_delivery_ready`、`failed_checks`。
- `/api/final-status` 暴露最终交付只读状态：`status`、`final_delivery_ready`、`failed_checks`、`blocked_reasons`、`next_required_actions`、`verification_commands`；接口返回 `no_browser_started=true`、`no_submit=true`，面板“最终交付门禁”会直接显示“不可最终交付”及阻塞原因，“最终复核命令”会显示 `python tools\reachops_client_delivery_check.py --json`、`python tools\reachops_delivery_package_check.py --json`、`python tools\reachops_final_acceptance_gate.py --json`，避免运营只在 CLI 中才能看到最终验收缺口。
- Mac 自检 `REQUIRED_WEB_UI_MARKERS` 已把“最终交付门禁”、`finalStatusState` 和 `fetch('/api/final-status')` 作为当前 Web 页面必备标记；验收包 manifest 也记录 `web_operator_api.final_status=/api/final-status` 以及 no-browser/no-submit 语义，避免旧页面或不完整验收包被误认为当前交付入口。
- 已通过真实 HTTP 服务级测试启动 `ThreadingHTTPServer` 并请求 `/api/acceptance`，确认网页端运营接口返回结构化客户端门禁，并同步落盘 `latest_delivery_check.json`，而不是只在函数级构造 payload。
- 已通过 `tools/reachops_web_panel_runtime_smoke.py` 启动真实本地 Web 服务，实际请求页面和 `/api/start`、`/api/logs`、`/api/control`、`/api/acceptance`、`/api/ixbrowser-status`、`/api/final-status`；冒烟结果证明页面控件不是静态样式，启动按钮会生成 `tools/run_reachops_headless_macos.py` 命令，暂停/继续/停止会进入本地运行态控制，ixBrowser 状态接口和最终门禁接口均只读且不会触发浏览器或平台动作。
- 已通过 `tools/reachops_web_panel_dom_smoke.py` 提取真实页面脚本并在 DOM/fetch harness 中执行按钮点击：`start.onclick()` 会携带运营输入 POST `/api/start`，`pause/resume/stop` 会 POST `/api/control`，API 返回会写入运营决策区。
- 已通过当前 Mac 真实浏览器 DOM 验收：Web UI 加载完成后，账号分组下拉框和顶部明细区显示真实 ixBrowser 分组和账号数量；当前自动循环验收显示 `United States（700账号）`，`group_count=15`、`known_group_count=15`、`profile_count=2910`。
- 已通过当前 Mac 真实预检复测：批次 `gb_87747dc9fdea4277` 由 Web `/api/start` 以 `mode=preflight`、`liveConfirm=false` 启动；日志显示 `CHECK profile_preflight checked=7 available=4 unavailable=3`，随后用 3 个可用账号进入采集，出现 `DONE collection processed_sources=1`、`DONE action_preflight skipped` 和 `FAST acceptance status=executed ... no_submit=true`。本轮没有真实评论提交。
- 已通过当前 Mac 产品链接目标模式复测：批次 `gb_3f0656c002024e6b` 使用产品链接 `https://www.amazon.sg/Owala-FreeSip-Sway-Stainless-30-oz/dp/B0FJZDV6BH/`，日志显示 `input_type=product_url`、产品名 `Owala FreeSip Sway Stainless 30 oz`，并生成可执行关键词来源 `keyword:Owala FreeSip Sway Stainless 30 oz`；账号预检 `checked=2 available=2 unavailable=0`，随后出现 `DONE collection`、`DONE action_preflight skipped` 和 `FAST acceptance ... no_submit=true`。本轮没有真实评论提交。
- Web UI 会解析 `/api/start` 和 `/api/control` 的 JSON 响应，并把 `started`、`already_running`、`failed`、`rejected`、`not_running` 等状态直接写入运营决策区；启动失败、控制失败或重复启动不会只停留在后台日志。
- “采集 + 真实评论”必须前端勾选“确认真实评论”，并且服务端 `/api/start` 也会校验 `liveConfirm/live_confirm` 和 `reachops_activation_status.json` 激活授权；未确认时返回 `live_comment_confirmation_required`，未激活或未授权时返回 `LIVE_SUBMIT_NOT_AUTHORIZED`，两种情况都不会启动 headless runner。
- Web UI 提供 `/api/activation`，面板“执行方案”区域会显示“真实评论授权”状态；该接口只读取激活状态，返回 `no_browser_started=true`、`no_submit=true`，不会打开浏览器或提交动作。
- `/api/start` 和 `/api/control` 要求请求体为 JSON 对象；非法 JSON、非对象 JSON、异常 `Content-Length` 或超过 64KB 的 JSON 请求体都会返回结构化 400。本地 headless 进程启动失败会返回 `launch_failed` JSON 并写入 `web_ui_launch_failed` 日志，避免运营端出现连接断开但无错误原因的状态。
- Web 服务启动时只允许绑定 localhost/127.0.0.1/::1，拒绝 `0.0.0.0` 或局域网 IP；Mac 自检启动器也会显式以 `--host 127.0.0.1` 和 `REACHOPS_WEB_HOST=127.0.0.1` 启动 Web 面板。若子进程启动失败，自检会返回 `started_web.ok=false`、`web_start_error` 和启动日志路径，而不是崩溃退出。`/api/start`、`/api/control`、`/api/acceptance` 等 POST/GET 本地 API 都会拒绝非 localhost/127.0.0.1/::1 的 Host、Origin 或 Referer，避免外站页面直接触发执行或读取本地验收数据。
- `/api/start` 在结果文件无法创建或打开时返回 `result_file_open_failed` JSON 并写入 `web_ui_result_file_open_failed` 日志，不会继续启动 headless 子进程。
- `/api/download` 只允许下载 runtime reports 目录下的文件；文件发送失败时返回 `download_failed` JSON 并写入 `web_ui_download_failed` 日志，不会让浏览器连接异常中断且无错误原因。
- 未知 `/api/*` GET/POST 路径返回结构化 `unknown_api` 404 JSON，不会回退成 HTML 页面或无状态 `not_found`，避免前端或验收脚本把接口错误误判为页面成功。
- `/api/start` 会在服务端把非法 `mode` 归一为 `preflight`、非法 `volume` 归一为 `quick`，避免把无效 choices 传给 headless runner 导致子进程立即退出。
- `/api/start` 会把参与账号数归一到 1..20，避免误填极端 `profiles` 值导致 ixBrowser 预检或执行压力失控。
- `/api/start` 成功启动后会关闭父进程侧 stdout 文件句柄，防止运营端长期反复执行造成文件描述符泄漏；重复启动返回 `already_running` 并带当前 `pid`。
- `/api/control` 对未知动作返回 `status=rejected`、`error=unknown_action`，暂停/继续/停止控制入口不会因误操作产生不一致响应。
- `/api/control` 的暂停/继续/停止信号发送捕获系统级 `OSError`，权限拒绝或进程组异常时返回结构化 `status=failed`，不会让控制请求中断；停止信号失败或强制终止后进程仍在运行时会保留 `RUN_PROCESS` 状态并返回 `running=true`，避免 UI 误报已停止。
- 服务端启动 headless runner，并复用 `GrowthIntelligenceService` 与 `GrowthWorkflowService`。
- 采集与触达动作都通过 `WorkbenchBrowserAdapter` 获取浏览器会话。
- `IxBrowserLocalAdapter` 调用 `ixbrowser_local_api.IXBrowserClient.open_profile`。
- Selenium 通过 ixBrowser 返回的 debug port 附着执行动作。

架构验收项结果：`passed`。

## 压力测试

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_operator_pressure.py \
  --max-campaigns 5 \
  --max-sources-per-campaign 5 \
  --max-videos 5 \
  --max-comments 4 \
  --collect-profile-count 4 \
  --execute-profile-count 4 \
  --action-limit 250 \
  --json
```

结果：

- `status=ok`
- campaigns：3
- target_sources：13
- content_found：69
- comment_users：108
- customer_leads：108
- outreach_actions：216
- selected_actions：36
- execution_success：16
- execution_failed：6
- account_switched：3
- workers：2
- available_profiles：4

压力路径结论：本地编排、客户线索生成、动作队列、账号切换和执行结果记录路径可承压。

## 自动化测试

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest \
  tests.test_reachops_campaign \
  tests.test_reachops_client_acceptance_status
```

结果：

- Ran 218 tests
- OK

## Web 面板运行时冒烟

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_web_panel_dom_smoke.py --json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_web_panel_runtime_smoke.py --json
```

结果：

- `status=passed`
- `failed_checks=[]`
- 分组刷新合同：通过。已覆盖 `get_group_list` 读取配置分组、`get_profile_list(group_id, limit=1)` 读取每组 `client.total`、返回 `count_label/count_status/count_source` 给运营面板，以及选择分组后 `/api/start` 使用该分组执行。
- JS 点击验证项：`click_start_posts_api_start=true`、`click_start_posts_operator_payload=true`、`click_controls_post_api_control=true`、`unconfirmed_live_comment_click_does_not_post_start=true`、`activation_status_is_visible_to_operator=true`、`final_status_is_visible_to_operator=true`、`operator_notice_updates_after_api_response=true`、`start_button_reenabled_after_click=true`。
- HTTP/API 验证项：页面控件真实绑定 API、Web 服务和 Mac 自检启动器只绑定 loopback、Mac 自检启动失败会结构化报告、POST 和 GET 型 `/api/*` 都拒绝外站 Origin、未知 GET/POST API 返回 JSON 404、报告下载失败会结构化返回 `download_failed`、空目标拒绝、未确认真实评论拒绝、未激活真实评论拒绝、`/api/activation`、`/api/ixbrowser-status` 和 `/api/final-status` 均只读返回 no-browser/no-submit 状态、`/api/ixbrowser-config` 可在网页端更新并持久化 ixBrowser Local API 端口且不会打开浏览器或提交动作、`/api/start` 生成 headless runner 命令、`profiles` 归一到 20、非法 `mode/volume` 归一、父进程 stdout 关闭、重复启动返回 `already_running`、暂停/继续/停止进入进程信号控制、`/api/acceptance` 暴露客户端交付门禁。
- 页面合同还验证了 `postJson`、`showApiNotice` 和 API 反馈保护期存在，运营面板会把启动/控制 API 的结果反馈到可见决策区，不会被后续刷新立即覆盖。
- 捕获的启动命令包含：`tools/run_reachops_headless_macos.py --base-dir <Web DATA_DIR> --target "anti aging serum" --source-type keyword --profile-group "United States" --profile-limit 20 --max-videos 3 --max-comments 20 --mode preflight --volume quick --comment-text Hi --timeout 900 --json`，确保 Web 面板读取的日志、快照和验收状态来自同一次 headless 运行目录。

## 交付审计

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_delivery_audit.py --json
```

结果：

- `status=ok`
- passed：45
- pending_external_validation：3
- failed：0
- processed_sources：2
- action_selected：24

新增覆盖项：最终交付文档合同必须统一要求客户端门禁、交付包检查和 `final_acceptance_gate.py` 全部通过；交付审计会运行 Web 面板运行时 API 冒烟，避免旧文档或静态页面把“看起来像控制台”误判成真实运营执行面板。

`delivery_audit` 原始审计仍把以下 3 项列为外部/门禁类待验证，用于提醒不能把本地 fixture 或环境阻断当成真实平台交付：

- 授权允许时能真实执行
- 真实 TikTok 平台提交
- 客户端交付验收门禁不会把环境阻断当通过

当前最终门禁已结合 `tools/reachops_client_delivery_check.py --json` 的落盘证据重新归类，客户端交付门禁为 `passed`；最终目标状态仍待处理的项目只剩真实授权提交和真实 TikTok 平台提交。

## 目标状态

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_goal_status_report.py --json
```

结果：

- `status=ready_for_external_validation`
- stages_passed：3
- stages_pending_external_validation：2
- stages_failed：0
- final_passed：30
- final_pending_external_validation：3
- final_failed：0

注：直接运行 `goal_status_report.py` 不读取最新客户端门禁落盘报告时会保守显示 3 个 pending；`final_acceptance_gate.py` 会把当前客户端交付证据传入目标状态，当前最终门禁中的目标 pending 为 2 个：`授权允许时能真实执行`、`真实 TikTok 平台提交`。

## 产品经理 MVP 验收摘要

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_mvp_acceptance_summary.py --json
```

结果：

- `status=blocked_by_accounts`
- `mvp_local_ready=false`
- `final_delivery_ready=false`
- `failed_checks=["client_delivery:acceptance:ready"]`
- 输出文件：`reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_mvp_acceptance_summary.json`

说明：该摘要聚合 `delivery_audit`、`goal_status`、客户端交付门禁、Web runtime smoke 和项目清洁度；当前客户端门禁未通过时，会以 `blocked_by_accounts` 覆盖历史通过快照，防止运营把 2026-07-03 历史本地证据误读为 2026-07-04 实时验收通过。

Web 运营面板 `/api/acceptance` 已暴露 `mvp_acceptance`，报告中心会显示“产品经理 MVP 验收摘要”下载入口；页面验收状态必须跟随当前摘要显示 `blocked_by_accounts` 或 `MVP待验`，不能在账号门禁失败时显示 `MVP已通过`。报告中心还提供“刷新MVP验收”按钮，调用 `/api/mvp-acceptance-refresh` 生成最新 `latest_mvp_acceptance_summary.json`；该接口只生成本地审计摘要，不打开浏览器、不提交平台动作。

## 目标模式总报告

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_goal_delivery_runner.py --json
```

结果：

- `status=local_mvp_accepted_final_pending`
- `local_mvp_ready=false`（2026-07-04 当前实时账号门禁阻断；2026-07-03 历史快照不再作为当前通过证据）
- `windows_build_ready=true`
- `final_delivery_ready=false`
- failed_checks：`client_delivery:acceptance:ready`、`delivery_package:passed`
- blockers：`local_mvp`、`windows_final_artifacts`、`external_authorized_execution`
- `delivery_boundary.overall_final_delivery_scope_ready=false`
- `deliverable_index.web_operator_panel.ready=false`
- `deliverable_index.local_mvp_acceptance.ready=false`
- `deliverable_index.windows_build_inputs.ready=true`
- `deliverable_index.windows_final_package.ready=false`
- `deliverable_index.authorized_live_submit.ready=false`
- `deliverable_index.final_acceptance_gate.ready=false`

说明：该脚本是目标模式推进入口，聚合 MVP 摘要、客户端门禁、Windows 打包前置门禁、交付包检查、最终门禁和项目清洁度。它不会绕过 `final_acceptance_gate.py`，只负责把当前边界转成 PM 可读状态并写出 `reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_goal_delivery_report.json`。PM 验收时必须优先看 `delivery_boundary` 和 `deliverable_index`：本地 MVP 与 Windows 构建输入 ready 只能证明本地验收基础成立；`windows_final_package.ready=false`、`authorized_live_submit.ready=false`、`final_acceptance_gate.ready=false` 仍然阻止最终客户交付。

## 客户端交付门禁

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_client_delivery_check.py --json
```

结果：

- `status=passed`
- `readiness=pass`
- `contract_ok=true`
- `acceptance_ready=true`
- `final_delivery_ready=true`
- `failed_checks=[]`
- `ixbrowser_metadata.selected_profile_count=700`
- `ixbrowser_metadata.group_count=15`
- `batch_id=gb_ae454bc97f08414f`
- `profile_available=2`
- `delivery_check_path=.../latest_delivery_check.json`

历史补充证据（不能替代 2026-07-04 当前实时门禁）：

- 2026-07-03 Mac 自动循环批次曾证明配置列表参与采集：`United States` 只读元数据约 700 个配置，运行日志和验收状态显示已从选中分组启动账号队列。
- 2026-07-03 Mac 自动循环批次曾证明账号预检可用：`profile_available_count=2`。
- 2026-07-03 Mac 自动循环批次曾出现 `DONE collection` 和 `action_started=true`；当时 `actions=0` 的原因是没有可执行触达动作，不是账号候选为 0。
- 历史产品链接批次 `gb_3f0656c002024e6b` 仍作为目标识别补充证据：`input_type=product_url`、产品名 `Owala FreeSip Sway Stainless 30 oz`、`DONE collection`、`no_submit=true`。
- 当 CLI 沙箱不能直接访问本地端口时，门禁会读取网页端写入的只读快照 `reports/reachops/mac_gui/runtime/config/latest_ixbrowser_groups.json`，避免把沙箱网络限制误判为 ixBrowser 没有账号。

当前门禁结论：Mac 本地客户端目标模式门禁未通过，状态为 `blocked_by_accounts`。网页端已能读取真实分组列表和数量，产品链接识别逻辑有历史证据；但 2026-07-04 当前账号预检 `profile_available=0`，不能进入真实采集/触达验收。最终项目交付仍未通过，因为当前 Mac MVP、授权真实提交和 Windows 客户端交付包均未闭环。

网页端 `/api/acceptance` 已接入 `write_delivery_check()`；运营打开网页端验收状态时，同一份客户端门禁会写入 `reports/acceptance_remediation/latest_delivery_check.json`，便于交付审计追溯。

## 交付包检查

Windows 打包前置门禁：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_windows_package_preflight.py --json
```

当前工作区结果：

- `status=ready_for_windows_build`
- `ready_for_windows_build=true`
- `failures=[]`
- 已验证 `tools/build_reachops_windows.ps1`、`ReachOps/packaging/reachops.spec`、`ReachOps/packaging/ReachOps.iss`、manifest 生成器、installer smoke、UI startup smoke、acceptance 脚本、repository cleanliness、package check、final gate 和 acceptance summary verifier 均存在且合同关键字齐全。
- 构建合同要求默认 Windows 构建必须生成安装包和 update manifest；`-SkipInstaller` 仅允许非最终 EXE-only 构建，不能作为最终交付结果。
- 该结果只证明 Windows 构建输入闭环，不代表最终交付完成。

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_delivery_package_check.py \
  --allow-external-pending \
  --json
```

当前工作区结果：

- `status=failed`
- missing_artifacts：`exe`、`installer`、`manifest`、`acceptance_summary`
- failures：`exe_missing`、`installer_missing`、`manifest_missing`、`acceptance_summary_missing`

说明：当前 Mac 工作区没有 Windows `dist/` 交付产物和最新 acceptance summary，因此最终客户端交付包不能验收通过。历史 Windows VM 验收记录已在 README/HANDOFF 中保留，但当前工作区必须重新生成最终交付包才能完成验收闭环。

## 严格最终验收 Gate

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_final_acceptance_gate.py \
  --audit-json /tmp/reachops_delivery_audit_latest.json \
  --pressure-json /tmp/reachops_pressure_latest.json \
  --goal-status-json /tmp/reachops_goal_status_latest.json \
  --client-delivery-json /tmp/reachops_client_delivery_latest.json \
  --package-check-json /tmp/reachops_package_latest.json \
  --json
```

当前工作区结果：

- `status=not_ready`
- `final_delivery_ready=false`
- failed_checks：`goal_status:passed`、`delivery_package:passed`
- evidence：`client_delivery:final_ready` 必须包含 `delivery_check_path` 且 `evidence_ready=true`，并要求该 JSON 文件内容本身也是 `status=passed`、`readiness=pass`、`failed_checks=[]`；`delivery_package:passed` 必须包含 `artifacts`、完整 final report set (`delivery_audit`、`operator_pressure`、`installer_smoke`、`ui_startup`、`activation_status`、`live_acceptance_status`、`live_validation`、`repository_cleanliness`、`windows_package_preflight`、`live_readiness`、`live_preflight`、`goal_status`、`live_submit`、`final_acceptance_gate`) 的 `report_files` 和 `final_gate_report`，终包产物和所有报告的 `size>0`，`final_gate_report.missing_required_checks=[]`、`final_gate_report.failed_required_checks=[]`，且 manifest 的 `expected_sha256/actual_sha256`、`expected_size/actual_size` 必须一致

说明：`ready_for_external_validation`、环境阻断、缺交付包产物都不能被最终 gate 误判为交付通过。最终交付必须让该命令返回 `status=passed`、`final_delivery_ready=true`。

Windows acceptance 脚本已自动接入该 gate：`tools/run_reachops_acceptance_windows.ps1` 会在 `delivery_package_check.json` 生成后运行 `tools/reachops_final_acceptance_gate.py`，输出 `final_acceptance_gate.json` 和 `FINAL_ACCEPTANCE_GATE_JSON=...`，并把 `final_acceptance_gate` 回写进 `acceptance_summary.json`。回写后脚本会再次复核 `delivery_package_check.json`，确认最终门禁报告文件也被包检查覆盖，再用复核后的包结果重跑 final gate。若 `acceptance_summary.json` 已经是 `passed` 但 final gate 或最终包复核未通过，脚本会直接失败。

`tools/verify_reachops_acceptance_summary.py` 会要求 `status=passed` 的 summary 必须包含 `windows_package_preflight` 和 `final_acceptance_gate`，并校验 Windows 构建合同、`final_acceptance_gate.status=passed`、`final_delivery_ready=true`、`failed_checks=[]`。真实 live submit 成功动作还必须包含本地截图 evidence 和 sidecar 细节，sidecar 的 `screenshot_sha256` 必须匹配截图文件，并且必须包含 `action_type`、`profile_id`、`action_id`、`current_url`；评论动作还要求 `submitted_text` 匹配且 `comment_visible_confirmed=true`。`evidence://...` 只能用于预检/fixture 记录，不能作为真实提交成功证据。`tools/reachops_delivery_package_check.py` 的最终模式默认要求 `final_acceptance_gate.json` 和 `windows_package_preflight.json` 存在且非空；只有 Windows acceptance 脚本首次 bootstrap 包检查可以使用 `--allow-missing-final-gate`。该中间 JSON 会标记 `bootstrap_only=true`、`final_delivery_ready=false`，最终复核不能使用该参数。

`tools/reachops_delivery_package_check.py` 还会读取 `final_acceptance_gate.json` 内容，要求 JSON 本身为 `status=passed`、`final_delivery_ready=true`、`failed_checks=[]`，并与 `acceptance_summary.json` 中回写的 `final_acceptance_gate` 一致；内容不一致会返回 `final_acceptance_gate_json_mismatch`。

`final_acceptance_gate.json` 还必须包含完整关键 `checks` 列表，且 `goal_status:passed`、`client_delivery:final_ready`、`delivery_package:passed`、`delivery_audit:no_failed_checks`、`operator_pressure:leads_and_actions` 都必须 `ok=true`；缺失或失败会返回 `final_acceptance_gate_json_checks_missing` / `final_acceptance_gate_json_checks_failed`。

`tools/reachops_delivery_package_check.py` 会在输出中保留 `final_gate_report` 摘要，包含 `required_checks`、`missing_required_checks`、`failed_required_checks` 和 `checks_by_name`，因此最终交付包不只给出失败码，还能直接审计每个关键 final gate check 的实际状态。

最终交付包还必须自包含：`acceptance_summary.json` 中所有报告 `json_path` 必须位于同一个 acceptance report 目录内；指向目录外文件会返回 `<section>_json_outside_acceptance_dir`。

后台验收恢复脚本 `tools/get_reachops_acceptance_background_status_windows.ps1` 已暴露 `FINAL_ACCEPTANCE_GATE_JSON`、`WINDOWS_PACKAGE_PREFLIGHT_JSON`、`delivery_package_check_path`、`delivery_package_check_exists`、`delivery_package_check`、`windows_package_preflight_path`、`windows_package_preflight_exists`、`windows_package_preflight`、`final_acceptance_gate_path`、`final_acceptance_gate_exists`、`final_acceptance_gate`、`final_delivery_ready`、`final_delivery_blockers` 和 `verification_commands`。恢复脚本会把 `delivery_package_check_not_final_ready`、`windows_package_preflight_missing` 或 `windows_package_preflight_not_ready` 作为阻断原因，断线恢复后也能直接看到最终门禁状态和包证据阻断原因；非 JSON 输出会打印 `VERIFICATION_COMMANDS=...`，便于人工远程复核直接复制最终验收命令。

只读状态汇总 `tools/reachops_live_acceptance_status.py` 已把 latest package check 的 `package_final_delivery_ready`、`package_bootstrap_only`、`package_evidence_ready`、`package_final_gate_summary_ready` 和 latest final gate 纳入 `final_delivery_ready` 判定，并在 `latest_acceptance` 中暴露 `summary_exists`、`package_check_exists`、`package_final_delivery_ready`、`package_evidence_ready`、`package_final_gate_summary_ready`、`final_acceptance_gate_exists`。缺失、bootstrap-only、缺少 package 内层验收/产物证据、缺少 `final_gate_report` 摘要或未通过 final gate 的旧报告不能再被识别为最终可交付。该状态汇总还会在阻断时输出顶层 `blocked_reasons` 和 `failed_checks`，在最终通过时二者必须为空，方便 Web/CLI/自动化验收直接显示具体缺口。`tools/reachops_live_environment_blocker_report.py` 会把 package 未最终 ready、`artifacts_ready=false`、`manifest_ready=false`、`report_files_ready=false`、`acceptance_verification_ready=false` 或 `package_final_gate_summary_ready=false` 标记为 `final_delivery_package` blocker，并把缺失或未通过的 final gate 标记为 `final_delivery_gate` blocker。

当 latest acceptance 已存在但 final gate 未通过时，`tools/reachops_live_acceptance_status.py` 会优先展示 final gate 的 `next_actions` 或 `failed_checks`，并在顶层输出 `verification_commands`，让运营/交付人员直接看到需要修复的最终门禁项和三条最终复核命令；尚未生成 acceptance 报告时仍提示先运行受控真实提交并生成 evidence。

Windows build 脚本 `tools/build_reachops_windows.ps1` 的 `py_compile` 预检已覆盖 Web 面板与最终验收关键工具，包括 `tools/reachops_web_ui.py`、`tools/reachops_client_acceptance_status.py`、`tools/reachops_client_delivery_check.py`、`tools/reachops_web_panel_dom_smoke.py`、`tools/reachops_web_panel_runtime_smoke.py`、`tools/reachops_delivery_package_check.py`、`tools/reachops_final_acceptance_gate.py`、`tools/reachops_live_acceptance_status.py`、`tools/reachops_live_environment_blocker_report.py` 和 `tools/verify_reachops_acceptance_summary.py`，避免最终验收关键工具在打包后期才暴露语法问题。

远端同步脚本 `tools/sync_reachops_to_windows_vm.sh --run-tests` 已同步并预检 Web 面板工具链：`reachops_web_ui.py`、`reachops_client_delivery_check.py`、`reachops_web_panel_dom_smoke.py`、`reachops_web_panel_runtime_smoke.py`。同步后的 Windows 侧测试链会检查这些文件存在，运行 `tools\reachops_delivery_audit.py --json` 和 `tools\reachops_final_acceptance_gate.py --json`，写出 `reachops_final_acceptance_gate_sync.json`，并输出 `SYNC_FINAL_ACCEPTANCE_GATE_STATUS` 与 `SYNC_FINAL_DELIVERY_READY`。同步测试允许未具备真实外部证据时返回 `not_ready`，但不允许 Web 面板工具、delivery audit 或 final gate 工具崩溃或缺少 JSON 状态。

Web 控制 API 的暂停/继续已做跨平台保护：支持 POSIX 信号的平台会发送 `SIGSTOP/SIGCONT`；不支持的平台使用本地 `control/pause.request` 与 `control/resume.request` 协作式控制文件，并把控制事件写入 RunSession，不会因为 Windows 缺少进程组暂停信号而导致 `/api/control` 或 `delivery_audit.py` 崩溃。

## 结构清理

本轮已清理并自动化验收以下确定冗余项：

- `__pycache__`
- `*.pyc`
- `.DS_Store`
- `*.tmp`
- `*.bak`
- `*~`

新增 `tools/reachops_repository_cleanliness_check.py --json` 作为可重复结构清洁度验收；`tools/reachops_delivery_audit.py --json` 已纳入 `项目结构无缓存临时备份冗余文件` 检查，当前结果为 `passed`、`forbidden_count=0`。Windows build 与 VM sync 脚本会在 `py_compile` 预检后立即清理 `__pycache__`、`.pyc`、`.pyo`，避免构建过程自造冗余文件导致审计门禁误失败。Windows acceptance 脚本会写出 `repository_cleanliness_payload.json`、`windows_package_preflight.json`，并把 `repository_cleanliness`、`windows_package_preflight` 写入 `acceptance_summary.json`；最终 `delivery_package_check.py` 和 `final_acceptance_gate.py` 会把这两份报告作为 `report_files` 必备证据，缺失时不能通过最终交付。

已清理并复查：

- `__pycache__`
- `*.pyc`
- `*.pyo`
- `.DS_Store`
- `*.tmp`
- `*~`
- `*.bak`
- `*.orig`
- `.pytest_cache`
- `.mypy_cache`
- `.ruff_cache`
- `.cache`

复查结果：冗余缓存计数为 0。

目录体积：

- 项目总量：88M
- `.venv`：60M，已被 git 忽略
- `reports`：436K，运行证据目录，已被 git 忽略

## 最终验收判定

本地审计验收：通过。

架构验收：通过，满足“运营通过网页端执行，通过服务器本地 API 调用指纹浏览器执行客户获取”的要求。

真实最终交付验收：未完成。必须在 Windows + ixBrowser + 已授权 TikTok 账号环境中重新完成：

1. 生成 `dist/ReachOps/ReachOps.exe`。
2. 生成 `dist/installer/ReachOps-Setup-<version>.exe`。
3. 生成 `dist/installer/reachops-update-manifest.json`。
4. 运行真实 acceptance，生成 `reports/reachops_acceptance/<timestamp>/acceptance_summary.json`。
5. 确认 `tools/reachops_client_delivery_check.py --json` 返回 `status=passed`、`final_delivery_ready=true`、`failed_checks=[]`。
6. 确认 `tools/reachops_delivery_package_check.py --json` 返回 `status=passed`。
7. 确认 `tools/reachops_final_acceptance_gate.py --json` 返回 `status=passed`、`final_delivery_ready=true`。
8. 确认 Web “最终复核命令”、`/api/final-status`、`tools/reachops_live_acceptance_status.py --json` 和 `tools/get_reachops_acceptance_background_status_windows.ps1 -Json` 暴露的 `verification_commands` 均包含以上三条命令。
