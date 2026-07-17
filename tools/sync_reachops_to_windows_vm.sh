#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_HOST="${REACHOPS_WINDOWS_VM_HOST:-windows-vm}"
REMOTE_DIR="${REACHOPS_WINDOWS_VM_DIR:-C:/Users/aofa/ReachOps_client}"
APPLY=0
RUN_TESTS=0

usage() {
  cat <<'USAGE'
Usage: tools/sync_reachops_to_windows_vm.sh [--apply] [--run-tests]

Default is dry-run. Use --apply to update the Windows VM workspace.

Environment:
  REACHOPS_WINDOWS_VM_HOST   SSH host alias, default: windows-vm
  REACHOPS_WINDOWS_VM_DIR    Windows target dir, default: C:/Users/aofa/ReachOps_client

Synced:
  ReachOps/
  ReachOpsApp.py
  HANDOFF.md
  README.md
  tests/test_reachops_campaign.py
  selected ReachOps helper scripts under tools/

Excluded by construction:
  data/, reports/, logs, databases, caches, .env, activation status, secrets, git metadata.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=1
      shift
      ;;
    --run-tests)
      RUN_TESTS=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

require_file() {
  local path="$1"
  if [[ ! -e "$ROOT_DIR/$path" ]]; then
    echo "Missing required path: $path" >&2
    exit 1
  fi
}

require_file "ReachOps"
require_file "ReachOpsApp.py"
require_file "GrowthIntelligenceApp.py"
require_file "tests/test_reachops_campaign.py"
require_file "requirements.txt"
require_file "README.md"
require_file "HANDOFF.md"

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/reachops-sync.XXXXXX")"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

STAGE_DIR="$TMP_DIR/stage"
mkdir -p "$STAGE_DIR/tests" "$STAGE_DIR/tools"
mkdir -p "$STAGE_DIR/ico"

rsync -a --delete \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  --exclude 'data/' \
  --exclude 'reports/' \
  --exclude 'logs/' \
  --exclude '*.db' \
  --exclude '*.sqlite' \
  --exclude '*.sqlite3' \
  --exclude '*.log' \
  --exclude '*.env' \
  --exclude '.env' \
  --exclude 'reachops_activation_status.json' \
  "$ROOT_DIR/ReachOps/" "$STAGE_DIR/ReachOps/"

cp "$ROOT_DIR/ReachOpsApp.py" "$STAGE_DIR/ReachOpsApp.py"
cp "$ROOT_DIR/GrowthIntelligenceApp.py" "$STAGE_DIR/GrowthIntelligenceApp.py"
find "$ROOT_DIR/tests" -maxdepth 1 -type f -name "*.py" -exec cp {} "$STAGE_DIR/tests/" \;
cp "$ROOT_DIR/requirements.txt" "$STAGE_DIR/requirements.txt"
cp "$ROOT_DIR/README.md" "$STAGE_DIR/README.md"
cp "$ROOT_DIR/HANDOFF.md" "$STAGE_DIR/HANDOFF.md"
for command_file in \
  "启动ReachOps本地客户端.command" \
  "启动ReachOps统一WebUI.command" \
  "启动ReachOps原生MacUI.command" \
  "执行ReachOps账号修复.command" \
  "复测ReachOps真实执行.command" \
  "打开ReachOps验收包.command"
do
  if [[ -f "$ROOT_DIR/$command_file" ]]; then
    cp "$ROOT_DIR/$command_file" "$STAGE_DIR/$command_file"
    chmod +x "$STAGE_DIR/$command_file" || true
  fi
done
if [[ -f "$ROOT_DIR/ico/startup_icon.ico" ]]; then
  cp "$ROOT_DIR/ico/startup_icon.ico" "$STAGE_DIR/ico/startup_icon.ico"
fi

for helper in \
  capture_growth_ui_windows.bat \
  capture_windows_desktop.py \
  capture_windows_desktop_hidden.ps1 \
  start_growth_ui_windows.bat \
  start_reachops_ui_windows.ps1 \
  reachops_web_ui.py \
  reachops_mac_web_ui.py \
  reachops_mac_self_check.py \
  run_reachops_headless_macos.py \
  reachops_client_acceptance_status.py \
  reachops_client_delivery_check.py \
  reachops_web_panel_dom_smoke.py \
  reachops_web_panel_runtime_smoke.py \
  reachops_delivery_smoke.py \
  reachops_action_preflight_existing_batch.py \
  reachops_real_acquisition_report.py \
  reachops_operator_pressure.py \
  reachops_delivery_audit.py \
  reachops_delivery_package_check.py \
  reachops_issue_closure_audit.py \
  reachops_final_acceptance_gate.py \
  reachops_activation_status_check.py \
  reachops_activation_status_template.py \
  init_reachops_acceptance_inputs.py \
  init_reachops_acceptance_inputs_windows.ps1 \
  reachops_acceptance_inputs.example.ps1 \
  reachops_goal_status_report.py \
  reachops_goal_delivery_runner.py \
  reachops_mvp_acceptance_summary.py \
  reachops_mac_loop_acceptance.py \
  reachops_two_phase_acceptance_matrix.py \
  reachops_live_validation_manifest.py \
  reachops_live_acceptance_status.py \
  reachops_live_environment_blocker_report.py \
  reachops_authorization_handoff_bundle.py \
  reachops_ixbrowser_profile_metadata_report.py \
  reachops_visual_collection_preflight.py \
  reachops_live_preflight.py \
  reachops_live_readiness.py \
  reachops_live_submit_acceptance.py \
  reachops_repository_cleanliness_check.py \
  reachops_windows_package_preflight.py \
  reachops_apply_account_repair_plan.py \
  run_reachops_live_readiness_windows.ps1 \
  run_reachops_live_validation_manifest_windows.ps1 \
  run_reachops_live_preflight_windows.ps1 \
  run_reachops_ui_startup_smoke_windows.ps1 \
  run_reachops_installer_smoke_windows.ps1 \
  run_reachops_acceptance_windows.ps1 \
  start_reachops_acceptance_background_windows.ps1 \
  get_reachops_acceptance_background_status_windows.ps1 \
  sync_reachops_to_windows_vm.sh \
  verify_reachops_acceptance_summary.py \
  write_reachops_update_manifest.py \
  build_reachops_windows.ps1
do
  if [[ -f "$ROOT_DIR/tools/$helper" ]]; then
    cp "$ROOT_DIR/tools/$helper" "$STAGE_DIR/tools/$helper"
  fi
done

ARCHIVE="$TMP_DIR/reachops-sync.tar.gz"
tar -C "$STAGE_DIR" -czf "$ARCHIVE" .

echo "ReachOps sync package prepared:"
tar -tzf "$ARCHIVE" | sed -n '1,220p'
COUNT="$(tar -tzf "$ARCHIVE" | wc -l | tr -d ' ')"
echo "Files/directories in package: $COUNT"
echo "Target: $REMOTE_HOST:$REMOTE_DIR"

if [[ "$APPLY" -ne 1 ]]; then
  echo "Dry-run only. Re-run with --apply to sync."
  exit 0
fi

REMOTE_ARCHIVE="C:/Users/aofa/reachops-sync.tar.gz"
scp "$ARCHIVE" "$REMOTE_HOST:$REMOTE_ARCHIVE"
ssh "$REMOTE_HOST" "powershell -NoProfile -ExecutionPolicy Bypass -Command \"New-Item -ItemType Directory -Force -Path '$REMOTE_DIR' | Out-Null; tar -xzf '$REMOTE_ARCHIVE' -C '$REMOTE_DIR'; Remove-Item '$REMOTE_ARCHIVE' -Force\""

echo "Synced ReachOps package to Windows VM."

if [[ "$RUN_TESTS" -eq 1 ]]; then
  ssh "$REMOTE_HOST" "powershell -NoProfile -ExecutionPolicy Bypass -Command \"\$ErrorActionPreference = 'Stop'; \$env:PYTHONIOENCODING = 'utf-8'; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; [Console]::InputEncoding = [System.Text.Encoding]::UTF8; \$OutputEncoding = [System.Text.Encoding]::UTF8; chcp 65001 | Out-Null; cd '$REMOTE_DIR'; C:\\Python311-x64\\python.exe -m py_compile ReachOps\\workbench\\authorization_gate.py ReachOps\\workbench\\action_router.py ReachOps\\workbench\\workflow_service.py ReachOps\\workbench\\standalone_app.py ReachOps\\intelligence\\schemas.py ReachOps\\intelligence\\ai_strategy.py ReachOps\\intelligence\\service.py tests\\test_reachops_campaign.py ReachOpsApp.py GrowthIntelligenceApp.py tools\\reachops_web_ui.py tools\\reachops_mac_web_ui.py tools\\reachops_mac_self_check.py tools\\reachops_client_acceptance_status.py tools\\reachops_client_delivery_check.py tools\\reachops_web_panel_dom_smoke.py tools\\reachops_web_panel_runtime_smoke.py tools\\reachops_delivery_audit.py tools\\reachops_delivery_package_check.py tools\\reachops_issue_closure_audit.py tools\\reachops_final_acceptance_gate.py tools\\reachops_activation_status_check.py tools\\reachops_activation_status_template.py tools\\init_reachops_acceptance_inputs.py tools\\reachops_action_preflight_existing_batch.py tools\\reachops_real_acquisition_report.py tools\\reachops_operator_pressure.py tools\\reachops_goal_status_report.py tools\\reachops_live_validation_manifest.py tools\\reachops_live_acceptance_status.py tools\\reachops_live_environment_blocker_report.py tools\\reachops_repository_cleanliness_check.py tools\\reachops_ixbrowser_profile_metadata_report.py tools\\reachops_visual_collection_preflight.py tools\\reachops_live_preflight.py tools\\reachops_live_submit_acceptance.py tools\\verify_reachops_acceptance_summary.py tools\\write_reachops_update_manifest.py; if (\$LASTEXITCODE -ne 0) { exit \$LASTEXITCODE }; Get-ChildItem -Path . -Directory -Recurse -Force -Filter __pycache__ -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; Get-ChildItem -Path . -File -Recurse -Force -Include *.pyc,*.pyo -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue; if (!(Test-Path tools\\run_reachops_installer_smoke_windows.ps1)) { throw 'run_reachops_installer_smoke_windows.ps1 missing' }; if (!(Test-Path tools\\start_reachops_ui_windows.ps1)) { throw 'start_reachops_ui_windows.ps1 missing' }; if (!(Test-Path tools\\run_reachops_ui_startup_smoke_windows.ps1)) { throw 'run_reachops_ui_startup_smoke_windows.ps1 missing' }; if (!(Test-Path tools\\run_reachops_live_validation_manifest_windows.ps1)) { throw 'run_reachops_live_validation_manifest_windows.ps1 missing' }; if (!(Test-Path tools\\init_reachops_acceptance_inputs.py)) { throw 'init_reachops_acceptance_inputs.py missing' }; if (!(Test-Path tools\\init_reachops_acceptance_inputs_windows.ps1)) { throw 'init_reachops_acceptance_inputs_windows.ps1 missing' }; if (!(Test-Path tools\\reachops_web_ui.py)) { throw 'reachops_web_ui.py missing' }; if (!(Test-Path tools\\reachops_client_delivery_check.py)) { throw 'reachops_client_delivery_check.py missing' }; if (!(Test-Path tools\\reachops_web_panel_runtime_smoke.py)) { throw 'reachops_web_panel_runtime_smoke.py missing' }; if (!(Test-Path tools\\reachops_issue_closure_audit.py)) { throw 'reachops_issue_closure_audit.py missing' }; C:\\Python311-x64\\python.exe -m unittest tests.test_reachops_campaign; if (\$LASTEXITCODE -ne 0) { exit \$LASTEXITCODE }; C:\\Python311-x64\\python.exe tools\\reachops_operator_pressure.py --json; if (\$LASTEXITCODE -ne 0) { exit \$LASTEXITCODE }; C:\\Python311-x64\\python.exe tools\\reachops_delivery_audit.py --json; if (\$LASTEXITCODE -ne 0) { exit \$LASTEXITCODE }; C:\\Python311-x64\\python.exe tools\\reachops_issue_closure_audit.py --json > reachops_issue_closure_sync.json; if (\$LASTEXITCODE -ne 0) { exit \$LASTEXITCODE }; C:\\Python311-x64\\python.exe tools\\reachops_goal_status_report.py --json; if (\$LASTEXITCODE -ne 0) { exit \$LASTEXITCODE }; C:\\Python311-x64\\python.exe tools\\reachops_final_acceptance_gate.py --json > reachops_final_acceptance_gate_sync.json; if (\$LASTEXITCODE -notin @(0,1)) { exit \$LASTEXITCODE }; \$syncIssueClosure = Get-Content reachops_issue_closure_sync.json -Raw -Encoding UTF8 | ConvertFrom-Json; if (-not \$syncIssueClosure.status) { throw 'issue closure audit did not produce status' }; Write-Host ('SYNC_ISSUE_CLOSURE_STATUS=' + \$syncIssueClosure.status); \$syncFinalGate = Get-Content reachops_final_acceptance_gate_sync.json -Raw -Encoding UTF8 | ConvertFrom-Json; if (-not \$syncFinalGate.status) { throw 'final acceptance gate did not produce status' }; Write-Host ('SYNC_FINAL_ACCEPTANCE_GATE_STATUS=' + \$syncFinalGate.status); Write-Host ('SYNC_FINAL_DELIVERY_READY=' + [string]\$syncFinalGate.final_delivery_ready)\""
fi
