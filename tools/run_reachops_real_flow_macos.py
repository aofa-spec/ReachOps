# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.reachops_run_id import unique_run_dir


DEMO_SCENARIOS = [
    {
        "name": "keyword_product",
        "target": "anti aging serum",
        "source_type": "keyword",
        "description": "产品关键词入口",
    },
    {
        "name": "hashtag_topic",
        "target": "makeupfinds",
        "source_type": "hashtag",
        "description": "TikTok 话题入口",
    },
    {
        "name": "creator_profile",
        "target": "https://www.tiktok.com/@tiktok",
        "source_type": "creator_url",
        "description": "达人主页入口",
    },
    {
        "name": "live_room",
        "target": "https://www.tiktok.com/@tiktok/live",
        "source_type": "live_room_url",
        "description": "直播间入口",
    },
]

EXECUTABLE_SOURCE_TYPES = {"keyword", "hashtag", "creator_url", "content_url", "live_room_url"}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def configure_localhost_proxy_bypass(env: dict[str, str] | None = None) -> dict[str, str]:
    target = dict(os.environ if env is None else env)
    existing = target.get("NO_PROXY") or target.get("no_proxy") or ""
    entries = [item.strip() for item in existing.split(",") if item.strip()]
    for item in ["127.0.0.1", "localhost", "::1"]:
        if item not in entries:
            entries.append(item)
    target["NO_PROXY"] = ",".join(entries)
    target["no_proxy"] = target["NO_PROXY"]
    return target


def safe_name(value: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))
    return text[:80] or "scenario"


def write_json(path: Path, payload: dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json_maybe(path_or_json: str) -> Any:
    text = str(path_or_json or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if path.exists():
        text = path.read_text(encoding="utf-8")
    return json.loads(text)


def scenario_from_source(source: dict[str, Any], index: int) -> dict[str, str] | None:
    source_type = str(source.get("source_type") or source.get("type") or "").strip()
    value = str(source.get("source_value") or source.get("value") or source.get("target") or "").strip()
    if source_type not in EXECUTABLE_SOURCE_TYPES or not value:
        return None
    return {
        "name": f"{index:02d}_{source_type}_{safe_name(value)[:36]}",
        "target": value,
        "source_type": source_type,
        "description": str(source.get("reason") or source.get("description") or "项目配置获客入口"),
    }


def scenario_identity(scenario: dict[str, str]) -> tuple[str, str]:
    return (str(scenario.get("source_type") or "").strip(), str(scenario.get("target") or "").strip())


def creator_url_from_tiktok_url(value: str) -> str:
    try:
        parsed = urlparse(str(value or "").strip())
        host = str(parsed.netloc or "").lower()
        if "tiktok.com" not in host:
            return ""
        for part in [item for item in parsed.path.split("/") if item]:
            if part.startswith("@"):
                return f"https://www.tiktok.com/{part}"
    except Exception:
        return ""
    return ""


def should_expand_related_sources(row: dict[str, Any]) -> bool:
    funnel = row.get("funnel") if isinstance(row.get("funnel"), dict) else {}
    if int(funnel.get("customer_leads") or 0) > 0 or int(funnel.get("outreach_actions") or 0) > 0:
        return False
    no_action = row.get("no_action_reason") if isinstance(row.get("no_action_reason"), dict) else {}
    code = str(no_action.get("code") or "").strip()
    diagnosis = str(row.get("diagnosis_status") or "").strip()
    return code in {"low_intent_candidates", "no_candidates"} or diagnosis in {
        "comment_users_found",
        "content_found_no_comments",
        "opened_but_no_results",
    }


def related_source_expansions(scenario: dict[str, str], next_index: int) -> list[dict[str, str]]:
    if str(scenario.get("source_type") or "").strip() != "content_url":
        return []
    target = str(scenario.get("target") or "").strip()
    creator_url = creator_url_from_tiktok_url(target)
    if not creator_url or creator_url == target:
        return []
    return [
        {
            "name": f"{next_index:02d}_creator_url_{safe_name(creator_url)[:36]}",
            "target": creator_url,
            "source_type": "creator_url",
            "description": "自动扩展：content_url 低意向或无候选后，回退到同达人主页继续 no-submit 采集。",
        }
    ]


def append_related_source_expansions(
    scenarios: list[dict[str, str]],
    scenario: dict[str, str],
    final_row: dict[str, Any],
    scenario_plan: dict[str, Any],
    max_sources: int,
) -> list[dict[str, str]]:
    if not should_expand_related_sources(final_row):
        return []
    max_total = max(1, int(max_sources or 1))
    if len(scenarios) >= max_total:
        return []
    existing = {scenario_identity(item) for item in scenarios}
    appended: list[dict[str, str]] = []
    for expansion in related_source_expansions(scenario, len(scenarios) + 1):
        if len(scenarios) >= max_total:
            break
        if scenario_identity(expansion) in existing:
            continue
        scenarios.append(expansion)
        existing.add(scenario_identity(expansion))
        appended.append(expansion)
    if appended:
        auto_expansions = scenario_plan.setdefault("auto_expansions", [])
        no_action = final_row.get("no_action_reason") if isinstance(final_row.get("no_action_reason"), dict) else {}
        for expansion in appended:
            auto_expansions.append(
                {
                    "from": list(scenario_identity(scenario)),
                    "to": list(scenario_identity(expansion)),
                    "reason": str(no_action.get("code") or final_row.get("diagnosis_status") or ""),
                }
            )
        scenario_plan["auto_expanded_source_count"] = len(auto_expansions)
    return appended


def build_scenarios(args: argparse.Namespace, run_dir: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    scenarios: list[dict[str, str]] = []
    metadata: dict[str, Any] = {
        "source": "",
        "target": str(args.target or ""),
        "include_demo_scenarios": bool(args.include_demo_scenarios),
    }
    if str(args.scenarios_json or "").strip():
        raw = read_json_maybe(str(args.scenarios_json or ""))
        rows = raw.get("scenarios") if isinstance(raw, dict) else raw
        for index, row in enumerate(rows or [], start=1):
            if isinstance(row, dict):
                scenario = scenario_from_source(row, index)
                if scenario:
                    scenarios.append(scenario)
        metadata["source"] = "scenarios_json"
        metadata["raw_count"] = len(rows or [])
    elif str(args.target or "").strip():
        from ReachOps.intelligence import GrowthIntelligenceService

        plan_base = run_dir / "planned_campaign"
        service = GrowthIntelligenceService(str(plan_base))
        plan = service.create_campaign_plan(
            str(args.target or ""),
            max_sources=max(1, int(args.max_sources or 1)),
        )
        rows = list(plan.get("sources") or [])
        for index, row in enumerate(rows, start=1):
            scenario = scenario_from_source(row, index)
            if scenario:
                scenarios.append(scenario)
        metadata.update(
            {
                "source": "project_source_planner",
                "campaign": plan.get("campaign") or {},
                "planned_source_count": len(rows),
                "executable_source_count": len(scenarios),
                "non_executable_sources": [
                    {
                        "source_type": row.get("source_type") or row.get("type") or "",
                        "source_value": row.get("source_value") or row.get("value") or "",
                    }
                    for row in rows
                    if not scenario_from_source(row, 0)
                ],
            }
        )
    if args.include_demo_scenarios:
        scenarios.extend(DEMO_SCENARIOS)
        metadata["source"] = (metadata.get("source") or "none") + "+demo"
    return scenarios, metadata


def load_launch_ledger(base_dir: Path) -> tuple[Path, dict[str, Any]]:
    day = datetime.now().strftime("%Y%m%d")
    path = base_dir / "profile_launch_ledger" / f"{day}.json"
    if not path.exists():
        return path, {"date": day, "profiles": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload.setdefault("date", day)
            payload.setdefault("profiles", {})
            return path, payload
    except Exception:
        pass
    return path, {"date": day, "profiles": {}}


def save_launch_ledger(path: Path, ledger: dict[str, Any]):
    write_json(path, ledger)


def daily_launch_count(ledger: dict[str, Any], profile_id: str) -> int:
    profiles = ledger.get("profiles") if isinstance(ledger.get("profiles"), dict) else {}
    row = profiles.get(str(profile_id)) if isinstance(profiles.get(str(profile_id)), dict) else {}
    return int(row.get("launch_count") or 0)


def record_profile_launches(ledger: dict[str, Any], profile_ids: list[str]):
    profiles = ledger.setdefault("profiles", {})
    for profile_id in profile_ids:
        key = str(profile_id)
        row = profiles.setdefault(key, {"launch_count": 0, "first_seen": utc_stamp(), "last_seen": ""})
        row["launch_count"] = int(row.get("launch_count") or 0) + 1
        row["last_seen"] = utc_stamp()


def select_profiles(args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    explicit = [item.strip() for item in str(args.profile_ids or "").replace("，", ",").split(",") if item.strip()]
    if explicit:
        scan_limit = max(1, int(args.profile_scan_limit or args.profile_limit or 1))
        return {
            "status": "explicit",
            "ids": explicit[:scan_limit],
            "source": "profile_ids",
            "group_name": str(args.profile_group or ""),
            "scan_limit": scan_limit,
            "group_id": None,
            "api_code": None,
            "api_message": "",
            "total": len(explicit),
            "error": "",
        }
    selection: dict[str, Any] = {
        "status": "failed",
        "ids": [],
        "source": "ixbrowser_group",
        "group_name": str(args.profile_group or ""),
        "scan_limit": max(1, int(args.profile_scan_limit or args.profile_limit or 1)),
        "group_id": None,
        "api_code": None,
        "api_message": "",
        "total": 0,
        "error": "",
    }
    try:
        from ixbrowser_local_api import IXBrowserClient

        old_env = dict(os.environ)
        os.environ.update(env)
        try:
            client = IXBrowserClient()
            wanted = str(args.profile_group or "").strip().lower()
            group_id = 0
            for page in range(1, 101):
                groups = client.get_group_list(page=page, limit=100) or []
                for group in groups:
                    title = str(group.get("title") or group.get("group_name") or group.get("name") or "").strip()
                    if title.lower() == wanted:
                        group_id = int(group.get("id") or 0)
                        break
                if group_id or len(groups) < 100:
                    break
            selection["group_id"] = group_id or None
            selection["api_code"] = getattr(client, "code", None)
            selection["api_message"] = str(getattr(client, "message", "") or "")
            selection["total"] = int(getattr(client, "total", 0) or 0)
            if not group_id:
                selection["status"] = "group_not_found"
                selection["error"] = f"profile group not found: {args.profile_group}"
                return selection
            scan_limit = max(1, int(args.profile_scan_limit or args.profile_limit or 1))
            rows = []
            errors = []
            for attempt in range(1, 4):
                rows = client.get_profile_list(group_id=group_id, page=1, limit=min(100, scan_limit)) or []
                selection["api_code"] = getattr(client, "code", None)
                selection["api_message"] = str(getattr(client, "message", "") or "")
                selection["total"] = int(getattr(client, "total", 0) or 0)
                if rows:
                    break
                error = {
                    "attempt": attempt,
                    "api_code": selection["api_code"],
                    "api_message": selection["api_message"],
                    "total": selection["total"],
                }
                errors.append(error)
                time.sleep(min(5, attempt * 2))
            selection["selection_attempts"] = errors
            selection["ids"] = [
                str(row.get("profile_id") or row.get("id") or "")
                for row in rows
                if str(row.get("profile_id") or row.get("id") or "").isdigit()
            ][:scan_limit]
            selection["status"] = "ok" if selection["ids"] else "empty"
            if not selection["ids"]:
                selection["error"] = "profile group returned no usable profile ids"
            return selection
        finally:
            os.environ.clear()
            os.environ.update(old_env)
    except Exception as exc:
        selection["error"] = f"{type(exc).__name__}: {exc}"
        return selection


def selected_profile_ids(args: argparse.Namespace, env: dict[str, str]) -> list[str]:
    return list(select_profiles(args, env).get("ids") or [])


def close_profiles(profile_ids: list[str], env: dict[str, str]) -> list[dict[str, Any]]:
    if not profile_ids:
        return []
    results: list[dict[str, Any]] = []
    try:
        from ixbrowser_local_api import IXBrowserClient

        old_env = dict(os.environ)
        os.environ.update(env)
        try:
            client = IXBrowserClient()
            for profile_id in profile_ids:
                try:
                    result = client.close_profile(int(profile_id))
                    results.append(
                        {
                            "profile_id": str(profile_id),
                            "closed": bool(result),
                            "code": getattr(client, "code", None),
                            "message": str(getattr(client, "message", "") or ""),
                        }
                    )
                except Exception as exc:
                    results.append({"profile_id": str(profile_id), "closed": False, "error": f"{type(exc).__name__}: {exc}"})
        finally:
            os.environ.clear()
            os.environ.update(old_env)
    except Exception as exc:
        results.append({"profile_id": "", "closed": False, "error": f"{type(exc).__name__}: {exc}"})
    return results


def quarantine_profiles(
    profile_ids: list[str],
    env: dict[str, str],
    reason: str,
    reasons_by_profile: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    ids = [str(profile_id).strip() for profile_id in profile_ids if str(profile_id).strip().isdigit()]
    if not ids:
        return []
    results: list[dict[str, Any]] = []
    try:
        from ReachOps.adapters.ix_profile_group_manager import IxProfileGroupManager

        old_env = dict(os.environ)
        os.environ.update(env)
        try:
            manager = IxProfileGroupManager()
            for profile_id in ids:
                profile_reason = str((reasons_by_profile or {}).get(profile_id) or reason or "runtime_blocked")
                try:
                    result = manager.move_profile_to_quarantine(profile_id, reason=profile_reason)
                    results.append(
                        {
                            "profile_id": profile_id,
                            "attempted": True,
                            "ok": bool(result.ok),
                            "group_id": result.group_id,
                            "group_name": result.group_name,
                            "reason": profile_reason,
                            "error_code": result.error_code,
                            "error_message": result.error_message,
                        }
                    )
                except Exception as exc:
                    results.append(
                        {
                            "profile_id": profile_id,
                            "attempted": True,
                            "ok": False,
                            "group_id": "",
                            "group_name": "",
                            "reason": profile_reason,
                            "error_code": "IX_PROFILE_GROUP_MOVE_FAILED",
                            "error_message": f"{type(exc).__name__}: {exc}",
                        }
                    )
        finally:
            os.environ.clear()
            os.environ.update(old_env)
    except Exception as exc:
        results.append(
            {
                "profile_id": "",
                "attempted": False,
                "ok": False,
                "group_id": "",
                "group_name": "",
                "reason": reason,
                "error_code": "IX_PROFILE_GROUP_MANAGER_UNAVAILABLE",
                "error_message": f"{type(exc).__name__}: {exc}",
            }
        )
    return results


def extract_json(stdout: str, stderr: str) -> dict[str, Any]:
    for source in [stdout, stderr]:
        lines = [line.strip() for line in str(source or "").splitlines() if line.strip()]
        for line in reversed(lines):
            if not line.startswith("{"):
                continue
            try:
                value = json.loads(line)
            except Exception:
                continue
            if isinstance(value, dict):
                return value
    return {}


def scenario_command(args: argparse.Namespace, scenario: dict[str, str], scenario_dir: Path) -> list[str]:
    command = [
        sys.executable,
        "tools/reachops_visual_collection_preflight.py",
        "--base-dir",
        str(scenario_dir),
        "--state-dir",
        str(args.state_dir or ""),
        "--target",
        scenario["target"],
        "--source-type",
        scenario["source_type"],
        "--profile-group",
        str(args.profile_group or ""),
        "--profile-limit",
        str(max(1, int(args.profile_limit or 1))),
        "--max-videos",
        str(max(1, int(args.max_videos or 1))),
        "--max-comments",
        str(max(1, int(args.max_comments or 1))),
        "--profile-page-timeout",
        str(max(1, int(args.profile_page_timeout or 20))),
        "--profile-preflight-timeout",
        str(max(0, int(args.profile_preflight_timeout or 0))),
        "--allow-fail",
        "--json",
    ]
    if str(args.profile_ids or "").strip():
        command.extend(["--profile-ids", str(args.profile_ids or "")])
    if args.skip_profile_preflight:
        command.append("--skip-profile-preflight")
    if args.quarantine_failed_profiles:
        command.append("--quarantine-failed-profiles")
    if args.no_quarantine_failed_profiles:
        command.append("--no-quarantine-failed-profiles")
    if args.accept_low_intent_actions:
        command.append("--accept-low-intent-actions")
    return command


def summarize_scenario(name: str, payload: dict[str, Any], returncode: int, stdout: str, stderr: str) -> dict[str, Any]:
    diagnosis = payload.get("operator_diagnosis") if isinstance(payload.get("operator_diagnosis"), dict) else {}
    funnel = payload.get("funnel") if isinstance(payload.get("funnel"), dict) else {}
    profile_preflight = payload.get("profile_preflight") if isinstance(payload.get("profile_preflight"), dict) else {}
    no_action_reason = payload.get("no_action_reason") if isinstance(payload.get("no_action_reason"), dict) else {}
    duplicate_suppression = payload.get("duplicate_suppression") if isinstance(payload.get("duplicate_suppression"), dict) else {}
    return {
        "name": name,
        "returncode": returncode,
        "status": str(payload.get("status") or "error"),
        "failures": list(payload.get("failures") or []),
        "diagnosis_status": str(diagnosis.get("status") or ""),
        "next_action": str(diagnosis.get("next_action") or ""),
        "browser_started": int(payload.get("browser_started") or 0),
        "browser_error_classes": diagnosis.get("browser_error_classes") or {},
        "profile_preflight": {
            "skipped": bool(profile_preflight.get("skipped")),
            "checked": int(profile_preflight.get("checked") or 0),
            "available": int(profile_preflight.get("available") or 0),
            "unavailable": int(profile_preflight.get("unavailable") or 0),
        },
        "funnel": {
            "target_sources": int(funnel.get("target_sources") or 0),
            "content_found": int(funnel.get("content_found") or 0),
            "comment_users": int(funnel.get("comment_users") or 0),
            "customer_leads": int(funnel.get("customer_leads") or 0),
            "outreach_actions": int(funnel.get("outreach_actions") or 0),
        },
        "no_action_reason": no_action_reason,
        "duplicate_suppression": duplicate_suppression,
        "report_path": str(payload.get("report_path") or ""),
        "stdout_lines": len((stdout or "").splitlines()),
        "stderr_lines": len((stderr or "").splitlines()),
    }


def run_command_with_timeout(command: list[str], env: dict[str, str], timeout_seconds: int) -> tuple[int, str, str, bool]:
    proc = subprocess.Popen(
        command,
        cwd=str(ROOT_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=max(1, int(timeout_seconds or 1)))
        return int(proc.returncode or 0), stdout or "", stderr or "", False
    except KeyboardInterrupt:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            proc.terminate()
        try:
            proc.communicate(timeout=5)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                proc.kill()
        raise
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            proc.terminate()
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                proc.kill()
            stdout, stderr = proc.communicate()
        timeout_message = f"scenario exceeded {max(1, int(timeout_seconds or 1))}s and was terminated"
        stderr = "\n".join([item for item in [stderr or "", timeout_message] if item])
        return int(proc.returncode or 124), stdout or "", stderr, True


def acceptance(summary_rows: list[dict[str, Any]]) -> dict[str, Any]:
    no_interruptions = not any("operator_interrupted" in set(row.get("failures") or []) for row in summary_rows)
    any_profile_available = any((row.get("profile_preflight") or {}).get("available", 0) > 0 for row in summary_rows)
    any_browser_started = any(int(row.get("browser_started") or 0) > 0 for row in summary_rows)
    any_duplicate_suppressed = any(bool((row.get("duplicate_suppression") or {}).get("duplicate_suppressed")) for row in summary_rows)
    any_collection_completed = any(
        str(row.get("status") or "") == "ok"
        and (
            int(((row.get("funnel") or {}).get("comment_users") or 0)) > 0
            or bool((row.get("duplicate_suppression") or {}).get("duplicate_suppressed"))
        )
        for row in summary_rows
    )
    any_leads = any(
        int(((row.get("funnel") or {}).get("customer_leads") or 0)) > 0
        or int(((row.get("funnel") or {}).get("outreach_actions") or 0)) > 0
        or bool((row.get("duplicate_suppression") or {}).get("duplicate_suppressed"))
        for row in summary_rows
    )
    no_action_reasons = [
        row.get("no_action_reason")
        for row in summary_rows
        if isinstance(row.get("no_action_reason"), dict) and str((row.get("no_action_reason") or {}).get("code") or "").strip()
    ]
    all_no_submit = True
    result = {
        "status": "passed" if no_interruptions and any_browser_started and any_collection_completed and any_leads else "blocked",
        "no_submit": all_no_submit,
        "targets": [
            {
                "name": "no_operator_interruption",
                "passed": no_interruptions,
                "goal": "整轮验收未被人工/程序中断。",
            },
            {
                "name": "profile_preflight_available",
                "passed": any_profile_available,
                "goal": "至少 1 个 ixBrowser profile 通过登录态/页面预检。",
            },
            {
                "name": "browser_started",
                "passed": any_browser_started,
                "goal": "至少 1 个 profile 成功启动并生成截图证据。",
            },
            {
                "name": "collection_completed",
                "passed": any_collection_completed,
                "goal": "至少 1 条真实入口完成评论用户采集任务。",
            },
            {
                "name": "lead_pipeline",
                "passed": any_leads,
                "goal": "真实采集后产生 customer_leads/outreach_actions，或对重复目标明确跳过重复动作生成。",
            },
        ],
    }
    if any_duplicate_suppressed:
        result["duplicate_suppression"] = {
            "passed": True,
            "goal": "同一目标重复运行不会无限重复生成相同线索或动作。",
        }
    if no_action_reasons and not any_leads:
        result["no_action_reason"] = no_action_reasons[0]
    return result


UNAVAILABLE_PROFILE_ERROR_CODES = {
    "LOGIN_REQUIRED",
    "CAPTCHA_DETECTED",
    "PROXY_FAILED",
    "COMMENT_ACCESS_GATED",
    "PROFILE_START_FAILED",
    "PROFILE_PREFLIGHT_TIMEOUT",
    "PAGE_OPEN_FAILED",
    "PAGE_TIMEOUT",
}


def unavailable_profile_ids(payload: dict[str, Any]) -> set[str]:
    return set(unavailable_profile_reasons(payload))


def unavailable_profile_reasons(payload: dict[str, Any]) -> dict[str, str]:
    profile_preflight = payload.get("profile_preflight") if isinstance(payload.get("profile_preflight"), dict) else {}
    blocked: dict[str, str] = {}
    for row in profile_preflight.get("results") or []:
        if not isinstance(row, dict) or row.get("ok"):
            continue
        code = str(row.get("error_code") or "")
        if code in UNAVAILABLE_PROFILE_ERROR_CODES:
            profile_id = str(row.get("profile_id") or "")
            if profile_id:
                blocked[profile_id] = code
    for row in payload.get("profile_attempts") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("error_code") or "")
        if code in UNAVAILABLE_PROFILE_ERROR_CODES:
            profile_id = str(row.get("profile_id") or "")
            if profile_id:
                blocked.setdefault(profile_id, code)
    return blocked


def scenario_should_retry(row: dict[str, Any], blocked_ids: set[str], attempted_ids: list[str]) -> bool:
    funnel = row.get("funnel") if isinstance(row.get("funnel"), dict) else {}
    if str(row.get("status") or "") == "ok":
        return int(funnel.get("customer_leads") or 0) <= 0 and int(funnel.get("outreach_actions") or 0) <= 0
    diagnosis = str(row.get("diagnosis_status") or "")
    failures = set(row.get("failures") or [])
    if diagnosis in {"no_logged_in_profile_available", "comment_access_gated"}:
        return True
    if diagnosis in {"content_found_no_comments", "opened_but_no_results"}:
        return True
    if diagnosis == "scenario_timeout" or "scenario_timeout" in failures:
        return True
    if not blocked_ids:
        return False
    if "no_logged_in_profile_available" in failures or "collection_not_completed" in failures:
        return bool(set(attempted_ids).issubset(blocked_ids))
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ReachOps real macOS browser flow across multiple TikTok entry types.")
    parser.add_argument("--base-dir", default="reports/reachops/mac_real_flow")
    parser.add_argument("--state-dir", default="", help="Persistent Growth Intelligence state dir. Defaults to <base-dir>/runtime_state.")
    parser.add_argument("--profile-group", default="United States")
    parser.add_argument("--profile-ids", default="")
    parser.add_argument("--profile-limit", type=int, default=2)
    parser.add_argument("--profile-scan-limit", type=int, default=20)
    parser.add_argument("--max-attempt-batches", type=int, default=2)
    parser.add_argument("--max-videos", type=int, default=1)
    parser.add_argument("--max-comments", type=int, default=5)
    parser.add_argument("--profile-page-timeout", type=int, default=20)
    parser.add_argument("--profile-preflight-timeout", type=int, default=25)
    parser.add_argument("--scenario-timeout", type=int, default=180)
    parser.add_argument("--target", default="", help="正式验收推广目标；只作为规划输入，采集入口由项目 source planner 生成。")
    parser.add_argument("--max-sources", type=int, default=3)
    parser.add_argument("--scenarios-json", default="", help="显式 TikTok 获客入口 JSON 或 JSON 文件路径。")
    parser.add_argument("--include-demo-scenarios", action="store_true", help="显式允许运行内置 demo 场景。正式验收默认关闭。")
    parser.add_argument("--max-profile-uses-per-run", type=int, default=3)
    parser.add_argument("--max-profile-launches-per-day", type=int, default=6)
    parser.add_argument("--skip-profile-preflight", action="store_true")
    parser.add_argument("--quarantine-failed-profiles", action="store_true")
    parser.add_argument("--no-quarantine-failed-profiles", action="store_true", help="Deprecated no-op; failed profiles are not moved unless --quarantine-failed-profiles is set.")
    parser.add_argument(
        "--accept-low-intent-actions",
        action="store_true",
        help="Acceptance-only mode: create pending-review comment actions for low-intent engaged commenters without submitting.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = Path(args.base_dir).resolve()
    if not str(args.state_dir or "").strip():
        args.state_dir = str(base_dir / "runtime_state")
    else:
        args.state_dir = str(Path(args.state_dir).resolve())
    run_id, run_dir = unique_run_dir(base_dir)
    env = configure_localhost_proxy_bypass()
    scenarios, scenario_plan = build_scenarios(args, run_dir)
    ledger_path, launch_ledger = load_launch_ledger(base_dir)
    profile_selection = select_profiles(args, env)
    fixed_profile_ids = list(profile_selection.get("ids") or [])
    candidate_profile_ids = list(fixed_profile_ids)
    blocked_profile_ids: set[str] = set()
    usable_profile_ids: list[str] = []
    profile_use_counts: dict[str, int] = {}
    summary_rows = []
    scenario_details = []
    interrupted = False
    try:
        scenario_iterable = list(scenarios)
        if not scenario_iterable:
            summary_rows.append(
                {
                    "name": "no_formal_scenarios",
                    "returncode": 2,
                    "status": "failed",
                    "failures": ["no_formal_scenarios"],
                    "diagnosis_status": "no_formal_scenarios",
                    "next_action": "正式验收未提供 --target 或 --scenarios-json；已停止，避免运行 demo 产品页/产品词消耗账号启动额度。",
                    "browser_started": 0,
                    "browser_error_classes": {},
                    "profile_preflight": {"skipped": True, "checked": 0, "available": 0, "unavailable": 0},
                    "funnel": {"target_sources": 0, "content_found": 0, "comment_users": 0, "customer_leads": 0, "outreach_actions": 0},
                    "report_path": "",
                    "stdout_lines": 0,
                    "stderr_lines": 0,
                    "description": "formal scenarios required",
                    "target": "",
                    "source_type": "",
                    "started_at": utc_stamp(),
                    "finished_at": utc_stamp(),
                    "cleanup": [],
                    "attempts": [],
                    "global_blocked_profile_ids": sorted(blocked_profile_ids),
                }
            )
            scenario_details.append({"scenario": {"name": "no_formal_scenarios"}, "attempts": [], "summary": summary_rows[-1]})
        scenario_index = 0
        while scenario_index < len(scenario_iterable):
            scenario = scenario_iterable[scenario_index]
            scenario_index += 1
            scenario_dir = run_dir / safe_name(scenario["name"])
            scenario_attempts = []
            final_row = None
            scenario_attempted_profile_ids: set[str] = set()
            while True:
                max_batches = max(1, int(args.max_attempt_batches or 1))
                if len(scenario_attempts) >= max_batches:
                    break
                reusable_ids = [
                    profile_id
                    for profile_id in usable_profile_ids
                    if profile_id not in blocked_profile_ids
                ]
                fresh_ids = [
                    profile_id
                    for profile_id in candidate_profile_ids
                    if profile_id not in blocked_profile_ids
                    and profile_id not in scenario_attempted_profile_ids
                    and profile_id not in reusable_ids
                ]
                max_run_uses = max(1, int(args.max_profile_uses_per_run or 1))
                max_daily_launches = max(0, int(args.max_profile_launches_per_day or 0))
                batch_source = [
                    profile_id
                    for profile_id in reusable_ids + fresh_ids
                    if int(profile_use_counts.get(profile_id, 0) or 0) < max_run_uses
                    and (max_daily_launches <= 0 or daily_launch_count(launch_ledger, profile_id) < max_daily_launches)
                ]
                batch_ids = batch_source[: max(1, int(args.profile_limit or 1))]
                if not batch_ids:
                    break
                for profile_id in batch_ids:
                    profile_use_counts[profile_id] = int(profile_use_counts.get(profile_id, 0) or 0) + 1
                record_profile_launches(launch_ledger, batch_ids)
                save_launch_ledger(ledger_path, launch_ledger)
                command_args = argparse.Namespace(**vars(args))
                command_args.profile_ids = ",".join(batch_ids)
                command = scenario_command(command_args, scenario, scenario_dir / f"attempt_{len(scenario_attempts) + 1:02d}")
                started_at = utc_stamp()
                try:
                    returncode, stdout, stderr, timed_out = run_command_with_timeout(command, env, int(args.scenario_timeout or 180))
                except KeyboardInterrupt:
                    close_profiles(batch_ids, env)
                    raise
                cleanup = close_profiles(batch_ids, env)
                scenario_attempted_profile_ids.update(batch_ids)
                payload = extract_json(stdout, stderr)
                if timed_out and not payload:
                    payload = {
                        "status": "failed",
                        "failures": ["scenario_timeout"],
                        "operator_diagnosis": {
                            "status": "scenario_timeout",
                            "next_action": "单入口执行超时；检查 ixBrowser profile 启动、页面加载或 Selenium 会话清理。",
                        },
                    }
                row = summarize_scenario(scenario["name"], payload, returncode, stdout, stderr)
                blocked_reasons = unavailable_profile_reasons(payload)
                blocked_ids = set(blocked_reasons)
                if timed_out:
                    blocked_ids.update(str(profile_id) for profile_id in batch_ids)
                    for profile_id in batch_ids:
                        blocked_reasons.setdefault(str(profile_id), "scenario_timeout")
                blocked_profile_ids.update(blocked_ids)
                usable_profile_ids = [profile_id for profile_id in usable_profile_ids if profile_id not in blocked_profile_ids]
                quarantine = (
                    quarantine_profiles(
                        sorted(blocked_ids),
                        env,
                        row.get("diagnosis_status") or "runtime_blocked",
                        reasons_by_profile=blocked_reasons,
                    )
                    if bool(args.quarantine_failed_profiles)
                    else [
                        {
                            "profile_id": profile_id,
                            "attempted": False,
                            "ok": False,
                            "group_id": "",
                            "group_name": "",
                            "reason": str(blocked_reasons.get(profile_id) or row.get("diagnosis_status") or "runtime_blocked"),
                            "error_code": "REMOTE_GROUP_UPDATE_DISABLED",
                            "error_message": "remote ixBrowser group update requires --quarantine-failed-profiles",
                        }
                        for profile_id in sorted(blocked_ids)
                    ]
                )
                preflight = payload.get("profile_preflight") if isinstance(payload.get("profile_preflight"), dict) else {}
                ok_ids = [
                    str(item.get("profile_id") or "")
                    for item in preflight.get("results") or []
                    if isinstance(item, dict) and item.get("ok") and str(item.get("profile_id") or "")
                ]
                for profile_id in ok_ids:
                    if profile_id not in usable_profile_ids and profile_id not in blocked_profile_ids:
                        usable_profile_ids.append(profile_id)
                row["attempt_index"] = len(scenario_attempts) + 1
                row["attempted_profile_ids"] = batch_ids
                row["profile_use_counts"] = dict(profile_use_counts)
                row["daily_launch_counts"] = {profile_id: daily_launch_count(launch_ledger, profile_id) for profile_id in batch_ids}
                row["usable_profile_ids_after"] = list(usable_profile_ids)
                row["blocked_profile_ids"] = sorted(blocked_ids)
                row["global_blocked_profile_ids"] = sorted(blocked_profile_ids)
                if timed_out and "scenario_timeout" not in row["failures"]:
                    row["failures"].append("scenario_timeout")
                    row["diagnosis_status"] = row["diagnosis_status"] or "scenario_timeout"
                row["description"] = scenario["description"]
                row["target"] = scenario["target"]
                row["source_type"] = scenario["source_type"]
                row["started_at"] = started_at
                row["finished_at"] = utc_stamp()
                row["cleanup"] = cleanup
                row["quarantine"] = quarantine
                scenario_attempts.append({"command": command, "summary": dict(row)})
                final_row = dict(row)
                if not scenario_should_retry(row, blocked_ids, batch_ids):
                    break
            if final_row is None:
                row = {
                    "name": scenario["name"],
                    "returncode": 2,
                    "status": "failed",
                    "failures": ["no_usable_profile_remaining"],
                    "diagnosis_status": "no_usable_profile_remaining",
                    "next_action": "已扫描候选账号池，或候选账号已达到本轮/每日启动预算，停止后续入口以避免超额消耗账号资源。",
                    "browser_started": 0,
                    "browser_error_classes": {},
                    "profile_preflight": {"skipped": True, "checked": 0, "available": 0, "unavailable": 0},
                    "funnel": {"target_sources": 0, "content_found": 0, "comment_users": 0, "customer_leads": 0, "outreach_actions": 0},
                    "report_path": "",
                    "stdout_lines": 0,
                    "stderr_lines": 0,
                    "description": scenario["description"],
                    "target": scenario["target"],
                    "source_type": scenario["source_type"],
                    "started_at": utc_stamp(),
                    "finished_at": utc_stamp(),
                    "cleanup": [],
                    "attempts": [],
                    "profile_use_counts": dict(profile_use_counts),
                    "global_blocked_profile_ids": sorted(blocked_profile_ids),
                }
                summary_rows.append(row)
                scenario_details.append({"scenario": scenario, "command": [], "summary": row})
                append_related_source_expansions(
                    scenario_iterable,
                    scenario,
                    row,
                    scenario_plan,
                    max(1, int(args.max_sources or 1)),
                )
                continue
            final_row["attempts"] = [dict(attempt["summary"]) for attempt in scenario_attempts]
            summary_rows.append(final_row)
            scenario_details.append({"scenario": scenario, "attempts": scenario_attempts, "summary": final_row})
            append_related_source_expansions(
                scenario_iterable,
                scenario,
                final_row,
                scenario_plan,
                max(1, int(args.max_sources or 1)),
            )
    except KeyboardInterrupt:
        interrupted = True
        summary_rows.append(
            {
                "name": "interrupted",
                "returncode": 130,
                "status": "failed",
                "failures": ["operator_interrupted"],
                "diagnosis_status": "operator_interrupted",
                "next_action": "压测被中断；已写入当前已完成场景的总报告，确认无残留浏览器后可续跑。",
                "browser_started": 0,
                "browser_error_classes": {},
                "profile_preflight": {"skipped": True, "checked": 0, "available": 0, "unavailable": 0},
                "funnel": {"target_sources": 0, "content_found": 0, "comment_users": 0, "customer_leads": 0, "outreach_actions": 0},
                "report_path": "",
                "stdout_lines": 0,
                "stderr_lines": 0,
                "description": "operator interrupted run",
                "target": "",
                "source_type": "",
                "started_at": utc_stamp(),
                "finished_at": utc_stamp(),
                "cleanup": [],
                "attempts": [],
                "global_blocked_profile_ids": sorted(blocked_profile_ids),
            }
        )
        scenario_details.append({"scenario": {"name": "interrupted"}, "attempts": [], "summary": summary_rows[-1]})
    report = {
        "status": "completed",
        "generated_at": utc_stamp(),
        "run_id": run_id,
        "mode": "mac_real_browser_flow_no_submit",
        "no_submit": True,
        "profile_group": str(args.profile_group or ""),
        "state_dir": str(args.state_dir or ""),
        "selected_profile_ids": fixed_profile_ids,
        "profile_selection": profile_selection,
        "scenario_plan": scenario_plan,
        "usable_profile_ids": usable_profile_ids,
        "blocked_profile_ids": sorted(blocked_profile_ids),
        "profile_use_counts": profile_use_counts,
        "profile_launch_budget": {
            "ledger_path": str(ledger_path),
            "max_profile_uses_per_run": max(1, int(args.max_profile_uses_per_run or 1)),
            "max_profile_launches_per_day": max(0, int(args.max_profile_launches_per_day or 0)),
            "daily_counts": {
                profile_id: daily_launch_count(launch_ledger, profile_id)
                for profile_id in sorted(set(fixed_profile_ids) | set(profile_use_counts))
            },
        },
        "profile_ids_filter": str(args.profile_ids or ""),
        "scenario_count": len(summary_rows),
        "scenarios": summary_rows,
        "acceptance": acceptance(summary_rows),
        "details": scenario_details,
        "operator_next_steps": [
            "先修复 acceptance.targets 中未通过项对应的 ixBrowser 内核、代理或登录态问题。",
            "至少 1 个入口达到 collection_completed 后，再进入 live readiness/preflight。",
            "评论/关注/私信真实提交必须额外满足激活状态、授权目标确认和截图证据校验。",
        ],
    }
    report_path = run_dir / "reachops_mac_real_flow_report.json"
    report["report_path"] = str(report_path)
    write_json(report_path, report)
    print(json.dumps(report if args.json else {k: v for k, v in report.items() if k != "details"}, ensure_ascii=False, separators=(",", ":") if args.json else None, indent=None if args.json else 2))
    return 0 if report["acceptance"]["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
