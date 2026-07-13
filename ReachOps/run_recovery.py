# -*- coding: utf-8 -*-
"""RunSession recovery helpers for interrupted local executions."""

from __future__ import annotations

from typing import Any

from ReachOps.run_session import TERMINAL_RUN_SESSION_STATES, transition_run_session, utc_now_iso


RUN_RECOVERY_SCHEMA_VERSION = "reachops.run_recovery.v1"
TERMINAL_RESULT_STATUSES = {
    "completed",
    "blocked",
    "degraded",
    "stopped",
    "launch_failed",
    "headless_exited_immediately",
    "timeout_finalized",
}


def should_recover_interrupted_run(session: dict[str, Any], *, running: bool, run_result: dict[str, Any] | None = None) -> bool:
    if running:
        return False
    state = str((session or {}).get("state") or "")
    if not session or state in TERMINAL_RUN_SESSION_STATES:
        return False
    result_status = str((run_result or {}).get("status") or "").strip()
    return result_status not in TERMINAL_RESULT_STATUSES


def build_interrupted_result(session: dict[str, Any], *, last_stage: str = "") -> dict[str, Any]:
    checkpoint = session.get("checkpoint") if isinstance(session.get("checkpoint"), dict) else {}
    return {
        "status": "blocked",
        "generated_at": utc_now_iso(),
        "error": "process_interrupted",
        "message": "本地执行进程不存在，运行会话已按中断归档。",
        "reason": "PROCESS_INTERRUPTED",
        "plan_id": str(session.get("plan_id") or ""),
        "run_session_id": str(session.get("session_id") or ""),
        "execution_plan_path": str(session.get("execution_plan_path") or (session.get("evidence") or {}).get("execution_plan_path") or ""),
        "log_path": str(checkpoint.get("log_path") or (session.get("evidence") or {}).get("log_path") or ""),
        "result_path": str(checkpoint.get("result_path") or (session.get("evidence") or {}).get("result_path") or ""),
        "last_stage": str(last_stage or checkpoint.get("last_stage") or ""),
        "recovery": {
            "schema_version": RUN_RECOVERY_SCHEMA_VERSION,
            "recovered": True,
            "reason": "PROCESS_INTERRUPTED",
            "no_ai_token_used": True,
        },
        "no_ai_token_during_execution": True,
    }


def recover_interrupted_run_session(
    session: dict[str, Any],
    *,
    running: bool,
    run_result: dict[str, Any] | None = None,
    last_stage: str = "",
    pid: int = 0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not should_recover_interrupted_run(session, running=running, run_result=run_result):
        return session or {}, {"schema_version": RUN_RECOVERY_SCHEMA_VERSION, "recovered": False, "no_ai_token_used": True}
    result = build_interrupted_result(session, last_stage=last_stage)
    updated = transition_run_session(
        session,
        "BLOCKED",
        pid=pid or int((session or {}).get("pid") or 0),
        last_stage=last_stage or "PROCESS_INTERRUPTED",
        result=result,
        control={
            "paused": False,
            "last_action": "recover_interrupted_run",
            "status": "blocked",
            "ok": True,
            "reason": "PROCESS_INTERRUPTED",
        },
        evidence={"recovery_reason": "PROCESS_INTERRUPTED"},
    )
    recovery = dict(result["recovery"])
    recovery["result"] = result
    recovery["run_session_state"] = updated.get("state", "")
    return updated, recovery
