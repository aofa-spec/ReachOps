#!/bin/zsh
cd "$(dirname "$0")"
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="python3"
fi
export PYTHONPYCACHEPREFIX="/private/tmp/reachops_pycache"

echo "ReachOps 原生客户端 UI 启动中。"
echo "该入口不会打开 Web 控制台。"
echo ""

"$PYTHON_BIN" ReachOpsApp.py
STATUS=$?
echo ""
if [ "$STATUS" -ne 0 ]; then
  echo "原生客户端启动失败，退出码：$STATUS"
  echo "如需备用 Web 控制台，请运行：./启动ReachOps统一WebUI.command"
  echo "按任意键关闭此窗口。"
  read -k 1
fi
exit "$STATUS"
