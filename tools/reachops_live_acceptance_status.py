# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.runtime_paths import RuntimePaths
from tools.reachops_activation_status_check import check_activation_status
from tools.reachops_live_validation_manifest import build_manifest


REQUIRED_PACKAGE_REPORT_FILES = (
    "delivery_audit",
    "operator_pressure",
    "installer_smoke",
    "ui_startup",
    "activation_status",
    "live_acceptance_status",
    "live_validation",
    "repository_cleanliness",
    "windows_package_preflight",
    "client_delivery",
    "live_readiness",
    "live_preflight",
    "goal_status",
    "live_submit",
    "final_acceptance_gate",
    "issue_closure",
)
FINAL_VERIFICATION_COMMANDS = [
    "python tools\\reachops_client_delivery_check.py --json",
    "python tools\\reachops_delivery_package_check.py --json",
    "python tools\\reachops_issue_closure_audit.py --json",
    "python tools\\reachops_final_acceptance_gate.py --json",
]
OPERATOR_COMMANDS = [
    "powershell -ExecutionPolicy Bypass -File tools\\init_reachops_acceptance_inputs_windows.ps1 -Json",
    "python tools\\reachops_live_acceptance_status.py --local-inputs-path tools\\reachops_acceptance_inputs.local.ps1 --write-report --json-report-path --json",
    "powershell -ExecutionPolicy Bypass -File tools\\run_reachops_acceptance_windows.ps1 -InputFile tools\\reachops_acceptance_inputs.local.ps1",
    "powershell -ExecutionPolicy Bypass -File tools\\run_reachops_acceptance_windows.ps1 -InputFile tools\\reachops_acceptance_inputs.local.ps1 -RunLiveSubmit -ConfirmAuthorizedTargets",
    *FINAL_VERIFICATION_COMMANDS,
]


LOCAL_INPUT_FIELDS = {
    "ProfileIds": "profile_ids",
    "Target": "target",
    "CommentVideoUrl": "comment_video_url",
    "FollowProfileUrl": "target_profile_url",
    "DmProfileUrl": "dm_profile_url",
    "TargetUsername": "target_username",
    "ActivationStatusPath": "activation_status_path",
    "ConfirmAuthorizedTargets": "confirm_authorized_targets",
}
REQUIRED_LOCAL_INPUTS = [
    "ProfileIds",
    "CommentVideoUrl",
    "FollowProfileUrl",
    "DmProfileUrl",
    "TargetUsername",
    "ActivationStatusPath",
    "ConfirmAuthorizedTargets",
]
PLACEHOLDER_PATTERN = re.compile(
    r"123,456|creator/video/123|target_user|C:\\path\\to|reachops_activation_status\.template\.json",
    re.IGNORECASE,
)
PS_ASSIGNMENT_PATTERN = re.compile(r"^\s*\$(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.+?)\s*$")


def _unquote_ps_value(value: str) -> str:
    value = str(value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _ps_truthy(value: str) -> bool:
    text = _unquote_ps_value(value).strip().lower()
    return text in {"$true", "true", "1", "yes", "y"}


def _activation_path_is_template(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if re.search(r"reachops_activation_status\.template\.json$", text, re.IGNORECASE):
        return True
    path = Path(text)
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return isinstance(payload, dict) and bool(payload.get("template_only"))


def inspect_local_inputs(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "usable": False,
        "values": {},
        "missing_fields": list(REQUIRED_LOCAL_INPUTS),
        "placeholder_fields": [],
    }
    if not path.exists():
        return result
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        result["error"] = str(exc)
        return result
    values: dict[str, str] = {}
    for line in lines:
        match = PS_ASSIGNMENT_PATTERN.match(line)
        if not match:
            continue
        name = match.group("name")
        if name in LOCAL_INPUT_FIELDS:
            values[name] = _unquote_ps_value(match.group("value"))
    missing = [name for name in REQUIRED_LOCAL_INPUTS if not values.get(name)]
    placeholders = [name for name in REQUIRED_LOCAL_INPUTS if PLACEHOLDER_PATTERN.search(values.get(name, ""))]
    if "ActivationStatusPath" not in placeholders and _activation_path_is_template(values.get("ActivationStatusPath", "")):
        placeholders.append("ActivationStatusPath")
    authorization_confirmed = _ps_truthy(values.get("ConfirmAuthorizedTargets", ""))
    result.update(
        {
            "values": {LOCAL_INPUT_FIELDS[name]: values.get(name, "") for name in LOCAL_INPUT_FIELDS},
            "missing_fields": missing,
            "placeholder_fields": placeholders,
            "authorization_confirmed": authorization_confirmed,
            "usable": not missing and not placeholders and authorization_confirmed,
        }
    )
    return result


def local_input_field_status(local_inputs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = local_inputs.get("values") if isinstance(local_inputs.get("values"), dict) else {}
    missing = set(str(item) for item in (local_inputs.get("missing_fields") or []))
    placeholders = set(str(item) for item in (local_inputs.get("placeholder_fields") or []))
    status: dict[str, dict[str, Any]] = {}
    for ps_name, public_name in LOCAL_INPUT_FIELDS.items():
        if ps_name == "ConfirmAuthorizedTargets":
            confirmed = bool(local_inputs.get("authorization_confirmed"))
            status[ps_name] = {
                "field": public_name,
                "ready": confirmed,
                "state": "ready" if confirmed else "authorization_not_confirmed",
                "required_action": ""
                if confirmed
                else "确认所有 TikTok 目标已授权后，将 ConfirmAuthorizedTargets 设置为 $true。",
            }
            continue
        value = str(values.get(public_name) or "")
        if ps_name in missing:
            state = "missing"
            action = f"填写 {ps_name}。"
        elif ps_name in placeholders:
            state = "placeholder"
            action = f"替换 {ps_name} 的占位值。"
        else:
            state = "ready"
            action = ""
        status[ps_name] = {
            "field": public_name,
            "ready": state == "ready",
            "state": state,
            "required_action": action,
            "value_present": bool(value),
        }
    return status


def _local_value_unless_placeholder(
    *,
    args_value: Any,
    local_values: dict[str, Any],
    public_name: str,
    ps_name: str,
    placeholder_fields: set[str],
) -> str:
    explicit = str(args_value or "").strip()
    if explicit:
        return explicit
    if ps_name in placeholder_fields:
        return ""
    return str(local_values.get(public_name) or "").strip()


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def latest_acceptance_report(reports_dir: str | Path = "") -> dict[str, Any]:
    root = Path(reports_dir or (ROOT_DIR / "reports" / "reachops_acceptance"))
    if not root.exists():
        return {"exists": False, "dir": "", "summary_path": "", "package_check_path": ""}
    repo_root = root.resolve()
    if repo_root.name == "reachops_acceptance" and repo_root.parent.name == "reports":
        repo_root = repo_root.parent.parent
    dirs = [item for item in root.iterdir() if item.is_dir()]
    if not dirs:
        return {"exists": False, "dir": "", "summary_path": "", "package_check_path": ""}
    latest = max(dirs, key=lambda item: item.stat().st_mtime)
    summary_path = latest / "acceptance_summary.json"
    package_path = latest / "delivery_package_check.json"
    final_gate_path = latest / "final_acceptance_gate.json"
    summary = load_json(summary_path)
    package = load_json(package_path)
    final_gate = load_json(final_gate_path)
    if not final_gate:
        final_gate = summary.get("final_acceptance_gate") if isinstance(summary.get("final_acceptance_gate"), dict) else {}
    verification = summary.get("acceptance_verification") if isinstance(summary.get("acceptance_verification"), dict) else {}
    delivery_audit = summary.get("delivery_audit") if isinstance(summary.get("delivery_audit"), dict) else {}
    if not delivery_audit:
        delivery_audit = verification.get("delivery_audit") if isinstance(verification.get("delivery_audit"), dict) else {}
    goal_status = summary.get("goal_status") if isinstance(summary.get("goal_status"), dict) else {}
    package_verification = (
        package.get("acceptance_verification")
        if isinstance(package.get("acceptance_verification"), dict)
        else {}
    )
    package_artifacts = package.get("artifacts") if isinstance(package.get("artifacts"), dict) else {}
    package_reports = package.get("report_files") if isinstance(package.get("report_files"), dict) else {}
    package_final_gate_summary = (
        package.get("final_gate_report")
        if isinstance(package.get("final_gate_report"), dict)
        else {}
    )
    package_artifacts_ready = all(
        bool((package_artifacts.get(name) or {}).get("exists"))
        for name in ("exe", "installer", "manifest", "acceptance_summary")
    )
    package_pe_artifacts_ready = all(
        bool((package_artifacts.get(name) or {}).get("pe_signature_valid"))
        for name in ("exe", "installer")
    )
    manifest_artifact = package_artifacts.get("manifest") if isinstance(package_artifacts.get("manifest"), dict) else {}
    expected_sha = str(manifest_artifact.get("expected_sha256") or "")
    actual_sha = str(manifest_artifact.get("actual_sha256") or "")
    expected_size = int(manifest_artifact.get("expected_size") or 0)
    actual_size = int(manifest_artifact.get("actual_size") or 0)
    package_manifest_hash_ready = len(expected_sha) == 64 and expected_sha == actual_sha
    package_manifest_size_ready = expected_size > 0 and expected_size == actual_size
    package_report_files_ready = all(
        bool((package_reports.get(name) or {}).get("exists"))
        and int((package_reports.get(name) or {}).get("size") or 0) > 0
        for name in REQUIRED_PACKAGE_REPORT_FILES
    )
    package_root = str(package.get("root") or "")
    try:
        package_root_matches = bool(package_root) and Path(package_root).resolve() == repo_root.resolve()
    except Exception:
        package_root_matches = False
    package_final_gate_report_ready = bool((package_reports.get("final_acceptance_gate") or {}).get("exists"))
    package_final_gate_summary_ready = (
        str(package_final_gate_summary.get("status") or "") == "passed"
        and bool(package_final_gate_summary.get("final_delivery_ready"))
        and not package_final_gate_summary.get("failed_checks")
        and not package_final_gate_summary.get("missing_required_checks")
        and not package_final_gate_summary.get("failed_required_checks")
        and bool(package_final_gate_summary.get("checks_by_name"))
    )
    package_acceptance_ready = (
        bool(package_verification.get("passed"))
        and not package_verification.get("failures")
        and not package_verification.get("pending")
    )
    package_evidence_ready = bool(
        package_artifacts_ready
        and package_pe_artifacts_ready
        and package_manifest_hash_ready
        and package_manifest_size_ready
        and package_root_matches
        and package_final_gate_report_ready
        and package_final_gate_summary_ready
        and package_acceptance_ready
        and package_report_files_ready
    )
    return {
        "exists": True,
        "dir": str(latest),
        "summary_path": str(summary_path),
        "summary_exists": summary_path.exists(),
        "package_check_path": str(package_path),
        "package_check_exists": package_path.exists(),
        "final_acceptance_gate_path": str(final_gate_path),
        "final_acceptance_gate_exists": final_gate_path.exists(),
        "summary_status": str(summary.get("status") or verification.get("status") or ""),
        "package_status": str(package.get("status") or ""),
        "package_passed": bool(package.get("passed")),
        "package_final_delivery_ready": bool(package.get("final_delivery_ready")),
        "package_bootstrap_only": bool(package.get("bootstrap_only")),
        "package_not_final_delivery_reasons": list(package.get("not_final_delivery_reasons") or []),
        "package_root": package_root,
        "package_root_matches": package_root_matches,
        "package_artifacts_ready": package_artifacts_ready,
        "package_pe_artifacts_ready": package_pe_artifacts_ready,
        "package_manifest_hash_ready": package_manifest_hash_ready,
        "package_manifest_size_ready": package_manifest_size_ready,
        "package_report_files_ready": package_report_files_ready,
        "package_final_gate_report_ready": package_final_gate_report_ready,
        "package_final_gate_summary_ready": package_final_gate_summary_ready,
        "package_final_gate_report": package_final_gate_summary,
        "package_acceptance_verification_ready": package_acceptance_ready,
        "package_evidence_ready": package_evidence_ready,
        "final_gate_status": str(final_gate.get("status") or ""),
        "final_gate_ready": bool(final_gate.get("final_delivery_ready")),
        "final_gate_failed_checks": list(final_gate.get("failed_checks") or []),
        "final_gate_next_actions": list(final_gate.get("next_actions") or []),
        "effective_pending_external_validation": int(delivery_audit.get("effective_pending_external_validation") or 0),
        "pending_external_validation": list(
            summary.get("pending_external_validation")
            or goal_status.get("pending_external_validation")
            or verification.get("pending")
            or []
        ),
    }


def pending_acceptance_actions(acceptance: dict[str, Any]) -> list[str]:
    pending = [str(item) for item in (acceptance.get("pending_external_validation") or []) if str(item or "").strip()]
    if not pending:
        return []
    mapping = {
        "授权允许时能真实执行": "运行 readiness/preflight 后执行受控真实提交，确认授权目标和激活状态通过。",
        "真实 TikTok 平台提交": "使用真实 ixBrowser Profile 和授权 TikTok 目标完成 platform_selenium live submit。",
        "客户端交付验收门禁不会把环境阻断当通过": "重新运行客户端交付验收，直到 acceptance_ready=true 且 readiness=pass。",
        "external_platform_validation": "完成外部平台真实验证并重新生成 acceptance_summary.json。",
        "live_preflight_environment_validation": "修复 ixBrowser Profile、代理和登录态后重新运行 no-submit live preflight。",
        "client_delivery_acceptance_gate": "重新运行客户端交付验收，直到 acceptance_ready=true 且 readiness=pass。",
        "real_tiktok_platform_submit": "使用真实 ixBrowser Profile 和授权 TikTok 目标完成 platform_selenium live submit。",
        "live_authorization_execution_validation": "运行 readiness/preflight 后执行受控真实提交，确认授权目标和激活状态通过。",
    }
    actions = []
    seen = set()
    for item in pending:
        action = mapping.get(item, f"处理待验证项: {item}")
        if action not in seen:
            seen.add(action)
            actions.append(action)
    return actions


def final_gate_actions(acceptance: dict[str, Any]) -> list[str]:
    if not acceptance.get("exists"):
        return []
    if acceptance.get("final_gate_status") == "passed" and acceptance.get("final_gate_ready"):
        return []
    explicit = [str(item) for item in (acceptance.get("final_gate_next_actions") or []) if str(item or "").strip()]
    if explicit:
        return explicit
    failed = [str(item) for item in (acceptance.get("final_gate_failed_checks") or []) if str(item or "").strip()]
    if failed:
        return [f"修复最终验收门禁失败项: {', '.join(failed)}。"]
    return ["运行 tools\\reachops_final_acceptance_gate.py --json 并确认 status=passed、final_delivery_ready=true。"]


def missing_input_actions(missing_inputs: list[str]) -> list[str]:
    if not missing_inputs:
        return []
    actions: list[str] = []
    if any("本地验收输入文件 tools/reachops_acceptance_inputs.local.ps1" == str(item) for item in missing_inputs):
        _append_unique(actions, "运行 tools\\init_reachops_acceptance_inputs_windows.ps1 生成本地验收输入文件，然后填入已授权 TikTok 目标和激活状态路径。")
    if any("本地验收输入文件仍有占位值或缺失字段" == str(item) for item in missing_inputs):
        _append_unique(actions, "编辑 tools\\reachops_acceptance_inputs.local.ps1，替换所有占位值并补齐必填字段。")
    field_actions = {
        "已授权 TikTok 视频链接": "填入已授权 TikTok 视频链接 CommentVideoUrl。",
        "已授权 TikTok 用户主页链接": "填入已授权 TikTok 用户主页链接 FollowProfileUrl/DmProfileUrl。",
        "目标用户名": "填入目标用户名 TargetUsername。",
        "激活状态文件": "生成或放置真实激活状态文件，并设置 ActivationStatusPath。",
        "有效激活状态文件": "生成或放置真实激活状态文件，并设置 ActivationStatusPath。",
        "授权确认 ConfirmAuthorizedTargets=YES": "确认目标已授权后使用 -ConfirmAuthorizedTargets 或 --confirm-authorized-targets。",
    }
    for item in missing_inputs:
        action = field_actions.get(str(item))
        if action:
            _append_unique(actions, action)
    return actions or [f"补齐真实验收输入: {', '.join(str(item) for item in missing_inputs)}。"]


def activation_failed_checks(activation: dict[str, Any]) -> list[str]:
    return [
        str(item.get("name") or "")
        for item in (activation.get("checks") or [])
        if isinstance(item, dict) and not bool(item.get("passed")) and str(item.get("name") or "").strip()
    ]


def activation_actions(activation: dict[str, Any]) -> list[str]:
    if activation.get("ready"):
        return []
    failed = set(activation_failed_checks(activation))
    actions: list[str] = []
    if "activation_status_file_exists" in failed:
        _append_unique(actions, "生成或放置真实激活状态文件，并设置 ActivationStatusPath。")
    if "activation_status_json_valid" in failed:
        _append_unique(actions, "修复 ActivationStatusPath 指向文件的 JSON 格式。")
    if "activation_not_template" in failed:
        _append_unique(actions, "使用真实激活状态文件替换 template_only=true 的模板文件。")
    if "activation_active" in failed:
        _append_unique(actions, "确认激活状态 active=true。")
    if "device_binding_matches" in failed:
        _append_unique(actions, "确认激活状态 device_id 绑定当前设备，或使用未绑定/重新签发的激活文件。")
    capability_failures = [
        name
        for name in failed
        if name in {"live_submit_capability_enabled", "comment_reply_capability_enabled", "follow_review_capability_enabled", "dm_review_capability_enabled"}
    ]
    if capability_failures:
        _append_unique(actions, "确认激活状态启用 live_submit、comment_reply、follow_review、dm_review 能力。")
    if "authorization_allows_live_actions" in failed:
        _append_unique(actions, "确认授权门允许 comment、follow、dm 三类真实动作。")
    return actions or ["生成或放置真实激活状态文件，并设置 ActivationStatusPath。"]


def _append_unique(items: list[str], value: str) -> None:
    value = str(value or "").strip()
    if value and value not in items:
        items.append(value)


def build_blocked_reasons(
    *,
    missing_inputs: list[str],
    local_inputs: dict[str, Any],
    activation: dict[str, Any],
    acceptance: dict[str, Any],
    final_delivery_ready: bool,
) -> tuple[list[str], list[str]]:
    if final_delivery_ready:
        return [], []
    failed_checks: list[str] = []
    blocked_reasons: list[str] = []

    if missing_inputs:
        _append_unique(failed_checks, "live_validation:inputs")
        for item in missing_inputs:
            _append_unique(blocked_reasons, item)
    if not local_inputs.get("usable"):
        _append_unique(failed_checks, "local_inputs:usable")
    if not activation.get("ready"):
        _append_unique(failed_checks, "activation:ready")
        _append_unique(blocked_reasons, "激活状态未 ready，不能进入真实提交验收。")
    if acceptance.get("summary_status") != "passed":
        _append_unique(failed_checks, "acceptance_summary:passed")
        _append_unique(blocked_reasons, "acceptance_summary.json 未达到 passed。")
    if not acceptance.get("package_passed"):
        _append_unique(failed_checks, "delivery_package:passed")
        _append_unique(blocked_reasons, "Windows 交付包检查未通过。")
    if not acceptance.get("package_final_delivery_ready"):
        _append_unique(failed_checks, "delivery_package:final_delivery_ready")
        _append_unique(blocked_reasons, "Windows 交付包未达到 final_delivery_ready=true。")
    if acceptance.get("package_bootstrap_only"):
        _append_unique(failed_checks, "delivery_package:not_bootstrap")
        _append_unique(blocked_reasons, "当前 package check 是 bootstrap-only，不能作为最终交付证据。")
    if not acceptance.get("package_evidence_ready"):
        _append_unique(failed_checks, "delivery_package:evidence")
        _append_unique(blocked_reasons, "Windows 交付包缺少 exe、installer、manifest、acceptance summary 或必需报告证据。")
    if acceptance.get("final_gate_status") != "passed" or not acceptance.get("final_gate_ready"):
        _append_unique(failed_checks, "final_acceptance_gate:passed")
        _append_unique(blocked_reasons, "final acceptance gate 未达到 status=passed 且 final_delivery_ready=true。")
    if int(acceptance.get("effective_pending_external_validation") or 0) != 0:
        _append_unique(failed_checks, "external_validation:complete")
        _append_unique(blocked_reasons, "仍存在真实 ixBrowser/TikTok 外部验证待完成项。")
    for item in acceptance.get("final_gate_failed_checks") or []:
        _append_unique(failed_checks, f"final_gate:{item}")
    return blocked_reasons, failed_checks


def build_blocking_plan(
    *,
    missing_inputs: list[str],
    local_inputs: dict[str, Any],
    activation: dict[str, Any],
    acceptance: dict[str, Any],
    final_delivery_ready: bool,
) -> list[dict[str, Any]]:
    if final_delivery_ready:
        return []
    stages: list[dict[str, Any]] = []
    stages.append(
        {
            "stage": "授权输入",
            "status": "ready" if not missing_inputs and local_inputs.get("usable") else "blocked",
            "blockers": list(missing_inputs),
            "actions": missing_input_actions(missing_inputs),
        }
    )
    stages.append(
        {
            "stage": "激活状态",
            "status": "ready" if activation.get("ready") else "blocked",
            "blockers": [] if activation.get("ready") else ["激活状态未 ready，不能进入真实提交验收。"],
            "actions": activation_actions(activation),
        }
    )
    package_blockers: list[str] = []
    if acceptance.get("summary_status") != "passed":
        package_blockers.append("acceptance_summary.json 未达到 passed。")
    if not acceptance.get("package_passed"):
        package_blockers.append("Windows 交付包检查未通过。")
    if not acceptance.get("package_final_delivery_ready"):
        package_blockers.append("Windows 交付包未达到 final_delivery_ready=true。")
    if acceptance.get("package_bootstrap_only"):
        package_blockers.append("当前 package check 是 bootstrap-only，不能作为最终交付证据。")
    if not acceptance.get("package_evidence_ready"):
        package_blockers.append("Windows 交付包缺少 exe、installer、manifest、acceptance summary 或必需报告证据。")
    stages.append(
        {
            "stage": "Windows交付包",
            "status": "ready" if not package_blockers else "blocked",
            "blockers": package_blockers,
            "actions": pending_acceptance_actions(acceptance) or [
                "在 Windows 实机生成 exe、installer、manifest 和 acceptance_summary.json 后复跑 package check。"
            ],
        }
    )
    gate_blockers: list[str] = []
    if acceptance.get("final_gate_status") != "passed" or not acceptance.get("final_gate_ready"):
        gate_blockers.append("final acceptance gate 未达到 status=passed 且 final_delivery_ready=true。")
    for item in acceptance.get("final_gate_failed_checks") or []:
        _append_unique(gate_blockers, f"final gate 失败项: {item}")
    stages.append(
        {
            "stage": "最终门禁",
            "status": "ready" if not gate_blockers else "blocked",
            "blockers": gate_blockers,
            "actions": final_gate_actions(acceptance),
        }
    )
    return stages


def build_status(args: argparse.Namespace, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    runtime_paths = RuntimePaths.build()
    local_inputs_path = Path(args.local_inputs_path or (ROOT_DIR / "tools" / "reachops_acceptance_inputs.local.ps1"))
    local_inputs = inspect_local_inputs(local_inputs_path)
    local_values = local_inputs.get("values") if isinstance(local_inputs.get("values"), dict) else {}
    placeholder_fields = set(str(item) for item in (local_inputs.get("placeholder_fields") or []))
    activation_path = _local_value_unless_placeholder(
        args_value=args.activation_status_path,
        local_values=local_values,
        public_name="activation_status_path",
        ps_name="ActivationStatusPath",
        placeholder_fields=placeholder_fields,
    ) or str(runtime_paths.activation_status_path)
    template_path = Path(args.activation_template_path or (Path(runtime_paths.config_dir) / "reachops_activation_status.template.json"))
    activation = check_activation_status(activation_path)
    profile_ids = _local_value_unless_placeholder(
        args_value=args.profile_ids,
        local_values=local_values,
        public_name="profile_ids",
        ps_name="ProfileIds",
        placeholder_fields=placeholder_fields,
    )
    comment_video_url = _local_value_unless_placeholder(
        args_value=args.comment_video_url,
        local_values=local_values,
        public_name="comment_video_url",
        ps_name="CommentVideoUrl",
        placeholder_fields=placeholder_fields,
    )
    target_profile_url = _local_value_unless_placeholder(
        args_value=args.target_profile_url,
        local_values=local_values,
        public_name="target_profile_url",
        ps_name="FollowProfileUrl",
        placeholder_fields=placeholder_fields,
    )
    dm_profile_url = _local_value_unless_placeholder(
        args_value=args.dm_profile_url,
        local_values=local_values,
        public_name="dm_profile_url",
        ps_name="DmProfileUrl",
        placeholder_fields=placeholder_fields,
    )
    target_username = _local_value_unless_placeholder(
        args_value=args.target_username,
        local_values=local_values,
        public_name="target_username",
        ps_name="TargetUsername",
        placeholder_fields=placeholder_fields,
    )
    manifest_args = SimpleNamespace(
        profile_group=args.profile_group,
        profile_ids=profile_ids,
        profile_limit=args.profile_limit,
        max_pages=args.max_pages,
        profile_scan_timeout=args.profile_scan_timeout,
        target=args.target or local_values.get("target") or "anti aging serum",
        comment_video_url=comment_video_url,
        target_profile_url=target_profile_url,
        dm_profile_url=dm_profile_url,
        target_username=target_username,
        activation_status_path=activation_path,
        limit=args.limit,
        allow_pressure_submit=args.allow_pressure_submit,
        confirm_authorized_targets="YES"
        if (args.confirm_authorized_targets or bool(local_inputs.get("authorization_confirmed")))
        else "",
        include_live_submit_command=False,
    )
    manifest = build_manifest(manifest_args, snapshot=snapshot)
    local_profile_ids_placeholder = "ProfileIds" in placeholder_fields and not str(args.profile_ids or "").strip()
    if local_profile_ids_placeholder:
        manifest["selected_profiles"] = []
        manifest["selected_profile_ids"] = []
        manifest["selected_profile_count"] = 0
        manifest_missing = list(manifest.get("missing_inputs") or [])
        if "ixBrowser 数字 Profile ID" not in manifest_missing:
            manifest_missing.insert(0, "ixBrowser 数字 Profile ID")
        manifest["missing_inputs"] = manifest_missing
        summary = manifest.get("blocking_summary") if isinstance(manifest.get("blocking_summary"), dict) else {}
        summary = dict(summary)
        summary["profile_ready"] = False
        summary["next_blocking_item"] = "ixBrowser 数字 Profile ID"
        manifest["blocking_summary"] = summary
    acceptance = latest_acceptance_report(args.acceptance_reports_dir)
    missing_inputs = list(manifest.get("missing_inputs") or [])
    if not local_inputs_path.exists():
        missing_inputs.insert(0, "本地验收输入文件 tools/reachops_acceptance_inputs.local.ps1")
    elif local_inputs.get("placeholder_fields") or local_inputs.get("missing_fields"):
        missing_inputs.insert(0, "本地验收输入文件仍有占位值或缺失字段")
    seen = set()
    deduped_missing = []
    for item in missing_inputs:
        key = str(item)
        if key not in seen:
            seen.add(key)
            deduped_missing.append(key)
    profile_ids = [str(item) for item in (manifest.get("selected_profile_ids") or [])]
    stage3_ready_for_preflight = (
        bool(profile_ids)
        and bool((manifest.get("blocking_summary") or {}).get("target_ready"))
        and bool((manifest.get("blocking_summary") or {}).get("activation_ready"))
        and bool((manifest.get("blocking_summary") or {}).get("authorization_confirmed"))
    )
    final_delivery_ready = (
        acceptance.get("summary_status") == "passed"
        and bool(acceptance.get("package_passed"))
        and bool(acceptance.get("package_final_delivery_ready"))
        and not bool(acceptance.get("package_bootstrap_only"))
        and bool(acceptance.get("package_evidence_ready"))
        and acceptance.get("final_gate_status") == "passed"
        and bool(acceptance.get("final_gate_ready"))
        and int(acceptance.get("effective_pending_external_validation") or 0) == 0
    )
    acceptance_actions = pending_acceptance_actions(acceptance)
    gate_actions = final_gate_actions(acceptance)
    input_actions = missing_input_actions(deduped_missing)
    next_required_actions: list[str] = []
    for action in input_actions + activation_actions(activation) + acceptance_actions + gate_actions:
        _append_unique(next_required_actions, action)
    if not next_required_actions and not final_delivery_ready:
        next_required_actions = ["运行受控真实提交并生成 live submit evidence"]
    blocked_reasons, failed_checks = build_blocked_reasons(
        missing_inputs=deduped_missing,
        local_inputs=local_inputs,
        activation=activation,
        acceptance=acceptance,
        final_delivery_ready=final_delivery_ready,
    )
    blocking_plan = build_blocking_plan(
        missing_inputs=deduped_missing,
        local_inputs=local_inputs,
        activation=activation,
        acceptance=acceptance,
        final_delivery_ready=final_delivery_ready,
    )

    return {
        "status": "passed" if final_delivery_ready else "blocked",
        "ready_for_live_preflight": stage3_ready_for_preflight,
        "ready_for_live_submit": stage3_ready_for_preflight,
        "final_delivery_ready": final_delivery_ready,
        "no_browser_started": True,
        "no_submit": True,
        "local_inputs": {
            "path": str(local_inputs_path),
            "exists": bool(local_inputs.get("exists")),
            "usable": bool(local_inputs.get("usable")),
            "authorization_confirmed": bool(local_inputs.get("authorization_confirmed")),
            "missing_fields": list(local_inputs.get("missing_fields") or []),
            "placeholder_fields": list(local_inputs.get("placeholder_fields") or []),
            "field_status": local_input_field_status(local_inputs),
        },
        "activation": {
            "path": activation_path,
            "template_path": str(template_path),
            "template_exists": template_path.exists(),
            "exists": bool(activation.get("activation_status_exists")),
            "ready": bool(activation.get("ready")),
            "status": str(activation.get("status") or ""),
            "failed_checks": activation_failed_checks(activation),
            "next_required_actions": activation_actions(activation),
        },
        "live_validation": {
            "status": str(manifest.get("status") or ""),
            "selected_profile_ids": profile_ids,
            "selected_profile_count": int(manifest.get("selected_profile_count") or 0),
            "missing_inputs": deduped_missing,
            "blocking_summary": manifest.get("blocking_summary") or {},
        },
        "latest_acceptance": acceptance,
        "blocked_reasons": blocked_reasons,
        "failed_checks": failed_checks,
        "blocking_plan": blocking_plan,
        "next_required_actions": next_required_actions,
        "operator_commands": list(OPERATOR_COMMANDS),
        "verification_commands": list(FINAL_VERIFICATION_COMMANDS),
    }


def default_report_path() -> Path:
    runtime_paths = RuntimePaths.build()
    return Path(runtime_paths.reports_dir) / "acceptance_remediation" / "latest_live_acceptance_readiness.md"


def render_markdown_report(status: dict[str, Any]) -> str:
    local_inputs = status.get("local_inputs") if isinstance(status.get("local_inputs"), dict) else {}
    activation = status.get("activation") if isinstance(status.get("activation"), dict) else {}
    live_validation = status.get("live_validation") if isinstance(status.get("live_validation"), dict) else {}
    latest_acceptance = status.get("latest_acceptance") if isinstance(status.get("latest_acceptance"), dict) else {}
    lines = [
        "# ReachOps Live Acceptance Readiness",
        "",
        f"- status: {status.get('status')}",
        f"- ready_for_live_preflight: {str(bool(status.get('ready_for_live_preflight'))).lower()}",
        f"- ready_for_live_submit: {str(bool(status.get('ready_for_live_submit'))).lower()}",
        f"- final_delivery_ready: {str(bool(status.get('final_delivery_ready'))).lower()}",
        f"- no_browser_started: {str(bool(status.get('no_browser_started'))).lower()}",
        f"- no_submit: {str(bool(status.get('no_submit'))).lower()}",
        "",
        "## Local Inputs",
        "",
        f"- path: {local_inputs.get('path') or ''}",
        f"- usable: {str(bool(local_inputs.get('usable'))).lower()}",
        f"- authorization_confirmed: {str(bool(local_inputs.get('authorization_confirmed'))).lower()}",
    ]
    field_status = local_inputs.get("field_status") if isinstance(local_inputs.get("field_status"), dict) else {}
    if field_status:
        lines.extend(["", "| Field | State | Action |", "| --- | --- | --- |"])
        for name in LOCAL_INPUT_FIELDS:
            row = field_status.get(name) if isinstance(field_status.get(name), dict) else {}
            lines.append(f"| {name} | {row.get('state') or ''} | {row.get('required_action') or ''} |")
    lines.extend(
        [
            "",
            "## Activation",
            "",
            f"- path: {activation.get('path') or ''}",
            f"- exists: {str(bool(activation.get('exists'))).lower()}",
            f"- ready: {str(bool(activation.get('ready'))).lower()}",
            f"- status: {activation.get('status') or ''}",
        ]
    )
    failed_activation = [str(item) for item in (activation.get("failed_checks") or [])]
    if failed_activation:
        lines.append(f"- failed_checks: {', '.join(failed_activation)}")
    activation_next = [str(item) for item in (activation.get("next_required_actions") or [])]
    if activation_next:
        lines.extend(["", "Activation actions:"])
        lines.extend([f"- {item}" for item in activation_next])
    lines.extend(
        [
            "",
            "## Live Validation",
            "",
            f"- status: {live_validation.get('status') or ''}",
            f"- selected_profile_count: {int(live_validation.get('selected_profile_count') or 0)}",
        ]
    )
    missing_inputs = [str(item) for item in (live_validation.get("missing_inputs") or [])]
    if missing_inputs:
        lines.append(f"- missing_inputs: {', '.join(missing_inputs)}")
    lines.extend(["", "## Blocking Plan", ""])
    for stage in status.get("blocking_plan") or []:
        if not isinstance(stage, dict):
            continue
        lines.append(f"### {stage.get('stage') or ''} / {stage.get('status') or ''}")
        blockers = [str(item) for item in (stage.get("blockers") or [])]
        actions = [str(item) for item in (stage.get("actions") or [])]
        if blockers:
            lines.append("Blockers:")
            lines.extend([f"- {item}" for item in blockers])
        if actions:
            lines.append("Actions:")
            lines.extend([f"- {item}" for item in actions])
        lines.append("")
    lines.extend(["## Final Package", ""])
    lines.append(f"- latest_acceptance_exists: {str(bool(latest_acceptance.get('exists'))).lower()}")
    lines.append(f"- acceptance_summary: {latest_acceptance.get('summary_path') or ''}")
    lines.append(f"- package_check: {latest_acceptance.get('package_check_path') or ''}")
    lines.append(f"- package_passed: {str(bool(latest_acceptance.get('package_passed'))).lower()}")
    lines.append(f"- package_final_delivery_ready: {str(bool(latest_acceptance.get('package_final_delivery_ready'))).lower()}")
    lines.extend(["", "## Next Required Actions", ""])
    next_actions = [str(item) for item in (status.get("next_required_actions") or [])]
    lines.extend([f"- {item}" for item in next_actions] or ["- None"])
    lines.extend(["", "## Operator Command Sequence", ""])
    lines.extend([f"- `{item}`" for item in (status.get("operator_commands") or OPERATOR_COMMANDS)])
    lines.extend(["", "## Verification Commands", ""])
    lines.extend([f"- `{item}`" for item in (status.get("verification_commands") or FINAL_VERIFICATION_COMMANDS)])
    lines.append("")
    return "\n".join(lines)


def write_markdown_report(status: dict[str, Any], report_path: str | Path = "") -> Path:
    path = Path(report_path).expanduser() if str(report_path or "").strip() else default_report_path()
    if not path.is_absolute():
        path = ROOT_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown_report(status), encoding="utf-8")
    return path


def default_json_report_path() -> Path:
    return default_report_path().with_suffix(".json")


def write_json_report(status: dict[str, Any], report_path: str | Path = "") -> Path:
    path = Path(report_path).expanduser() if str(report_path or "").strip() else default_json_report_path()
    if not path.is_absolute():
        path = ROOT_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(status)
    payload["json_report_path"] = str(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize ReachOps live acceptance readiness without opening a browser or submitting actions.")
    parser.add_argument("--profile-group", default="BR")
    parser.add_argument("--profile-ids", default="")
    parser.add_argument("--profile-limit", type=int, default=3)
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--profile-scan-timeout", type=int, default=8)
    parser.add_argument("--target", default="anti aging serum")
    parser.add_argument("--comment-video-url", default="")
    parser.add_argument("--target-profile-url", default="")
    parser.add_argument("--dm-profile-url", default="")
    parser.add_argument("--target-username", default="")
    parser.add_argument("--activation-status-path", default="")
    parser.add_argument("--activation-template-path", default="")
    parser.add_argument("--local-inputs-path", default="")
    parser.add_argument("--acceptance-reports-dir", default="")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--allow-pressure-submit", default="")
    parser.add_argument("--confirm-authorized-targets", action="store_true")
    parser.add_argument("--write-report", action="store_true", help="Write a Markdown readiness report without opening a browser or submitting actions.")
    parser.add_argument("--report-path", default="", help="Markdown report output path. Defaults to the ReachOps runtime reports directory.")
    parser.add_argument(
        "--json-report-path",
        nargs="?",
        const="__default__",
        default="",
        help="Write a machine-readable JSON handoff report. Omit the value to use the default runtime report path.",
    )
    parser.add_argument("--require-final", action="store_true", help="Return non-zero unless final_delivery_ready is true.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status = build_status(args)
    if args.write_report:
        status["report_path"] = str(write_markdown_report(status, args.report_path))
    if args.json_report_path is not None and str(args.json_report_path).strip():
        json_report_arg = "" if str(args.json_report_path) == "__default__" else args.json_report_path
        status["json_report_path"] = str(write_json_report(status, json_report_arg))
    if args.json:
        print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0 if (status.get("final_delivery_ready") or not args.require_final) else 2


if __name__ == "__main__":
    raise SystemExit(main())
