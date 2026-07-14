# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

OUT_PATH = ROOT_DIR / "reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_goal_delivery_report.json"
SUMMARY_PATH = ROOT_DIR / "reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_goal_delivery_summary.md"
ACCEPTANCE_REMEDIATION_DIR = ROOT_DIR / "reports/reachops/mac_gui/runtime/reports/acceptance_remediation"
LIVE_READINESS_REPORT_PATH = ACCEPTANCE_REMEDIATION_DIR / "latest_live_acceptance_readiness.md"
LIVE_READINESS_JSON_PATH = ACCEPTANCE_REMEDIATION_DIR / "latest_live_acceptance_readiness.json"
AUTHORIZATION_HANDOFF_BUNDLE_PATH = ACCEPTANCE_REMEDIATION_DIR / "latest_reachops_authorization_handoff.zip"
RUNTIME_LOG_PATH = ROOT_DIR / "reports/reachops/mac_gui/runtime/logs/growth_ops_runtime.log"
SECTION_TIMEOUT_RETURN_CODE = 124
PM_SECTION_TIMEOUTS = {
    "mvp_acceptance": 15,
    "mac_loop_acceptance": 45,
    "client_delivery": 15,
    "windows_package_preflight": 20,
    "issue_closure": 20,
    "delivery_package": 20,
    "final_gate": 30,
    "repository_cleanliness": 15,
}


def _timeout_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


def run_json(command: list[str], timeout: int = 120) -> tuple[dict[str, Any], int, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={"PYTHONDONTWRITEBYTECODE": "1", **dict(os.environ)},
        )
    except subprocess.TimeoutExpired as exc:
        return (
            {
                "status": "timeout",
                "passed": False,
                "timed_out": True,
                "timeout_seconds": timeout,
                "command": " ".join(command),
                "stdout_tail": _timeout_text(exc.output)[-4000:],
                "stderr_tail": _timeout_text(exc.stderr)[-4000:],
                "next_action": "Run this section command directly, fix the slow or blocked dependency, then rerun goal delivery.",
            },
            SECTION_TIMEOUT_RETURN_CODE,
            f"timeout_after_{timeout}s",
        )
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if not stdout:
        return {}, completed.returncode, stderr
    try:
        return json.loads(stdout), completed.returncode, stderr
    except Exception as exc:
        return {"raw_stdout": stdout, "json_error": f"{type(exc).__name__}: {exc}"}, completed.returncode, stderr


def command_payload(command: list[str], timeout: int = 120) -> dict[str, Any]:
    payload, returncode, stderr = run_json(command, timeout=timeout)
    return {
        "command": " ".join(command),
        "returncode": returncode,
        "stderr": stderr,
        "timeout_seconds": timeout,
        "timed_out": bool(isinstance(payload, dict) and payload.get("timed_out")),
        "payload": payload,
    }


def _payload(section: dict[str, Any]) -> dict[str, Any]:
    payload = section.get("payload")
    return payload if isinstance(payload, dict) else {}


def _section_timed_out(section: dict[str, Any]) -> bool:
    payload = _payload(section)
    return (
        bool(section.get("timed_out"))
        or int(section.get("returncode") or 0) == SECTION_TIMEOUT_RETURN_CODE
        or bool(payload.get("timed_out"))
        or str(payload.get("status") or "") == "timeout"
    )


def _timed_out_sections(sections: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    timed_out = []
    for name, section in sections.items():
        if not _section_timed_out(section):
            continue
        payload = _payload(section)
        timed_out.append(
            {
                "section": name,
                "command": section.get("command") or payload.get("command") or "",
                "timeout_seconds": int(section.get("timeout_seconds") or payload.get("timeout_seconds") or 0),
                "returncode": int(section.get("returncode") or 0),
                "stderr": str(section.get("stderr") or ""),
                "next_action": payload.get("next_action")
                or "Run the section command directly, fix the slow dependency, then rerun goal delivery.",
            }
        )
    return timed_out


def build_execution_contract() -> dict[str, Any]:
    return {
        "entrypoint": "PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/reachops_goal_delivery_runner.py --json",
        "purpose": "目标模式总控：聚合本地 MVP、客户端门禁、Windows 包、最终门禁和项目清洁度，给出 PM 可验收状态。",
        "mode": "local_pm_goal_gate",
        "does_not_submit": True,
        "does_not_open_browser_profile": True,
        "section_timeouts": dict(PM_SECTION_TIMEOUTS),
        "authoritative_report": str(OUT_PATH),
        "operator_summary": str(SUMMARY_PATH),
    }


def build_deliverables() -> list[dict[str, Any]]:
    return [
        {
            "name": "Web 运营面板",
            "path": "http://127.0.0.1:8769/",
            "required_for": "local_mvp",
            "acceptance": "运营能在网页端刷新 ixBrowser 分组、选择账号分组、启动获客并查看日志/漏斗/验收状态。",
        },
        {
            "name": "目标模式总报告",
            "path": str(OUT_PATH),
            "required_for": "pm_goal_tracking",
            "acceptance": "报告写出 status、local_mvp_ready、windows_build_ready、final_delivery_ready、blockers、next_actions。",
        },
        {
            "name": "目标模式 PM 摘要",
            "path": str(SUMMARY_PATH),
            "required_for": "pm_goal_tracking",
            "acceptance": "用 Markdown 固化当前本地 MVP、Windows 包、授权真实提交和最终门禁边界，便于 PM/运营交接复核。",
        },
        {
            "name": "客户端交付门禁",
            "path": "reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_delivery_check.json",
            "required_for": "local_mvp",
            "acceptance": "tools/reachops_client_delivery_check.py --json 返回 status=passed、readiness=pass、failed_checks=[]。",
        },
        {
            "name": "Mac 本地自动循环验收",
            "path": "tools/reachops_mac_loop_acceptance.py --base-url http://127.0.0.1:8769 --json",
            "required_for": "local_mvp",
            "acceptance": "ixBrowser Local API 实时 ready、分组不是缓存、最近一次开始获客链路完成且无 HEADLESS_TIMEOUT。",
        },
        {
            "name": "Mac 本地 MVP 验收交付单",
            "path": "ReachOps/docs/REACHOPS_MAC_LOCAL_MVP_ACCEPTANCE.md",
            "required_for": "local_mvp",
            "acceptance": "固化第一阶段 Mac 本地 MVP 的运行入口、实时验收快照、开始获客定义、触达边界和最终交付阻断。",
        },
        {
            "name": "Windows 最终交付包",
            "path": "dist/ReachOps + dist/installer + reports/reachops_acceptance/<timestamp>/acceptance_summary.json",
            "required_for": "final_delivery",
            "acceptance": "exe、installer、update manifest、acceptance_summary、windows_package_preflight、issue_closure_payload、authorization_handoff、repository_cleanliness、final_acceptance_gate 全部存在且被 package check 验证。",
        },
        {
            "name": "授权真实提交证据",
            "path": "reports/reachops_acceptance/<timestamp>/evidence",
            "required_for": "final_delivery",
            "acceptance": "仅对授权目标执行，成功动作必须有截图和 sidecar；评论动作还要证明 submitted_text 与 comment_visible_confirmed。",
        },
    ]


def build_start_acquisition_contract() -> dict[str, Any]:
    return {
        "name": "开始获客",
        "definition": "运营在网页端输入目标、实时读取 ixBrowser 分组、选择账号分组后，由本地 API 启动 ReachOps headless runner 的完整获客链路。",
        "required_steps": [
            "运营输入推广目标：产品链接、关键词、达人主页、视频链接、话题或直播间。",
            "系统识别目标类型并生成可执行来源。",
            "刷新 ixBrowser 分组，实时读取分组列表和每组账号数量。",
            "选择账号分组，后端确认该分组来自当前 ixBrowser 实时列表。",
            "启动本地 headless runner。",
            "账号预检：检查登录态、验证码、代理、页面可打开性和启动失败。",
            "用可用账号采集 TikTok 内容和评论用户。",
            "候选用户去重、意向识别和评分。",
            "生成线索和触达动作。",
            "默认 preflight/no-submit，不真实评论、不关注、不私信。",
        ],
        "ready_conditions": [
            "ixBrowser Local API ready=true。",
            "分组数量实时读取完整，不能只使用 stale cache。",
            "选中分组真实存在于当前 ixBrowser 分组列表。",
            "/api/start 成功启动本地执行器。",
            "日志出现 PLAN、START、CHECK profile_preflight、DONE collection。",
            "无触达动作时必须说明原因：无候选、低意向、账号不可用、页面失败或策略跳过。",
        ],
        "blocking_conditions": [
            "ixBrowser Local API 不可连接。",
            "分组列表或账号数量只来自缓存。",
            "选中分组不存在。",
            "真实评论未确认或激活状态未 ready。",
            "HEADLESS_TIMEOUT 或本地执行器异常退出。",
        ],
    }


def build_outreach_effectiveness_contract() -> dict[str, Any]:
    return {
        "modes": {
            "collect_only": {
                "label": "只采集",
                "submits_to_platform": False,
                "definition": "只发现内容、评论用户和候选线索，不生成或不执行真实触达。",
                "effective_when": ["产生可解释的候选用户、空结果原因或采集失败原因。"],
            },
            "preflight": {
                "label": "采集 + 触达预检",
                "submits_to_platform": False,
                "definition": "默认模式。生成评论/关注/私信动作，但只验证页面和入口是否可执行，不提交平台动作。",
                "effective_when": [
                    "目标页面可打开。",
                    "评论框、关注按钮或私信入口存在。",
                    "动作状态记录为 preflight 成功或可执行。",
                    "证据标记 preflight_only=true/no_submit=true。",
                ],
            },
            "live_comment": {
                "label": "采集 + 真实评论",
                "submits_to_platform": True,
                "definition": "授权模式。仅在明确授权、激活 ready 和人工确认后执行真实评论提交。",
                "required_authorization": [
                    "用户明确授权目标链接、账号分组和评论内容。",
                    "勾选真实评论确认。",
                    "激活状态 ready。",
                    "使用真实授权账号。",
                    "评论内容或自动生成文案经过确认。",
                ],
                "effective_when": [
                    "平台提交成功。",
                    "有截图和 sidecar 元数据。",
                    "评论动作包含 submitted_text。",
                    "comment_visible_confirmed=true。",
                ],
            },
        },
        "invalid_outreach": [
            "低意向线索被策略跳过。",
            "目标页面不可访问。",
            "账号未登录、验证码、风控、代理失败或 Profile 启动失败。",
            "评论入口不存在或私信不允许。",
            "缺少授权、激活或人工确认时尝试真实提交。",
        ],
    }


def build_acceptance_standards() -> dict[str, Any]:
    return {
        "local_mvp": [
            "Web 面板可访问并绑定真实本地 API。",
            "刷新分组读取 ixBrowser 配置分组和账号数量。",
            "Mac 本地循环验收通过：ixBrowser API ready、分组不是缓存、最近一次开始获客链路完成且无 HEADLESS_TIMEOUT。",
            "选择分组后 /api/start 使用该分组启动 headless runner。",
            "默认 no-submit；未授权或未确认时不能真实评论、关注或私信。",
            "客户端交付门禁 passed，项目清洁度 passed。",
        ],
        "windows_build": [
            "Windows build 输入、spec、Inno Setup 和 acceptance 脚本合同齐全。",
            "默认 build 必须生成安装包和 update manifest；-SkipInstaller 只能作为非最终构建。",
        ],
        "final_delivery": [
            "tools/reachops_delivery_package_check.py --json 返回 status=passed、final_delivery_ready=true。",
            "tools/reachops_final_acceptance_gate.py --json 返回 status=passed、failed_checks=[]、final_delivery_ready=true。",
            "Windows acceptance summary 必须包含 authorization_handoff，且授权交接包 latest_reachops_authorization_handoff.zip、authorization_handoff_payload.json、latest_live_acceptance_readiness.md/json 可追溯。",
            "真实 TikTok 提交只允许在授权目标、有效激活和账号预检通过后执行，并必须保留证据。",
        ],
    }


def build_delivery_boundary(
    *,
    local_ready: bool,
    windows_build_ready: bool,
    final_ready: bool,
    client: dict[str, Any],
    package: dict[str, Any],
    goal_pending: list[str],
    authorized_live_ready: bool,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    client_gate_ready = bool(
        client
        and (
            bool(client.get("contract_ok"))
            or str(client.get("status") or "") in {"passed", "blocked_by_accounts", "blocked_by_environment", "failed"}
            or isinstance(client.get("checks"), list)
        )
    )
    return {
        "summary": (
            "本地 MVP 和客户端门禁已可验收；整项目最终交付仍未完成。"
            if local_ready and not final_ready
            else "整项目最终交付已完成。"
            if final_ready
            else "本地 MVP 尚未达到可验收状态。"
        ),
        "local_mvp_scope_ready": bool(local_ready),
        "client_gate_scope_ready": bool(client_gate_ready),
        "windows_build_input_scope_ready": bool(windows_build_ready),
        "overall_final_delivery_scope_ready": bool(final_ready),
        "client_gate_final_delivery_ready_is_not_overall_final_delivery": True,
        "windows_final_artifacts_ready": str(package.get("status") or "") == "passed"
        and bool(package.get("final_delivery_ready")),
        "external_authorized_execution_ready": bool(authorized_live_ready),
        "blocking_scopes": [str(row.get("scope") or "") for row in blockers if row.get("scope")],
    }


def final_gate_pending_external_validation(final_gate: dict[str, Any]) -> list[str]:
    checks = final_gate.get("checks") if isinstance(final_gate.get("checks"), list) else []
    if not checks or not isinstance(checks[0], dict):
        return []
    evidence = checks[0].get("evidence") if isinstance(checks[0].get("evidence"), dict) else {}
    return [str(item) for item in evidence.get("pending_external_validation") or []]


def final_gate_authorized_live_submit_ready(final_gate: dict[str, Any]) -> bool:
    checks = final_gate.get("checks") if isinstance(final_gate.get("checks"), list) else []
    checks_by_name = {str(row.get("name") or ""): row for row in checks if isinstance(row, dict)}
    goal_check = checks_by_name.get("goal_status:passed")
    if not goal_check or goal_check.get("ok") is not True:
        return False
    evidence = goal_check.get("evidence") if isinstance(goal_check.get("evidence"), dict) else {}
    if evidence.get("pending_external_validation"):
        return False
    blockers = final_gate.get("final_delivery_blockers") if isinstance(final_gate.get("final_delivery_blockers"), list) else []
    return not any(str(row.get("scope") or "") == "external_authorized_execution" for row in blockers if isinstance(row, dict))


def final_gate_blocker_summary(final_gate: dict[str, Any], scope: str) -> dict[str, Any]:
    blockers = final_gate.get("final_delivery_blockers") if isinstance(final_gate.get("final_delivery_blockers"), list) else []
    for row in blockers:
        if not isinstance(row, dict) or str(row.get("scope") or "") != scope:
            continue
        summary = row.get("blocker_summary") if isinstance(row.get("blocker_summary"), dict) else {}
        if summary:
            return summary
    evidence_plan = (
        final_gate.get("final_delivery_evidence_plan")
        if isinstance(final_gate.get("final_delivery_evidence_plan"), dict)
        else {}
    )
    items = evidence_plan.get("items") if isinstance(evidence_plan.get("items"), list) else []
    for row in items:
        if not isinstance(row, dict) or str(row.get("scope") or "") != scope:
            continue
        summary = row.get("blocker_summary") if isinstance(row.get("blocker_summary"), dict) else {}
        if summary:
            return summary
    return {}


def build_deliverable_index(
    *,
    local_ready: bool,
    windows_build_ready: bool,
    final_ready: bool,
    mvp: dict[str, Any],
    client: dict[str, Any],
    windows_preflight: dict[str, Any],
    package: dict[str, Any],
    final_gate: dict[str, Any],
    clean: dict[str, Any],
    blockers: list[dict[str, Any]],
    issue_closure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocker_by_scope = {str(row.get("scope") or ""): row for row in blockers if isinstance(row, dict)}
    windows_blocker = blocker_by_scope.get("windows_final_artifacts", {})
    windows_blocker_summary = (
        windows_blocker.get("blocker_summary")
        if isinstance(windows_blocker.get("blocker_summary"), dict)
        else {}
    ) or final_gate_blocker_summary(final_gate, "windows_final_artifacts")
    windows_missing_artifacts = sorted(
        {
            str(item)
            for item in list(package.get("missing_artifacts") or [])
            + list(windows_preflight.get("missing_final_artifacts") or [])
            if str(item or "").strip()
        }
    )
    pending_external = final_gate_pending_external_validation(final_gate)
    authorized_live_ready = final_gate_authorized_live_submit_ready(final_gate)
    issue_summary = (issue_closure or {}).get("summary") if isinstance((issue_closure or {}).get("summary"), dict) else {}
    issue_closure_ready = bool(
        issue_closure
        and issue_closure.get("passed")
        and int(issue_summary.get("acceptance_criteria_total") or 0) == 53
        and int(issue_summary.get("acceptance_criteria_unclassified") or 0) == 0
        and int(issue_summary.get("acceptance_criteria_external_pending") or 0) == 0
        and int(issue_summary.get("external_pending_count") or 0) == 0
        and (issue_closure.get("github_issues") or {}).get("closure_requires_external_validation") is False
    )
    return {
        "web_operator_panel": {
            "required_for": "local_mvp",
            "ready": bool(local_ready),
            "evidence": ["http://127.0.0.1:8769/", str(OUT_PATH)],
            "blocking_scope": "" if local_ready else "local_mvp",
        },
        "local_mvp_acceptance": {
            "required_for": "local_mvp",
            "ready": bool(local_ready),
            "status": mvp.get("status"),
            "evidence": [
                str(mvp.get("evidence_files", {}).get("mvp_acceptance_summary") or ""),
                str(client.get("delivery_check_path") or ""),
            ],
            "failed_checks": list(mvp.get("failed_checks") or []) + list(client.get("failed_checks") or []),
            "blocking_scope": "" if local_ready else "local_mvp",
        },
        "windows_build_inputs": {
            "required_for": "windows_build",
            "ready": bool(windows_build_ready),
            "status": windows_preflight.get("status"),
            "preflight_report_path": str((windows_preflight.get("build_contract") or {}).get("preflight_report_path") or ""),
            "failures": windows_preflight.get("failures") or [],
            "blocking_scope": "" if windows_build_ready else "windows_build_inputs",
        },
        "windows_final_package": {
            "required_for": "final_delivery",
            "ready": str(package.get("status") or "") == "passed" and bool(package.get("final_delivery_ready")),
            "status": package.get("status"),
            "missing_artifacts": windows_missing_artifacts,
            "artifacts": package.get("artifacts") or {},
            "remediation_plan": windows_blocker.get("remediation_plan") or package.get("remediation_plan") or {},
            "blocker_summary": windows_blocker_summary,
            "blocking_scope": "" if str(package.get("status") or "") == "passed" and bool(package.get("final_delivery_ready")) else "windows_final_artifacts",
        },
        "authorized_live_submit": {
            "required_for": "final_delivery",
            "ready": authorized_live_ready,
            "pending_external_validation": pending_external,
            "blocking_scope": "external_authorized_execution"
            if (not authorized_live_ready or blocker_by_scope.get("external_authorized_execution"))
            else "",
        },
        "commercial_issue_closure": {
            "required_for": "final_delivery",
            "ready": issue_closure_ready,
            "status": (issue_closure or {}).get("status") or "",
            "acceptance_criteria_total": issue_summary.get("acceptance_criteria_total"),
            "acceptance_criteria_external_pending": issue_summary.get("acceptance_criteria_external_pending"),
            "acceptance_criteria_unclassified": issue_summary.get("acceptance_criteria_unclassified"),
            "external_pending_count": issue_summary.get("external_pending_count"),
            "blocking_scope": "" if issue_closure_ready else "commercial_issue_closure",
        },
        "final_acceptance_gate": {
            "required_for": "final_delivery",
            "ready": bool(final_ready),
            "status": final_gate.get("status"),
            "failed_checks": final_gate.get("failed_checks") or [],
            "blocking_scope": "" if final_ready else "final_acceptance_gate",
        },
        "repository_cleanliness": {
            "required_for": "local_mvp_and_final_delivery",
            "ready": bool(clean.get("passed")),
            "status": clean.get("status"),
            "forbidden_count": clean.get("forbidden_count"),
            "blocking_scope": "" if clean.get("passed") else "repository_cleanliness",
        },
    }


def build_local_mvp_evidence(mvp: dict[str, Any], mac_loop: dict[str, Any], client: dict[str, Any]) -> dict[str, Any]:
    client_no_action = client.get("no_action_reason") if isinstance(client.get("no_action_reason"), dict) else {}
    mvp_client = mvp.get("client_delivery") if isinstance(mvp.get("client_delivery"), dict) else {}
    mvp_no_action = mvp_client.get("no_action_reason") if isinstance(mvp_client.get("no_action_reason"), dict) else {}
    mac_operations = mac_loop.get("operations") if isinstance(mac_loop.get("operations"), dict) else {}
    mac_no_action = mac_operations.get("no_action_reason") if isinstance(mac_operations.get("no_action_reason"), dict) else {}
    no_action_reason = client_no_action or mvp_no_action or mac_no_action
    operation_counts = (
        client.get("operation_counts")
        if isinstance(client.get("operation_counts"), dict)
        else mvp_client.get("operation_counts")
        if isinstance(mvp_client.get("operation_counts"), dict)
        else {}
    )
    if not operation_counts and isinstance(mac_operations, dict):
        operation_counts = {
            "candidates": mac_operations.get("candidates", 0),
            "actions": mac_operations.get("actions", 0),
            "touch_success": mac_operations.get("touch_success", 0),
            "touch_failed": mac_operations.get("touch_failed", 0),
        }
    start_contract_sources = [
        mac_loop.get("start_contract_evidence") if isinstance(mac_loop.get("start_contract_evidence"), dict) else {},
        mvp.get("start_contract_evidence") if isinstance(mvp.get("start_contract_evidence"), dict) else {},
        client.get("start_contract_evidence") if isinstance(client.get("start_contract_evidence"), dict) else {},
    ]
    start_contract_evidence: dict[str, Any] = {}
    for evidence in start_contract_sources:
        for key, value in (evidence or {}).items():
            if key not in start_contract_evidence or value:
                start_contract_evidence[key] = value
    log_evidence = infer_start_contract_from_runtime_log(no_action_reason=no_action_reason)
    for key, value in log_evidence.items():
        if key not in start_contract_evidence or value:
            start_contract_evidence[key] = value
    explicit_complete = any(
        bool(
            ((source.get("checks") or {}) if isinstance(source.get("checks"), dict) else {}).get(
                "start_contract_evidence_complete"
            )
        )
        for source in [mac_loop, mvp, client]
    )
    required_contract_keys = [
        "target_planned",
        "campaign_started",
        "profile_preflight_checked",
        "collection_done",
        "action_terminal_or_no_submit_reason",
    ]
    start_contract_complete = explicit_complete or all(bool(start_contract_evidence.get(key)) for key in required_contract_keys)
    return {
        "mac_loop_status": mac_loop.get("status", ""),
        "client_delivery_status": client.get("status", ""),
        "client_delivery_readiness": client.get("readiness", ""),
        "latest_batch": mac_loop.get("latest_batch") or {},
        "groups": mac_loop.get("groups") or {},
        "start_contract_evidence": start_contract_evidence,
        "start_contract_evidence_complete": bool(start_contract_complete),
        "operation_counts": operation_counts or {},
        "no_action_reason": no_action_reason or {},
        "no_action_reason_required_when_actions_zero": bool(
            int((operation_counts or {}).get("actions") or 0) == 0
        ),
        "no_action_reason_present_when_no_actions": bool(
            int((operation_counts or {}).get("actions") or 0) > 0
            or str((no_action_reason or {}).get("code") or "").strip()
        ),
    }


def infer_start_contract_from_runtime_log(no_action_reason: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        lines = RUNTIME_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        lines = []
    scoped = lines[-800:]
    joined = "\n".join(scoped)
    no_action_code = str((no_action_reason or {}).get("code") or "").strip()
    return {
        "target_planned": "PLAN   campaign" in joined or "PLAN campaign" in joined,
        "campaign_started": "START  campaign" in joined or "START campaign" in joined,
        "profile_preflight_checked": "CHECK  profile_preflight" in joined or "CHECK profile_preflight" in joined,
        "collection_done": "DONE   collection" in joined or "DONE collection" in joined,
        "action_terminal_or_no_submit_reason": bool(
            "DONE   action_preflight" in joined
            or "DONE   action_submit" in joined
            or "DONE action_preflight" in joined
            or "DONE action_submit" in joined
            or no_action_code
        ),
        "scoped_log_lines": len(scoped),
        "source": "runtime_log_fallback" if scoped else "",
    }


def build_report() -> dict[str, Any]:
    python = sys.executable
    sections = {
        "mvp_acceptance": command_payload([python, "tools/reachops_mvp_acceptance_summary.py", "--json"], timeout=PM_SECTION_TIMEOUTS["mvp_acceptance"]),
        "mac_loop_acceptance": command_payload(
            [python, "tools/reachops_mac_loop_acceptance.py", "--base-url", "http://127.0.0.1:8769", "--json"],
            timeout=PM_SECTION_TIMEOUTS["mac_loop_acceptance"],
        ),
        "client_delivery": command_payload([python, "tools/reachops_client_delivery_check.py", "--json"], timeout=PM_SECTION_TIMEOUTS["client_delivery"]),
        "windows_package_preflight": command_payload([python, "tools/reachops_windows_package_preflight.py", "--json"], timeout=PM_SECTION_TIMEOUTS["windows_package_preflight"]),
        "issue_closure": command_payload([python, "tools/reachops_issue_closure_audit.py", "--json"], timeout=PM_SECTION_TIMEOUTS["issue_closure"]),
        "delivery_package": command_payload(
            [python, "tools/reachops_delivery_package_check.py", "--allow-external-pending", "--json"],
            timeout=PM_SECTION_TIMEOUTS["delivery_package"],
        ),
        "final_gate": command_payload([python, "tools/reachops_final_acceptance_gate.py", "--json"], timeout=PM_SECTION_TIMEOUTS["final_gate"]),
        "repository_cleanliness": command_payload(
            [python, "tools/reachops_repository_cleanliness_check.py", "--clean", "--json"],
            timeout=PM_SECTION_TIMEOUTS["repository_cleanliness"],
        ),
    }
    section_timeouts = _timed_out_sections(sections)

    mvp = _payload(sections["mvp_acceptance"])
    mac_loop = _payload(sections["mac_loop_acceptance"])
    client = _payload(sections["client_delivery"])
    windows_preflight = _payload(sections["windows_package_preflight"])
    issue_closure = _payload(sections["issue_closure"])
    package = _payload(sections["delivery_package"])
    final_gate = _payload(sections["final_gate"])
    clean = _payload(sections["repository_cleanliness"])

    local_ready = (
        bool(mvp.get("mvp_local_ready"))
        and bool(mac_loop.get("mac_loop_ready"))
        and str(client.get("status") or "") == "passed"
        and bool(client.get("final_delivery_ready"))
        and bool(clean.get("passed"))
    )
    windows_build_ready = bool(windows_preflight.get("ready_for_windows_build")) and not windows_preflight.get("failures")
    final_ready = str(final_gate.get("status") or "") == "passed" and bool(final_gate.get("final_delivery_ready"))

    blockers: list[dict[str, Any]] = []
    if section_timeouts:
        blockers.append(
            {
                "scope": "goal_delivery_section_timeout",
                "status": "timeout",
                "timed_out_sections": [row["section"] for row in section_timeouts],
                "section_timeouts": section_timeouts,
                "action": "先单独运行超时 section 的命令，修复慢依赖或环境阻断，再复跑 tools\\reachops_goal_delivery_runner.py --json。",
            }
        )
    if not local_ready:
        blockers.append(
            {
                "scope": "local_mvp",
                "status": mac_loop.get("status") or mvp.get("status") or client.get("status") or clean.get("status"),
                "mac_loop_checks": mac_loop.get("checks") or {},
                "next_actions": mac_loop.get("next_actions") or [],
                "action": "修复 Mac 本地自动循环、客户端门禁或项目清洁度失败项。",
            }
        )
    if not windows_build_ready:
        blockers.append(
            {
                "scope": "windows_build_inputs",
                "status": windows_preflight.get("status"),
                "failures": windows_preflight.get("failures") or [],
                "action": "补齐 Windows 打包输入文件和脚本合同。",
            }
        )
    if package.get("missing_artifacts"):
        remediation = package.get("remediation_plan") if isinstance(package.get("remediation_plan"), dict) else {}
        package_blocker_summary = final_gate_blocker_summary(final_gate, "windows_final_artifacts")
        blockers.append(
            {
                "scope": "windows_final_artifacts",
                "status": package.get("status"),
                "missing_artifacts": package.get("missing_artifacts") or [],
                "remediation_plan": remediation,
                "blocker_summary": package_blocker_summary,
                "action": "在 Windows 实机运行 build 和 acceptance，生成 exe、installer、manifest、acceptance_summary。",
            }
        )
    goal_pending = final_gate_pending_external_validation(final_gate)
    authorized_live_ready = final_gate_authorized_live_submit_ready(final_gate)
    if goal_pending or not authorized_live_ready:
        blockers.append(
            {
                "scope": "external_authorized_execution",
                "status": "pending_external_validation" if goal_pending else str(final_gate.get("status") or "missing_final_gate_evidence"),
                "pending": goal_pending,
                "action": "在明确授权目标、账号分组、评论内容和有效激活状态后完成真实 TikTok 平台提交验收。",
            }
        )
    issue_summary = issue_closure.get("summary") if isinstance(issue_closure.get("summary"), dict) else {}
    issue_closure_ready = bool(
        issue_closure.get("passed")
        and int(issue_summary.get("acceptance_criteria_total") or 0) == 53
        and int(issue_summary.get("acceptance_criteria_unclassified") or 0) == 0
        and int(issue_summary.get("acceptance_criteria_external_pending") or 0) == 0
        and int(issue_summary.get("external_pending_count") or 0) == 0
        and (issue_closure.get("github_issues") or {}).get("closure_requires_external_validation") is False
    )
    if not issue_closure_ready:
        blockers.append(
            {
                "scope": "commercial_issue_closure",
                "status": issue_closure.get("status"),
                "summary": issue_summary,
                "action": "完成 Issues #1-#7 中仍标记 external_pending 的验收标准，并复跑 tools\\reachops_issue_closure_audit.py --json。",
            }
        )

    status = "final_delivery_ready" if final_ready else "local_mvp_accepted_final_pending" if local_ready else "not_ready"
    delivery_boundary = build_delivery_boundary(
        local_ready=local_ready,
        windows_build_ready=windows_build_ready,
        final_ready=final_ready,
        client=client,
        package=package,
        goal_pending=goal_pending,
        authorized_live_ready=authorized_live_ready,
        blockers=blockers,
    )
    deliverable_index = build_deliverable_index(
        local_ready=local_ready,
        windows_build_ready=windows_build_ready,
        final_ready=final_ready,
        mvp=mvp,
        client=client,
        windows_preflight=windows_preflight,
        package=package,
        final_gate=final_gate,
        clean=clean,
        blockers=blockers,
        issue_closure=issue_closure,
    )
    local_mvp_evidence = build_local_mvp_evidence(mvp, mac_loop, client)
    final_delivery_blockers = (
        final_gate.get("final_delivery_blockers")
        if isinstance(final_gate.get("final_delivery_blockers"), list)
        else []
    )
    return {
        "product": "ReachOps",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "execution_contract": build_execution_contract(),
        "start_acquisition_contract": build_start_acquisition_contract(),
        "outreach_effectiveness_contract": build_outreach_effectiveness_contract(),
        "deliverables": build_deliverables(),
        "acceptance_standards": build_acceptance_standards(),
        "status": status,
        "local_mvp_ready": local_ready,
        "windows_build_ready": windows_build_ready,
        "final_delivery_ready": final_ready,
        "delivery_boundary": delivery_boundary,
        "deliverable_index": deliverable_index,
        "local_mvp_evidence": local_mvp_evidence,
        "failed_checks": final_gate.get("failed_checks") or [],
        "final_delivery_blockers": final_delivery_blockers,
        "goal_pending_external_validation": goal_pending,
        "section_timeouts": section_timeouts,
        "blockers": blockers,
        "sections": sections,
        "next_actions": [
            "Windows 实机运行：powershell -ExecutionPolicy Bypass -File tools\\build_reachops_windows.ps1",
            "填写授权验收输入：powershell -ExecutionPolicy Bypass -File tools\\init_reachops_acceptance_inputs_windows.ps1",
            "授权后运行 acceptance：powershell -ExecutionPolicy Bypass -File tools\\run_reachops_acceptance_windows.ps1 -RunLiveSubmit -ConfirmAuthorizedTargets",
            "最终复核：python tools\\reachops_final_acceptance_gate.py --json",
        ]
        if not final_ready
        else [],
        "evidence_files": {
            "goal_delivery_report": str(OUT_PATH),
            "goal_delivery_summary": str(SUMMARY_PATH),
            "pm_delivery_baseline": str(ROOT_DIR / "ReachOps/docs/REACHOPS_PM_DELIVERY_BASELINE.md"),
            "pressure_audit_report": str(ROOT_DIR / "ReachOps/docs/REACHOPS_REAL_PRESSURE_AUDIT_ACCEPTANCE_REPORT.md"),
            "mac_local_mvp_acceptance": str(ROOT_DIR / "ReachOps/docs/REACHOPS_MAC_LOCAL_MVP_ACCEPTANCE.md"),
            "live_acceptance_readiness": str(LIVE_READINESS_REPORT_PATH),
            "live_acceptance_readiness_json": str(LIVE_READINESS_JSON_PATH),
            "authorization_handoff_bundle": str(AUTHORIZATION_HANDOFF_BUNDLE_PATH),
            "client_delivery_check": str(ROOT_DIR / "reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_delivery_check.json"),
            "mac_loop_acceptance": str(ROOT_DIR / "tools/reachops_mac_loop_acceptance.py"),
        },
    }


def _markdown_bool(value: Any) -> str:
    return "true" if bool(value) else "false"


def render_markdown_summary(report: dict[str, Any]) -> str:
    boundary = report.get("delivery_boundary") if isinstance(report.get("delivery_boundary"), dict) else {}
    index = report.get("deliverable_index") if isinstance(report.get("deliverable_index"), dict) else {}
    local_evidence = report.get("local_mvp_evidence") if isinstance(report.get("local_mvp_evidence"), dict) else {}
    operation_counts = local_evidence.get("operation_counts") if isinstance(local_evidence.get("operation_counts"), dict) else {}
    no_action_reason = local_evidence.get("no_action_reason") if isinstance(local_evidence.get("no_action_reason"), dict) else {}
    start_contract = report.get("start_acquisition_contract") if isinstance(report.get("start_acquisition_contract"), dict) else {}
    outreach_contract = report.get("outreach_effectiveness_contract") if isinstance(report.get("outreach_effectiveness_contract"), dict) else {}
    blockers = report.get("blockers") if isinstance(report.get("blockers"), list) else []
    final_delivery_blockers = (
        report.get("final_delivery_blockers")
        if isinstance(report.get("final_delivery_blockers"), list)
        else []
    )
    lines = [
        "# ReachOps 目标模式验收摘要",
        "",
        f"- 生成时间：`{report.get('generated_at') or '-'}`",
        f"- 当前状态：`{report.get('status') or '-'}`",
        f"- 本地 MVP：`{_markdown_bool(report.get('local_mvp_ready'))}`",
        f"- Windows 构建输入：`{_markdown_bool(report.get('windows_build_ready'))}`",
        f"- 最终交付：`{_markdown_bool(report.get('final_delivery_ready'))}`",
        "",
        "## PM 边界",
        "",
        f"- 摘要：{boundary.get('summary') or '-'}",
        f"- `delivery_boundary.local_mvp_scope_ready={_markdown_bool(boundary.get('local_mvp_scope_ready'))}`",
        f"- `delivery_boundary.client_gate_scope_ready={_markdown_bool(boundary.get('client_gate_scope_ready'))}`",
        f"- `delivery_boundary.windows_build_input_scope_ready={_markdown_bool(boundary.get('windows_build_input_scope_ready'))}`",
        f"- `delivery_boundary.overall_final_delivery_scope_ready={_markdown_bool(boundary.get('overall_final_delivery_scope_ready'))}`",
        "",
        "## 交付物索引",
        "",
        "| 交付物 | ready | blocking_scope |",
        "| --- | --- | --- |",
    ]
    for key in (
        "web_operator_panel",
        "local_mvp_acceptance",
        "windows_build_inputs",
        "windows_final_package",
        "authorized_live_submit",
        "commercial_issue_closure",
        "final_acceptance_gate",
        "repository_cleanliness",
    ):
        item = index.get(key) if isinstance(index.get(key), dict) else {}
        lines.append(f"| `{key}` | `{_markdown_bool(item.get('ready'))}` | `{item.get('blocking_scope') or ''}` |")
    lines.extend(["", "## 本地 MVP 证据", ""])
    lines.append(f"- Mac 循环验收：`{local_evidence.get('mac_loop_status') or '-'}`")
    lines.append(f"- 客户端门禁：`{local_evidence.get('client_delivery_status') or '-'}` / `{local_evidence.get('client_delivery_readiness') or '-'}`")
    lines.append(f"- 候选用户：`{operation_counts.get('candidates', 0)}`")
    lines.append(f"- 触达动作：`{operation_counts.get('actions', 0)}`")
    start_evidence = local_evidence.get("start_contract_evidence") if isinstance(local_evidence.get("start_contract_evidence"), dict) else {}
    lines.append(f"- 开始获客合同完整：`{_markdown_bool(local_evidence.get('start_contract_evidence_complete'))}`")
    if start_evidence:
        lines.append(
            "- 开始获客证据："
            f"目标规划={_markdown_bool(start_evidence.get('target_planned'))}，"
            f"批次启动={_markdown_bool(start_evidence.get('campaign_started'))}，"
            f"账号预检={_markdown_bool(start_evidence.get('profile_preflight_checked'))}，"
            f"采集完成={_markdown_bool(start_evidence.get('collection_done'))}，"
            f"触达终态/跳过原因={_markdown_bool(start_evidence.get('action_terminal_or_no_submit_reason'))}，"
            f"批次日志行={start_evidence.get('scoped_log_lines', 0)}"
        )
    if no_action_reason:
        lines.append(f"- 无触达原因：`{no_action_reason.get('code') or '-'}`，{no_action_reason.get('message') or '-'}")
    else:
        lines.append("- 无触达原因：`-`")
    lines.extend(["", "## 开始获客合同", ""])
    if start_contract:
        lines.append(f"- 定义：{start_contract.get('definition') or '-'}")
        lines.append("- 可启动条件：")
        for item in start_contract.get("ready_conditions") or []:
            lines.append(f"  - {item}")
        lines.append("- 阻断条件：")
        for item in start_contract.get("blocking_conditions") or []:
            lines.append(f"  - {item}")
    else:
        lines.append("- 未生成")
    lines.extend(["", "## 有效触达定义", ""])
    modes = outreach_contract.get("modes") if isinstance(outreach_contract.get("modes"), dict) else {}
    if modes:
        for key, item in modes.items():
            if not isinstance(item, dict):
                continue
            lines.append(f"- `{key}` / {item.get('label') or '-'}：提交平台={_markdown_bool(item.get('submits_to_platform'))}，{item.get('definition') or '-'}")
            for condition in item.get("effective_when") or []:
                lines.append(f"  - 有效条件：{condition}")
    else:
        lines.append("- 未生成")
    standards = report.get("acceptance_standards") if isinstance(report.get("acceptance_standards"), dict) else {}
    final_standards = standards.get("final_delivery") if isinstance(standards.get("final_delivery"), list) else []
    lines.extend(["", "## 最终交付标准", ""])
    if final_standards:
        for item in final_standards:
            lines.append(f"- {item}")
    else:
        lines.append("- 未生成")
    lines.extend(["", "## 当前阻断", ""])
    if not blockers:
        lines.append("- 无")
    for blocker in blockers:
        if not isinstance(blocker, dict):
            continue
        details = blocker.get("missing_artifacts") or blocker.get("pending") or blocker.get("failures") or []
        detail_text = ", ".join(str(row) for row in details) if details else "-"
        lines.append(f"- `{blocker.get('scope') or '-'}`：`{blocker.get('status') or '-'}`，明细：{detail_text}")
        if blocker.get("action"):
            lines.append(f"  - 下一步：{blocker.get('action')}")
        for action in blocker.get("next_actions") or []:
            lines.append(f"  - 本地执行下一步：{action}")
    if final_delivery_blockers:
        lines.append("- final_gate 结构化阻断：")
        for blocker in final_delivery_blockers:
            if not isinstance(blocker, dict):
                continue
            lines.append(f"  - `{blocker.get('scope') or '-'}`：{blocker.get('next_action') or '-'}")
            required = blocker.get("required_evidence") or blocker.get("required_artifacts") or []
            for item in required:
                lines.append(f"    - 必需证据：{item}")
    lines.extend(["", "## 下一步命令", ""])
    next_actions = report.get("next_actions") if isinstance(report.get("next_actions"), list) else []
    if not next_actions:
        lines.append("- 无")
    for action in next_actions:
        lines.append(f"- `{action}`")
    lines.extend(
        [
            "",
            "## 验收结论",
            "",
            "本地 MVP 可验收不等于最终客户交付完成。只有 `final_delivery_ready=true` 且 `delivery_boundary.overall_final_delivery_scope_ready=true` 时，才允许声明整项目最终交付完成。",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ReachOps PM goal delivery checkpoint.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", default=str(OUT_PATH))
    return parser.parse_args(argv)


def print_human_summary(report: dict[str, Any], output: Path):
    print(
        f"status={report['status']} local_mvp_ready={report['local_mvp_ready']} "
        f"windows_build_ready={report['windows_build_ready']} final_delivery_ready={report['final_delivery_ready']}"
    )
    print(f"report={output}")
    print("")
    print("execution_entrypoint:")
    print(f"  {report.get('execution_contract', {}).get('entrypoint')}")
    print("")
    print("acceptance_gates:")
    for key in ("local_mvp", "windows_build", "final_delivery"):
        standards = (report.get("acceptance_standards") or {}).get(key) or []
        print(f"  {key}:")
        for item in standards:
            print(f"    - {item}")
    print("")
    print("deliverables:")
    for item in report.get("deliverables") or []:
        print(f"  - {item.get('name')}: {item.get('path')} [{item.get('required_for')}]")
    print("")
    boundary = report.get("delivery_boundary") or {}
    print("delivery_boundary:")
    print(f"  summary={boundary.get('summary')}")
    print(f"  local_mvp_scope_ready={boundary.get('local_mvp_scope_ready')}")
    print(f"  client_gate_scope_ready={boundary.get('client_gate_scope_ready')}")
    print(f"  windows_build_input_scope_ready={boundary.get('windows_build_input_scope_ready')}")
    print(f"  overall_final_delivery_scope_ready={boundary.get('overall_final_delivery_scope_ready')}")
    if boundary.get("client_gate_final_delivery_ready_is_not_overall_final_delivery"):
        print("  note=client_delivery.final_delivery_ready 只代表客户端门禁自身通过，不代表整项目最终交付完成。")
    print("")
    print("blockers:")
    blockers = report.get("blockers") or []
    if not blockers:
        print("  - none")
    for item in blockers:
        scope = item.get("scope")
        status = item.get("status")
        action = item.get("action")
        missing = item.get("missing_artifacts") or item.get("pending") or item.get("failures") or []
        suffix = f" missing={','.join(missing)}" if missing else ""
        print(f"  - {scope}: {status}{suffix}")
        if action:
            print(f"    action={action}")
    if report.get("next_actions"):
        print("")
        print("next_actions:")
        for item in report["next_actions"]:
            print(f"  - {item}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(render_markdown_summary(report), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    else:
        print_human_summary(report, output)
    return 0 if report["local_mvp_ready"] and report["windows_build_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
