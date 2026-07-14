# ReachOps / 增长获客工作台

这是 ReachOps 独立增长获客客户端工程。

当前版本：`0.4.0` / `mvp`。

产品目标不是做数据展示页，而是交付一个可实盘运行的商家获客工作台：

```text
采集目标
→ 账号调度
→ 内容扫描
→ 评论用户采集
→ 用户去重
→ 意向识别
→ 高意向线索池
→ 动作队列
→ 执行前预检
→ 评论/关注/私信触达
→ 失败换号与降级
→ 运营报告
```

## 独立边界

当前目录是独立客户端的产品入口，所有增长获客相关能力应收敛到这里：

- `launcher.py`：独立启动入口
- `__main__.py`：支持 `python -m ReachOps`
- `PRODUCT_ARCHITECTURE.md`：产品和架构交付边界

当前版本已经把增长获客实现收敛到独立产品目录：

- UI 与工作台：`ReachOps/workbench`
- 采集与数据模型：`ReachOps/intelligence`
- 页面采集适配器：`ReachOps/collectors`
- 外部浏览器适配：`ReachOps/adapters`

开发原则：

1. 所有 UI 设置必须有真实后端逻辑。
2. 所有执行结果必须有 batch、event、error、report 证据。
3. 配置、数据、授权、日志、报告必须使用独立运行目录。
4. 新增增长获客能力优先写入本目录下的 `ReachOps/workbench`、`ReachOps/intelligence`、`ReachOps/collectors` 或 `ReachOps/adapters`。

PM/运营验收先看 `docs/REACHOPS_GOAL_MODE_EXECUTION.md` 和 `docs/REACHOPS_PM_DELIVERY_BASELINE.md`。目标模式总控入口是：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_goal_delivery_runner.py --json
```

## 启动方式

默认客户端入口为原生 UI；以下命令会启动本地原生客户端窗口：

```bash
python -m ReachOps
python ReachOpsApp.py
```

Mac 桌面入口 `启动ReachOps本地客户端.command` 和 `启动ReachOps原生MacUI.command` 会启动原生客户端 UI。

Web 控制台仅作为备用入口，需要时显式开启：

```bash
python ReachOpsApp.py --web
./启动ReachOps统一WebUI.command
```

Web 控制台也可用开发命令直接启动，用于调试本机后端执行链路：

```bash
python tools/reachops_web_ui.py --web --host 127.0.0.1 --port 8769
```

## Windows 独立打包

ReachOps 使用独立版本源和打包脚本：

- 版本源：`ReachOps/version.py`
- PyInstaller spec：`ReachOps/packaging/reachops.spec`
- Inno Setup：`ReachOps/packaging/ReachOps.iss`
- Windows 构建入口：`tools/build_reachops_windows.ps1`
- 升级清单：`tools/write_reachops_update_manifest.py`
- 客户端升级校验：`ReachOps/updater.py`

Windows 构建命令：

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_reachops_windows.ps1
```

仅构建 exe、不生成安装包：

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_reachops_windows.ps1 -SkipInstaller
```

构建脚本会先执行 ReachOps 独立 smoke、完整交付审计和独立单测，确认“产品/关键词 → 客户池 → 动作队列 → 预检 → 报告”链路可用后再打包。

升级流程使用 `reachops-update-manifest.json`：

```text
读取 manifest → 校验 product/platform/channel/version/signature/rollback_policy
→ 比较版本 → 校验安装包 size/sha256 → 生成静默安装参数
```

远程 manifest 必须使用 HTTPS 且带 `manifest_signature`；本地 manifest 只用于离线构建、恢复和测试。升级策略默认保留独立配置目录、数据目录和授权状态；默认禁止降级，只有 manifest 显式声明 `rollback_policy.allow_downgrade=true` 时才进入受控 rollback 路径。

商业运行时的真实触达授权必须来自服务端签发的 `entitlement_signature`。打包运行时会拒绝 unsigned、过期、设备不匹配、撤销、离线宽限过期、超并发设备限制或被紧急禁用的 entitlement；源码开发环境仍可使用无提交的模板和本地 blocked 报告做测试。

## 数据治理、迁移和恢复

SQLite schema 迁移由 `ReachOps/intelligence/migrations.py` 注册，运行时初始化会写入 `schema_migrations`，并记录每个迁移的 checksum、rollback policy 和应用时间。隐私操作审计写入 `data_privacy_audit`，用于 export、delete、legal hold、backup 和 restore 证据。

本地数据治理验收命令：

```bash
python tools/reachops_data_governance.py --create-missing-db --verify-backup --json
```

该检查会验证 schema integrity、已应用迁移、备份/恢复 hash、retention classes、PII data catalog 和默认 redacted support bundle policy。

## WAQO 和商业结果漏斗

商业验收不以评论数、浏览器打开数或 fixture 动作数作为最终指标。`tools/reachops_outcome_metrics.py` 定义 WAQO：一周内由人工 owner 接受、进入 active follow-up、有 source/evidence/dedupe_key 的唯一 qualified opportunity。默认排除 `fixture` 和 `dry_run` 数据。

```bash
python tools/reachops_outcome_metrics.py --create-missing-db --json
```

CSV outcome ingestion 用于试点客户先回填人工确认结果，不需要先接入重型 CRM：

```powershell
python tools/reachops_outcome_metrics.py --db-path data/growth_intelligence.sqlite --create-missing-db --import-csv pilot_outcomes.csv --ingest-source csv --json
```

该检查会输出 WAQO、accepted/rejected、reply、meaningful conversation、meeting、quote、order、revenue、lost reason、elapsed time、conversion rates、cost per accepted opportunity、precision/recall 占位和 duplicate rate；accepted opportunity 必须有 `contact_policy`，rejected lead 必须具备结构化 rejection reason。Webhook-style JSON payload 可以通过 `--import-webhook-json` 进入同一张 outcome 表，默认仍排除 fixture/dry-run。

## 交付状态

当前本地已验证：

- 产品/关键词/达人/话题目标可以创建获客任务。
- 系统可以生成受众画像、来源规划、客户线索和触达动作。
- 执行预检、失败原因、换号、降级评论、限频和证据要求已有本地验收覆盖。
- AI/规则策略、外部 AI 失败降级、人工策略编辑已有本地验收覆盖。

仍需外部环境验证：

- Windows UI startup smoke。
- Windows PyInstaller build 和 Inno Setup installer。
- 真实 ixBrowser profile readiness/preflight。
- 授权后的真实 TikTok comment/follow/DM 受控提交。

执行计划和实机 runbook：

```text
ReachOps/docs/REACHOPS_DELIVERY_EXECUTION_PLAN.md
ReachOps/docs/REACHOPS_WINDOWS_LIVE_ACCEPTANCE_RUNBOOK.md
```

完整交付前，acceptance summary 必须达到 `passed`，`effective_pending_external_validation` 必须为 `0`，客户端交付门禁必须达到 `final_delivery_ready=true`，Windows 交付包检查必须返回 `status=passed` 且包含 `repository_cleanliness` 报告证据，并且 `tools/reachops_final_acceptance_gate.py --json` 必须返回 `status=passed`、`failed_checks=[]`。
