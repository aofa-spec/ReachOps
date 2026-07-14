# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.reachops_client_acceptance_status import DEFAULT_BASE_DIR


DEFAULT_PLAN_PATH = DEFAULT_BASE_DIR / "reports" / "acceptance_remediation" / "latest_account_repair_plan.json"
DEFAULT_APPLY_RESULT_PATH = DEFAULT_BASE_DIR / "reports" / "acceptance_remediation" / "latest_account_repair_apply.json"
DEFAULT_APPLY_ERRORS = {
    "IXBROWSER_KERNEL_MISMATCH",
    "LOGIN_REQUIRED",
    "CAPTCHA_DETECTED",
    "PROXY_FAILED",
    "COMMENT_ACCESS_GATED",
    "ACCOUNT_RESTRICTED",
}


def load_plan(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "error", "error_code": "PLAN_READ_FAILED", "error_message": f"{type(exc).__name__}: {exc}"}
    return payload if isinstance(payload, dict) else {"status": "error", "error_code": "PLAN_INVALID", "error_message": "plan is not an object"}


def profile_ids_for_errors(plan: dict, error_codes: set[str]) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for group in plan.get("groups") or []:
        if not isinstance(group, dict):
            continue
        error = str(group.get("error") or "").strip()
        if error not in error_codes:
            continue
        for profile_id in group.get("profile_ids") or []:
            value = str(profile_id or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            rows.append({"profile_id": value, "reason": error})
    return rows


def plan_error_codes_with_profiles(plan: dict) -> set[str]:
    codes: set[str] = set()
    for group in plan.get("groups") or []:
        if not isinstance(group, dict):
            continue
        error = str(group.get("error") or "").strip()
        if error and group.get("profile_ids"):
            codes.add(error)
    return codes


def apply_account_repair_plan(
    plan_path: Path,
    apply: bool = False,
    error_codes: set[str] | None = None,
    manager_factory: Callable[[], Any] | None = None,
) -> dict:
    plan_path = Path(plan_path)
    plan = load_plan(plan_path)
    if plan.get("status") == "error":
        return {"status": "error", "ok": False, "plan_path": str(plan_path), **plan}
    allowed_errors = error_codes or DEFAULT_APPLY_ERRORS
    selected = profile_ids_for_errors(plan, allowed_errors)
    plan_profile_errors = plan_error_codes_with_profiles(plan)
    non_auto_error_codes = sorted(plan_profile_errors - set(allowed_errors))
    results: list[dict] = []
    if apply and selected:
        if manager_factory is None:
            from ReachOps.adapters.ix_profile_group_manager import IxProfileGroupManager

            manager_factory = IxProfileGroupManager
        manager = manager_factory()
        for item in selected:
            profile_id = item["profile_id"]
            reason = item["reason"]
            try:
                move = manager.move_profile_to_quarantine(profile_id, reason=reason)
                results.append(
                    {
                        "profile_id": profile_id,
                        "reason": reason,
                        "attempted": True,
                        "ok": bool(move.ok),
                        "group_id": str(move.group_id or ""),
                        "group_name": str(move.group_name or ""),
                        "error_code": str(move.error_code or ""),
                        "error_message": str(move.error_message or ""),
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "profile_id": profile_id,
                        "reason": reason,
                        "attempted": True,
                        "ok": False,
                        "group_id": "",
                        "group_name": "",
                        "error_code": "IX_PROFILE_GROUP_MOVE_FAILED",
                        "error_message": f"{type(exc).__name__}: {exc}",
                    }
                )
    else:
        results = [
            {
                "profile_id": item["profile_id"],
                "reason": item["reason"],
                "attempted": False,
                "ok": False,
                "group_id": "",
                "group_name": "",
                "error_code": "DRY_RUN",
                "error_message": "pass --apply to move this profile to quarantine group",
            }
            for item in selected
        ]
    moved = [row for row in results if row.get("ok")]
    failed = [row for row in results if row.get("attempted") and not row.get("ok")]
    selected_error_codes = sorted({str(row.get("reason") or "") for row in selected if str(row.get("reason") or "")})
    allowed_error_codes = sorted(allowed_errors)
    status = "dry_run"
    if apply and failed:
        status = "failed"
    elif apply and selected:
        status = "applied"
    elif apply and not selected:
        status = "no_applicable_profiles"
    next_commands = [
        "python tools/reachops_client_delivery_check.py --json",
        "python tools/reachops_mac_self_check.py --json",
    ]
    next_actions: list[str] = []
    if not selected:
        next_actions = [
            "最新账号修复计划没有默认可自动隔离的账号，未移动任何 ixBrowser 配置。",
            "手动打开受影响账号，确认登录状态、内核版本、代理和 TikTok 页面加载；不可用账号再移入封禁账号分组。",
            "至少保留 1 个已登录、内核匹配、可手动打开 TikTok 的账号在执行分组内，再复跑真实执行复测。",
        ]
    return {
        "status": status,
        "ok": bool(apply and selected and not failed),
        "apply": bool(apply),
        "plan_path": str(plan_path),
        "batch_id": str(plan.get("batch_id") or ""),
        "profile_group": str(plan.get("profile_group") or ""),
        "selected_count": len(selected),
        "moved_count": len(moved),
        "failed_count": len(failed),
        "no_applicable_profiles": bool(not selected),
        "non_auto_error_codes": non_auto_error_codes,
        "results": results,
        "safety_contract": {
            "schema_version": "reachops.account_repair_safety_contract.v1",
            "manual_apply_required": True,
            "operator_confirmed_apply": bool(apply),
            "selected_error_codes": selected_error_codes,
            "allowed_error_codes": allowed_error_codes,
            "hard_blocker_only": all(code in set(allowed_error_codes) for code in selected_error_codes),
            "moves_only_to_quarantine_group": True,
            "no_browser_started": True,
            "no_submit": True,
            "no_ai_token_used": True,
        },
        "no_browser_started": True,
        "no_submit": True,
        "no_ai_token_used": True,
        "next_commands": next_commands,
        "next_actions": next_actions,
    }


def write_account_repair_apply_result(result: dict, path: Path | None = None) -> Path:
    target = Path(path or DEFAULT_APPLY_RESULT_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply the latest ReachOps account repair plan to ixBrowser groups.")
    parser.add_argument("--plan", default=str(DEFAULT_PLAN_PATH), help="Path to account repair plan JSON.")
    parser.add_argument("--apply", action="store_true", help="Actually move selected profiles to quarantine group. Default is dry-run.")
    parser.add_argument("--errors", default=",".join(sorted(DEFAULT_APPLY_ERRORS)), help="Comma separated error codes to apply.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    error_codes = {item.strip() for item in str(args.errors or "").split(",") if item.strip()}
    old_no_proxy = os.environ.get("NO_PROXY", "")
    old_no_proxy_lower = os.environ.get("no_proxy", "")
    try:
        for key, old_value in (("NO_PROXY", old_no_proxy), ("no_proxy", old_no_proxy_lower)):
            items = [item.strip() for item in old_value.split(",") if item.strip()]
            for host in ["127.0.0.1", "localhost", "::1"]:
                if host not in items:
                    items.append(host)
            os.environ[key] = ",".join(items)
        payload = apply_account_repair_plan(Path(args.plan), apply=bool(args.apply), error_codes=error_codes)
        if args.apply:
            write_account_repair_apply_result(payload, Path(args.plan).parent / "latest_account_repair_apply.json")
    finally:
        os.environ["NO_PROXY"] = old_no_proxy
        os.environ["no_proxy"] = old_no_proxy_lower
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") in {"dry_run", "applied"} and not payload.get("failed_count") else 1


if __name__ == "__main__":
    raise SystemExit(main())
