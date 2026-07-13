# -*- coding: utf-8 -*-
"""Deterministic operator chat console for ReachOps.

This module intentionally does not call an LLM. It translates common operator
messages into ExecutionPlan-compatible changes and status explanations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ReachOps.execution_plan import attach_autonomous_preflight_forecast, build_autonomous_preflight_forecast, build_execution_plan
from ReachOps.run_session import build_ai_usage_ledger, normalize_ai_usage_ledger


AI_CONSOLE_SCHEMA_VERSION = "reachops.ai_console.v1"


def _text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    return text


def _sentence(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    if text.endswith(("。", "！", "？", ".", "!", "?")):
        return text
    return text + "。"


def _safe_int(value: Any, default: int = 3, minimum: int = 1, maximum: int = 20) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:
        parsed = int(default)
    return max(minimum, min(maximum, parsed))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "确认", "已确认", "授权"}


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _final_delivery_evidence_plan(runtime: dict, delivery_boundary: dict | None = None) -> dict:
    delivery_boundary = delivery_boundary if isinstance(delivery_boundary, dict) else {}
    plan = runtime.get("final_delivery_evidence_plan") if isinstance(runtime.get("final_delivery_evidence_plan"), dict) else {}
    if plan:
        return plan
    final_status = runtime.get("final_status") if isinstance(runtime.get("final_status"), dict) else {}
    plan = (
        final_status.get("final_delivery_evidence_plan")
        if isinstance(final_status.get("final_delivery_evidence_plan"), dict)
        else {}
    )
    if plan:
        return plan
    plan = (
        delivery_boundary.get("final_delivery_evidence_plan")
        if isinstance(delivery_boundary.get("final_delivery_evidence_plan"), dict)
        else {}
    )
    return plan


def _runtime_final_status(runtime: dict) -> dict:
    return runtime.get("final_status") if isinstance(runtime.get("final_status"), dict) else {}


def _delivery_boundary(runtime: dict, bundle: dict | None = None) -> dict:
    bundle = bundle if isinstance(bundle, dict) else {}
    boundary = runtime.get("delivery_boundary") if isinstance(runtime.get("delivery_boundary"), dict) else {}
    if boundary:
        return boundary
    final_status = _runtime_final_status(runtime)
    boundary = final_status.get("delivery_boundary") if isinstance(final_status.get("delivery_boundary"), dict) else {}
    if boundary:
        return boundary
    return bundle.get("delivery_boundary") if isinstance(bundle.get("delivery_boundary"), dict) else {}


def _product_capability_summary(runtime: dict, bundle: dict | None = None) -> dict:
    bundle = bundle if isinstance(bundle, dict) else {}
    product = bundle.get("product_capability_summary") if isinstance(bundle.get("product_capability_summary"), dict) else {}
    if product:
        return product
    final_status = _runtime_final_status(runtime)
    return (
        final_status.get("product_capability_summary")
        if isinstance(final_status.get("product_capability_summary"), dict)
        else {}
    )


def _product_development_goals(runtime: dict, bundle: dict | None = None) -> dict:
    bundle = bundle if isinstance(bundle, dict) else {}
    goals = bundle.get("product_development_goals") if isinstance(bundle.get("product_development_goals"), dict) else {}
    if goals:
        return goals
    final_status = _runtime_final_status(runtime)
    return (
        final_status.get("product_development_goals")
        if isinstance(final_status.get("product_development_goals"), dict)
        else {}
    )


def _evidence_plan_pending_scopes(plan: dict) -> list[str]:
    scopes = plan.get("pending_scopes") if isinstance(plan.get("pending_scopes"), list) else []
    if scopes:
        return [str(scope) for scope in scopes if str(scope)]
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    return [str((item or {}).get("scope")) for item in items if isinstance(item, dict) and str((item or {}).get("scope"))]


def _evidence_plan_next_actions(plan: dict, limit: int = 4) -> list[str]:
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    actions: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        next_action = _text(item.get("next_action"))
        if next_action:
            actions.append(next_action)
        commands = item.get("commands") if isinstance(item.get("commands"), list) else []
        for command in commands[:1]:
            command_text = _text(command)
            if command_text:
                actions.append(f"验收命令：{command_text}")
        if len(actions) >= limit:
            break
    return actions[:limit]


def _autonomous_preflight_machine_actions(forecast: dict) -> list[str]:
    if not isinstance(forecast, dict):
        return []
    if forecast and not forecast.get("exists", bool(forecast.get("schema_version"))):
        return ["启动前自治预判：missing / 当前证据包来自旧计划或未持久化 forecast"]
    actions = [
        f"启动前自治预判：{forecast.get('forecast_schema_version') or forecast.get('schema_version') or '-'} / "
        f"{forecast.get('status') or '-'} / source={forecast.get('source') or 'runtime'}"
    ]
    if forecast.get("source") == "derived_from_execution_plan":
        actions.append("启动前自治预判由 ExecutionPlan 派生；旧 run 未持久化 forecast，不作为当时现场证据。")
    routes = forecast.get("repair_routes") if isinstance(forecast.get("repair_routes"), list) else []
    route_texts = []
    for row in routes[:5]:
        if isinstance(row, dict):
            route_texts.append(f"{row.get('state') or '-'}:{row.get('action') or '-'}")
    if route_texts:
        actions.append("预判自修复路线：" + " / ".join(route_texts))
    evidence = forecast.get("evidence_requirements") if isinstance(forecast.get("evidence_requirements"), list) else []
    if evidence:
        actions.append("预判证据要求：" + ", ".join(str(item) for item in evidence[:5]))
    invariants = forecast.get("runtime_invariants") if isinstance(forecast.get("runtime_invariants"), dict) else {}
    if invariants:
        actions.append(
            "预判运行约束："
            f"0 token={str(bool(invariants.get('no_ai_token_during_execution'))).lower()} / "
            f"不绕过登录验证码={str(bool(invariants.get('never_bypass_login_or_captcha'))).lower()}"
        )
    return actions


def _autonomous_preflight_timeline(forecast: dict) -> list[str]:
    if not isinstance(forecast, dict):
        return []
    if forecast and not forecast.get("exists", bool(forecast.get("schema_version"))):
        return ["预判状态链：未记录（旧计划未持久化 autonomous_preflight_forecast）"]
    lines = []
    states = forecast.get("predicted_state_sequence") if isinstance(forecast.get("predicted_state_sequence"), list) else []
    if states:
        lines.append("预判状态链：" + " -> ".join(str(item) for item in states[:8]))
    blockers = forecast.get("predicted_blockers") if isinstance(forecast.get("predicted_blockers"), list) else []
    if blockers:
        lines.append("预判阻断：" + ", ".join(str(item) for item in blockers[:5]))
    return lines


def _autonomous_preflight_reconciliation_actions(reconciliation: dict) -> list[str]:
    if not isinstance(reconciliation, dict) or not reconciliation:
        return []
    actions = [
        "预判对账："
        f"status={reconciliation.get('status') or '-'} / "
        f"matched={int(reconciliation.get('matched_route_count') or 0)} / "
        f"unobserved={int(reconciliation.get('unobserved_route_count') or 0)} / "
        f"risk_gate_aligned={str(bool(reconciliation.get('risk_gate_aligned'))).lower()}"
    ]
    states = reconciliation.get("actual_page_states") if isinstance(reconciliation.get("actual_page_states"), list) else []
    if states:
        actions.append("预判对账实际页面状态：" + ", ".join(str(item) for item in states[:6]))
    reasons = reconciliation.get("actual_risk_reasons") if isinstance(reconciliation.get("actual_risk_reasons"), list) else []
    if reasons:
        actions.append("预判对账实际风险原因：" + ", ".join(str(item) for item in reasons[:6]))
    matched = reconciliation.get("matched_routes") if isinstance(reconciliation.get("matched_routes"), list) else []
    if matched:
        rows = []
        for row in matched[:5]:
            if isinstance(row, dict):
                rows.append(f"{row.get('state') or '-'}:{row.get('action') or '-'}")
        if rows:
            actions.append("预判对账命中路线：" + " / ".join(rows))
    return actions


def _run_recovery_machine_actions(recovery: dict) -> list[str]:
    if not isinstance(recovery, dict) or not recovery:
        return []
    if not recovery.get("recovered"):
        return []
    actions = [
        "中断恢复："
        f"reason={recovery.get('latest_reason') or '-'} / "
        f"state={recovery.get('terminal_state') or '-'} / "
        f"last_stage={recovery.get('last_stage') or '-'}"
    ]
    result_error = _text(recovery.get("result_error"))
    if result_error:
        actions.append(f"中断恢复结果：{result_error}")
    inferred = _text(recovery.get("runtime_state_inferred"))
    if inferred:
        actions.append(f"中断恢复 checkpoint：{inferred} / log_lines={int(recovery.get('checkpoint_log_line_count') or 0)}")
    return actions


def _operations_risk_gate_rows(runtime: dict) -> list[dict]:
    operations = runtime.get("operations") if isinstance(runtime.get("operations"), dict) else {}
    rows = operations.get("outreach_view") if isinstance(operations.get("outreach_view"), list) else []
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        risk_text = _text(row.get("risk_gate_summary"))
        risk_gate = row.get("risk_gate") if isinstance(row.get("risk_gate"), dict) else {}
        if risk_text or risk_gate:
            result.append(row)
    return result


def _operations_risk_gate_summary(runtime: dict) -> dict:
    rows = _operations_risk_gate_rows(runtime)
    blocked_rows = []
    allowed_count = 0
    for row in rows:
        risk_gate = row.get("risk_gate") if isinstance(row.get("risk_gate"), dict) else {}
        risk_text = _text(row.get("risk_gate_summary"))
        allowed = bool(risk_gate.get("allowed")) if risk_gate else risk_text == "风险门禁通过"
        if allowed:
            allowed_count += 1
            continue
        blocked_rows.append(row)
    first = blocked_rows[0] if blocked_rows else (rows[0] if rows else {})
    return {
        "schema_version": "reachops.operations_risk_gate_summary.v1",
        "row_count": len(rows),
        "blocked_count": len(blocked_rows),
        "allowed_count": allowed_count,
        "primary_reason": _text(first.get("risk_gate_summary")),
        "primary_next_step": _text(first.get("next_step")),
        "primary_target": _text(first.get("target_username")),
        "primary_action_type": _text(first.get("action_type")),
        "primary_profile_id": _text(first.get("profile_id")),
        "rows": [
            {
                "target_username": _text(row.get("target_username")),
                "action_type": _text(row.get("action_type")),
                "profile_id": _text(row.get("profile_id")),
                "status": _text(row.get("status")),
                "risk_gate_summary": _text(row.get("risk_gate_summary")),
                "next_step": _text(row.get("next_step")),
                "error_code": _text(row.get("error_code")),
            }
            for row in rows[:5]
        ],
        "no_ai_token_used": True,
    }


def _operations_risk_gate_actions(summary: dict) -> list[str]:
    if not isinstance(summary, dict) or int(summary.get("row_count") or 0) <= 0:
        return []
    actions = [
        "运营触达风险门禁："
        f"blocked={int(summary.get('blocked_count') or 0)} / "
        f"allowed={int(summary.get('allowed_count') or 0)}"
    ]
    reason = _text(summary.get("primary_reason"))
    if reason:
        actions.append("运营触达阻断原因：" + reason)
    next_step = _text(summary.get("primary_next_step"))
    if next_step:
        actions.append("运营触达下一步：" + next_step)
    return actions


def _operator_risk_gate_actions(summary: dict) -> list[str]:
    if not isinstance(summary, dict) or int(summary.get("row_count") or 0) <= 0:
        return []
    actions = [
        "证据包运营风险门禁："
        f"blocked={int(summary.get('blocked_count') or 0)} / "
        f"allowed={int(summary.get('allowed_count') or 0)}"
    ]
    reason = _text(summary.get("primary_reason"))
    if reason:
        actions.append("证据包运营阻断原因：" + reason)
    next_step = _text(summary.get("primary_next_step"))
    if next_step:
        actions.append("证据包运营下一步：" + next_step)
    return actions


def _account_repair_safety(summary: dict) -> dict:
    if not isinstance(summary, dict) or not summary:
        return {}
    contract = summary.get("safety_contract") if isinstance(summary.get("safety_contract"), dict) else {}
    safety_keys = {
        "manual_apply_required",
        "operator_confirmed_apply",
        "hard_blocker_only",
        "no_browser_started",
        "no_submit",
        "no_ai_token_used",
    }
    if not contract and not any(key in summary for key in safety_keys):
        return {}
    return {
        "manual_apply_required": bool(summary.get("manual_apply_required", contract.get("manual_apply_required"))),
        "operator_confirmed_apply": bool(summary.get("operator_confirmed_apply", contract.get("operator_confirmed_apply"))),
        "hard_blocker_only": bool(summary.get("hard_blocker_only", contract.get("hard_blocker_only"))),
        "no_browser_started": bool(summary.get("no_browser_started", contract.get("no_browser_started"))),
        "no_submit": bool(summary.get("no_submit", contract.get("no_submit"))),
        "no_ai_token_used": bool(summary.get("no_ai_token_used", contract.get("no_ai_token_used", True))),
    }


def _account_repair_safety_text(summary: dict) -> str:
    safety = _account_repair_safety(summary)
    if not safety:
        return ""
    return (
        "账号修复安全边界："
        f"manual_apply_required={str(safety['manual_apply_required']).lower()}，"
        f"operator_confirmed_apply={str(safety['operator_confirmed_apply']).lower()}，"
        f"hard_blocker_only={str(safety['hard_blocker_only']).lower()}，"
        f"no_browser_started={str(safety['no_browser_started']).lower()}，"
        f"no_submit={str(safety['no_submit']).lower()}，"
        f"no_ai_token_used={str(safety['no_ai_token_used']).lower()}。"
    )


def _account_repair_safety_actions(summary: dict) -> list[str]:
    if not isinstance(summary, dict) or not summary:
        return []
    safety = _account_repair_safety(summary)
    if not safety:
        return []
    return [
        "账号修复安全边界：人工触发隔离计划，只处理硬阻断账号，不打开浏览器，不提交平台动作，执行期 0 token"
    ]


def _preflight_decision_from_form_plan(form_state: dict, plan: dict) -> dict:
    mode = str(plan.get("mode") or form_state.get("mode") or "preflight")
    authorization = plan.get("authorization") if isinstance(plan.get("authorization"), dict) else {}
    group_ready = bool(form_state.get("groupListReady"))
    account_blocked = bool(form_state.get("accountGateBlocked"))
    account_repair_confirmed = bool(form_state.get("accountRepairConfirmed"))
    blockers: list[str] = []
    next_actions: list[str] = []
    if not _text(plan.get("target")):
        blockers.append("target_required")
        next_actions.append("输入产品链接、关键词、达人主页、视频链接、话题或直播间。")
    if not group_ready:
        blockers.append("profile_group_list_not_ready")
        next_actions.append("先刷新 ixBrowser 配置分组，确认所选分组账号数量。")
    if mode == "live_comment" and not authorization.get("live_submit_allowed"):
        blockers.append("live_comment_confirmation_required")
        next_actions.append("真实评论前必须勾选授权确认。")
    if account_blocked and not account_repair_confirmed:
        blockers.append("account_repair_required")
        next_actions.append("执行账号修复计划或勾选已修复账号后重新预检。")
    return {
        "schema_version": "reachops.start_preflight_decision.v1",
        "status": "ready" if not blockers else "blocked",
        "start_allowed": not blockers,
        "gate_state": "可启动" if not blockers else "启动前需处理门禁",
        "blockers": blockers,
        "next_actions": next_actions or ["可以启动本地执行。"],
        "submit_policy": "真实评论提交" if mode == "live_comment" and authorization.get("live_submit_allowed") else "预检，不提交",
        "mode": mode,
        "profile_group": str(plan.get("profile_group") or ""),
        "no_ai_token_used": True,
        "no_browser_started": True,
        "no_submit": True,
    }


def _copy_form_state(form: dict | None) -> dict:
    form = form if isinstance(form, dict) else {}
    return {
        "target": _text(form.get("target")),
        "sourceType": _text(form.get("sourceType") or form.get("source_type"), "auto") or "auto",
        "group": _text(form.get("group"), "United States") or "United States",
        "mode": _text(form.get("mode"), "preflight") or "preflight",
        "volume": _text(form.get("volume"), "quick") or "quick",
        "profiles": _safe_int(form.get("profiles"), 3),
        "commentText": _text(form.get("commentText") or form.get("comment_text")),
        "liveConfirm": _truthy(form.get("liveConfirm", form.get("live_confirm"))),
        "accountRepairConfirmed": _truthy(form.get("accountRepairConfirmed", form.get("account_repair_confirmed"))),
        "groupListReady": _truthy(form.get("groupListReady", form.get("group_list_ready"))),
        "accountGateBlocked": _truthy(form.get("accountGateBlocked", form.get("account_gate_blocked"))),
    }


def _extract_target_from_message(raw: str) -> str:
    text = " ".join(str(raw or "").replace("，", ",").replace("。", ".").split()).strip()
    if not text:
        return ""
    lowered = text.lower()
    if _contains_any(text, ["为什么", "为何", "停了", "卡住", "失败", "阻断", "复盘", "报告", "未知错误", "未知状态"]) or _contains_any(
        lowered, ["why", "stuck", "failed", "blocked", "recap", "report", "unknown"]
    ):
        return ""
    separators = [",", ".", ";", "；"]
    first_clause = text
    for sep in separators:
        if sep in first_clause:
            first_clause = first_clause.split(sep, 1)[0].strip()
    markers = [
        "目标是",
        "目标为",
        "目标:",
        "目标：",
        "推广",
        "采集",
        "找一下",
        "找",
        "寻找",
        "帮我",
        "帮我找",
        "帮我采集",
        "帮我推广",
        "我要",
        "我想",
    ]
    candidate = first_clause
    for marker in markers:
        if marker in candidate:
            candidate = candidate.split(marker, 1)[1].strip()
            break
    strip_terms = [
        "只采集",
        "不评论",
        "不要评论",
        "不提交",
        "不要提交",
        "不触达",
        "真实评论",
        "真实提交",
        "预检",
        "模拟",
        "快速",
        "小批量",
        "标准",
        "压测",
        "账号",
        "用户",
        "线索",
        "达人",
    ]
    for term in strip_terms:
        candidate = candidate.replace(term, " ")
    candidate = " ".join(candidate.split()).strip(" :-：,，。.")
    if len(candidate) < 2 or candidate.lower() in {"collect", "preflight", "live comment"}:
        return ""
    return candidate[:120]


def _local_ai_usage_ledger(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    ledger = build_ai_usage_ledger(plan if isinstance(plan, dict) else {})
    operator_console = dict(ledger.get("operator_console") or {})
    operator_console["local_rule_call_count"] = int(operator_console.get("local_rule_call_count") or 0) + 1
    operator_console["ai_call_count"] = 0
    operator_console["token_estimate"] = 0
    ledger["operator_console"] = operator_console
    return normalize_ai_usage_ledger(ledger, plan if isinstance(plan, dict) else {})


@dataclass
class LocalAIConsole:
    """Local rule-based operator console.

    The name keeps the product language ("AI console") while the behavior stays
    deterministic and auditable.
    """

    base_dir: str = ""
    max_profile_limit: int = 20
    schema_version: str = AI_CONSOLE_SCHEMA_VERSION
    no_ai_token_used: bool = True
    mode_labels: dict[str, str] = field(
        default_factory=lambda: {
            "preflight": "采集 + 触达预检",
            "collect": "只采集",
            "live_comment": "采集 + 真实评论",
        }
    )

    def handle(self, message: Any, *, form: dict | None = None, runtime: dict | None = None) -> dict:
        raw = _text(message)
        lowered = raw.lower()
        form_state = _copy_form_state(form)
        runtime = runtime if isinstance(runtime, dict) else {}
        if self._is_unknown_state_analysis(raw, lowered):
            return self.analyze_unknown_states(raw, form_state=form_state, runtime=runtime)
        if self._is_product_capability_request(raw, lowered):
            return self.explain_product_capability(raw, form_state=form_state, runtime=runtime)
        if self._is_recap_request(raw, lowered):
            return self.recap_run(raw, form_state=form_state, runtime=runtime)
        if self._is_explain_status(raw, lowered):
            return self.explain_status(raw, form_state=form_state, runtime=runtime)
        return self.update_plan(raw, lowered=lowered, form_state=form_state)

    def _is_unknown_state_analysis(self, raw: str, lowered: str) -> bool:
        return _contains_any(raw, ["未知错误", "未知状态", "未知页面", "离线学习", "分析异常", "分析未知"]) or _contains_any(
            lowered, ["unknown state", "unknown error", "offline learning", "analyze unknown"]
        )

    def _is_product_capability_request(self, raw: str, lowered: str) -> bool:
        return _contains_any(
            raw,
            [
                "产品能力",
                "能力矩阵",
                "阶段矩阵",
                "八阶段",
                "8阶段",
                "闭环进度",
                "自治能力",
                "能力闭环",
                "最终交付",
                "交付证据",
                "证据计划",
                "交付边界",
                "还差什么",
            ],
        ) or _contains_any(lowered, ["product capability", "phase matrix", "capability matrix", "autonomy capability"])

    def _is_recap_request(self, raw: str, lowered: str) -> bool:
        return _contains_any(
            raw,
            ["复盘", "总结", "执行结果", "报告", "做了什么", "没做什么", "本次运行", "这次执行", "交付结果"],
        ) or _contains_any(lowered, ["recap", "summary", "report", "what happened", "run result"])

    def _is_explain_status(self, raw: str, lowered: str) -> bool:
        return _contains_any(
            raw,
            ["为什么", "为何", "原因", "停了", "卡住", "失败", "阻断", "报错", "没动", "不能启动"],
        ) or _contains_any(lowered, ["why", "stuck", "failed", "blocked", "stop"])

    def update_plan(self, raw: str, *, lowered: str, form_state: dict) -> dict:
        patch: dict[str, Any] = {}
        extracted_target = _extract_target_from_message(raw)
        if extracted_target and (not form_state.get("target") or extracted_target != form_state.get("target")):
            patch["target"] = extracted_target
            patch["sourceType"] = form_state.get("sourceType") or "keyword"
        if _contains_any(raw, ["只采集", "不评论", "不要评论", "不提交", "不要提交", "不触达"]) or "collect only" in lowered:
            patch["mode"] = "collect"
            patch["liveConfirm"] = False
        elif _contains_any(raw, ["预检", "模拟", "检查"]) or "preflight" in lowered:
            patch["mode"] = "preflight"
            patch["liveConfirm"] = False
        elif _contains_any(raw, ["真实评论", "真实提交", "可以评论", "允许评论", "开始评论"]) or "live comment" in lowered:
            patch["mode"] = "live_comment"
            patch["liveConfirm"] = _contains_any(raw, ["确认授权", "我确认", "已授权", "确认真实评论"])

        if _contains_any(raw, ["快速", "小批量", "先跑一轮"]) or "quick" in lowered:
            patch["volume"] = "quick"
        elif _contains_any(raw, ["标准", "正常"]) or "standard" in lowered:
            patch["volume"] = "standard"
        elif _contains_any(raw, ["压测", "压力", "大批量"]) or "stress" in lowered:
            patch["volume"] = "stress"

        if _contains_any(raw, ["美国", "United States", "US账号", "美区"]):
            patch["group"] = "United States"
        elif _contains_any(raw, ["加拿大", "Canada", "CA账号", "加区"]):
            patch["group"] = "Canada"

        merged = dict(form_state)
        merged.update(patch)
        plan = self._build_plan(merged, origin="local_ai_console")
        preflight_decision = _preflight_decision_from_form_plan(merged, plan)
        plan = attach_autonomous_preflight_forecast(
            plan,
            preflight_decision=preflight_decision,
        )
        autonomous_preflight_forecast = (plan.get("runtime") or {}).get("autonomous_preflight_forecast") or build_autonomous_preflight_forecast(
            plan,
            preflight_decision=preflight_decision,
        )
        mode = str(plan.get("mode") or merged.get("mode") or "preflight")
        return {
            "status": "ok",
            "schema_version": self.schema_version,
            "no_ai_token_used": True,
            "ai_usage_ledger": _local_ai_usage_ledger(plan),
            "intent": "plan_update" if patch else "unknown",
            "message": raw,
            "reply": self._plan_reply(patch, mode),
            "plan_patch": patch,
            "execution_plan": plan,
            "execution_plan_schema": plan.get("schema_version"),
            "execution_plan_id": plan.get("plan_id"),
            "preflight_decision": preflight_decision,
            "autonomous_preflight_forecast": autonomous_preflight_forecast,
            "next_actions": self._next_actions_for_plan(plan),
        }

    def explain_product_capability(self, raw: str, *, form_state: dict, runtime: dict) -> dict:
        bundle = runtime.get("evidence_bundle") if isinstance(runtime.get("evidence_bundle"), dict) else {}
        product = _product_capability_summary(runtime, bundle)
        development_goals = _product_development_goals(runtime, bundle)
        autonomy = bundle.get("autonomy_readiness_summary") if isinstance(bundle.get("autonomy_readiness_summary"), dict) else {}
        operator_summary = bundle.get("operator_summary") if isinstance(bundle.get("operator_summary"), dict) else {}
        delivery_boundary = _delivery_boundary(runtime, bundle)
        final_delivery_evidence_plan = _final_delivery_evidence_plan(runtime, delivery_boundary)
        pending_evidence_scopes = _evidence_plan_pending_scopes(final_delivery_evidence_plan)
        phases = product.get("phases") if isinstance(product.get("phases"), list) else []
        passed = [row for row in phases if isinstance(row, dict) and row.get("passed")]
        failed = [row for row in phases if isinstance(row, dict) and not row.get("passed")]
        failed_titles = [f"{row.get('phase')}. {row.get('title')}" for row in failed[:5]]
        passed_titles = [f"{row.get('phase')}. {row.get('title')}" for row in passed[:5]]
        if product:
            reply = (
                f"产品能力矩阵 ready={str(bool(product.get('ready'))).lower()}，"
                f"8 阶段通过 {int(product.get('passed_count') or len(passed))} 个，"
                f"未闭环 {int(product.get('failed_count') or len(failed))} 个。"
            )
            if failed_titles:
                reply += f"未闭环阶段：{'；'.join(failed_titles)}。"
            if passed_titles:
                reply += f"已验证阶段：{'；'.join(passed_titles)}。"
            reply += (
                f"自治 readiness ready={str(bool(autonomy.get('ready'))).lower()}，"
                f"失败检查 {int(autonomy.get('failed_count') or 0)} 个。"
            )
            if delivery_boundary:
                reply += (
                    f"交付边界：本地能力={str(bool(delivery_boundary.get('local_product_capability_ready'))).lower()}，"
                    f"最终交付={str(bool(delivery_boundary.get('final_delivery_ready'))).lower()}。"
                )
                if delivery_boundary.get("external_validation_pending"):
                    reply += "真实授权平台验证仍待完成。"
                if delivery_boundary.get("windows_final_artifacts_pending"):
                    reply += "Windows 最终包证据仍待完成。"
            if pending_evidence_scopes:
                reply += f"待补证据：{'、'.join(pending_evidence_scopes[:5])}。"
            focus = development_goals.get("current_focus") if isinstance(development_goals.get("current_focus"), dict) else {}
            if focus:
                reply += f"当前开发目标：{focus.get('title')}，下一步：{focus.get('next_action') or focus.get('gap') or '归档证据'}。"
        else:
            reply = "当前还没有产品能力矩阵；需要先生成 evidence bundle 后才能按八阶段解释闭环状态。"
            if pending_evidence_scopes:
                reply += f"最终交付待补证据：{'、'.join(pending_evidence_scopes[:5])}。"
        next_actions = [str(action) for action in development_goals.get("next_actions", []) if str(action)] if development_goals else []
        if not next_actions:
            next_actions = [str(action) for action in product.get("next_actions", []) if str(action)] if product else []
        next_actions = self._merge_actions(next_actions, _evidence_plan_next_actions(final_delivery_evidence_plan))
        if not next_actions:
            next_actions = [str(action) for action in operator_summary.get("next_actions", []) if str(action)]
        if not next_actions:
            next_actions = ["启动一次预检或打开证据包，让系统生成产品能力矩阵。"]
        machine_actions = [
            "读取 evidence_bundle.product_capability_summary",
            "读取 evidence_bundle.product_development_goals",
            "按八阶段产品目标计算 passed/failed",
            "读取 final_delivery_evidence_plan 并列出最终交付待补证据",
            "输出当前开发焦点、验收证据和下一步动作",
            "保持本地规则解释，不调用外部 AI",
        ]
        timeline_summary = [
            f"产品能力矩阵：passed={int(product.get('passed_count') or len(passed) or 0)} failed={int(product.get('failed_count') or len(failed) or 0)}"
        ]
        for row in failed[:5]:
            timeline_summary.append(f"未闭环阶段：{row.get('key')} / {row.get('title')} / next={row.get('next_action')}")
        return {
            "status": "ok",
            "schema_version": self.schema_version,
            "no_ai_token_used": True,
            "ai_usage_ledger": _local_ai_usage_ledger(self._build_plan(form_state, origin="local_ai_console_product_capability")),
            "intent": "product_capability_status",
            "message": raw,
            "reply": reply,
            "plan_patch": {},
            "execution_plan": self._build_plan(form_state, origin="local_ai_console_product_capability"),
            "product_capability_summary": product,
            "product_development_goals": development_goals,
            "autonomy_readiness_summary": autonomy,
            "delivery_boundary": delivery_boundary,
            "final_delivery_evidence_plan": final_delivery_evidence_plan,
            "operator_summary": operator_summary,
            "evidence_bundle": {
                "schema_version": bundle.get("schema_version", ""),
                "bundle_id": bundle.get("bundle_id", ""),
                "product_capability_summary": product,
                "product_development_goals": development_goals,
                "autonomy_readiness_summary": autonomy,
                "delivery_boundary": delivery_boundary,
                "final_delivery_evidence_plan": final_delivery_evidence_plan,
                "operator_summary": operator_summary,
            },
            "machine_actions": machine_actions,
            "timeline_summary": timeline_summary,
            "next_actions": next_actions[:8],
        }

    def explain_status(self, raw: str, *, form_state: dict, runtime: dict) -> dict:
        run_session = runtime.get("run_session") if isinstance(runtime.get("run_session"), dict) else {}
        run_result = runtime.get("run_result") if isinstance(runtime.get("run_result"), dict) else {}
        bundle = runtime.get("evidence_bundle") if isinstance(runtime.get("evidence_bundle"), dict) else {}
        operator_summary = bundle.get("operator_summary") if isinstance(bundle.get("operator_summary"), dict) else {}
        repair_summary = bundle.get("repair_summary") if isinstance(bundle.get("repair_summary"), dict) else {}
        risk_summary = bundle.get("risk_summary") if isinstance(bundle.get("risk_summary"), dict) else {}
        operator_risk_gate_summary = (
            bundle.get("operator_risk_gate_summary")
            if isinstance(bundle.get("operator_risk_gate_summary"), dict)
            else {}
        )
        risk_policy_summary = (
            bundle.get("risk_policy_summary") if isinstance(bundle.get("risk_policy_summary"), dict) else {}
        )
        page_state_summary = bundle.get("page_state_summary") if isinstance(bundle.get("page_state_summary"), dict) else {}
        control_summary = bundle.get("control_summary") if isinstance(bundle.get("control_summary"), dict) else {}
        run_recovery_summary = (
            bundle.get("run_recovery_summary") if isinstance(bundle.get("run_recovery_summary"), dict) else {}
        )
        run_session_health = bundle.get("run_session_health") if isinstance(bundle.get("run_session_health"), dict) else {}
        if not run_session_health:
            run_session_health = run_session.get("session_health") if isinstance(run_session.get("session_health"), dict) else {}
        ai_usage_summary = bundle.get("ai_usage_summary") if isinstance(bundle.get("ai_usage_summary"), dict) else {}
        plan_runtime_contract = bundle.get("plan_runtime_contract") if isinstance(bundle.get("plan_runtime_contract"), dict) else {}
        autonomous_execution_summary = (
            bundle.get("autonomous_execution_summary")
            if isinstance(bundle.get("autonomous_execution_summary"), dict)
            else {}
        )
        autonomous_preflight_forecast = (
            bundle.get("autonomous_preflight_forecast")
            if isinstance(bundle.get("autonomous_preflight_forecast"), dict)
            else {}
        )
        autonomous_preflight_reconciliation = (
            bundle.get("autonomous_preflight_reconciliation")
            if isinstance(bundle.get("autonomous_preflight_reconciliation"), dict)
            else {}
        )
        account_health_summary = (
            bundle.get("account_health_summary") if isinstance(bundle.get("account_health_summary"), dict) else {}
        )
        account_repair_summary = (
            bundle.get("account_repair_summary") if isinstance(bundle.get("account_repair_summary"), dict) else {}
        )
        autonomy_readiness_summary = (
            bundle.get("autonomy_readiness_summary") if isinstance(bundle.get("autonomy_readiness_summary"), dict) else {}
        )
        autonomous_execution_summary = (
            bundle.get("autonomous_execution_summary")
            if isinstance(bundle.get("autonomous_execution_summary"), dict)
            else {}
        )
        product_capability_summary = _product_capability_summary(runtime, bundle)
        offline_learning = bundle.get("offline_learning") if isinstance(bundle.get("offline_learning"), dict) else {}
        timeline_summary = self._timeline_summary_from_bundle(bundle)
        acceptance = runtime.get("acceptance") if isinstance(runtime.get("acceptance"), dict) else {}
        client_delivery = acceptance.get("client_delivery") if isinstance(acceptance.get("client_delivery"), dict) else {}
        acceptance_state = acceptance.get("acceptance") if isinstance(acceptance.get("acceptance"), dict) else {}
        delivery_boundary = _delivery_boundary(runtime, bundle)
        final_delivery_evidence_plan = _final_delivery_evidence_plan(runtime, delivery_boundary)
        pending_evidence_scopes = _evidence_plan_pending_scopes(final_delivery_evidence_plan)
        operations_risk_gate_summary = _operations_risk_gate_summary(runtime)

        blockers = []
        primary_blocker = _text(operator_summary.get("primary_blocker"))
        if primary_blocker:
            blockers.append(primary_blocker)
        if int(risk_summary.get("authorization_block_count") or 0) > 0:
            blockers.append("风险门禁阻断：真实动作缺少授权。")
        elif int(risk_summary.get("blocked_count") or 0) > 0:
            blockers.append("风险门禁阻断：账号、额度、限频或高风险状态不允许继续。")
        if int(risk_policy_summary.get("duplicate_text_block_count") or 0) > 0:
            blockers.append("风险策略阻断：触达话术重复，需要改写或等待去重窗口。")
        if int(risk_policy_summary.get("quota_block_count") or 0) > 0:
            blockers.append("风险策略阻断：账号或任务额度已用尽。")
        if int(risk_policy_summary.get("rate_limit_block_count") or 0) > 0:
            blockers.append("风险策略阻断：检测到限频窗口。")
        if int(operations_risk_gate_summary.get("blocked_count") or 0) > 0:
            blockers.append(
                "运营触达阻断："
                + (
                    _text(operations_risk_gate_summary.get("primary_reason"))
                    or "触达表中存在风险门禁阻断。"
                )
            )
        if int(page_state_summary.get("unknown_count") or 0) > 0:
            blockers.append("页面状态阻断：存在 UNKNOWN_PAGE_STATE，需要查看错误包。")
        elif int(page_state_summary.get("blocking_count") or 0) > 0:
            blockers.append("页面状态阻断：登录、验证码、限频、弹窗或 DOM 状态不可继续。")
        if int(repair_summary.get("block_count") or 0) > 0:
            blockers.append("自修复策略已阻断继续执行。")
        if int(control_summary.get("stop_count") or 0) > 0:
            blockers.append("运行控制记录显示本次包含停止事件。")
        if run_recovery_summary.get("recovered"):
            blockers.append("本次运行已从中断会话恢复并归档为阻断状态。")
        if ai_usage_summary.get("audit_status") == "fail":
            blockers.append("执行期 AI token 审计失败，需要复核 ai_usage_ledger。")
        if int(account_repair_summary.get("hard_blocker_profile_count") or 0) > 0:
            blockers.append(
                f"账号修复计划包含 {int(account_repair_summary.get('hard_blocker_profile_count') or 0)} 个硬阻断账号。"
            )
        if account_repair_summary.get("pending_recheck"):
            blockers.append("账号修复已应用，当前需要刷新账号分组并重新预检。")
        policy_candidates = offline_learning.get("policy_candidates") if isinstance(offline_learning.get("policy_candidates"), dict) else {}
        if int(policy_candidates.get("candidate_count") or 0) > 0:
            blockers.append("离线学习已有候选规则，但人工确认前不会自动改变执行策略。")
        blockers.extend(str(x) for x in client_delivery.get("blockers") or [])
        blockers.extend(str(x) for x in client_delivery.get("failed_checks") or [])
        blockers.extend(str(x) for x in acceptance_state.get("blockers") or [])
        client_delivery_next_actions = [str(x) for x in client_delivery.get("next_actions") or [] if str(x)]
        acceptance_next_actions = [str(x) for x in acceptance_state.get("next_actions") or [] if str(x)]
        if run_result.get("error"):
            blockers.append(str(run_result.get("error")))
        if run_result.get("message"):
            blockers.append(str(run_result.get("message")))
        if not blockers and run_session.get("state") in {"BLOCKED", "DEGRADED"}:
            blockers.append(str((run_session.get("result") or {}).get("reason") or run_session.get("state")))
        if not blockers:
            blockers.append("当前没有明确阻断记录；可查看运行日志和账号诊断。")
        if pending_evidence_scopes:
            blockers.append(f"最终交付证据待补：{'、'.join(pending_evidence_scopes[:5])}。")

        state = str(run_session.get("state") or runtime.get("run_session_state") or "READY")
        operator_title = _text(operator_summary.get("title"))
        machine_actions = self._machine_actions_from_evidence(repair_summary, risk_summary)
        account_repair_safety_actions = _account_repair_safety_actions(account_repair_summary)
        recovery_machine_actions = _run_recovery_machine_actions(run_recovery_summary)
        preflight_machine_actions = _autonomous_preflight_machine_actions(autonomous_preflight_forecast)
        preflight_timeline = _autonomous_preflight_timeline(autonomous_preflight_forecast)
        preflight_reconciliation_actions = _autonomous_preflight_reconciliation_actions(
            autonomous_preflight_reconciliation
        )
        operations_risk_actions = _operations_risk_gate_actions(operations_risk_gate_summary)
        machine_actions = self._merge_actions(
            machine_actions,
            account_repair_safety_actions,
            operations_risk_actions,
            recovery_machine_actions,
            preflight_reconciliation_actions,
            preflight_machine_actions,
        )
        timeline_summary = self._merge_actions(timeline_summary, preflight_timeline)
        reply = f"当前会话状态是 {state}。"
        if run_session_health:
            reply += (
                f"会话健康={run_session_health.get('status', '-')}，"
                f"stale={str(bool(run_session_health.get('stale'))).lower()}，"
                f"last_stage={run_session_health.get('last_stage') or '-'}。"
            )
        if operator_title:
            reply += f"运营摘要：{operator_title}。"
        reply += f"主要原因：{_sentence(blockers[0])}"
        if int(operations_risk_gate_summary.get("blocked_count") or 0) > 0:
            reply += (
                f"运营触达表显示 {int(operations_risk_gate_summary.get('blocked_count') or 0)} 条风险阻断，"
                f"目标={operations_risk_gate_summary.get('primary_target') or '-'}，"
                f"动作={operations_risk_gate_summary.get('primary_action_type') or '-'}。"
            )
        if machine_actions:
            reply += f"本地机器动作：{_sentence(machine_actions[0])}"
        if client_delivery_next_actions:
            reply += f"客户端门禁下一步：{_sentence(client_delivery_next_actions[0])}"
        account_repair_safety_text = _account_repair_safety_text(account_repair_summary)
        if account_repair_safety_text:
            reply += account_repair_safety_text
        if timeline_summary:
            reply += f"时间线显示：{timeline_summary[0]}"
        if product_capability_summary:
            reply += (
                f"产品能力矩阵：ready={str(bool(product_capability_summary.get('ready'))).lower()}，"
                f"failed={int(product_capability_summary.get('failed_count') or 0)}。"
            )
        if delivery_boundary:
            reply += (
                f"交付边界：本地能力={str(bool(delivery_boundary.get('local_product_capability_ready'))).lower()}，"
                f"最终交付={str(bool(delivery_boundary.get('final_delivery_ready'))).lower()}。"
            )
        if autonomous_preflight_forecast:
            reply += (
                f"启动前预判：exists={str(bool(autonomous_preflight_forecast.get('exists', True))).lower()}，"
                f"status={autonomous_preflight_forecast.get('status') or '-'}，"
                f"source={autonomous_preflight_forecast.get('source') or '-'}，"
                f"repair_routes={int(autonomous_preflight_forecast.get('repair_route_count') or len(autonomous_preflight_forecast.get('repair_routes') or []))}。"
            )
        if autonomous_preflight_reconciliation:
            reply += (
                f"预判对账：status={autonomous_preflight_reconciliation.get('status') or '-'}，"
                f"matched={int(autonomous_preflight_reconciliation.get('matched_route_count') or 0)}，"
                f"unobserved={int(autonomous_preflight_reconciliation.get('unobserved_route_count') or 0)}。"
            )
        if run_recovery_summary.get("recovered"):
            reply += (
                f"中断恢复：reason={run_recovery_summary.get('latest_reason') or '-'}，"
                f"last_stage={run_recovery_summary.get('last_stage') or '-'}，"
                f"result={run_recovery_summary.get('result_error') or '-'}。"
            )
        if pending_evidence_scopes:
            reply += f"最终交付还差证据：{'、'.join(pending_evidence_scopes[:5])}。"
        return {
            "status": "ok",
            "schema_version": self.schema_version,
            "no_ai_token_used": True,
            "ai_usage_ledger": _local_ai_usage_ledger(self._build_plan(form_state, origin="local_ai_console_explain")),
            "intent": "explain_status",
            "message": raw,
            "reply": reply,
            "plan_patch": {},
            "execution_plan": self._build_plan(form_state, origin="local_ai_console_explain"),
            "run_session_state": state,
            "operator_summary": operator_summary,
            "final_delivery_evidence_plan": final_delivery_evidence_plan,
            "autonomous_preflight_forecast": autonomous_preflight_forecast,
            "autonomous_preflight_reconciliation": autonomous_preflight_reconciliation,
            "evidence_bundle": {
                "schema_version": bundle.get("schema_version", ""),
                "bundle_id": bundle.get("bundle_id", ""),
                "operator_summary": operator_summary,
                "repair_summary": repair_summary,
                "risk_summary": risk_summary,
                "risk_policy_summary": risk_policy_summary,
                "page_state_summary": page_state_summary,
                "control_summary": control_summary,
                "run_recovery_summary": run_recovery_summary,
                "run_session_health": run_session_health,
                "autonomous_execution_summary": autonomous_execution_summary,
                "autonomous_preflight_forecast": autonomous_preflight_forecast,
                "autonomous_preflight_reconciliation": autonomous_preflight_reconciliation,
                "ai_usage_summary": ai_usage_summary,
                "plan_runtime_contract": plan_runtime_contract,
                "account_health_summary": account_health_summary,
                "account_repair_summary": account_repair_summary,
                "operations_risk_gate_summary": operations_risk_gate_summary,
                "autonomy_readiness_summary": autonomy_readiness_summary,
                "autonomous_execution_summary": autonomous_execution_summary,
                "product_capability_summary": product_capability_summary,
                "delivery_boundary": delivery_boundary,
                "final_delivery_evidence_plan": final_delivery_evidence_plan,
                "timeline_summary": timeline_summary,
            },
            "blockers": blockers[:8],
            "client_delivery": client_delivery,
            "client_delivery_summary": {
                "status": client_delivery.get("status"),
                "readiness": client_delivery.get("readiness"),
                "acceptance_ready": client_delivery.get("acceptance_ready"),
                "final_delivery_ready": client_delivery.get("final_delivery_ready"),
                "failed_checks": list(client_delivery.get("failed_checks") or []),
                "blocker_count": len(client_delivery.get("blockers") or []),
                "next_action_count": len(client_delivery_next_actions),
                "no_ai_token_used": True,
                "no_browser_started": bool(client_delivery.get("no_browser_started", True)),
                "no_submit": bool(client_delivery.get("no_submit", True)),
            },
            "operations_risk_gate_summary": operations_risk_gate_summary,
            "timeline_summary": timeline_summary,
            "machine_actions": machine_actions,
            "next_actions": self._merge_actions(
                self._status_next_actions(blockers, run_session, operator_summary),
                client_delivery_next_actions,
                acceptance_next_actions,
                machine_actions,
                _evidence_plan_next_actions(final_delivery_evidence_plan),
            ),
        }

    def recap_run(self, raw: str, *, form_state: dict, runtime: dict) -> dict:
        bundle = runtime.get("evidence_bundle") if isinstance(runtime.get("evidence_bundle"), dict) else {}
        summary = bundle.get("summary") if isinstance(bundle.get("summary"), dict) else {}
        operator_summary = bundle.get("operator_summary") if isinstance(bundle.get("operator_summary"), dict) else {}
        audit = bundle.get("audit") if isinstance(bundle.get("audit"), dict) else {}
        run_session = runtime.get("run_session") if isinstance(runtime.get("run_session"), dict) else {}
        run_result = runtime.get("run_result") if isinstance(runtime.get("run_result"), dict) else {}
        timeline = bundle.get("timeline") if isinstance(bundle.get("timeline"), list) else []
        artifacts = bundle.get("artifacts") if isinstance(bundle.get("artifacts"), list) else []
        offline_learning = bundle.get("offline_learning") if isinstance(bundle.get("offline_learning"), dict) else {}
        repair_summary = bundle.get("repair_summary") if isinstance(bundle.get("repair_summary"), dict) else {}
        risk_summary = bundle.get("risk_summary") if isinstance(bundle.get("risk_summary"), dict) else {}
        operator_risk_gate_summary = (
            bundle.get("operator_risk_gate_summary")
            if isinstance(bundle.get("operator_risk_gate_summary"), dict)
            else {}
        )
        risk_policy_summary = (
            bundle.get("risk_policy_summary") if isinstance(bundle.get("risk_policy_summary"), dict) else {}
        )
        page_state_summary = bundle.get("page_state_summary") if isinstance(bundle.get("page_state_summary"), dict) else {}
        control_summary = bundle.get("control_summary") if isinstance(bundle.get("control_summary"), dict) else {}
        run_recovery_summary = (
            bundle.get("run_recovery_summary") if isinstance(bundle.get("run_recovery_summary"), dict) else {}
        )
        run_session_health = bundle.get("run_session_health") if isinstance(bundle.get("run_session_health"), dict) else {}
        if not run_session_health:
            run_session_health = run_session.get("session_health") if isinstance(run_session.get("session_health"), dict) else {}
        ai_usage_summary = bundle.get("ai_usage_summary") if isinstance(bundle.get("ai_usage_summary"), dict) else {}
        plan_runtime_contract = bundle.get("plan_runtime_contract") if isinstance(bundle.get("plan_runtime_contract"), dict) else {}
        account_health_summary = (
            bundle.get("account_health_summary") if isinstance(bundle.get("account_health_summary"), dict) else {}
        )
        account_repair_summary = (
            bundle.get("account_repair_summary") if isinstance(bundle.get("account_repair_summary"), dict) else {}
        )
        autonomy_readiness_summary = (
            bundle.get("autonomy_readiness_summary") if isinstance(bundle.get("autonomy_readiness_summary"), dict) else {}
        )
        autonomous_execution_summary = (
            bundle.get("autonomous_execution_summary")
            if isinstance(bundle.get("autonomous_execution_summary"), dict)
            else {}
        )
        autonomous_preflight_forecast = (
            bundle.get("autonomous_preflight_forecast")
            if isinstance(bundle.get("autonomous_preflight_forecast"), dict)
            else {}
        )
        autonomous_preflight_reconciliation = (
            bundle.get("autonomous_preflight_reconciliation")
            if isinstance(bundle.get("autonomous_preflight_reconciliation"), dict)
            else {}
        )
        product_capability_summary = (
            bundle.get("product_capability_summary") if isinstance(bundle.get("product_capability_summary"), dict) else {}
        )
        timeline_summary = self._timeline_summary_from_bundle(bundle)

        status = _text(summary.get("status") or run_result.get("status") or run_session.get("status") or "unknown")
        state = _text(summary.get("state") or run_session.get("state") or runtime.get("run_session_state") or "READY")
        target = _text(summary.get("target") or form_state.get("target") or "未设置目标")
        mode = _text(summary.get("mode") or form_state.get("mode") or "preflight")
        profile_group = _text(summary.get("profile_group") or form_state.get("group") or "United States")
        reason = _text(summary.get("reason") or run_result.get("error") or run_result.get("message"))
        no_ai_token = bool(summary.get("no_ai_token_during_execution", audit.get("no_ai_token_during_execution", True)))
        execution_ai_calls = int(ai_usage_summary.get("execution_phase_ai_call_count") or 0)
        execution_token_estimate = int(ai_usage_summary.get("execution_phase_token_estimate") or 0)
        machine_actions = self._machine_actions_from_evidence(repair_summary, risk_summary)
        account_repair_safety_actions = _account_repair_safety_actions(account_repair_summary)
        recovery_machine_actions = _run_recovery_machine_actions(run_recovery_summary)
        preflight_machine_actions = _autonomous_preflight_machine_actions(autonomous_preflight_forecast)
        preflight_timeline = _autonomous_preflight_timeline(autonomous_preflight_forecast)
        preflight_reconciliation_actions = _autonomous_preflight_reconciliation_actions(
            autonomous_preflight_reconciliation
        )
        operator_risk_actions = _operator_risk_gate_actions(operator_risk_gate_summary)
        machine_actions = self._merge_actions(
            machine_actions,
            account_repair_safety_actions,
            recovery_machine_actions,
            preflight_reconciliation_actions,
            preflight_machine_actions,
            operator_risk_actions,
        )
        timeline_summary = self._merge_actions(timeline_summary, preflight_timeline)

        existing_artifacts = len([row for row in artifacts if isinstance(row, dict) and row.get("exists")])
        timeline_count = len(timeline)
        blocker = reason or ("已完成，没有记录阻断原因。" if str(status).lower() == "completed" else "没有记录明确阻断原因。")
        operator_title = _text(operator_summary.get("title"))
        operator_blocker = _text(operator_summary.get("primary_blocker"))
        reply = (
            f"本次执行状态是 {status} / {state}，目标 {target}，模式 {mode}，账号组 {profile_group}。"
            f"运营摘要：{operator_title or '未生成'}；首要问题：{operator_blocker or blocker}。"
            f"证据包记录了 {timeline_count} 条时间线和 {existing_artifacts} 个已存在产物。"
            f"关键时间线：{'；'.join(timeline_summary[:3]) if timeline_summary else '未提取到结构化关键事件'}。"
            f"自修复记录：{int(repair_summary.get('decision_count') or 0)} 个决策，"
            f"{int(repair_summary.get('retry_count') or 0)} 次重试，"
            f"{int(repair_summary.get('switch_profile_count') or 0)} 次换号，"
            f"{int(repair_summary.get('degrade_count') or 0)} 次降级。"
            f"风险门禁：{int(risk_summary.get('decision_count') or 0)} 个决策，"
            f"{int(risk_summary.get('blocked_count') or 0)} 次阻断，"
            f"{int(risk_summary.get('authorization_block_count') or 0)} 次授权阻断，"
            f"{int(risk_summary.get('risk_action_count') or 0)} 个风险动作，"
            f"{int(risk_summary.get('human_review_required_count') or 0)} 个需要人工复核。"
            f"风险策略：{int(risk_policy_summary.get('policy_block_count') or 0)} 个策略阻断，"
            f"{int(risk_policy_summary.get('quota_block_count') or 0)} 个额度阻断，"
            f"{int(risk_policy_summary.get('rate_limit_block_count') or 0)} 个限频阻断，"
            f"{int(risk_policy_summary.get('duplicate_text_block_count') or 0)} 个重复话术阻断。"
            f"运营风险门禁：{int(operator_risk_gate_summary.get('row_count') or 0)} 条记录，"
            f"{int(operator_risk_gate_summary.get('blocked_count') or 0)} 条阻断，"
            f"主原因={operator_risk_gate_summary.get('primary_reason') or '-'}，"
            f"下一步={operator_risk_gate_summary.get('primary_next_step') or '-'}。"
            f"页面状态：{int(page_state_summary.get('snapshot_count') or 0)} 个快照，"
            f"{int(page_state_summary.get('blocking_count') or 0)} 个阻断状态，"
            f"{int(page_state_summary.get('unknown_count') or 0)} 个未知状态。"
            f"运行控制：{int(control_summary.get('event_count') or 0)} 个事件，"
            f"{int(control_summary.get('pause_count') or 0)} 次暂停，"
            f"{int(control_summary.get('resume_count') or 0)} 次继续，"
            f"{int(control_summary.get('stop_count') or 0)} 次停止。"
            f"中断恢复：recovered={str(bool(run_recovery_summary.get('recovered'))).lower()}，"
            f"reason={run_recovery_summary.get('latest_reason') or '-'}，"
            f"last_stage={run_recovery_summary.get('last_stage') or '-'}。"
            f"会话健康：{run_session_health.get('status', '-')}，"
            f"stale={str(bool(run_session_health.get('stale'))).lower()}，"
            f"last_stage={run_session_health.get('last_stage') or '-'}。"
            f"账号健康：{int(account_health_summary.get('event_count') or 0)} 个事件，"
            f"{int(account_health_summary.get('cooldown_event_count') or 0)} 次冷却。"
            f"账号修复：{int(account_repair_summary.get('error_group_count') or 0)} 个错误分组，"
            f"{int(account_repair_summary.get('hard_blocker_profile_count') or 0)} 个硬阻断账号，"
            f"待重新预检={str(bool(account_repair_summary.get('pending_recheck'))).lower()}。"
            f"{_account_repair_safety_text(account_repair_summary)}"
            f"计划运行合同：plan_id_match={str(bool(plan_runtime_contract.get('plan_id_matches'))).lower()}，"
            f"fingerprint_match={str(bool(plan_runtime_contract.get('plan_fingerprint_matches'))).lower()}，"
            f"runtime_fingerprint={str(bool(plan_runtime_contract.get('runtime_after_fingerprint_present'))).lower()}，"
            f"cli_args_ignored={str(bool(plan_runtime_contract.get('cli_args_ignored_for_plan_fields'))).lower()}。"
            f"启动前预判：exists={str(bool(autonomous_preflight_forecast.get('exists'))).lower()}，"
            f"status={autonomous_preflight_forecast.get('status') or '-'}，"
            f"source={autonomous_preflight_forecast.get('source') or '-'}，"
            f"repair_routes={int(autonomous_preflight_forecast.get('repair_route_count') or len(autonomous_preflight_forecast.get('repair_routes') or []))}，"
            f"evidence_requirements={int(autonomous_preflight_forecast.get('evidence_requirement_count') or len(autonomous_preflight_forecast.get('evidence_requirements') or []))}。"
            f"预判对账：status={autonomous_preflight_reconciliation.get('status') or '-'}，"
            f"matched={int(autonomous_preflight_reconciliation.get('matched_route_count') or 0)}，"
            f"unobserved={int(autonomous_preflight_reconciliation.get('unobserved_route_count') or 0)}，"
            f"risk_gate_aligned={str(bool(autonomous_preflight_reconciliation.get('risk_gate_aligned'))).lower()}。"
            f"执行期 AI 调用：{execution_ai_calls} 次，token 估算：{execution_token_estimate}。"
            f"结论：{blocker} 执行过程默认未消耗 AI token：{str(no_ai_token and execution_ai_calls == 0 and execution_token_estimate == 0).lower()}。"
            f"自治链路：ready={str(bool(autonomy_readiness_summary.get('ready'))).lower()}，"
            f"failed={int(autonomy_readiness_summary.get('failed_count') or 0)}。"
            f"产品能力矩阵：ready={str(bool(product_capability_summary.get('ready'))).lower()}，"
            f"passed={int(product_capability_summary.get('passed_count') or 0)}，"
            f"failed={int(product_capability_summary.get('failed_count') or 0)}。"
        )
        if machine_actions:
            reply += f"机器动作摘要：{'；'.join(machine_actions[:3])}。"

        next_actions = self._recap_next_actions(
            summary,
            audit,
            offline_learning,
            repair_summary,
            risk_summary,
            risk_policy_summary,
            page_state_summary,
            control_summary,
            operator_summary,
            account_repair_summary,
            run_session,
        )
        return {
            "status": "ok",
            "schema_version": self.schema_version,
            "no_ai_token_used": True,
            "ai_usage_ledger": _local_ai_usage_ledger(self._build_plan(form_state, origin="local_ai_console_recap")),
            "intent": "run_recap",
            "message": raw,
            "reply": reply,
            "plan_patch": {},
            "execution_plan": self._build_plan(form_state, origin="local_ai_console_recap"),
            "run_session_state": state,
            "evidence_bundle": {
                "schema_version": bundle.get("schema_version", ""),
                "bundle_id": bundle.get("bundle_id", ""),
                "path": bundle.get("path", ""),
                "markdown_path": bundle.get("markdown_path", ""),
                "summary": summary,
                "operator_summary": operator_summary,
                "audit": audit,
                "repair_summary": repair_summary,
                "risk_summary": risk_summary,
                "operator_risk_gate_summary": operator_risk_gate_summary,
                "risk_policy_summary": risk_policy_summary,
                "page_state_summary": page_state_summary,
                "control_summary": control_summary,
                "run_recovery_summary": run_recovery_summary,
                "run_session_health": run_session_health,
                "ai_usage_summary": ai_usage_summary,
                "plan_runtime_contract": plan_runtime_contract,
                "account_health_summary": account_health_summary,
                "account_repair_summary": account_repair_summary,
                "autonomy_readiness_summary": autonomy_readiness_summary,
                "autonomous_execution_summary": autonomous_execution_summary,
                "autonomous_preflight_forecast": autonomous_preflight_forecast,
                "autonomous_preflight_reconciliation": autonomous_preflight_reconciliation,
                "product_capability_summary": product_capability_summary,
                "timeline_summary": timeline_summary,
            },
            "blockers": [blocker] if blocker else [],
            "timeline_summary": timeline_summary,
            "machine_actions": machine_actions,
            "next_actions": self._merge_actions(next_actions, machine_actions),
        }

    def analyze_unknown_states(self, raw: str, *, form_state: dict, runtime: dict) -> dict:
        bundle = runtime.get("evidence_bundle") if isinstance(runtime.get("evidence_bundle"), dict) else {}
        offline_learning = runtime.get("offline_learning") if isinstance(runtime.get("offline_learning"), dict) else {}
        if not offline_learning:
            offline_learning = bundle.get("offline_learning") if isinstance(bundle.get("offline_learning"), dict) else {}
        records = offline_learning.get("records") if isinstance(offline_learning.get("records"), list) else []
        record_count = int(offline_learning.get("record_count") or len(records) or 0)
        policy_candidates = offline_learning.get("policy_candidates") if isinstance(offline_learning.get("policy_candidates"), dict) else {}
        policy_review_summary = (
            offline_learning.get("policy_review_summary") if isinstance(offline_learning.get("policy_review_summary"), dict) else {}
        )
        policy_release_proposal = (
            offline_learning.get("policy_release_proposal")
            if isinstance(offline_learning.get("policy_release_proposal"), dict)
            else {}
        )
        candidates = policy_candidates.get("candidates") if isinstance(policy_candidates.get("candidates"), list) else []
        evidence_paths = self._offline_learning_evidence_paths(records, candidates)
        top = records[0] if records and isinstance(records[0], dict) else {}
        suggested = top.get("suggested_policy") if isinstance(top.get("suggested_policy"), dict) else {}
        candidate_state = _text(suggested.get("candidate_state") or top.get("state") or "UNKNOWN_PAGE_STATE")
        candidate_action = _text(suggested.get("candidate_action") or "capture_unknown_state_bundle")
        confidence = _text(suggested.get("confidence") or "none")
        occurrence = int(top.get("occurrence_count") or 0)
        if record_count:
            top_candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
            candidate_note = ""
            if top_candidate:
                candidate_note = (
                    f" 已形成 {int(policy_candidates.get('candidate_count') or 0)} 个候选规则，"
                    f"最高频候选是 {top_candidate.get('candidate_state')} → {top_candidate.get('candidate_action')}，"
                    f"累计 {int(top_candidate.get('occurrence_count') or 0)} 次。"
                )
            review_note = ""
            if int(policy_review_summary.get("review_count") or 0) > 0:
                review_note = (
                    f" 已记录人工复核 {int(policy_review_summary.get('review_count') or 0)} 条，"
                    f"批准 {int(policy_review_summary.get('approved_count') or 0)} 条，"
                    f"拒绝 {int(policy_review_summary.get('rejected_count') or 0)} 条；"
                    "这些复核只进入审计账本，不会自动绕过 RiskGate。"
                )
            release_note = ""
            if int(policy_release_proposal.get("ready_for_release_count") or 0) > 0:
                release_note = (
                    f" 已生成 {int(policy_release_proposal.get('ready_for_release_count') or 0)} 条策略发布建议，"
                    f"发布门禁={policy_release_proposal.get('release_gate') or 'code_or_policy_release_required'}，"
                    f"runtime_auto_apply={int(policy_release_proposal.get('runtime_auto_apply_count') or 0)}。"
                )
            reply = (
                f"未知状态账本共有 {record_count} 类记录。最高频签名出现 {occurrence} 次，"
                f"候选分类是 {candidate_state}，建议策略是 {candidate_action}，置信度 {confidence}。"
                f"{candidate_note}"
                f"{review_note}"
                f"{release_note}"
                f"可核对证据文件 {len(evidence_paths)} 个。"
                "这只是本地离线分析，不会自动绕过 RiskGate 或改变真实执行策略。"
            )
        else:
            reply = "当前没有未知状态离线学习记录；如果后续出现 UNKNOWN_PAGE_STATE，程序会保存证据包再进入分析。"
        machine_actions = [
            "读取 offline_learning unknown_states 本地账本",
            "聚合 UNKNOWN_PAGE_STATE 签名和出现次数",
            "输出候选规则但保持 RiskGate 默认阻断",
        ]
        if evidence_paths:
            machine_actions.append(f"索引未知状态证据文件 {len(evidence_paths)} 个")
        if int(policy_review_summary.get("review_count") or 0) > 0:
            machine_actions.append("读取离线候选规则人工复核记录，保持 runtime_auto_apply=0")
        if int(policy_release_proposal.get("ready_for_release_count") or 0) > 0:
            machine_actions.append("生成离线策略发布建议，等待代码或策略发布门禁")
        timeline_summary = self._unknown_state_timeline(records, candidates)
        return {
            "status": "ok",
            "schema_version": self.schema_version,
            "no_ai_token_used": True,
            "ai_usage_ledger": _local_ai_usage_ledger(self._build_plan(form_state, origin="local_ai_console_unknown_state_analysis")),
            "intent": "unknown_state_analysis",
            "message": raw,
            "reply": reply,
            "plan_patch": {},
            "execution_plan": self._build_plan(form_state, origin="local_ai_console_unknown_state_analysis"),
            "offline_learning": {
                "schema_version": offline_learning.get("schema_version", ""),
                "ledger_path": offline_learning.get("ledger_path", ""),
                "record_count": record_count,
                "records": records[:5],
                "evidence_paths": evidence_paths[:20],
                "evidence_path_count": len(evidence_paths),
                "policy_candidates": policy_candidates,
                "policy_review_summary": policy_review_summary,
                "policy_release_proposal": policy_release_proposal,
                "no_ai_token_used": True,
            },
            "machine_actions": machine_actions,
            "timeline_summary": timeline_summary,
            "next_actions": self._unknown_state_next_actions(record_count, candidate_state, candidate_action, policy_candidates, len(evidence_paths)),
        }

    def _build_plan(self, state: dict, *, origin: str) -> dict:
        volume = str(state.get("volume") or "quick")
        max_videos, max_comments = {"quick": (3, 20), "standard": (10, 80), "stress": (30, 300)}.get(volume, (3, 20))
        profile_limit = _safe_int(state.get("profiles"), 3, maximum=self.max_profile_limit)
        timeout_seconds = max(300, min(7200, 300 + profile_limit * 120 + max_videos * 90 + max_comments * 3))
        return build_execution_plan(
            target=state.get("target") or "",
            source_type=state.get("sourceType") or "auto",
            mode=state.get("mode") or "preflight",
            profile_group=state.get("group") or "United States",
            volume=volume,
            profile_limit=profile_limit,
            max_videos=max_videos,
            max_comments=max_comments,
            timeout_seconds=timeout_seconds,
            comment_text=state.get("commentText") or "",
            live_confirmed=state.get("liveConfirm"),
            account_repair_confirmed=state.get("accountRepairConfirmed"),
            force_account_recheck=state.get("accountRepairConfirmed") and state.get("accountGateBlocked"),
            base_dir=self.base_dir,
            origin=origin,
        )

    def _plan_reply(self, patch: dict, mode: str) -> str:
        if not patch:
            return "我没有识别到可直接修改的执行参数，已保留当前计划。"
        label = self.mode_labels.get(mode, mode)
        if mode == "live_comment" and not patch.get("liveConfirm"):
            return f"已切换到 {label}，但真实评论仍需要明确授权确认后才会提交。"
        return f"已按你的意图调整为 {label}，执行开始后由本地程序自动执行。"

    def _next_actions_for_plan(self, plan: dict) -> list[str]:
        actions = ["检查执行计划预览。"]
        if plan.get("mode") == "live_comment" and not (plan.get("authorization") or {}).get("live_confirmed"):
            actions.append("真实评论前需要勾选授权确认。")
        if not _text(plan.get("target")):
            actions.append("补充推广目标。")
        return actions

    def _status_next_actions(self, blockers: list[str], run_session: dict, operator_summary: dict | None = None) -> list[str]:
        operator_actions = [
            str(action)
            for action in ((operator_summary or {}).get("next_actions") or [])
            if str(action)
        ]
        if operator_actions:
            return operator_actions[:5]
        joined = " ".join(blockers)
        if "account" in joined.lower() or "账号" in joined:
            return ["查看账号诊断。", "隔离坏账号后重新预检。"]
        if "activation" in joined.lower() or "授权" in joined or "真实" in joined:
            return ["补齐授权输入和激活状态。", "确认真实评论目标已授权。"]
        if run_session.get("state") == "BLOCKED":
            return ["查看最新日志和证据包。", "处理阻断后重新启动。"]
        return ["刷新运行状态。", "查看报告中心。"]

    def _machine_actions_from_evidence(self, repair_summary: dict, risk_summary: dict) -> list[str]:
        actions: list[str] = []
        repair_steps = self._extract_step_names(repair_summary, ["audit_events", "decisions"], "executable_steps")
        if repair_steps:
            actions.append(f"自修复机器步骤：{', '.join(repair_steps[:5])}")
        outcome_counts = repair_summary.get("terminal_outcome_counts") if isinstance(repair_summary.get("terminal_outcome_counts"), dict) else {}
        if outcome_counts:
            outcome_text = ", ".join(f"{key}={value}" for key, value in sorted(outcome_counts.items()) if int(value or 0) > 0)
            if outcome_text:
                actions.append(f"自修复最终处置：{outcome_text}")
        retry_after = self._first_positive_int(repair_summary, ["audit_events", "decisions"], "retry_after_seconds")
        if retry_after:
            actions.append(f"自修复退避等待 {retry_after} 秒后再试")
        cooldown = self._first_positive_int(repair_summary, ["audit_events", "decisions"], "cooldown_seconds")
        if cooldown:
            actions.append(f"账号或范围冷却 {cooldown} 秒")
        if self._has_truthy(repair_summary, ["audit_events", "decisions"], "requires_human_review"):
            actions.append("自修复需要人工复核")

        risk_steps = self._extract_step_names(risk_summary, ["decisions"], "risk_actions")
        if risk_steps:
            actions.append(f"风险门禁机器步骤：{', '.join(risk_steps[:5])}")
        risk_categories = risk_summary.get("risk_category_counts") if isinstance(risk_summary.get("risk_category_counts"), dict) else {}
        if risk_categories:
            category_text = ", ".join(f"{key}={value}" for key, value in sorted(risk_categories.items()) if int(value or 0) > 0)
            if category_text:
                actions.append(f"风险分类：{category_text}")
        risk_outcomes = risk_summary.get("terminal_outcome_counts") if isinstance(risk_summary.get("terminal_outcome_counts"), dict) else {}
        if risk_outcomes:
            outcome_text = ", ".join(f"{key}={value}" for key, value in sorted(risk_outcomes.items()) if int(value or 0) > 0)
            if outcome_text:
                actions.append(f"风险最终处置：{outcome_text}")
        risk_action_count = int(risk_summary.get("risk_action_count") or len(risk_steps) or 0)
        if risk_action_count and not risk_steps:
            actions.append(f"风险门禁记录了 {risk_action_count} 个机器动作")
        if int(risk_summary.get("block_execution_count") or 0) > 0:
            actions.append("风险门禁要求阻断执行")
        if int(risk_summary.get("human_review_required_count") or 0) > 0 or self._has_truthy(
            risk_summary, ["decisions"], "requires_human_review"
        ):
            actions.append("风险门禁要求人工复核")
        return self._merge_actions(actions)

    def _timeline_summary_from_bundle(self, bundle: dict) -> list[str]:
        timeline = bundle.get("timeline") if isinstance(bundle.get("timeline"), list) else []
        if not timeline:
            return []
        priority = {
            "RISK_GATE": 0,
            "ACCOUNT_HEALTH": 1,
            "PAGE_STATE": 2,
            "REPAIR": 3,
            "CHECKPOINT": 4,
            "CONTROL": 5,
            "BLOCK": 6,
            "ERROR": 7,
        }
        rows = [row for row in timeline if isinstance(row, dict)]
        rows = sorted(
            rows,
            key=lambda row: (
                priority.get(_text(row.get("stage")), 20),
                -len(_text(row.get("message"))),
            ),
        )
        summaries: list[str] = []
        for row in rows:
            stage = _text(row.get("stage"), "EVENT")
            message = _text(row.get("message"))
            source = _text(row.get("source"))
            if stage == "RISK_GATE":
                reason = _text(row.get("reason_code"))
                allowed = "放行" if row.get("allowed") else "阻断"
                profile = _text(row.get("profile_id"))
                text = f"风险门禁{allowed}"
                if reason:
                    text += f"：{reason}"
                if profile:
                    text += f" profile={profile}"
            elif stage == "ACCOUNT_HEALTH":
                profile = _text(row.get("profile_id"))
                error_code = _text(row.get("error_code"))
                status = _text(row.get("status"))
                text = "账号健康事件"
                if row.get("cooldown"):
                    text = "账号已进入冷却"
                if profile:
                    text += f" profile={profile}"
                if status:
                    text += f" status={status}"
                if error_code:
                    text += f" error={error_code}"
            elif stage == "PAGE_STATE":
                state = _text(row.get("state"), "UNKNOWN_PAGE_STATE")
                text = f"页面状态：{state}"
                signals = row.get("signals") if isinstance(row.get("signals"), list) else []
                if signals:
                    text += f" signals={','.join(str(item) for item in signals[:3])}"
            elif stage == "REPAIR":
                text = f"自修复事件：{message or _text(row.get('error_code')) or '-'}"
            elif stage == "CHECKPOINT":
                state = _text(row.get("runtime_state_inferred") or row.get("state"))
                text = f"运行 checkpoint：{state or '-'}"
                if message:
                    text += f" {message}"
            elif stage == "CONTROL":
                text = f"运行控制：{message or '-'}"
            else:
                text = f"{stage}: {message or '-'}"
            if source and source not in text:
                text += f" source={source}"
            summaries.append(text[:220])
        return self._merge_actions(summaries)[:5]

    def _extract_step_names(self, summary: dict, row_keys: list[str], step_key: str) -> list[str]:
        steps: list[str] = []
        for row in self._summary_rows(summary, row_keys):
            for step in row.get(step_key) or []:
                if isinstance(step, dict):
                    name = _text(step.get("step"))
                else:
                    name = _text(step)
                if name:
                    steps.append(name)
        return self._merge_actions(steps)

    def _summary_rows(self, summary: dict, row_keys: list[str]) -> list[dict]:
        rows: list[dict] = []
        if isinstance(summary, dict):
            for key in row_keys:
                values = summary.get(key)
                if isinstance(values, list):
                    rows.extend(row for row in values if isinstance(row, dict))
        return rows

    def _first_positive_int(self, summary: dict, row_keys: list[str], key: str) -> int:
        for row in self._summary_rows(summary, row_keys):
            try:
                value = int(row.get(key) or 0)
            except Exception:
                value = 0
            if value > 0:
                return value
        return 0

    def _has_truthy(self, summary: dict, row_keys: list[str], key: str) -> bool:
        return any(bool(row.get(key)) for row in self._summary_rows(summary, row_keys))

    def _merge_actions(self, *groups: list[str]) -> list[str]:
        merged: list[str] = []
        for group in groups:
            for action in group or []:
                text = str(action).strip()
                if text and text not in merged:
                    merged.append(text)
        return merged[:24]

    def _recap_next_actions(
        self,
        summary: dict,
        audit: dict,
        offline_learning: dict,
        repair_summary: dict,
        risk_summary: dict,
        risk_policy_summary: dict,
        page_state_summary: dict,
        control_summary: dict,
        operator_summary: dict,
        account_repair_summary: dict,
        run_session: dict,
    ) -> list[str]:
        actions: list[str] = []
        for action in operator_summary.get("next_actions") or []:
            if action:
                actions.append(str(action))
        if _account_repair_safety_actions(account_repair_summary):
            actions.append("账号修复只允许人工确认隔离硬阻断账号，不打开浏览器、不提交平台动作。")
        if account_repair_summary.get("pending_recheck"):
            actions.append("账号修复已应用，刷新账号分组并重新预检。")
        elif int(account_repair_summary.get("hard_blocker_profile_count") or 0) > 0:
            actions.append("打开账号修复计划，先处理硬阻断账号。")
        if summary.get("blocked_or_degraded") or run_session.get("state") in {"BLOCKED", "DEGRADED"}:
            actions.append("先处理阻断原因，再重新启动同一计划。")
        if int(control_summary.get("stop_count") or 0) > 0:
            actions.append("本次包含停止控制事件，复盘时确认是人工停止还是系统保护停止。")
        elif int(control_summary.get("recovery_count") or 0) > 0:
            actions.append("本次包含中断恢复事件，先查看恢复点和最后 checkpoint。")
        if int(page_state_summary.get("unknown_count") or 0) > 0:
            actions.append("查看未知页面状态证据包，必要时升级 PageStateDetector 规则。")
        elif int(page_state_summary.get("blocking_count") or 0) > 0:
            actions.append("查看页面状态摘要，处理登录、验证码、限频或 DOM 阻断。")
        if int(risk_summary.get("authorization_block_count") or 0) > 0:
            actions.append("补齐真实动作授权；未授权前不能评论、关注或私信。")
        elif int(risk_summary.get("blocked_count") or 0) > 0:
            actions.append("查看风险门禁摘要，处理账号冷却、额度或限频阻断。")
        for action in risk_policy_summary.get("next_actions") or []:
            if action:
                actions.append(str(action))
        if int(repair_summary.get("block_count") or 0) > 0:
            actions.append("复核自修复阻断项，确认是否需要新增修复策略或隔离账号。")
        elif int(repair_summary.get("decision_count") or 0) > 0:
            actions.append("检查自修复摘要，确认重试、换号或降级是否符合预期。")
        missing = audit.get("missing_artifacts") if isinstance(audit.get("missing_artifacts"), list) else []
        if missing:
            actions.append("补齐缺失证据产物，避免复盘链路不完整。")
        if int(offline_learning.get("record_count") or 0) > 0:
            actions.append("查看未知状态离线学习账本，把重复问题沉淀为修复策略。")
        if not actions:
            actions.append("查看证据包 Markdown 报告并归档本次运行。")
        return list(dict.fromkeys(actions))[:8]

    def _offline_learning_evidence_paths(self, records: list[dict], candidates: list[dict]) -> list[str]:
        paths: list[str] = []
        for row in list(records or []) + list(candidates or []):
            if isinstance(row, dict):
                paths.extend(str(item) for item in (row.get("evidence_paths") or []) if str(item))
        return list(dict.fromkeys(paths))

    def _unknown_state_timeline(self, records: list[dict], candidates: list[dict]) -> list[str]:
        lines: list[str] = []
        for row in (records or [])[:3]:
            if not isinstance(row, dict):
                continue
            state = _text(row.get("state"), "UNKNOWN_PAGE_STATE")
            signature = _text(row.get("state_signature") or row.get("signature"), "-")
            count = int(row.get("occurrence_count") or row.get("count") or 1)
            lines.append(f"未知状态：{state} signature={signature} occurrences={count}")
        for row in (candidates or [])[:2]:
            if not isinstance(row, dict):
                continue
            lines.append(
                "候选规则："
                f"{_text(row.get('candidate_state'), 'UNKNOWN_PAGE_STATE')} -> "
                f"{_text(row.get('candidate_action'), 'capture_unknown_state_bundle')} "
                f"occurrences={int(row.get('occurrence_count') or 0)}"
            )
        if not lines:
            lines.append("未知状态：暂无 UNKNOWN_PAGE_STATE 离线记录，保持默认阻断")
        return lines[:5]

    def _unknown_state_next_actions(
        self,
        record_count: int,
        candidate_state: str,
        candidate_action: str,
        policy_candidates: dict | None = None,
        evidence_path_count: int = 0,
    ) -> list[str]:
        if record_count <= 0:
            return ["等待下一次 UNKNOWN_PAGE_STATE 证据包。", "保持未知状态默认阻断，不自动放行。"]
        actions = ["打开离线学习账本，核对截图、URL、标题和 selector 计数。"]
        if evidence_path_count > 0:
            actions.append(f"先复核 {evidence_path_count} 个未知状态证据文件，再决定是否升级规则。")
        if int((policy_candidates or {}).get("candidate_count") or 0) > 0:
            actions.append("复核候选规则队列；人工确认前不写入运行时策略。")
        if candidate_state and candidate_state != "UNKNOWN_PAGE_STATE":
            actions.append(f"把高频未知状态评估为 {candidate_state} 的候选规则。")
        if candidate_action:
            actions.append(f"评估是否把 {candidate_action} 纳入 RepairPolicyEngine。")
        actions.append("规则升级前不要改变真实执行策略。")
        return actions[:5]
