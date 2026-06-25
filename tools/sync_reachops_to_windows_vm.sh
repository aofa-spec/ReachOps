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
cp "$ROOT_DIR/tests/test_reachops_campaign.py" "$STAGE_DIR/tests/test_reachops_campaign.py"
cp "$ROOT_DIR/requirements.txt" "$STAGE_DIR/requirements.txt"
cp "$ROOT_DIR/README.md" "$STAGE_DIR/README.md"
if [[ -f "$ROOT_DIR/ico/startup_icon.ico" ]]; then
  cp "$ROOT_DIR/ico/startup_icon.ico" "$STAGE_DIR/ico/startup_icon.ico"
fi

for helper in \
  capture_growth_ui_windows.bat \
  capture_windows_desktop.py \
  capture_windows_desktop_hidden.ps1 \
  start_growth_ui_windows.bat \
  start_reachops_ui_windows.ps1 \
  reachops_delivery_smoke.py \
  reachops_action_preflight_existing_batch.py \
  reachops_real_acquisition_report.py \
  reachops_operator_pressure.py \
  reachops_delivery_audit.py \
  reachops_delivery_package_check.py \
  reachops_activation_status_check.py \
  reachops_activation_status_template.py \
  reachops_acceptance_inputs.example.ps1 \
  reachops_goal_status_report.py \
  reachops_live_validation_manifest.py \
  reachops_visual_collection_preflight.py \
  reachops_live_preflight.py \
  reachops_live_readiness.py \
  reachops_live_submit_acceptance.py \
  run_reachops_live_readiness_windows.ps1 \
  run_reachops_live_validation_manifest_windows.ps1 \
  run_reachops_live_preflight_windows.ps1 \
  run_reachops_ui_startup_smoke_windows.ps1 \
  run_reachops_installer_smoke_windows.ps1 \
  run_reachops_acceptance_windows.ps1 \
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
  ssh "$REMOTE_HOST" "powershell -NoProfile -ExecutionPolicy Bypass -Command \"\$ErrorActionPreference = 'Stop'; \$env:PYTHONIOENCODING = 'utf-8'; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; [Console]::InputEncoding = [System.Text.Encoding]::UTF8; \$OutputEncoding = [System.Text.Encoding]::UTF8; chcp 65001 | Out-Null; cd '$REMOTE_DIR'; C:\\Python311-x64\\python.exe -m py_compile ReachOps\\workbench\\authorization_gate.py ReachOps\\workbench\\action_router.py ReachOps\\workbench\\workflow_service.py ReachOps\\workbench\\standalone_app.py ReachOps\\intelligence\\schemas.py ReachOps\\intelligence\\ai_strategy.py ReachOps\\intelligence\\service.py tests\\test_reachops_campaign.py ReachOpsApp.py GrowthIntelligenceApp.py tools\\reachops_delivery_audit.py tools\\reachops_delivery_package_check.py tools\\reachops_activation_status_check.py tools\\reachops_activation_status_template.py tools\\reachops_action_preflight_existing_batch.py tools\\reachops_real_acquisition_report.py tools\\reachops_operator_pressure.py tools\\reachops_goal_status_report.py tools\\reachops_live_validation_manifest.py tools\\reachops_visual_collection_preflight.py tools\\reachops_live_preflight.py tools\\reachops_live_submit_acceptance.py tools\\verify_reachops_acceptance_summary.py tools\\write_reachops_update_manifest.py; if (\$LASTEXITCODE -ne 0) { exit \$LASTEXITCODE }; if (!(Test-Path tools\\run_reachops_installer_smoke_windows.ps1)) { throw 'run_reachops_installer_smoke_windows.ps1 missing' }; if (!(Test-Path tools\\start_reachops_ui_windows.ps1)) { throw 'start_reachops_ui_windows.ps1 missing' }; if (!(Test-Path tools\\run_reachops_ui_startup_smoke_windows.ps1)) { throw 'run_reachops_ui_startup_smoke_windows.ps1 missing' }; if (!(Test-Path tools\\run_reachops_live_validation_manifest_windows.ps1)) { throw 'run_reachops_live_validation_manifest_windows.ps1 missing' }; C:\\Python311-x64\\python.exe -m unittest tests.test_reachops_campaign; if (\$LASTEXITCODE -ne 0) { exit \$LASTEXITCODE }; C:\\Python311-x64\\python.exe tools\\reachops_operator_pressure.py --json; if (\$LASTEXITCODE -ne 0) { exit \$LASTEXITCODE }; C:\\Python311-x64\\python.exe tools\\reachops_delivery_audit.py --json; if (\$LASTEXITCODE -ne 0) { exit \$LASTEXITCODE }; C:\\Python311-x64\\python.exe tools\\reachops_goal_status_report.py --json; if (\$LASTEXITCODE -ne 0) { exit \$LASTEXITCODE }\""
fi
