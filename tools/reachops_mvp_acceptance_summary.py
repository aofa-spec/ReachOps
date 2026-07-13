# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

OUT_PATH = ROOT_DIR / "reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_mvp_acceptance_summary.json"


def run_json(command: list[str], timeout: int = 120) -> tuple[dict[str, Any], int, str]:
    completed = subprocess.run(
        command,
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env={"PYTHONDONTWRITEBYTECODE": "1", **dict(__import__("os").environ)},
    )
    stdout = (completed.stdout or "").strip()
    if not stdout:
        return {}, completed.returncode, (completed.stderr or "").strip()
    try:
        return json.loads(stdout), completed.returncode, (completed.stderr or "").strip()
    except Exception as exc:
        return {"raw_stdout": stdout, "json_error": f"{type(exc).__name__}: {exc}"}, completed.returncode, (completed.stderr or "").strip()


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def build_summary() -> dict[str, Any]:
    audit, audit_rc, audit_err = run_json([sys.executable, "tools/reachops_delivery_audit.py", "--json"], timeout=180)
    goal, goal_rc, goal_err = run_json([sys.executable, "tools/reachops_goal_status_report.py", "--json"], timeout=180)
    client, client_rc, client_err = run_json([sys.executable, "tools/reachops_client_delivery_check.py", "--json"], timeout=120)
    mac_loop, mac_loop_rc, mac_loop_err = run_json(
        [sys.executable, "tools/reachops_mac_loop_acceptance.py", "--base-url", "http://127.0.0.1:8769", "--json"],
        timeout=180,
    )
    cleanliness, clean_rc, clean_err = run_json([sys.executable, "tools/reachops_repository_cleanliness_check.py", "--clean", "--json"], timeout=120)
    runtime_smoke = read_json(ROOT_DIR / "reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_web_panel_runtime_smoke.json")

    audit_summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
    goal_summary = goal.get("summary") if isinstance(goal.get("summary"), dict) else {}
    pending_external = list(goal.get("pending_external_validation") or [])
    client_acceptance_ready = (
        str(client.get("status") or "") == "passed"
        and str(client.get("readiness") or "") == "pass"
        and bool(client.get("acceptance_ready"))
        and bool(client.get("contract_ok"))
        and not client.get("failed_checks")
    )
    failed_checks = [
        name
        for name, payload in {
            "delivery_audit": (audit_rc, audit, audit_err),
            "goal_status": (goal_rc, goal, goal_err),
            "client_delivery": (client_rc, client, client_err),
            "mac_loop_acceptance": (mac_loop_rc, mac_loop, mac_loop_err),
            "repository_cleanliness": (clean_rc, cleanliness, clean_err),
        }.items()
        if payload[0] not in {0, 1} or (name == "repository_cleanliness" and not payload[1].get("passed"))
    ]
    failed_checks.extend(f"client_delivery:{item}" for item in (client.get("failed_checks") or []))
    mvp_local_ready = (
        str(audit.get("status") or "") == "ok"
        and int(audit_summary.get("failed") or 0) == 0
        and str(goal.get("status") or "") == "ready_for_external_validation"
        and int(goal_summary.get("stages_failed") or 0) == 0
        and int(goal_summary.get("final_failed") or 0) == 0
        and bool(mac_loop.get("mac_loop_ready"))
        and bool((mac_loop.get("checks") or {}).get("start_contract_evidence_complete"))
        and bool(runtime_smoke.get("passed"))
        and bool(cleanliness.get("passed"))
        and client_acceptance_ready
    )
    final_delivery_ready = (
        mvp_local_ready
        and not pending_external
        and bool(client.get("final_delivery_ready"))
        and str(client.get("readiness") or "") == "pass"
    )
    if final_delivery_ready:
        status = "final_delivery_ready"
    elif mvp_local_ready:
        status = "mvp_accepted_external_pending"
    elif str(client.get("status") or "") in {"blocked_by_accounts", "blocked_by_environment", "partial", "not_started"}:
        status = str(client.get("status") or "")
    else:
        status = "not_ready"
    blockers = list(client.get("blockers") or [])
    if not client_acceptance_ready and not blockers:
        blockers.append("当前客户端门禁未通过，不能使用历史 MVP 通过快照作为实时验收结论。")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "mvp_local_ready": mvp_local_ready,
        "final_delivery_ready": final_delivery_ready,
        "current_client_gate_ready": client_acceptance_ready,
        "audit": {
            "status": audit.get("status"),
            "summary": audit_summary,
            "returncode": audit_rc,
            "error": audit_err,
        },
        "goal_status": {
            "status": goal.get("status"),
            "audit_status": goal.get("audit_status"),
            "summary": goal_summary,
            "pending_external_validation": pending_external,
            "returncode": goal_rc,
            "error": goal_err,
        },
        "client_delivery": {
            "status": client.get("status"),
            "readiness": client.get("readiness"),
            "contract_ok": client.get("contract_ok"),
            "acceptance_ready": client.get("acceptance_ready"),
            "final_delivery_ready": client.get("final_delivery_ready"),
            "failed_checks": client.get("failed_checks") or [],
            "blockers": client.get("blockers") or [],
            "next_actions": client.get("next_actions") or [],
            "no_action_reason": client.get("no_action_reason") or {},
            "operation_counts": client.get("operation_counts") or {},
            "returncode": client_rc,
            "error": client_err,
        },
        "mac_loop_acceptance": {
            "status": mac_loop.get("status"),
            "mac_loop_ready": mac_loop.get("mac_loop_ready"),
            "start_contract_evidence": mac_loop.get("start_contract_evidence") or {},
            "checks": {
                "start_contract_evidence_complete": (mac_loop.get("checks") or {}).get("start_contract_evidence_complete"),
                "loop_terminal_evidence": (mac_loop.get("checks") or {}).get("loop_terminal_evidence"),
                "no_action_reason_present_when_no_actions": (mac_loop.get("checks") or {}).get("no_action_reason_present_when_no_actions"),
            },
            "returncode": mac_loop_rc,
            "error": mac_loop_err,
        },
        "web_runtime_smoke": {
            "status": runtime_smoke.get("status"),
            "passed": runtime_smoke.get("passed"),
            "failed_checks": runtime_smoke.get("failed_checks") or [],
            "source_mtimes": runtime_smoke.get("source_mtimes") or {},
        },
        "repository_cleanliness": {
            "status": cleanliness.get("status"),
            "passed": cleanliness.get("passed"),
            "forbidden_count": cleanliness.get("forbidden_count"),
            "returncode": clean_rc,
            "error": clean_err,
        },
        "failed_checks": failed_checks,
        "blockers": blockers,
        "next_required_actions": (
            client.get("next_actions")
            or [
                "完成真实 ixBrowser/TikTok 授权环境验收。",
                "生成 Windows 最终交付包并运行 final acceptance gate。",
            ]
        ),
        "evidence_files": {
            "mvp_acceptance_summary": str(OUT_PATH),
            "latest_delivery_check": str(ROOT_DIR / "reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_delivery_check.json"),
            "latest_web_panel_runtime_smoke": str(ROOT_DIR / "reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_web_panel_runtime_smoke.json"),
            "pressure_audit_report": str(ROOT_DIR / "ReachOps/docs/REACHOPS_REAL_PRESSURE_AUDIT_ACCEPTANCE_REPORT.md"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a product-manager MVP acceptance summary for ReachOps.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    summary = build_summary()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"status={summary['status']} mvp_local_ready={summary['mvp_local_ready']} final_delivery_ready={summary['final_delivery_ready']}")
        print(f"summary={OUT_PATH}")
    return 0 if summary["mvp_local_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
