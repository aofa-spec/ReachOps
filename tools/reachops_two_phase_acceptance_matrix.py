# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools import reachops_goal_delivery_runner

OUT_DIR = ROOT_DIR / "reports/reachops/mac_gui/runtime/reports/acceptance_remediation"
JSON_OUT = OUT_DIR / "latest_two_phase_acceptance_matrix.json"
MD_OUT = OUT_DIR / "latest_two_phase_acceptance_matrix.md"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def truthy(value: Any) -> bool:
    return bool(value)


def nested(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def latest_or_refresh(refresh: bool, use_existing: bool = False) -> dict[str, Any]:
    if use_existing and not refresh and reachops_goal_delivery_runner.OUT_PATH.is_file():
        return json.loads(reachops_goal_delivery_runner.OUT_PATH.read_text(encoding="utf-8"))
    return reachops_goal_delivery_runner.build_report()


def row(
    *,
    stage: str,
    item_id: str,
    requirement: str,
    passed: bool,
    evidence: dict[str, Any] | None = None,
    blocker: str = "",
) -> dict[str, Any]:
    return {
        "stage": stage,
        "id": item_id,
        "requirement": requirement,
        "passed": bool(passed),
        "evidence": evidence or {},
        "blocking_scope": "" if passed else blocker,
    }


def build_matrix(goal: dict[str, Any]) -> dict[str, Any]:
    boundary = goal.get("delivery_boundary") if isinstance(goal.get("delivery_boundary"), dict) else {}
    index = goal.get("deliverable_index") if isinstance(goal.get("deliverable_index"), dict) else {}
    local = goal.get("local_mvp_evidence") if isinstance(goal.get("local_mvp_evidence"), dict) else {}
    sections = goal.get("sections") if isinstance(goal.get("sections"), dict) else {}
    mac_loop = nested(sections, "mac_loop_acceptance", "payload", default={})
    client = nested(sections, "client_delivery", "payload", default={})
    clean = nested(sections, "repository_cleanliness", "payload", default={})
    package = nested(sections, "delivery_package", "payload", default={})
    final_gate = nested(sections, "final_gate", "payload", default={})
    start_evidence = local.get("start_contract_evidence") if isinstance(local.get("start_contract_evidence"), dict) else {}
    mac_checks = mac_loop.get("checks") if isinstance(mac_loop.get("checks"), dict) else {}
    acceptance_checks = nested(mac_loop, "acceptance", "checks", default={})
    if not isinstance(acceptance_checks, dict):
        acceptance_checks = {}
    groups = local.get("groups") if isinstance(local.get("groups"), dict) else {}
    latest_batch = local.get("latest_batch") if isinstance(local.get("latest_batch"), dict) else {}
    no_action = local.get("no_action_reason") if isinstance(local.get("no_action_reason"), dict) else {}
    operations = local.get("operation_counts") if isinstance(local.get("operation_counts"), dict) else {}
    last_stage = str(nested(mac_loop, "web_ui", "last_stage", default="") or "")

    local_rows = [
        row(
            stage="mac_local_mvp",
            item_id="web_ui_accessible",
            requirement="Web UI 可访问并绑定本地 API。",
            passed=truthy(mac_checks.get("web_ui_reachable")),
            evidence={"base_url": nested(mac_loop, "web_ui", "base_url", default="http://127.0.0.1:8769")},
            blocker="local_mvp",
        ),
        row(
            stage="mac_local_mvp",
            item_id="ixbrowser_ready",
            requirement="ixBrowser Local API 实时 ready。",
            passed=truthy(mac_checks.get("ixbrowser_api_ready")),
            evidence={"ixbrowser_ready": nested(mac_loop, "web_ui", "ixbrowser_ready", default=False)},
            blocker="local_mvp",
        ),
        row(
            stage="mac_local_mvp",
            item_id="fresh_group_counts",
            requirement="刷新分组能实时读取全部分组和账号数量，不能只用缓存。",
            passed=truthy(mac_checks.get("groups_available"))
            and truthy(mac_checks.get("group_counts_known"))
            and truthy(mac_checks.get("all_group_counts_known"))
            and truthy(mac_checks.get("groups_fresh")),
            evidence={
                "group_count": groups.get("group_count"),
                "known_group_count": groups.get("known_group_count"),
                "all_group_counts_known": groups.get("all_group_counts_known"),
                "profile_count": groups.get("profile_count"),
                "groups_fresh": mac_checks.get("groups_fresh"),
            },
            blocker="local_mvp",
        ),
        row(
            stage="mac_local_mvp",
            item_id="selected_group_execution",
            requirement="选中的分组真实存在，并由 /api/start 使用该分组执行。",
            passed=truthy(latest_batch.get("profile_group"))
            and (
                truthy(acceptance_checks.get("account_queue_started_for_selected_group"))
                or truthy(acceptance_checks.get("profile_list_execution_evidence"))
                or truthy(mac_checks.get("start_contract_evidence_complete"))
                or truthy(local.get("start_contract_evidence_complete"))
            ),
            evidence={"latest_batch": latest_batch},
            blocker="local_mvp",
        ),
        row(
            stage="mac_local_mvp",
            item_id="target_type_and_source_planning",
            requirement="运营输入推广目标后，系统识别目标类型并生成可执行来源。",
            passed=truthy(start_evidence.get("target_planned"))
            and (truthy(acceptance_checks.get("product_auto_detected")) or truthy(acceptance_checks.get("target_planned"))),
            evidence={
                "target_planned": start_evidence.get("target_planned"),
                "product_auto_detected": acceptance_checks.get("product_auto_detected"),
                "acceptance_target_planned": acceptance_checks.get("target_planned"),
            },
            blocker="local_mvp",
        ),
        row(
            stage="mac_local_mvp",
            item_id="headless_runner_started",
            requirement="/api/start 能启动本地 headless runner 并创建批次。",
            passed=truthy(start_evidence.get("campaign_started")) and truthy(latest_batch.get("id")),
            evidence={"campaign_started": start_evidence.get("campaign_started"), "latest_batch": latest_batch},
            blocker="local_mvp",
        ),
        row(
            stage="mac_local_mvp",
            item_id="profile_preflight_checked",
            requirement="账号预检检查登录态、验证码、代理、页面可打开性或 Profile 启动失败。",
            passed=truthy(start_evidence.get("profile_preflight_checked"))
            and truthy(acceptance_checks.get("profile_preflight_fresh")),
            evidence={
                "profile_preflight_checked": start_evidence.get("profile_preflight_checked"),
                "profile_preflight_fresh": acceptance_checks.get("profile_preflight_fresh"),
                "profile_available_count": acceptance_checks.get("profile_available_count"),
            },
            blocker="local_mvp",
        ),
        row(
            stage="mac_local_mvp",
            item_id="collection_completed",
            requirement="用可用账号完成 TikTok 内容和评论用户采集。",
            passed=truthy(start_evidence.get("collection_done")) and truthy(acceptance_checks.get("collection_done")),
            evidence={
                "collection_done": start_evidence.get("collection_done"),
                "acceptance_collection_done": acceptance_checks.get("collection_done"),
                "candidates": operations.get("candidates"),
            },
            blocker="local_mvp",
        ),
        row(
            stage="mac_local_mvp",
            item_id="candidate_scoring_completed",
            requirement="候选用户完成去重、意向识别和评分，并产出线索/空结果原因。",
            passed=(
                int(operations.get("candidates") or 0) > 0
                or truthy(no_action.get("code"))
                or int(operations.get("qualified_leads") or 0) > 0
            ),
            evidence={"operation_counts": operations, "no_action_reason": no_action},
            blocker="local_mvp",
        ),
        row(
            stage="mac_local_mvp",
            item_id="start_acquisition_contract",
            requirement="开始获客完成目标识别、批次启动、账号预检、采集和触达预检/跳过终态。",
            passed=truthy(local.get("start_contract_evidence_complete")),
            evidence=start_evidence,
            blocker="local_mvp",
        ),
        row(
            stage="mac_local_mvp",
            item_id="no_headless_timeout",
            requirement="最近一次执行没有 HEADLESS_TIMEOUT。",
            passed=truthy(mac_checks.get("no_headless_timeout_in_current_result")),
            evidence={"run_result_status": nested(mac_loop, "web_ui", "run_result_status", default="")},
            blocker="local_mvp",
        ),
        row(
            stage="mac_local_mvp",
            item_id="no_submit_safety",
            requirement="默认 no-submit，未授权不会真实评论、关注或私信。",
            passed=truthy(no_action.get("no_submit")) or int(operations.get("actions") or 0) == 0 or "no_submit=true" in last_stage,
            evidence={"no_action_reason": no_action, "operation_counts": operations, "last_stage": last_stage},
            blocker="local_mvp",
        ),
        row(
            stage="mac_local_mvp",
            item_id="outreach_terminal_or_skip_reason",
            requirement="生成触达动作或给出触达预检/跳过终态；没有触达动作时必须说明无候选、低意向、账号不可用或页面失败等原因。",
            passed=truthy(local.get("no_action_reason_present_when_no_actions")),
            evidence={
                "action_terminal_or_no_submit_reason": start_evidence.get("action_terminal_or_no_submit_reason"),
                "no_action_reason": no_action,
                "operation_counts": operations,
            },
            blocker="local_mvp",
        ),
        row(
            stage="mac_local_mvp",
            item_id="client_delivery_gate",
            requirement="客户端门禁通过。",
            passed=str(client.get("status") or "") == "passed" and not client.get("failed_checks"),
            evidence={
                "status": client.get("status"),
                "readiness": client.get("readiness"),
                "failed_checks": client.get("failed_checks") or [],
            },
            blocker="local_mvp",
        ),
        row(
            stage="mac_local_mvp",
            item_id="repository_cleanliness",
            requirement="项目清洁度检查通过。",
            passed=truthy(clean.get("passed")),
            evidence={"status": clean.get("status"), "forbidden_count": clean.get("forbidden_count")},
            blocker="repository_cleanliness",
        ),
    ]

    final_rows = [
        row(
            stage="final_customer_delivery",
            item_id="windows_final_artifacts",
            requirement="Windows exe、installer、update manifest、acceptance summary 齐全。",
            passed=truthy(nested(index, "windows_final_package", "ready", default=False)),
            evidence={
                "status": package.get("status"),
                "missing_artifacts": package.get("missing_artifacts") or [],
                "final_delivery_ready": package.get("final_delivery_ready"),
            },
            blocker="windows_final_artifacts",
        ),
        row(
            stage="final_customer_delivery",
            item_id="authorized_live_submit",
            requirement="授权真实触达验收完成，无 pending external validation。",
            passed=truthy(nested(index, "authorized_live_submit", "ready", default=False)),
            evidence={
                "pending_external_validation": goal.get("goal_pending_external_validation") or [],
                "required_evidence": [
                    item
                    for blocker in goal.get("final_delivery_blockers") or []
                    if isinstance(blocker, dict) and blocker.get("scope") == "external_authorized_execution"
                    for item in blocker.get("required_evidence") or []
                ],
            },
            blocker="external_authorized_execution",
        ),
        row(
            stage="final_customer_delivery",
            item_id="final_package_gate",
            requirement="delivery_package_check 返回 status=passed、final_delivery_ready=true。",
            passed=str(package.get("status") or "") == "passed" and truthy(package.get("final_delivery_ready")),
            evidence={
                "status": package.get("status"),
                "final_delivery_ready": package.get("final_delivery_ready"),
                "failures": package.get("failures") or [],
            },
            blocker="windows_final_artifacts",
        ),
        row(
            stage="final_customer_delivery",
            item_id="final_acceptance_gate",
            requirement="final_acceptance_gate 返回 status=passed、failed_checks=[]、final_delivery_ready=true。",
            passed=str(final_gate.get("status") or "") == "passed"
            and truthy(final_gate.get("final_delivery_ready"))
            and not final_gate.get("failed_checks"),
            evidence={
                "status": final_gate.get("status"),
                "final_delivery_ready": final_gate.get("final_delivery_ready"),
                "failed_checks": final_gate.get("failed_checks") or [],
            },
            blocker="final_acceptance_gate",
        ),
    ]
    rows = local_rows + final_rows
    local_ready = all(item["passed"] for item in local_rows)
    final_ready = all(item["passed"] for item in final_rows) and truthy(goal.get("final_delivery_ready"))
    failed = [item for item in rows if not item["passed"]]
    return {
        "product": "ReachOps",
        "generated_at": utc_now(),
        "source_report": str(reachops_goal_delivery_runner.OUT_PATH),
        "status": "final_delivery_ready" if final_ready else "local_mvp_accepted_final_pending" if local_ready else "not_ready",
        "local_mvp_ready": local_ready,
        "final_delivery_ready": final_ready,
        "delivery_boundary": boundary,
        "rows": rows,
        "failed_items": [item["id"] for item in failed],
        "blocking_scopes": sorted({item["blocking_scope"] for item in failed if item["blocking_scope"]}),
    }


def render_markdown(matrix: dict[str, Any]) -> str:
    lines = [
        "# ReachOps Two-Phase Acceptance Matrix",
        "",
        f"- Generated: `{matrix.get('generated_at')}`",
        f"- Status: `{matrix.get('status')}`",
        f"- Local MVP Ready: `{str(bool(matrix.get('local_mvp_ready'))).lower()}`",
        f"- Final Delivery Ready: `{str(bool(matrix.get('final_delivery_ready'))).lower()}`",
        f"- Blocking Scopes: `{', '.join(matrix.get('blocking_scopes') or []) or '-'}`",
        "",
        "| Stage | Requirement | Result | Blocking Scope |",
        "| --- | --- | --- | --- |",
    ]
    for item in matrix.get("rows") or []:
        result = "PASS" if item.get("passed") else "FAIL"
        lines.append(
            f"| `{item.get('stage')}` | {item.get('requirement')} | `{result}` | `{item.get('blocking_scope') or '-'}` |"
        )
    lines.append("")
    lines.append("This matrix separates Mac local MVP acceptance from final customer delivery. A local PASS is not final delivery.")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a two-phase ReachOps acceptance matrix from goal-mode evidence.")
    parser.add_argument("--refresh", action="store_true", help="Refresh goal-mode evidence before building the matrix.")
    parser.add_argument("--use-existing", action="store_true", help="Use the existing goal-mode report instead of refreshing current evidence.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write", action="store_true", help="Write latest JSON and Markdown matrix reports.")
    parser.add_argument(
        "--require-final",
        action="store_true",
        help="Exit non-zero unless final customer delivery is ready. Without this, exit status only gates Mac local MVP readiness.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    goal = latest_or_refresh(bool(args.refresh), bool(args.use_existing))
    matrix = build_matrix(goal)
    if args.write:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        JSON_OUT.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
        MD_OUT.write_text(render_markdown(matrix), encoding="utf-8")
    if args.json:
        print(json.dumps(matrix, ensure_ascii=False, indent=2))
    else:
        print(f"ReachOps two-phase acceptance: {matrix['status']}")
        print(f"local_mvp_ready={matrix['local_mvp_ready']} final_delivery_ready={matrix['final_delivery_ready']}")
        if matrix.get("blocking_scopes"):
            print("blocking_scopes=" + ",".join(matrix["blocking_scopes"]))
    if args.require_final:
        return 0 if matrix.get("final_delivery_ready") else 1
    return 0 if matrix.get("local_mvp_ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
