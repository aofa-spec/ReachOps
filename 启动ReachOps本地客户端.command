#!/bin/zsh
cd "$(dirname "$0")"
echo "ReachOps 本地客户端启动中..."
echo "该入口会启动统一 Web 控制台。"
echo ""
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="python3"
fi
export PYTHONPYCACHEPREFIX="/private/tmp/reachops_pycache"
exec ./启动ReachOps统一WebUI.command
