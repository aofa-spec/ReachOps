#!/bin/zsh
cd "$(dirname "$0")"
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="python3"
fi
export PYTHONPYCACHEPREFIX="/private/tmp/reachops_pycache"
export REACHOPS_LEGACY_TK=1

echo "ReachOps 客户端入口已统一到本地客户端控制台。"
echo "旧 Tk 仅作为诊断入口保留。"
echo ""

"$PYTHON_BIN" ReachOpsApp.py --legacy-tk
STATUS=$?
echo ""
if [ "$STATUS" -ne 0 ]; then
  echo "原生客户端启动失败，退出码：$STATUS"
  echo "如需备用 Web 控制台，请运行：./启动ReachOps统一WebUI.command"
  echo "按任意键关闭此窗口。"
  read -k 1
fi
exit "$STATUS"
