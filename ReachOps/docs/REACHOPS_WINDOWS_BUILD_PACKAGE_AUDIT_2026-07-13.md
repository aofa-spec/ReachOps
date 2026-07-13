# ReachOps Windows 构建包审计验收记录

日期：2026-07-13（Asia/Shanghai）

## 结论

已恢复连接 Windows VM，并在真实 Windows 环境构建出 Windows 主程序和安装包。

当前状态不是“构建失败”，而是“Windows 可执行构建已产出，客户最终验收仍未闭环”。最终验收未通过的原因是缺少本轮通过态 `acceptance_summary.json`，并且真实 ixBrowser 账号/授权 TikTok 触达证据仍未完成。

## VM 连接原因排查

现象：

- 初始 SSH 到 `windows-vm` 返回 `No route to host`。
- SSH 配置解析到 `10.211.55.3`，用户 `aofa`，密钥 `~/.ssh/id_ed25519_windows`。
- Parallels VM 处于 running 状态，但 `prlctl list --all` 一度显示 IP 为空。

原因判断：

- 不是项目代码问题，也不是 Windows 构建脚本问题。
- 是 Parallels 共享网络/Guest Tools IP 报告或 ARP 状态短暂不可达。
- 后续 `nc -vz 10.211.55.3 22` 成功，SSH 恢复，说明 VM 网络端口已恢复。
- 另有一次远程 PowerShell 命令因本地 shell 展开 `$env` 导致引用错误，已改用正确 quoting 继续执行。

## 已生成 Windows 真实产物

- Windows 主程序：`dist/ReachOps/ReachOps.exe`
  - 大小：`5,978,288` bytes
  - SHA256：`4cafe35f2ce7bc56cf8920cfcf00aaa989e33efcc39f34b2d026b7431775dfe3`
  - PE 签名结构检查：通过

- Windows 安装包：`dist/installer/ReachOps-Setup-0.4.0.exe`
  - 大小：`19,980,761` bytes
  - SHA256：`e9949b607267018f081f5d3bb4d2ee6fa130a39ea7f932e6cb2c2a4279b06247`
  - PE 签名结构检查：通过

- 更新清单：`dist/installer/reachops-update-manifest.json`
  - 大小：`666` bytes
  - SHA256：`c4507d407f98ac3b402f0605830a70808ed7e5ea7f83d073a83035709ab7ca32`
  - manifest 内安装包大小和 SHA256 与实际文件一致。

以上产物已从 Windows VM 拉回本机。

## 本轮修复内容

- 修复 Windows 同步脚本缺失关键验收/构建工具的问题，补齐：
  - `reachops_goal_delivery_runner.py`
  - `reachops_repository_cleanliness_check.py`
  - `reachops_windows_package_preflight.py`
  - `reachops_mvp_acceptance_summary.py`
  - `reachops_mac_loop_acceptance.py`
  - `reachops_two_phase_acceptance_matrix.py`
  - `reachops_apply_account_repair_plan.py`
  - `reachops_authorization_handoff_bundle.py`
  - 全量 `tests/*.py`

- 修复 Windows Web 面板烟测兼容性：
  - Node 子进程输出改为 UTF-8 容错解码，避免 Windows GBK 解码崩溃。
  - FakeProcess 增加 `send_signal`，pause/resume/stop 控制链路可验证。
  - 临时目录清理允许 Windows SQLite 文件锁容错。
  - 启动命令断言改为跨平台路径判断。

- 修复客户端交付检查在 Windows 上误要求 macOS `.command` 入口的问题，Windows 改检查：
  - `tools/start_reachops_ui_windows.ps1`
  - `tools/start_growth_ui_windows.bat`
  - `tools/run_reachops_acceptance_windows.ps1`
  - `tools/build_reachops_windows.ps1`

## 已执行审计

- Windows Web 面板运行时烟测：
  - 命令：`tools/reachops_web_panel_runtime_smoke.py --json`
  - 状态：`passed`
  - 失败项：无

- Windows 预检：
  - 命令：`tools/reachops_windows_package_preflight.py --json`
  - 状态：`ready_for_windows_build`
  - 失败项：无
  - 缺失最终产物：`acceptance_summary`

- 本机交付包检查：
  - 命令：`tools/reachops_delivery_package_check.py --json`
  - 状态：`failed`
  - `final_delivery_ready=false`
  - 已验证：`exe`、`installer`、`manifest`
  - 失败项：`acceptance_summary_missing`、`acceptance_summary_not_passed`

- 最终验收门禁：
  - 命令：`tools/reachops_final_acceptance_gate.py --json`
  - 状态：`not_ready`
  - `final_delivery_ready=false`
  - 失败项：
    - `goal_status:passed`
    - `client_delivery:final_ready`
    - `delivery_package:passed`

- Windows 端交付包检查：
  - `exe`、`installer`、`manifest` 均存在。
  - Windows 上旧 `acceptance_summary.json` 存在，但不是本轮通过态，仍包含真实 ixBrowser/账号/授权触达阻塞，因此不能作为客户最终验收通过证据。

## 客户最终验收缺口

最终交付仍必须补齐：

- `reports/reachops_acceptance/acceptance_summary.json`
- 真实授权目标输入
- 激活状态 ready
- 可用 ixBrowser 登录账号
- 至少一次授权范围内的真实采集/触达证据
- `tools/reachops_delivery_package_check.py --json` 返回 `status=passed`
- `tools/reachops_final_acceptance_gate.py --json` 返回 `status=passed` 且 `final_delivery_ready=true`

## 当前可交付边界

可以交付说明为：

- “Windows 构建包已真实生成，安装包和 manifest 已完成文件级校验。”

不能交付说明为：

- “客户最终验收已通过。”
- “真实 TikTok 采集触达已完成。”
- “登录成功账号已经完成采集触达任务。”

原因是当前门禁仍明确显示账号/授权/真实平台验证未闭环。
