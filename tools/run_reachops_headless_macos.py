# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


class DummyVar:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class DummyRoot:
    def after(self, delay_ms, callback=None):
        if callable(callback):
            return callback()
        return None


class DummyConsole:
    def __init__(self, args):
        mode_labels = {
            "preflight": "采集 + 触达预检",
            "collect": "只采集",
            "live_comment": "采集 + 真实评论",
        }
        volume_labels = {
            "quick": "快速",
            "standard": "标准",
            "stress": "压测",
        }
        self.scan_source_type_var = DummyVar(str(args.source_type))
        self.scan_source_value_var = DummyVar(str(args.target))
        self.scan_profile_group_var = DummyVar(str(args.profile_group))
        self.scan_profile_group_display_var = DummyVar(str(args.profile_group))
        self.quick_send_mode_var = DummyVar(mode_labels.get(str(args.mode), "采集 + 触达预检"))
        self.quick_send_volume_var = DummyVar(volume_labels.get(str(args.volume), "快速"))
        interval_by_volume = {"quick": 3, "standard": 8, "stress": 1}
        interval = interval_by_volume.get(str(args.volume), 3)
        if str(args.mode) == "live_comment":
            interval = max(interval, 12)
        self.scan_interval_var = DummyVar(interval)
        self.scan_max_videos_var = DummyVar(int(args.max_videos))
        self.scan_max_comments_var = DummyVar(int(args.max_comments))
        self.scan_profile_limit_var = DummyVar(int(args.profile_limit))
        self.scan_intent_keywords_var = DummyVar("price, buy, link, download, app, coupon")
        self.scan_exclude_keywords_var = DummyVar("haha, lol, spam")
        live_comment = str(args.mode) == "live_comment"
        self.action_execution_mode_var = DummyVar("真实提交" if live_comment else "预检，不提交")
        self.action_execution_group_var = DummyVar(str(args.profile_group))
        self.action_execution_workers_var = DummyVar(int(args.profile_limit))
        self.action_execution_per_profile_var = DummyVar(5)
        self.action_execution_hour_limit_var = DummyVar(10)
        self.action_execution_video_hour_limit_var = DummyVar(1)
        self.action_execution_live_confirm_var = DummyVar(live_comment)
        self.quick_comment_text_var = DummyVar(str(args.comment_text or ""))

    def apply_quick_send_preset(self):
        return None

    def show_campaign_plan(self, *_args, **_kwargs):
        return None

    def refresh(self, *_args, **_kwargs):
        return None

    def append_runtime_log(self, *_args, **_kwargs):
        return None

    def set_profile_group_options(self, *_args, **_kwargs):
        return None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def latest_log_lines(path: Path, limit: int = 400) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except Exception:
        return []


def parse_profile_preflight_progress(lines: list[str]) -> dict:
    import re

    progress: dict = {}
    summary_pattern = re.compile(
        r"profile_preflight\s+checked=(?P<checked>\d+)\s+available=(?P<available>\d+)\s+"
        r"unavailable=(?P<unavailable>\d+)\s+errors=(?P<errors>.*)$"
    )
    batch_pattern = re.compile(
        r"profile_preflight\s+stage=(?P<stage>\S+)\s+reason=(?P<reason>\S+)\s+profiles=(?P<profiles>\d+)"
    )
    for line in lines:
        if "profile_preflight" not in line:
            continue
        batch_match = batch_pattern.search(line)
        if batch_match:
            progress.update(
                {
                    "stage": batch_match.group("stage"),
                    "reason": batch_match.group("reason"),
                    "batch_profiles": int(batch_match.group("profiles") or 0),
                    "last_line": line,
                }
            )
        summary_match = summary_pattern.search(line)
        if summary_match:
            progress.update(
                {
                    "stage": progress.get("stage") or "collection",
                    "checked": int(summary_match.group("checked") or 0),
                    "available": int(summary_match.group("available") or 0),
                    "unavailable": int(summary_match.group("unavailable") or 0),
                    "errors": summary_match.group("errors") or "",
                    "last_line": line,
                }
            )
    return progress


def lines_after_marker(lines: list[str], marker: str) -> list[str]:
    start = -1
    for index, line in enumerate(lines):
        if marker in line:
            start = index
    return lines[start:] if start >= 0 else []


def collection_terminal_seen(lines: list[str]) -> bool:
    return any(
        "DONE   collection" in line
        or "BLOCK  campaign failed" in line
        or "BLOCK  campaign not_started" in line
        for line in lines
    )


def action_terminal_seen(lines: list[str]) -> bool:
    return any(
        "DONE   action_submit" in line
        or "DONE   action_preflight" in line
        or "TOUCH  run_completed" in line
        or "BLOCK  action_submit" in line
        or "BLOCK  action_preflight" in line
        or "ERROR  action_preflight" in line
        for line in lines
    )


def terminal_seen(lines: list[str], mode: str) -> bool:
    if any("BLOCK  campaign failed" in line or "BLOCK  campaign not_started" in line for line in lines):
        return True
    if str(mode) == "collect":
        return collection_terminal_seen(lines)
    return collection_terminal_seen(lines) and action_terminal_seen(lines)


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def check_ixbrowser_start_gate() -> dict:
    try:
        from ReachOps.workbench.standalone_app import create_ixbrowser_client, require_ixbrowser_response

        client = create_ixbrowser_client()
        response = require_ixbrowser_response(
            client,
            client.get_group_list(page=1, limit=1),
            "ixbrowser_group_list",
        )
        return {
            "ready": True,
            "base_url": str(getattr(client, "base_url", "")),
            "sample_type": type(response).__name__,
            "no_browser_started": True,
            "no_submit": True,
        }
    except Exception as exc:
        return {
            "ready": False,
            "error": "IXBROWSER_LOCAL_API_UNAVAILABLE",
            "message": str(exc),
            "no_browser_started": True,
            "no_submit": True,
            "next_actions": [
                "确认 ixBrowser 客户端已启动，并开启 Local API。",
                "在 Web UI 点击刷新分组，必须实时读取分组和数量后再开始获客。",
            ],
        }


def apply_execution_plan_to_args(args, execution_plan: dict, *, source: str = "execution_plan") -> dict:
    """Apply the validated ExecutionPlan as the authoritative runtime contract."""
    from ReachOps.execution_plan import build_execution_plan_runtime_contract

    before = {
        "target": str(getattr(args, "target", "")),
        "source_type": str(getattr(args, "source_type", "")),
        "profile_group": str(getattr(args, "profile_group", "")),
        "mode": str(getattr(args, "mode", "")),
        "volume": str(getattr(args, "volume", "")),
        "profile_limit": int(getattr(args, "profile_limit", 0) or 0),
        "max_videos": int(getattr(args, "max_videos", 0) or 0),
        "max_comments": int(getattr(args, "max_comments", 0) or 0),
        "timeout": int(getattr(args, "timeout", 0) or 0),
        "comment_text": str(getattr(args, "comment_text", "") or ""),
        "base_dir": str(getattr(args, "base_dir", "") or ""),
    }
    contract = build_execution_plan_runtime_contract(execution_plan, before, source=source)
    after = contract.get("after") if isinstance(contract.get("after"), dict) else {}
    args.target = str(after.get("target") or "")
    args.source_type = str(after.get("source_type") or "")
    args.profile_group = str(after.get("profile_group") or "")
    args.mode = str(after.get("mode") or "")
    args.volume = str(after.get("volume") or "")
    args.profile_limit = int(after.get("profile_limit") or 0)
    args.max_videos = int(after.get("max_videos") or 0)
    args.max_comments = int(after.get("max_comments") or 0)
    args.timeout = int(after.get("timeout") or 0)
    args.comment_text = str(after.get("comment_text") or "")
    if after.get("base_dir"):
        args.base_dir = str(after.get("base_dir"))
    return contract


def finalize_timeout(app, reason: str = "HEADLESS_TIMEOUT") -> dict:
    batch_id = str(getattr(app, "active_batch_id", "") or "")
    if not batch_id:
        return {"finalized": False, "reason": "no_active_batch"}
    try:
        now = utc_now()
        with app.service.storage.connect() as conn:
            row = conn.execute(
                """
                SELECT id, campaign_id, total_sources, processed_sources, failed_sources, status
                FROM collection_batches
                WHERE id=?
                """,
                (batch_id,),
            ).fetchone()
            if not row:
                return {"finalized": False, "batch_id": batch_id, "reason": "batch_not_found"}
            if str(row["status"] or "") not in {"pending", "running"}:
                return {"finalized": False, "batch_id": batch_id, "reason": f"batch_already_{row['status']}"}
            total = int(row["total_sources"] or 0)
            processed = int(row["processed_sources"] or 0)
            failed = max(int(row["failed_sources"] or 0), max(0, total - processed))
            conn.execute(
                """
                UPDATE collection_tasks
                SET status='failed', error_code=?,
                    error_message='Headless acceptance run timed out before terminal evidence',
                    completed_at=COALESCE(completed_at, ?), updated_at=?
                WHERE batch_id=? AND status IN ('pending', 'running')
                """,
                (reason, now, now, batch_id),
            )
            conn.execute(
                """
                UPDATE collection_batches
                SET status='failed', failed_sources=?, completed_at=COALESCE(completed_at, ?), updated_at=?
                WHERE id=?
                """,
                (failed, now, now, batch_id),
            )
            campaign_id = str(row["campaign_id"] or "")
        app.service.storage.log_event(
            "collection_batch_headless_timeout",
            batch_id,
            {"campaign_id": campaign_id, "reason": reason},
        )
        app._log(
            f"BLOCK  campaign failed batch={batch_id} reason={reason} "
            "next=检查 ixBrowser 本地服务、账号分组和网络后重新复测"
        )
        return {"finalized": True, "batch_id": batch_id, "reason": reason}
    except Exception as exc:
        app._log(f"WARN   headless_timeout_finalize_failed batch={batch_id} error={exc}")
        return {"finalized": False, "batch_id": batch_id, "reason": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ReachOps macOS flow without creating a Tk UI.")
    parser.add_argument("--base-dir", default="reports/reachops/mac_gui/runtime")
    parser.add_argument("--control-dir", default="")
    parser.add_argument("--target", default="https://www.tiktok.com/@aofacore/video/7656416339531205901")
    parser.add_argument("--source-type", default="auto")
    parser.add_argument("--profile-group", default="United States")
    parser.add_argument("--profile-limit", type=int, default=3)
    parser.add_argument("--max-videos", type=int, default=3)
    parser.add_argument("--max-comments", type=int, default=20)
    parser.add_argument("--mode", choices=["preflight", "collect", "live_comment"], default="preflight")
    parser.add_argument("--volume", choices=["quick", "standard", "stress"], default="quick")
    parser.add_argument("--comment-text", default="")
    parser.add_argument("--execution-plan", default="")
    parser.add_argument("--run-session", default="")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    initial_base_dir = Path(args.base_dir)
    if not initial_base_dir.is_absolute():
        initial_base_dir = (ROOT_DIR / initial_base_dir).resolve()
    initial_base_dir.mkdir(parents=True, exist_ok=True)

    execution_plan: dict = {}
    execution_plan_contract: dict = {}
    execution_plan_path = ""
    execution_plan_source = "execution_plan"
    run_session_path = ""
    run_session_latest_path = ""
    if args.execution_plan:
        plan_path = Path(args.execution_plan)
        if not plan_path.is_absolute():
            plan_path = (ROOT_DIR / plan_path).resolve()
        from ReachOps.execution_plan import read_execution_plan

        execution_plan = read_execution_plan(plan_path)
        execution_plan_path = str(plan_path)
        execution_plan_contract = apply_execution_plan_to_args(args, execution_plan, source="execution_plan")
    else:
        from ReachOps.execution_plan import build_execution_plan, write_execution_plan

        execution_plan_source = "cli_synthesized_execution_plan"
        execution_plan = build_execution_plan(
            target=args.target,
            source_type=args.source_type,
            mode=args.mode,
            profile_group=args.profile_group,
            volume=args.volume,
            profile_limit=args.profile_limit,
            max_videos=args.max_videos,
            max_comments=args.max_comments,
            timeout_seconds=args.timeout,
            comment_text=args.comment_text,
            base_dir=str(initial_base_dir),
            origin="headless_cli_synthesized",
        )
        plans_dir = initial_base_dir / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plans_dir / f"{execution_plan.get('plan_id') or 'execution_plan'}.json"
        write_execution_plan(execution_plan, plan_path)
        write_execution_plan(execution_plan, plans_dir / "latest_execution_plan.json")
        execution_plan_path = str(plan_path)
        execution_plan_contract = apply_execution_plan_to_args(
            args,
            execution_plan,
            source=execution_plan_source,
        )

    base_dir = Path(args.base_dir)
    if not base_dir.is_absolute():
        base_dir = (ROOT_DIR / base_dir).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    progress_path = base_dir / "reachops_web_ui_progress.json"
    heartbeat_path = base_dir / "reachops_web_ui_heartbeat.json"
    control_dir = Path(args.control_dir) if str(args.control_dir or "").strip() else base_dir / "control"
    if not control_dir.is_absolute():
        control_dir = (ROOT_DIR / control_dir).resolve()
    control_dir.mkdir(parents=True, exist_ok=True)

    if args.run_session:
        path = Path(args.run_session)
        if not path.is_absolute():
            path = (ROOT_DIR / path).resolve()
        run_session_path = str(path)
        run_session_latest_path = str(path.parent / "latest_run_session.json")
    else:
        from ReachOps.run_session import create_run_session, write_run_session

        runs_dir = base_dir / "runs"
        session = create_run_session(
            execution_plan,
            execution_plan_path=execution_plan_path,
        )
        run_session_path = str(runs_dir / f"{session.get('session_id') or 'run_session'}.json")
        run_session_latest_path = str(runs_dir / "latest_run_session.json")
        write_run_session(session, run_session_path, run_session_latest_path)

    def update_run_session(state: str, **kwargs):
        if not run_session_path:
            return {}
        from ReachOps.run_session import read_run_session, transition_run_session, write_run_session

        session = read_run_session(run_session_path)
        if not session:
            return {}
        updated = transition_run_session(session, state, **kwargs)
        write_run_session(updated, run_session_path, run_session_latest_path)
        return updated

    def write_progress_snapshot(lines: list[str], *, running: bool, last_stage: str = "") -> dict:
        preflight_progress = parse_profile_preflight_progress(lines)
        heartbeat_at = utc_now()
        resolved_last_stage = last_stage or (str(lines[-1]) if lines else "")
        payload = {
            "status": "running" if running else "finalizing",
            "generated_at": heartbeat_at,
            "target": args.target,
            "profile_group": args.profile_group,
            "mode": args.mode,
            "volume": args.volume,
            "execution_plan": {
                "plan_id": execution_plan.get("plan_id", ""),
                "schema_version": execution_plan.get("schema_version", ""),
                "path": execution_plan_path,
                "source": execution_plan_source,
            },
            "run_session": {"path": run_session_path},
            "stage": "profile_preflight" if preflight_progress else ("running" if running else "finalizing"),
            "profile_preflight_progress": preflight_progress,
            "last_stage": resolved_last_stage,
            "tail": lines[-40:],
            "no_submit": args.mode != "live_comment",
            "no_ai_token_used": True,
            "heartbeat": {
                "schema_version": "reachops.runtime_heartbeat.v1",
                "pid": os.getpid(),
                "heartbeat_at": heartbeat_at,
                "monotonic_seconds": round(time.monotonic(), 3),
                "running": bool(running),
                "stage": "profile_preflight" if preflight_progress else ("running" if running else "finalizing"),
                "last_stage": resolved_last_stage[:500],
                "run_session_path": run_session_path,
                "progress_path": str(progress_path),
                "no_ai_token_used": True,
            },
        }
        try:
            write_json_atomic(progress_path, payload)
        except Exception:
            pass
        try:
            write_json_atomic(heartbeat_path, payload["heartbeat"])
        except Exception:
            pass
        return payload

    def update_runtime_checkpoint(lines: list[str], *, running: bool, last_stage: str = "") -> dict:
        if not run_session_path:
            return {}
        from ReachOps.run_session import RUN_SESSION_STATE_RANK, TERMINAL_RUN_SESSION_STATES, infer_run_state, read_run_session

        progress_payload = write_progress_snapshot(lines, running=running, last_stage=last_stage)
        inferred_state = infer_run_state(lines, running=running)
        session = read_run_session(run_session_path)
        current_state = str(session.get("state") or "CREATED")
        if current_state in TERMINAL_RUN_SESSION_STATES:
            return session
        current_rank = RUN_SESSION_STATE_RANK.get(current_state, 0)
        inferred_rank = RUN_SESSION_STATE_RANK.get(inferred_state, 0)
        next_state = inferred_state if inferred_rank >= current_rank else current_state
        last_line = str(lines[-1]) if lines else str(last_stage or "")
        checkpoint_update = {
            "runtime_state_inferred": inferred_state,
            "runtime_state_rank": RUN_SESSION_STATE_RANK.get(next_state, 0),
            "log_line_count": len(lines),
            "last_log_line": last_line[:500],
            "terminal_seen": terminal_seen(lines, args.mode),
            "mode": str(args.mode),
            "running": bool(running),
            "progress_path": str(progress_path),
            "heartbeat_path": str(heartbeat_path),
            "heartbeat_at": str((progress_payload.get("heartbeat") or {}).get("heartbeat_at") or ""),
            "heartbeat_pid": int((progress_payload.get("heartbeat") or {}).get("pid") or 0),
            "heartbeat_age_seconds": 0,
            "profile_preflight_progress": progress_payload.get("profile_preflight_progress") or {},
            "no_ai_token_used": True,
        }
        return update_run_session(
            next_state,
            last_stage=last_stage or last_line,
            checkpoint_update=checkpoint_update,
        )

    def wait_if_cooperatively_paused(deadline: float, *, state: str, last_stage: str) -> None:
        pause_path = control_dir / "pause.request"
        if not pause_path.exists():
            return
        logged = False
        while pause_path.exists() and time.monotonic() < deadline:
            if not logged:
                logged = True
                try:
                    app._log("PAUSE  cooperative_pause_waiting no_ai_token_used=true")
                except Exception:
                    pass
            update_run_session(
                state,
                last_stage=last_stage,
                checkpoint_update={
                    "cooperative_pause_waiting": True,
                    "control_dir": str(control_dir),
                    "no_ai_token_used": True,
                },
                control={"paused": True},
            )
            time.sleep(0.5)
        if logged:
            try:
                app._log("RESUME cooperative_pause_released no_ai_token_used=true")
            except Exception:
                pass
            update_run_session(
                state,
                last_stage="cooperative_pause_released",
                checkpoint_update={
                    "cooperative_pause_waiting": False,
                    "control_dir": str(control_dir),
                    "no_ai_token_used": True,
                },
                control={"paused": False},
            )

    def attach_evidence_bundle(result: dict) -> dict:
        if not run_session_path:
            return result
        try:
            from ReachOps.evidence_bundle import build_evidence_bundle, write_evidence_bundle, write_evidence_markdown

            session_id = Path(run_session_path).stem
            result_reports_dir = Path(args.base_dir) / "run_results"
            result_reports_dir.mkdir(parents=True, exist_ok=True)
            result_artifact_path = result_reports_dir / f"{session_id}.json"
            result_artifact_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            reports_dir = Path(args.base_dir) / "evidence_bundles"
            bundle_path = reports_dir / f"{session_id}.json"
            markdown_path = reports_dir / f"{session_id}.md"
            bundle = build_evidence_bundle(
                base_dir=args.base_dir,
                execution_plan_path=execution_plan_path,
                run_session_path=run_session_path,
                result_path=str(result_artifact_path),
                log_path=str(log_path),
                offline_learning_path=str(Path(args.base_dir) / "offline_learning" / "unknown_states.json"),
            )
            write_evidence_bundle(bundle, bundle_path, reports_dir / "latest_evidence_bundle.json")
            write_evidence_markdown(bundle, markdown_path, reports_dir / "latest_evidence_bundle.md")
            result["evidence_bundle"] = {
                "schema_version": bundle.get("schema_version"),
                "bundle_id": bundle.get("bundle_id"),
                "path": str(bundle_path),
                "markdown_path": str(markdown_path),
                "latest_path": str(reports_dir / "latest_evidence_bundle.json"),
                "latest_markdown_path": str(reports_dir / "latest_evidence_bundle.md"),
                "run_result_path": str(result_artifact_path),
            }
        except Exception as exc:
            result["evidence_bundle"] = {"status": "failed", "error": str(exc)}
        return result

    def finalize_with_evidence_bundle(result: dict, state: str, last_stage: str) -> dict:
        update_run_session(
            state,
            result=result,
            last_stage=last_stage,
        )
        result = attach_evidence_bundle(result)
        update_run_session(
            state,
            result=result,
            last_stage=last_stage,
            evidence=result.get("evidence_bundle") if isinstance(result.get("evidence_bundle"), dict) else None,
        )
        return result

    os.environ["REACHOPS_DATA_DIR"] = str(base_dir)
    existing_no_proxy = [item.strip() for item in str(os.environ.get("NO_PROXY") or "").split(",") if item.strip()]
    for item in ["127.0.0.1", "localhost", "::1"]:
        if item not in existing_no_proxy:
            existing_no_proxy.append(item)
    os.environ["NO_PROXY"] = ",".join(existing_no_proxy)
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    os.environ.setdefault("REACHOPS_IXBROWSER_REFRESH_MAX_PAGES", "1")

    from ReachOps.intelligence import GrowthIntelligenceService
    from ReachOps.runtime_paths import RuntimePaths
    from ReachOps.workbench.standalone_app import GrowthIntelligenceStandaloneApp, StandaloneProfileRegistry
    from ReachOps.workbench.workflow_service import GrowthWorkflowService

    class HeadlessApp(GrowthIntelligenceStandaloneApp):
        def __init__(self, root, base_dir: str):
            self.root = DummyRoot()
            self.paths = RuntimePaths.build(base_dir).ensure_dirs()
            self.base_dir = self.paths.base_dir
            self.auto_refresh_profiles = False
            self.disable_async_group_count_refresh = True
            self.service = GrowthIntelligenceService(base_dir=self.base_dir, logger=self._log)
            self.workflow = GrowthWorkflowService(self.service)
            self.profile_registry = StandaloneProfileRegistry()
            self.profile_group_display_map = {}
            self.status_var = DummyVar("已就绪")
            self.group_var = DummyVar("")
            self.refresh_groups_button = None
            self.active_campaign_id = ""
            self.active_batch_id = ""
            self._collection_start_lock = threading.Lock()
            self._collection_start_in_progress = False
            self._group_count_refresh_in_progress = False
            self._runtime_event_last_rowid = self._current_growth_event_rowid()
            self.runtime_log_path = Path(self.service.paths.logs_dir) / "growth_ops_runtime.log"
            self.console = DummyConsole(args)
            self._log(f"READY  headless_app_started data_dir={self.base_dir} log={self.runtime_log_path}")
            self._cleanup_interrupted_collection_batches()
            self._cleanup_interrupted_action_queue()

        def _schedule_runtime_refresh(self):
            return None

    app = HeadlessApp(DummyRoot(), base_dir=str(base_dir))
    log_path = Path(app.runtime_log_path)
    marker = (
        f"RUN    web_headless_start target={args.target} source_type={args.source_type} "
        f"group={args.profile_group} mode={args.mode} volume={args.volume}"
    )
    app._log(marker)
    update_run_session("PRECHECK", last_stage=marker)
    start_gate = check_ixbrowser_start_gate()
    if not start_gate.get("ready"):
        app._log(
            "BLOCK  campaign not_started reason=IXBROWSER_LOCAL_API_UNAVAILABLE "
            f"error={start_gate.get('message', '')} no_browser_started=true no_submit=true"
        )
        result = {
            "status": "blocked",
            "generated_at": utc_now(),
            "log_path": str(log_path),
            "target": args.target,
            "profile_group": args.profile_group,
            "execution_plan": {
                "plan_id": execution_plan.get("plan_id", ""),
                "schema_version": execution_plan.get("schema_version", ""),
                "path": execution_plan_path,
                "source": execution_plan_source,
            },
            "execution_plan_contract": execution_plan_contract,
            "run_session": {"path": run_session_path},
            "start_gate": start_gate,
            "timeout_finalization": {},
            "tail": lines_after_marker(latest_log_lines(log_path), marker)[-120:],
        }
        result = finalize_with_evidence_bundle(result, "BLOCKED", "IXBROWSER_LOCAL_API_UNAVAILABLE")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(result)
        return 2
    try:
        app.refresh_profile_groups(show_message=False)
    except Exception as exc:
        app._log(f"WARN   headless_refresh_profiles_failed error={exc}")
    app.start_collection_from_console()
    update_run_session("PROFILE_PREFLIGHT", last_stage="headless_profile_preflight_started")

    deadline = time.monotonic() + max(30, int(args.timeout))
    lines: list[str] = []
    while time.monotonic() < deadline:
        wait_if_cooperatively_paused(deadline, state="COLLECTING", last_stage="cooperative_pause_waiting")
        lines = lines_after_marker(latest_log_lines(log_path), marker)
        update_runtime_checkpoint(lines, running=True)
        if terminal_seen(lines, args.mode):
            time.sleep(2)
            lines = lines_after_marker(latest_log_lines(log_path), marker)
            update_runtime_checkpoint(lines, running=False)
            break
        time.sleep(1)

    timed_out = not terminal_seen(lines, args.mode)
    timeout_finalization = finalize_timeout(app) if timed_out else {}
    if timed_out:
        lines = lines_after_marker(latest_log_lines(log_path), marker)
        update_runtime_checkpoint(lines, running=False, last_stage="headless_timeout_finalized")

    result = {
        "status": "completed" if not timed_out else "timeout_finalized",
        "generated_at": utc_now(),
        "log_path": str(log_path),
        "target": args.target,
        "profile_group": args.profile_group,
        "execution_plan": {
            "plan_id": execution_plan.get("plan_id", ""),
            "schema_version": execution_plan.get("schema_version", ""),
            "path": execution_plan_path,
            "source": execution_plan_source,
        },
        "execution_plan_contract": execution_plan_contract,
        "run_session": {"path": run_session_path},
        "timeout_finalization": timeout_finalization,
        "tail": lines[-120:],
    }
    result = finalize_with_evidence_bundle(
        result,
        "COMPLETED" if result["status"] == "completed" else "BLOCKED",
        lines[-1] if lines else result["status"],
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result)
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
