#!/bin/zsh
cd "$(dirname "$0")"
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="python3"
fi
export PYTHONPYCACHEPREFIX="/private/tmp/reachops_pycache"

echo "ReachOps 客户端入口已统一到本地客户端控制台。"
echo "ReachOps 本地客户端控制台实际地址会由 ./启动ReachOps统一WebUI.command 打印。"
echo "旧 Tk 仅作为诊断入口保留；本脚本通过 REACHOPS_LEGACY_TK=1 启动诊断 UI。"
echo "等效命令：python ReachOpsApp.py --legacy-tk"
echo ""

REACHOPS_LEGACY_TK=1 "$PYTHON_BIN" ReachOpsApp.py --legacy-tk
STATUS=$?
echo ""
if [ "$STATUS" -ne 0 ]; then
  echo "原生客户端启动失败，退出码：$STATUS"
  echo "请运行本地客户端控制台：./启动ReachOps统一WebUI.command"
  echo "按任意键关闭此窗口。"
  read -k 1
fi
exit "$STATUS"
