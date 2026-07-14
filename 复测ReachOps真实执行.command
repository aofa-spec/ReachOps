#!/bin/zsh
cd "$(dirname "$0")"
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="python3"
fi
export PYTHONPYCACHEPREFIX="/private/tmp/reachops_pycache"

TARGET_URL="${REACHOPS_TARGET:-https://www.amazon.com/APRILSKIN-Pore-Care-Long-lasting-Duo/dp/B0GXKPKRW6?ref_=ast_sto_dp}"
PROFILE_GROUP="${REACHOPS_GROUP:-United States}"
PROFILE_LIMIT="${REACHOPS_PROFILES:-3}"
MODE="preflight"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="reports/reachops/mac_gui/runtime/reports/manual_retest"
OUT_FILE="$OUT_DIR/retest_$TIMESTAMP.json"

mkdir -p "$OUT_DIR"

echo "ReachOps Mac 真实执行复测"
echo "目标: $TARGET_URL"
echo "分组: $PROFILE_GROUP"
echo "账号数: $PROFILE_LIMIT"
echo ""
echo "默认执行: 采集 + 触达预检，不真实提交评论。"
echo ""
echo "读取当前客户端门禁和账号修复状态..."
PRECHECK_JSON="$OUT_DIR/precheck_$TIMESTAMP.json"
"$PYTHON_BIN" tools/reachops_client_delivery_check.py --json > "$PRECHECK_JSON"
PRECHECK_STATUS=$?
PENDING_RECHECK="$("$PYTHON_BIN" - "$PRECHECK_JSON" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    payload = {}
repair = payload.get("account_repair_apply") if isinstance(payload.get("account_repair_apply"), dict) else {}
if repair.get("pending_recheck"):
    print("1")
else:
    print("0")
PY
)"
STALE_REPAIR="$("$PYTHON_BIN" - "$PRECHECK_JSON" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    payload = {}
repair = payload.get("account_repair_apply") if isinstance(payload.get("account_repair_apply"), dict) else {}
if repair.get("stale"):
    print("1")
else:
    print("0")
PY
)"
if [ "$STALE_REPAIR" = "1" ]; then
  "$PYTHON_BIN" - "$PRECHECK_JSON" <<'PY'
import json, sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
repair = payload.get("account_repair_apply") or {}
summary = payload.get("account_repair_summary") or {}
print("旧账号修复结果已失效：系统已产生新的账号阻断批次，不能继续用旧修复结果复测。")
print(f"旧修复结果: {repair.get('path') or repair.get('source') or '-'}")
print(f"失效原因: {repair.get('stale_reason') or '-'}")
print(f"最新修复计划: {summary.get('path') or '-'}")
print("请先执行 ./执行ReachOps账号修复.command 处理最新计划，再重新运行本复测入口。")
print("本次不会启动浏览器，也不会提交任何平台动作。")
PY
  echo ""
  echo "按任意键关闭此窗口。"
  read -k 1
  exit 2
fi
if [ "$PENDING_RECHECK" = "1" ]; then
  export REACHOPS_FORCE_ACCOUNT_RECHECK="1"
  "$PYTHON_BIN" - "$PRECHECK_JSON" <<'PY'
import json, sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
repair = payload.get("account_repair_apply") or {}
print(f"账号修复已执行：已隔离 {repair.get('moved_count', 0)} 个账号，进入重新预检模式。")
print("本次复测会重新读取分组并重新预检剩余账号；若仍为 0 个可用账号，会生成新的阻断原因。")
PY
else
  unset REACHOPS_FORCE_ACCOUNT_RECHECK
  echo "未检测到待重新预检的账号修复结果，按普通复测执行。"
fi
echo "预检状态文件: $PRECHECK_JSON"
echo ""
echo "如需真实评论触达，请输入 LIVE 后回车；直接回车则执行预检。"
read "CONFIRM_MODE?>"
if [ "$CONFIRM_MODE" = "LIVE" ]; then
  MODE="live_comment"
  echo "已选择真实评论模式。"
else
  echo "已选择触达预检模式。"
fi

echo ""
echo "开始执行..."
"$PYTHON_BIN" tools/run_reachops_headless_macos.py \
  --target "$TARGET_URL" \
  --source-type auto \
  --profile-group "$PROFILE_GROUP" \
  --profile-limit "$PROFILE_LIMIT" \
  --max-videos 3 \
  --max-comments 20 \
  --mode "$MODE" \
  --volume quick \
  --timeout 420 \
  --json | tee "$OUT_FILE"

echo ""
echo "复测输出: $OUT_FILE"
echo ""
echo "生成验收状态和报告..."
"$PYTHON_BIN" tools/reachops_client_acceptance_status.py
"$PYTHON_BIN" tools/reachops_client_delivery_check.py --json

echo ""
echo "按任意键关闭此窗口。"
read -k 1
