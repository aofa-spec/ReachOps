# ReachOps / 增长获客工作台

这是 ReachOps 独立增长获客客户端工程。

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

## 启动方式

```bash
python -m ReachOps
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
读取 manifest → 校验 product/platform/version → 比较版本
→ 校验安装包 size/sha256 → 生成静默安装参数
```

升级策略默认保留独立配置目录、数据目录和授权状态。
