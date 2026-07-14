#!/bin/zsh
cd "$(dirname "$0")"
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="python3"
fi
export PYTHONPYCACHEPREFIX="/private/tmp/reachops_pycache"
export NO_PROXY="127.0.0.1,localhost,::1${NO_PROXY:+,$NO_PROXY}"
export no_proxy="127.0.0.1,localhost,::1${no_proxy:+,$no_proxy}"

echo "ReachOps 账号修复计划"
echo "用途: 将最新修复计划中的硬失败账号移入 ixBrowser 的封禁账号分组。"
echo "前提: ixBrowser 客户端已启动，Local API 端口可连接。"
echo ""
echo "先预览待处理账号:"
PREVIEW_JSON="$(mktemp /tmp/reachops_account_repair_preview.XXXXXX.json)"
"$PYTHON_BIN" tools/reachops_apply_account_repair_plan.py --json > "$PREVIEW_JSON"
cat "$PREVIEW_JSON"
NO_APPLICABLE="$("$PYTHON_BIN" - "$PREVIEW_JSON" <<'PY'
import json, sys
from pathlib import Path
try:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    payload = {}
print("1" if payload.get("no_applicable_profiles") else "0")
PY
)"
if [ "$NO_APPLICABLE" = "1" ]; then
  APPLY_JSON="$(mktemp /tmp/reachops_account_repair_apply.XXXXXX.json)"
  "$PYTHON_BIN" tools/reachops_apply_account_repair_plan.py --apply --json > "$APPLY_JSON"
  "$PYTHON_BIN" - "$PREVIEW_JSON" <<'PY'
import json, sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print("")
print("最新账号修复计划没有默认可自动隔离的账号，未移动任何 ixBrowser 配置。")
if payload.get("non_auto_error_codes"):
    print("需要人工处理的错误类型: " + ", ".join(payload.get("non_auto_error_codes") or []))
for action in payload.get("next_actions") or []:
    print("下一步: " + str(action))
print("本次不会启动浏览器，也不会提交任何平台动作。")
PY
  echo "已记录本次账号修复结果: no_applicable_profiles"
  echo ""
  echo "按任意键关闭此窗口。"
  read -k 1
  exit 2
fi
echo ""
echo "确认执行请输入 APPLY 后回车；直接回车取消。"
read "CONFIRM?>"
if [ "$CONFIRM" != "APPLY" ]; then
  echo "已取消，未移动任何账号。"
  echo "按任意键关闭此窗口。"
  read -k 1
  exit 0
fi

echo ""
echo "开始执行账号修复计划..."
"$PYTHON_BIN" tools/reachops_apply_account_repair_plan.py --apply --json
STATUS=$?
echo ""
echo "刷新客户端门禁状态..."
"$PYTHON_BIN" tools/reachops_client_delivery_check.py
echo ""
if [ "$STATUS" -eq 0 ]; then
  echo "账号修复计划执行完成。请重新刷新 Web UI 分组，再执行开始获客。"
else
  echo "账号修复计划未完全执行，请检查上方错误；常见原因是 ixBrowser Local API 未启动或端口不可连接。"
fi
echo ""
echo "按任意键关闭此窗口。"
read -k 1
