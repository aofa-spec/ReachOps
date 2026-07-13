#!/bin/zsh
cd "$(dirname "$0")"
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="python3"
fi
export PYTHONPYCACHEPREFIX="/private/tmp/reachops_pycache"
"$PYTHON_BIN" tools/reachops_mac_self_check.py --start-web
echo ""
URL_FILE="reports/reachops/mac_gui/runtime/reachops_web_ui_url.txt"
if [ -f "$URL_FILE" ]; then
  REACHOPS_URL="$(cat "$URL_FILE")"
  echo "ReachOps 本地客户端控制台实际地址: $REACHOPS_URL"
  echo "请以这里打印的实际地址为准；如果旧端口仍打开，说明旧服务还在运行。"
  echo "如果浏览器没有自动打开，请复制上面的实际地址。"
  REACHOPS_URL="$REACHOPS_URL" "$PYTHON_BIN" - <<'PY'
import os
import webbrowser
webbrowser.open(os.environ.get("REACHOPS_URL", "http://127.0.0.1:8769/"))
PY
else
  echo "本地客户端控制台未生成可用地址，请查看上方自检输出。"
fi
echo ""
echo "按任意键关闭此窗口。"
read -k 1
