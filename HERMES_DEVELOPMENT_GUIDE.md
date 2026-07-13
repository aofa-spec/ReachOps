# ReachOps 开发指南

## 环境准备

### 开发环境要求
- Python 3.8 或更高版本
- pip 包管理器
- Git 版本控制工具
- 开发 IDE (推荐 VSCode)

### 依赖安装
```bash
pip install -r requirements.txt
```

## 项目结构

```
ReachOps/
├── adapters/          # 平台适配器模块
│   ├── __init__.py
│   └── tiktok_adapter.py
├── collectors/        # 数据采集模块
│   ├── __init__.py
│   └── tiktok_comment_collector.py
├── intelligence/      # 智能分析模块
│   ├── __init__.py
│   └── growth_task_router.py
├── launcher/          # 启动入口
│   ├── __init__.py
│   └── launcher.py
├── packaging/         # 打包配置
│   └── reachops.spec
├── workbench/         # 工作台模块  
│   ├── __init__.py
│   ├── console.py
│   ├── execution_reporter.py
│   ├── profile_preflight.py
│   ├── standalone_app.py
│   └── workflow_service.py
├── tools/             # 工具脚本目录
│   ├── reachops_delivery_audit.py
│   ├── reachops_goal_status_report.py
│   ├── run_reachops_ui_startup_smoke_windows.ps1
│   ├── verify_reachops_acceptance_summary.py
│   └── sync_reachops_to_windows_vm.sh
└── tests/             # 测试用例目录
    ├── __init__.py
    └── test_reachops_campaign.py
```

## 开发规范

### 代码风格
- 遵循 PEP8 代码规范
- 使用 docstring 文档注释
- 模块文件使用下划线命名法（snake_case）
- 类名使用驼峰命名法（CamelCase）

### 测试要求
- 所有新增功能均需包含单元测试
- 遵循 TDD 开发模式
- 使用 unittest 框架
- 单测覆盖率达到 80%+

## 构建与部署

### Windows 构建命令
```bash
# 运行UI启动smoke测试
tools\run_reachops_ui_startup_smoke_windows.ps1

# 执行Windows构建  
tools\build_reachops_windows.ps1
```

## 工具使用说明

### 操作工具
- `run_reachops_ui_startup_smoke_windows.ps1` - Windows UI启动Smoke测试
- `build_reachops_windows.ps1` - Windows平台构建脚本
- `reachops_delivery_audit.py` - 交付审计工具
- `reachops_goal_status_report.py` - 目标状态报告工具

## API 文档

### 核心接口
```
POST /api/v1/reachops/submit
请求参数:
{
  "target": "tiktok_post_url",
  "action": "comment",
  "content": "comment text"
}
```

## 安全说明

所有操作均需通过授权机制验证，在配置认证文件后方可进行真实提交。