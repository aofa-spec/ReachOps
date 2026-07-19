#!/bin/zsh
cd "$(dirname "$0")"
echo "ReachOps 本地客户端控制台启动中..."
echo "客户端入口已统一到本地客户端控制台。"
echo ""
if [ -x "./启动ReachOps统一WebUI.command" ]; then
  exec ./启动ReachOps统一WebUI.command
fi
export PYTHONPYCACHEPREFIX="/private/tmp/reachops_pycache"
exec python3 ReachOpsApp.py
