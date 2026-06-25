# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.reachops_delivery_audit import LOCAL_PENDING, run_audit
from tools.verify_reachops_acceptance_summary import load_summary, verify_summary


PASSED = "passed"
FAILED = "failed"
PENDING_EXTERNAL = "pending_external_validation"
READY_FOR_EXTERNAL_VALIDATION = "ready_for_external_validation"
REAL_PLATFORM_REQUIREMENTS = {"授权允许时能真实执行", "真实 TikTok 平台提交"}


STAGE_REQUIREMENTS = {
    "阶段 1：ReachOps MVP": [
        "输入产品/关键词即可创建获客任务",
        "产品链接能自动生成获客任务和可执行来源",
        "达人链接和话题能自动生成获客任务",
        "AI/规则能生成产品分析",
        "系统能自动生成受众画像",
        "系统能自动规划来源",
        "刷新分组能完整读取 ixBrowser 配置列表",
        "选择哪个分组就实际用哪个分组执行",
        "能识别并排除异常账号",
        "客户端按钮和设置接入真实执行链路",
        "客户可见设置都有执行证据映射",
        "客户能看到成功失败换号和错误码",
        "开始任务后日志能实时显示执行进度",
        "异常不弹窗卡死",
        "客户端文案面向运营用户",
        "漏斗只显示本轮 Campaign",
        "能识别页面打不开和无评论",
        "系统能发现内容",
        "系统能采集互动用户",
        "系统能识别购买/咨询意向",
        "系统能生成客户线索",
        "全程有实时漏斗",
        "可导出客户名单和执行报告",
        "导出内容包含客户池动作漏斗和错误统计",
    ],
    "阶段 2：触达计划 MVP": [
        "AI/规则能生成意图分类和话术建议",
        "系统能生成触达动作",
        "系统能执行预检",
    ],
    "阶段 3：真实执行": [
        "授权允许时能真实执行",
        "真实提交验收入口默认阻止误提交",
        "真实提交验收入口支持授权证据校验",
        "真实执行成功必须有有效证据",
        "授权门覆盖设备绑定、过期和能力限制",
        "真实 TikTok 平台提交",
        "账号失败能自动换号",
        "私信/关注失败能降级评论",
        "全程有错误码和证据",
    ],
    "阶段 4：AI 增强": [
        "AI/规则能生成产品分析",
        "外部 AI 故障可自动降级规则策略",
        "AI/规则能生成意图分类和话术建议",
        "AI/规则能扩展获客来源",
        "人工可编辑策略可保存并进入报告",
    ],
    "阶段 5：独立打包": [
        "独立配置/数据/授权目录存在",
        "Windows 打包入口存在",
        "升级清单和安装校验机制可用",
    ],
}


FINAL_ACCEPTANCE_REQUIREMENTS = [
    "输入产品/关键词即可创建获客任务",
    "产品链接能自动生成获客任务和可执行来源",
    "达人链接和话题能自动生成获客任务",
    "系统能自动生成受众画像",
    "系统能自动规划来源",
    "刷新分组能完整读取 ixBrowser 配置列表",
    "选择哪个分组就实际用哪个分组执行",
    "能识别并排除异常账号",
    "客户端按钮和设置接入真实执行链路",
    "客户可见设置都有执行证据映射",
    "客户能看到成功失败换号和错误码",
    "开始任务后日志能实时显示执行进度",
    "异常不弹窗卡死",
    "客户端文案面向运营用户",
    "漏斗只显示本轮 Campaign",
    "能识别页面打不开和无评论",
    "系统能发现内容",
    "系统能采集互动用户",
    "系统能识别购买/咨询意向",
    "系统能生成客户线索",
    "系统能生成触达动作",
    "系统能执行预检",
    "授权允许时能真实执行",
    "真实 TikTok 平台提交",
    "真实执行成功必须有有效证据",
    "账号失败能自动换号",
    "私信/关注失败能降级评论",
    "全程有实时漏斗",
    "全程有错误码和证据",
    "可导出客户名单和执行报告",
    "导出内容包含客户池动作漏斗和错误统计",
]


def _check_index(audit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("name") or ""): row for row in audit.get("checks", []) if isinstance(row, dict)}


def _status_for_requirement(name: str, checks: dict[str, dict[str, Any]], external_platform_validated: bool = False) -> str:
    if name in REAL_PLATFORM_REQUIREMENTS:
        if external_platform_validated:
            return PASSED
        status = str((checks.get(name) or {}).get("status") or FAILED)
        return FAILED if status == FAILED else LOCAL_PENDING
    return str((checks.get(name) or {}).get("status") or FAILED)


def _stage_status(requirements: list[str], checks: dict[str, dict[str, Any]], external_platform_validated: bool = False) -> str:
    statuses = [_status_for_requirement(name, checks, external_platform_validated=external_platform_validated) for name in requirements]
    if any(status == FAILED for status in statuses):
        return FAILED
    if any(status == LOCAL_PENDING for status in statuses):
        return PENDING_EXTERNAL
    return PASSED


def _requirement_rows(requirements: list[str], checks: dict[str, dict[str, Any]], external_platform_validated: bool = False) -> list[dict[str, Any]]:
    rows = []
    for name in requirements:
        check = checks.get(name) or {}
        status = _status_for_requirement(name, checks, external_platform_validated=external_platform_validated)
        evidence = check.get("evidence") or {}
        if name in REAL_PLATFORM_REQUIREMENTS and external_platform_validated:
            evidence = dict(evidence)
            evidence["platform_validation"] = True
        rows.append(
            {
                "name": name,
                "status": status,
                "evidence": evidence,
            }
        )
    return rows


def build_goal_status_report(
    audit_result: dict[str, Any],
    acceptance_summary: dict[str, Any] | None = None,
    allow_external_pending: bool = True,
) -> dict[str, Any]:
    checks = _check_index(audit_result)
    acceptance_verification = None
    if acceptance_summary is not None:
        acceptance_verification = verify_summary(acceptance_summary, allow_external_pending=allow_external_pending)
    external_platform_validated = bool(
        acceptance_verification
        and not acceptance_verification.get("failures")
        and int((acceptance_verification.get("delivery_audit") or {}).get("effective_pending_external_validation") or 0) == 0
        and str((acceptance_verification.get("live_submit") or {}).get("status") or "") == "completed"
        and bool((acceptance_verification.get("live_submit") or {}).get("platform_validation"))
    )
    stage_rows = []
    for stage_name, requirements in STAGE_REQUIREMENTS.items():
        stage_rows.append(
            {
                "name": stage_name,
                "status": _stage_status(requirements, checks, external_platform_validated=external_platform_validated),
                "requirements": _requirement_rows(requirements, checks, external_platform_validated=external_platform_validated),
            }
        )

    final_rows = _requirement_rows(FINAL_ACCEPTANCE_REQUIREMENTS, checks, external_platform_validated=external_platform_validated)
    failed = [row for row in final_rows if row["status"] == FAILED]
    pending = [row for row in final_rows if row["status"] == LOCAL_PENDING]

    status = PASSED
    if failed or any(row["status"] == FAILED for row in stage_rows):
        status = FAILED
    elif pending or any(row["status"] == PENDING_EXTERNAL for row in stage_rows):
        status = READY_FOR_EXTERNAL_VALIDATION
    if acceptance_verification and not acceptance_verification.get("passed"):
        status = FAILED

    return {
        "product": "ReachOps",
        "status": status,
        "audit_status": audit_result.get("status"),
        "campaign_id": audit_result.get("campaign_id", ""),
        "batch_id": audit_result.get("batch_id", ""),
        "summary": {
            "stages_passed": len([row for row in stage_rows if row["status"] == PASSED]),
            "stages_pending_external_validation": len([row for row in stage_rows if row["status"] == PENDING_EXTERNAL]),
            "stages_failed": len([row for row in stage_rows if row["status"] == FAILED]),
            "final_passed": len([row for row in final_rows if row["status"] == PASSED]),
            "final_pending_external_validation": len(pending),
            "final_failed": len(failed),
        },
        "stages": stage_rows,
        "final_acceptance": final_rows,
        "pending_external_validation": [row["name"] for row in pending],
        "next_required_inputs": [
            "真实 ixBrowser 数字 Profile ID",
            "已授权的 TikTok 视频链接",
            "已授权的 TikTok 用户主页链接",
            "目标用户名与页面匹配",
            "允许 live_submit/comment_reply/follow_review/dm_review 的激活状态文件",
        ]
        if pending
        else [],
        "safety_gates": [
            "真实提交默认阻止误提交",
            "live readiness 不启动浏览器、不提交动作",
            "Profile ID 必须是 ixBrowser 数字 ID",
            "授权确认缺失时禁止真实提交",
            "真实提交必须保留截图证据和 sidecar 校验",
            "私信/关注失败可降级评论",
            "账号失败可自动换号",
        ],
        "acceptance_verification": acceptance_verification,
    }


def run_default_audit(target: str, base_dir: str = "") -> dict[str, Any]:
    if base_dir:
        return run_audit(SimpleNamespace(target=target, base_dir=base_dir, json=True))
    with tempfile.TemporaryDirectory(prefix="reachops-goal-status-") as tmp:
        return run_audit(SimpleNamespace(target=target, base_dir=tmp, json=True))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a ReachOps goal status report.")
    parser.add_argument("--target", default="anti aging serum", help="Audit target used when no audit JSON is supplied.")
    parser.add_argument("--base-dir", default="", help="Optional base dir for a fresh audit run.")
    parser.add_argument("--audit-json", default="", help="Existing reachops_delivery_audit JSON file.")
    parser.add_argument("--acceptance-summary", default="", help="Optional Windows acceptance_summary.json.")
    parser.add_argument("--strict-external", action="store_true", help="Treat external platform validation pending as not passed.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.audit_json:
        audit_result = json.loads(Path(args.audit_json).read_text(encoding="utf-8"))
    else:
        audit_result = run_default_audit(args.target, args.base_dir)
    acceptance_summary = load_summary(args.acceptance_summary) if args.acceptance_summary else None
    report = build_goal_status_report(
        audit_result,
        acceptance_summary=acceptance_summary,
        allow_external_pending=not args.strict_external,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] == FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
