#!/bin/zsh
cd "$(dirname "$0")"
echo "ReachOps 本地客户端启动中..."
echo "该入口会启动统一本地客户端控制台。"
echo ""
exec ./启动ReachOps统一WebUI.command
