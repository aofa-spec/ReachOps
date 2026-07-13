#!/bin/zsh
cd "$(dirname "$0")"
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="python3"
fi
export PYTHONPYCACHEPREFIX="/private/tmp/reachops_pycache"

REPORT_DIR="reports/reachops/mac_gui/runtime/reports/acceptance_remediation"
LATEST_GUIDE="$REPORT_DIR/latest_client_acceptance_guide.md"
LATEST_INDEX="$REPORT_DIR/latest_acceptance_index.html"
LATEST_MANIFEST="$REPORT_DIR/latest_acceptance_manifest.json"

echo "刷新 ReachOps 当前验收状态..."
"$PYTHON_BIN" tools/reachops_client_acceptance_status.py
"$PYTHON_BIN" tools/reachops_client_delivery_check.py --json >/dev/null

echo ""
if [ -f "$LATEST_INDEX" ]; then
  echo "打开验收包首页: $LATEST_INDEX"
  open "$LATEST_INDEX"
elif [ -f "$LATEST_GUIDE" ]; then
  echo "打开客户验收指南: $LATEST_GUIDE"
  open "$LATEST_GUIDE"
else
  echo "未找到最新验收首页或指南。"
fi

if [ -f "$LATEST_MANIFEST" ]; then
  echo "打开验收包目录: $REPORT_DIR"
  open "$REPORT_DIR"
else
  echo "未找到最新验收 manifest。"
fi

echo ""
echo "按任意键关闭此窗口。"
read -k 1
