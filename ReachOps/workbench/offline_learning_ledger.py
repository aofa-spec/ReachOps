# -*- coding: utf-8 -*-
"""Local offline learning ledger for unknown ReachOps execution states."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


OFFLINE_LEARNING_SCHEMA_VERSION = "reachops.offline_learning.v1"
OFFLINE_POLICY_CANDIDATES_SCHEMA_VERSION = "reachops.offline_policy_candidates.v1"
OFFLINE_POLICY_REVIEW_SCHEMA_VERSION = "reachops.offline_policy_review.v1"
OFFLINE_POLICY_RELEASE_PROPOSAL_SCHEMA_VERSION = "reachops.offline_policy_release_proposal.v1"


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _text(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


def state_signature(page_state: dict[str, Any] | None, *, error_code: str = "", action_type: str = "") -> str:
    page_state = page_state if isinstance(page_state, dict) else {}
    stable = {
        "state": str(page_state.get("state") or "UNKNOWN_PAGE_STATE"),
        "url_host_path": _url_host_path(str(page_state.get("current_url") or "")),
        "title": _text(page_state.get("title"), 160).lower(),
        "body_sha": str(page_state.get("body_text_sha256") or ""),
        "signals": sorted(str(item) for item in (page_state.get("signals") or [])),
        "selector_counts": page_state.get("selector_counts") or {},
        "error_code": str(error_code or ""),
        "action_type": str(action_type or ""),
    }
    raw = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "uls_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _url_host_path(url: str) -> str:
    text = str(url or "").strip()
    if "://" not in text:
        return text[:180]
    try:
        from urllib.parse import urlparse

        parsed = urlparse(text)
        return f"{parsed.netloc}{parsed.path}"[:180]
    except Exception:
        return text[:180]


@dataclass
class OfflineLearningRecord:
    signature: str
    state: str
    error_code: str = ""
    action_type: str = ""
    first_seen_at: str = field(default_factory=utc_now_iso)
    last_seen_at: str = field(default_factory=utc_now_iso)
    occurrence_count: int = 1
    current_url: str = ""
    title: str = ""
    signals: list[str] = field(default_factory=list)
    selector_counts: dict[str, int] = field(default_factory=dict)
    evidence_paths: list[str] = field(default_factory=list)
    suggested_policy: dict[str, Any] = field(default_factory=dict)
    schema_version: str = OFFLINE_LEARNING_SCHEMA_VERSION
    no_ai_token_used: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["occurrence_count"] = max(1, int(payload.get("occurrence_count") or 1))
        payload["signals"] = list(payload.get("signals") or [])
        payload["selector_counts"] = dict(payload.get("selector_counts") or {})
        payload["evidence_paths"] = list(dict.fromkeys(str(item) for item in payload.get("evidence_paths") or [] if str(item)))
        payload["suggested_policy"] = dict(payload.get("suggested_policy") or {})
        payload["schema_version"] = OFFLINE_LEARNING_SCHEMA_VERSION
        payload["no_ai_token_used"] = True
        return payload


class OfflineLearningLedger:
    """Append-only local learning index for unclassified states.

    It never changes runtime behavior directly. It only records signatures and
    deterministic suggestions for later rule upgrades or optional AI analysis.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def record_unknown_state(
        self,
        *,
        page_state: dict[str, Any] | None,
        error_code: str = "",
        action_type: str = "",
        evidence_path: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        page_state = page_state if isinstance(page_state, dict) else {}
        state = str(page_state.get("state") or "UNKNOWN_PAGE_STATE")
        if state != "UNKNOWN_PAGE_STATE" and str(error_code or "") not in {"UNKNOWN_PAGE_STATE", "ACTION_FAILED", "OUTREACH_EXECUTION_FAILED"}:
            return {}
        signature = state_signature(page_state, error_code=error_code, action_type=action_type)
        ledger = self._read()
        records = ledger.setdefault("records", {})
        previous = records.get(signature) if isinstance(records.get(signature), dict) else {}
        record = self._merge_record(previous, signature, page_state, error_code, action_type, evidence_path, context or {})
        records[signature] = record
        ledger["schema_version"] = OFFLINE_LEARNING_SCHEMA_VERSION
        ledger["updated_at"] = utc_now_iso()
        ledger["no_ai_token_used"] = True
        self._write(ledger)
        return {
            "schema_version": OFFLINE_LEARNING_SCHEMA_VERSION,
            "signature": signature,
            "occurrence_count": record.get("occurrence_count", 1),
            "suggested_policy": record.get("suggested_policy") or {},
            "ledger_path": str(self.path),
            "no_ai_token_used": True,
        }

    def _merge_record(
        self,
        previous: dict[str, Any],
        signature: str,
        page_state: dict[str, Any],
        error_code: str,
        action_type: str,
        evidence_path: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now_iso()
        evidence_paths = list(previous.get("evidence_paths") or [])
        if evidence_path:
            evidence_paths.append(str(evidence_path))
        record = OfflineLearningRecord(
            signature=signature,
            state=str(page_state.get("state") or "UNKNOWN_PAGE_STATE"),
            error_code=str(error_code or previous.get("error_code") or ""),
            action_type=str(action_type or previous.get("action_type") or ""),
            first_seen_at=str(previous.get("first_seen_at") or now),
            last_seen_at=now,
            occurrence_count=int(previous.get("occurrence_count") or 0) + 1,
            current_url=str(page_state.get("current_url") or previous.get("current_url") or ""),
            title=_text(page_state.get("title") or previous.get("title"), 160),
            signals=[str(item) for item in (page_state.get("signals") or previous.get("signals") or [])],
            selector_counts=dict(page_state.get("selector_counts") or previous.get("selector_counts") or {}),
            evidence_paths=evidence_paths[-20:],
            suggested_policy=self._suggest_policy(page_state, error_code, action_type, context),
        )
        return record.to_dict()

    def _suggest_policy(self, page_state: dict[str, Any], error_code: str, action_type: str, context: dict[str, Any]) -> dict[str, Any]:
        text = " ".join(
            [
                str(page_state.get("title") or ""),
                str(page_state.get("body_text_sample") or ""),
                " ".join(str(item) for item in page_state.get("signals") or []),
                str(context.get("error_message") or ""),
            ]
        ).lower()
        if any(token in text for token in ["login", "log in", "sign in", "登录", "注册"]):
            return {"candidate_state": "LOGIN_REQUIRED", "candidate_action": "cooldown_profile_and_switch", "confidence": "medium"}
        if any(token in text for token in ["captcha", "verify", "verification", "验证码", "验证"]):
            return {"candidate_state": "CAPTCHA_DETECTED", "candidate_action": "cooldown_profile_and_switch", "confidence": "medium"}
        if any(token in text for token in ["too many", "limit", "try again later", "temporarily blocked", "频繁"]):
            return {"candidate_state": "RATE_LIMITED", "candidate_action": "cooldown_profile_or_scope", "confidence": "medium"}
        counts = page_state.get("selector_counts") if isinstance(page_state.get("selector_counts"), dict) else {}
        if str(action_type or "") == "comment_reply" and int(counts.get("comment_box_count") or 0) <= 0:
            return {"candidate_state": "COMMENT_BOX_MISSING", "candidate_action": "degrade_to_collect", "confidence": "low"}
        return {"candidate_state": "UNKNOWN_PAGE_STATE", "candidate_action": "capture_unknown_state_bundle", "confidence": "low"}

    def _read(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {"schema_version": OFFLINE_LEARNING_SCHEMA_VERSION, "records": {}, "no_ai_token_used": True}

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summarize_offline_learning(path: str | Path, limit: int = 20) -> dict[str, Any]:
    ledger = OfflineLearningLedger(path)._read()
    records = [row for row in (ledger.get("records") or {}).values() if isinstance(row, dict)]
    records.sort(key=lambda row: (int(row.get("occurrence_count") or 0), str(row.get("last_seen_at") or "")), reverse=True)
    reviews = ledger.get("policy_reviews") if isinstance(ledger.get("policy_reviews"), dict) else {}
    candidates = build_policy_candidates_from_records(records, policy_reviews=reviews)
    return {
        "schema_version": OFFLINE_LEARNING_SCHEMA_VERSION,
        "ledger_path": str(path),
        "record_count": len(records),
        "records": records[: max(1, int(limit or 1))],
        "policy_candidates": candidates,
        "policy_review_summary": build_policy_review_summary(reviews),
        "policy_release_proposal": build_policy_release_proposal(candidates, reviews),
        "no_ai_token_used": True,
    }


def build_policy_candidates_from_records(
    records: list[dict[str, Any]],
    *,
    min_occurrences: int = 2,
    policy_reviews: dict[str, Any] | None = None,
) -> dict[str, Any]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    reviews = policy_reviews if isinstance(policy_reviews, dict) else {}
    for record in records:
        if not isinstance(record, dict):
            continue
        suggested = record.get("suggested_policy") if isinstance(record.get("suggested_policy"), dict) else {}
        candidate_state = str(suggested.get("candidate_state") or record.get("state") or "UNKNOWN_PAGE_STATE")
        candidate_action = str(suggested.get("candidate_action") or "capture_unknown_state_bundle")
        if candidate_state == "UNKNOWN_PAGE_STATE" and candidate_action == "capture_unknown_state_bundle":
            continue
        occurrence_count = int(record.get("occurrence_count") or 0)
        if occurrence_count < max(1, int(min_occurrences or 1)):
            continue
        key = (candidate_state, candidate_action)
        row = grouped.setdefault(
            key,
            {
                "candidate_id": policy_candidate_id(candidate_state, candidate_action),
                "candidate_state": candidate_state,
                "candidate_action": candidate_action,
                "confidence": str(suggested.get("confidence") or "low"),
                "occurrence_count": 0,
                "signatures": [],
                "evidence_paths": [],
                "source_states": [],
                "requires_human_review": True,
                "auto_apply": False,
                "no_ai_token_used": True,
            },
        )
        row["occurrence_count"] = int(row.get("occurrence_count") or 0) + occurrence_count
        row["signatures"].append(str(record.get("signature") or ""))
        row["source_states"].append(str(record.get("state") or "UNKNOWN_PAGE_STATE"))
        row["evidence_paths"].extend(str(item) for item in (record.get("evidence_paths") or []) if str(item))
    candidates = []
    for row in grouped.values():
        row["signatures"] = list(dict.fromkeys(item for item in row.get("signatures") or [] if item))[:20]
        row["source_states"] = sorted(set(item for item in row.get("source_states") or [] if item))
        row["evidence_paths"] = list(dict.fromkeys(item for item in row.get("evidence_paths") or [] if item))[-20:]
        row["recommended_review"] = (
            f"评估是否把 {row.get('candidate_state')} → {row.get('candidate_action')} "
            "纳入 PageStateDetector 或 RepairPolicyEngine；未人工确认前不自动生效。"
        )
        review = latest_policy_review_for_candidate(
            reviews,
            str(row.get("candidate_state") or ""),
            str(row.get("candidate_action") or ""),
        )
        if review:
            row["review"] = review
            row["review_status"] = str(review.get("decision") or "")
            row["approved_for_rule_upgrade"] = str(review.get("decision") or "") == "approved"
            row["auto_apply"] = False
            row["runtime_effect"] = "review_recorded_only"
        candidates.append(row)
    candidates.sort(key=lambda row: int(row.get("occurrence_count") or 0), reverse=True)
    return {
        "schema_version": OFFLINE_POLICY_CANDIDATES_SCHEMA_VERSION,
        "candidate_count": len(candidates),
        "min_occurrences": max(1, int(min_occurrences or 1)),
        "candidates": candidates,
        "no_ai_token_used": True,
    }


def policy_candidate_id(candidate_state: str, candidate_action: str) -> str:
    raw = json.dumps(
        {
            "schema_version": OFFLINE_POLICY_CANDIDATES_SCHEMA_VERSION,
            "candidate_state": str(candidate_state or ""),
            "candidate_action": str(candidate_action or ""),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "opc_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def policy_review_id(candidate_id: str, decision: str, reviewed_at: str) -> str:
    raw = json.dumps(
        {
            "schema_version": OFFLINE_POLICY_REVIEW_SCHEMA_VERSION,
            "candidate_id": str(candidate_id or ""),
            "decision": str(decision or ""),
            "reviewed_at": str(reviewed_at or ""),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "opr_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def latest_policy_review_for_candidate(
    policy_reviews: dict[str, Any],
    candidate_state: str,
    candidate_action: str,
) -> dict[str, Any]:
    if not isinstance(policy_reviews, dict):
        return {}
    candidate_id = policy_candidate_id(candidate_state, candidate_action)
    review = policy_reviews.get(candidate_id)
    return dict(review) if isinstance(review, dict) else {}


def build_policy_review_summary(policy_reviews: dict[str, Any] | None) -> dict[str, Any]:
    rows = [row for row in (policy_reviews or {}).values() if isinstance(row, dict)]
    approved = [row for row in rows if str(row.get("decision") or "") == "approved"]
    rejected = [row for row in rows if str(row.get("decision") or "") == "rejected"]
    return {
        "schema_version": OFFLINE_POLICY_REVIEW_SCHEMA_VERSION,
        "review_count": len(rows),
        "approved_count": len(approved),
        "rejected_count": len(rejected),
        "reviews": sorted(rows, key=lambda row: str(row.get("reviewed_at") or ""), reverse=True)[:20],
        "runtime_auto_apply_count": 0,
        "no_ai_token_used": True,
    }


def build_policy_release_proposal(
    policy_candidates: dict[str, Any] | None,
    policy_reviews: dict[str, Any] | None,
) -> dict[str, Any]:
    candidates = policy_candidates.get("candidates") if isinstance(policy_candidates, dict) else []
    reviews = policy_reviews if isinstance(policy_reviews, dict) else {}
    approved = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        candidate_id = str(candidate.get("candidate_id") or "")
        review = reviews.get(candidate_id) if isinstance(reviews.get(candidate_id), dict) else {}
        if str(review.get("decision") or candidate.get("review_status") or "") != "approved":
            continue
        candidate_state = str(candidate.get("candidate_state") or "UNKNOWN_PAGE_STATE")
        candidate_action = str(candidate.get("candidate_action") or "capture_unknown_state_bundle")
        approved.append(
            {
                "candidate_id": candidate_id,
                "candidate_state": candidate_state,
                "candidate_action": candidate_action,
                "target_components": release_target_components(candidate_state, candidate_action),
                "occurrence_count": int(candidate.get("occurrence_count") or 0),
                "signatures": list(candidate.get("signatures") or [])[:20],
                "evidence_paths": list(candidate.get("evidence_paths") or [])[-20:],
                "review_id": str(review.get("review_id") or ""),
                "reviewed_at": str(review.get("reviewed_at") or ""),
                "release_required": True,
                "runtime_auto_apply": False,
                "runtime_effect": "release_proposal_only",
                "no_ai_token_used": True,
            }
        )
    approved.sort(key=lambda row: (int(row.get("occurrence_count") or 0), str(row.get("reviewed_at") or "")), reverse=True)
    return {
        "schema_version": OFFLINE_POLICY_RELEASE_PROPOSAL_SCHEMA_VERSION,
        "approved_count": len(approved),
        "ready_for_release_count": len(approved),
        "proposals": approved,
        "release_gate": "code_or_policy_release_required",
        "runtime_auto_apply_count": 0,
        "runtime_auto_apply": False,
        "no_ai_token_used": True,
    }


def release_target_components(candidate_state: str, candidate_action: str) -> list[str]:
    components = ["PageStateDetector"]
    action = str(candidate_action or "")
    if action and action not in {"classify_only", "capture_unknown_state_bundle"}:
        components.append("RepairPolicyEngine")
    if str(candidate_state or "") in {"LOGIN_REQUIRED", "CAPTCHA_DETECTED", "RATE_LIMITED"}:
        components.append("RiskGate")
    return list(dict.fromkeys(components))


def review_policy_candidate(
    path: str | Path,
    *,
    candidate_state: str,
    candidate_action: str,
    decision: str,
    reviewer: str = "operator",
    note: str = "",
) -> dict[str, Any]:
    decision = str(decision or "").strip().lower()
    if decision not in {"approved", "rejected"}:
        raise ValueError("decision must be approved or rejected")
    candidate_state = str(candidate_state or "").strip()
    candidate_action = str(candidate_action or "").strip()
    if not candidate_state or not candidate_action:
        raise ValueError("candidate_state and candidate_action are required")
    ledger = OfflineLearningLedger(path)
    payload = ledger._read()
    records = [row for row in (payload.get("records") or {}).values() if isinstance(row, dict)]
    candidates = build_policy_candidates_from_records(records).get("candidates") or []
    candidate_id = policy_candidate_id(candidate_state, candidate_action)
    matched = next(
        (
            row
            for row in candidates
            if str(row.get("candidate_id") or "") == candidate_id
            or (
                str(row.get("candidate_state") or "") == candidate_state
                and str(row.get("candidate_action") or "") == candidate_action
            )
        ),
        {},
    )
    if not matched:
        raise ValueError("policy candidate is not present in the current offline learning ledger")
    reviewed_at = utc_now_iso()
    review = {
        "schema_version": OFFLINE_POLICY_REVIEW_SCHEMA_VERSION,
        "review_id": policy_review_id(candidate_id, decision, reviewed_at),
        "candidate_id": candidate_id,
        "candidate_state": candidate_state,
        "candidate_action": candidate_action,
        "decision": decision,
        "reviewer": str(reviewer or "operator")[:80],
        "note": _text(note, 500),
        "reviewed_at": reviewed_at,
        "candidate_snapshot": matched,
        "runtime_effect": "review_recorded_only",
        "auto_apply": False,
        "requires_code_or_policy_release": decision == "approved",
        "no_ai_token_used": True,
    }
    reviews = payload.setdefault("policy_reviews", {})
    if not isinstance(reviews, dict):
        reviews = {}
        payload["policy_reviews"] = reviews
    reviews[candidate_id] = review
    payload["schema_version"] = OFFLINE_LEARNING_SCHEMA_VERSION
    payload["updated_at"] = reviewed_at
    payload["no_ai_token_used"] = True
    ledger._write(payload)
    return {
        "schema_version": OFFLINE_POLICY_REVIEW_SCHEMA_VERSION,
        "status": "review_recorded",
        "review": review,
        "policy_review_summary": build_policy_review_summary(reviews),
        "policy_release_proposal": build_policy_release_proposal(
            build_policy_candidates_from_records(records, policy_reviews=reviews),
            reviews,
        ),
        "no_ai_token_used": True,
    }
