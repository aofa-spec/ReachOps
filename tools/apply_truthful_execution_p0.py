from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one anchor in {path}: found {count}\nANCHOR:\n{old[:400]}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_action_router() -> None:
    path = ROOT / "ReachOps/workbench/action_router.py"

    replace_once(
        path,
        '''FALLBACK_CODES = {
    "DM_NOT_AVAILABLE",
    "DM_ENTRY_NOT_FOUND",
    "DM_NOT_ALLOWED",
    "DM_RATE_LIMITED",
    "FOLLOW_NOT_AVAILABLE",
    "FOLLOW_BUTTON_MISSING",
    "FOLLOW_RATE_LIMITED",
    "FOLLOW_BLOCKED",
}
''',
        '''FALLBACK_CODES = {
    "DM_NOT_AVAILABLE",
    "DM_ENTRY_NOT_FOUND",
    "DM_NOT_ALLOWED",
    "DM_RATE_LIMITED",
    "FOLLOW_NOT_AVAILABLE",
    "FOLLOW_BUTTON_MISSING",
    "FOLLOW_RATE_LIMITED",
    "FOLLOW_BLOCKED",
}

PLATFORM_ENFORCEMENT_CODES = {
    "CAPTCHA_DETECTED",
    "ACCOUNT_RESTRICTED",
    "RATE_LIMITED",
    "COMMENT_BLOCKED",
    "FOLLOW_RATE_LIMITED",
    "DM_RATE_LIMITED",
    "DAILY_QUOTA_EXCEEDED",
    "PROFILE_HOURLY_LIMIT_EXCEEDED",
    "VIDEO_HOURLY_LIMIT_EXCEEDED",
}
''',
    )

    replace_once(
        path,
        '''        self._lock = threading.Lock()
        self._profile_locks: dict[str, threading.Lock] = {}

    def run(self, profiles: list[dict], config: ActionRouterConfig | None = None, limit: int = 100) -> dict:
        config = config or ActionRouterConfig()
        previous_batch_id = self.storage._active_batch_id()
''',
        '''        self._lock = threading.Lock()
        self._profile_locks: dict[str, threading.Lock] = {}
        self._run_stop_event = threading.Event()
        self._active_execution_mode = "simulated"

    def run(self, profiles: list[dict], config: ActionRouterConfig | None = None, limit: int = 100) -> dict:
        config = config or ActionRouterConfig()
        self._active_execution_mode = self._execution_mode(config)
        self._run_stop_event = threading.Event()
        self._assert_executor_contract(config)
        previous_batch_id = self.storage._active_batch_id()
''',
    )

    replace_once(
        path,
        '''                while handled < config.per_profile_action_limit:
                    profile_id = str(profile.get("profile_id") or profile.get("id") or "")
''',
        '''                while handled < config.per_profile_action_limit:
                    if self._run_stop_event.is_set():
                        self.storage.log_event(
                            "action_router_worker_stopped",
                            "",
                            {"reason": "run_circuit_breaker", "execution_mode": self._active_execution_mode},
                        )
                        return
                    profile_id = str(profile.get("profile_id") or profile.get("id") or "")
''',
    )

    replace_once(
        path,
        '''            if result["status"] == "success":
                return results
            if result.get("retry_same_profile") and attempt < config.max_switch_attempts:
''',
        '''            if result["status"] == "success":
                return results
            if result.get("block_execution"):
                self._run_stop_event.set()
                self.storage.log_event(
                    "action_router_run_circuit_breaker",
                    str(current_action.get("id") or ""),
                    {
                        "error_code": str(result.get("error_code") or ""),
                        "profile_id": str(current_profile.get("profile_id") or current_profile.get("id") or ""),
                        "scope": str(result.get("circuit_breaker_scope") or "run"),
                        "execution_mode": self._active_execution_mode,
                    },
                )
                return results
            if result.get("retry_same_profile") and attempt < config.max_switch_attempts:
''',
    )

    replace_once(
        path,
        '''            result = self._record(action, profile, "skipped", rate_code, rate_code, "", attempt, risk_gate=rate_gate)
            if rate_code in SWITCH_PROFILE_CODES:
                result["switch_profile"] = True
            return result
''',
        '''            result = self._record(action, profile, "skipped", rate_code, rate_code, "", attempt, risk_gate=rate_gate)
            result["block_execution"] = True
            result["circuit_breaker_scope"] = "run"
            result["switch_profile"] = False
            return result
''',
    )

    replace_once(
        path,
        '''            result = self._record(
                action,
                profile,
                "success",
                "",
                rendered.rendered_text,
                evidence_path or self._evidence_stub(action, profile, "success"),
                attempt,
                risk_gate={**pre_gate, "allowed": True},
            )
''',
        '''            result = self._record(
                action,
                profile,
                "success",
                "",
                rendered.rendered_text,
                evidence_path or self._evidence_stub(action, profile, "success"),
                attempt,
                risk_gate={**pre_gate, "allowed": True},
                execution_mode=self._active_execution_mode,
                evidence_verified=self._active_execution_mode == "live",
            )
''',
    )

    replace_once(
        path,
        '''        result["repair_decision"] = repair_decision
        if account_health:
            result["account_health"] = account_health
        result["retry_same_profile"] = bool(repair_decision.get("retry_same_profile"))
        result["switch_profile"] = bool(repair_decision.get("switch_profile")) or error_code in SWITCH_PROFILE_CODES
        result["degrade_to"] = str(repair_decision.get("degrade_to") or "")
        result["fallback_available"] = bool(repair_decision.get("fallback_allowed")) or bool(
            self._fallback_action(action, error_code, create=False, batch_id=config.batch_id)
        )
''',
        '''        if error_code in PLATFORM_ENFORCEMENT_CODES:
            repair_decision["block_execution"] = True
            repair_decision["retry_same_profile"] = False
            repair_decision["switch_profile"] = False
            repair_decision["fallback_allowed"] = False
            repair_decision["terminal_outcome"] = "blocked"
        blocked = bool(repair_decision.get("block_execution"))
        result["repair_decision"] = repair_decision
        if account_health:
            result["account_health"] = account_health
        result["block_execution"] = blocked
        result["circuit_breaker_scope"] = "run" if blocked else ""
        result["retry_same_profile"] = (not blocked) and bool(repair_decision.get("retry_same_profile"))
        result["switch_profile"] = (not blocked) and (
            bool(repair_decision.get("switch_profile")) or error_code in SWITCH_PROFILE_CODES
        )
        result["degrade_to"] = str(repair_decision.get("degrade_to") or "")
        result["fallback_available"] = (not blocked) and (
            bool(repair_decision.get("fallback_allowed"))
            or bool(self._fallback_action(action, error_code, create=False, batch_id=config.batch_id))
        )
''',
    )

    replace_once(
        path,
        '''        return result

    def _repair_audit_event(
''',
        '''        return result

    def _execution_mode(self, config: ActionRouterConfig) -> str:
        if config.live_preflight_only:
            return "preflight"
        if config.dry_run:
            return "simulated" if isinstance(self.executor, FixtureActionExecutor) else "dry_run"
        if config.allow_live_submit:
            return "live"
        return "blocked"

    def _assert_executor_contract(self, config: ActionRouterConfig) -> None:
        if self._execution_mode(config) == "live" and isinstance(self.executor, FixtureActionExecutor):
            raise RuntimeError("LIVE_EXECUTOR_REQUIRED: live execution cannot use FixtureActionExecutor")

    def _repair_audit_event(
''',
    )

    old_record = '''    def _record(
        self,
        action: dict,
        profile: dict,
        public_status: str,
        error_code: str,
        message: str,
        evidence_path: str,
        attempt: int,
        risk_gate: dict[str, Any] | None = None,
    ) -> dict:
        action_id = str(action.get("id") or "")
        action_type = str(action.get("action_type") or "")
        profile_id = str(profile.get("profile_id") or profile.get("id") or "")
        if not evidence_path:
            evidence_path = self._evidence_stub(action, profile, public_status or error_code or "recorded")
        execution_id = self.storage.create_outreach_execution(
            action_id,
            action_type,
            str(action.get("target_username") or ""),
            status=public_status,
            profile_id=profile_id,
            evidence_path=evidence_path,
            error_code=error_code,
            error_message=message,
            risk_gate=risk_gate,
        )
        self.storage.record_action_execution_result(
            action_id,
            execution_id,
            "completed" if public_status == "success" else public_status,
            error_code=error_code,
            error_message=message,
            retryable=public_status == "failed" and error_code in SWITCH_PROFILE_CODES,
        )
        if public_status in {"skipped", "failed"}:
            self.storage.update_action_status(action_id, public_status, message or error_code)
        if public_status == "success":
            self.storage.update_action_status(action_id, "success", "action router success")
        self.storage.log_event(
            f"action_router_{public_status}",
            action_id,
            {
                "profile_id": profile_id,
                "execution_id": execution_id,
                "error_code": error_code,
                "attempt": attempt,
                "risk_gate": risk_gate or {},
            },
        )
        result = {
            "action_id": action_id,
            "execution_id": execution_id,
            "action_type": action_type,
            "public_action_type": PUBLIC_ACTION_TYPE.get(action_type, action_type),
            "status": public_status,
            "profile_id": profile_id,
            "attempt": attempt,
            "error_code": error_code,
            "error_message": message,
            "evidence_path": evidence_path,
        }
        if isinstance(risk_gate, dict) and risk_gate:
            result["risk_gate"] = risk_gate
        return result
'''

    new_record = '''    def _record(
        self,
        action: dict,
        profile: dict,
        public_status: str,
        error_code: str,
        message: str,
        evidence_path: str,
        attempt: int,
        risk_gate: dict[str, Any] | None = None,
        execution_mode: str = "",
        submission_state: str = "",
        verification_state: str = "",
        evidence_verified: bool = False,
    ) -> dict:
        action_id = str(action.get("id") or "")
        action_type = str(action.get("action_type") or "")
        profile_id = str(profile.get("profile_id") or profile.get("id") or "")
        execution_mode = str(execution_mode or self._active_execution_mode or "simulated")
        if public_status == "success":
            if execution_mode == "live":
                submission_state = submission_state or ("verified_success" if evidence_verified else "submitted_unverified")
                verification_state = verification_state or ("verified" if evidence_verified else "pending")
            elif execution_mode == "preflight":
                submission_state = submission_state or "prepared"
                verification_state = verification_state or "not_required"
            else:
                submission_state = submission_state or "not_attempted"
                verification_state = verification_state or "not_required"
        else:
            submission_state = submission_state or ("blocked" if public_status == "skipped" else "failed")
            verification_state = verification_state or "not_required"
            evidence_verified = False
        if not evidence_path:
            evidence_path = self._evidence_stub(action, profile, public_status or error_code or "recorded")
        execution_id = self.storage.create_outreach_execution(
            action_id,
            action_type,
            str(action.get("target_username") or ""),
            status=public_status,
            profile_id=profile_id,
            evidence_path=evidence_path,
            error_code=error_code,
            error_message=message,
            risk_gate=risk_gate,
            execution_mode=execution_mode,
            submission_state=submission_state,
            verification_state=verification_state,
            evidence_verified=evidence_verified,
        )
        recorded_action_status = public_status
        if public_status == "success" and execution_mode != "live":
            recorded_action_status = "approved" if str(action.get("status") or "") in {"approved", "retryable", "account_switched"} else "pending_review"
        self.storage.record_action_execution_result(
            action_id,
            execution_id,
            "completed" if public_status == "success" and execution_mode == "live" else recorded_action_status,
            error_code=error_code,
            error_message=message,
            retryable=public_status == "failed" and error_code in SWITCH_PROFILE_CODES,
        )
        if public_status in {"skipped", "failed"}:
            self.storage.update_action_status(action_id, public_status, message or error_code)
        elif public_status == "success" and execution_mode == "live":
            self.storage.update_action_status(action_id, "success", "verified live action success")
        elif public_status == "success":
            self.storage.update_action_status(
                action_id,
                recorded_action_status,
                f"{execution_mode} passed without live submission",
            )
        event_payload = {
            "profile_id": profile_id,
            "execution_id": execution_id,
            "error_code": error_code,
            "attempt": attempt,
            "risk_gate": risk_gate or {},
            "execution_mode": execution_mode,
            "submission_state": submission_state,
            "verification_state": verification_state,
            "evidence_verified": bool(evidence_verified),
            "counts_as_live_success": bool(
                public_status == "success"
                and execution_mode == "live"
                and submission_state == "verified_success"
                and verification_state == "verified"
                and evidence_verified
            ),
        }
        self.storage.log_event(f"action_router_{public_status}", action_id, event_payload)
        result = {
            "action_id": action_id,
            "execution_id": execution_id,
            "action_type": action_type,
            "public_action_type": PUBLIC_ACTION_TYPE.get(action_type, action_type),
            "status": public_status,
            "profile_id": profile_id,
            "attempt": attempt,
            "error_code": error_code,
            "error_message": message,
            "evidence_path": evidence_path,
            "execution_mode": execution_mode,
            "submission_state": submission_state,
            "verification_state": verification_state,
            "evidence_verified": bool(evidence_verified),
            "counts_as_live_success": event_payload["counts_as_live_success"],
        }
        if isinstance(risk_gate, dict) and risk_gate:
            result["risk_gate"] = risk_gate
        return result
'''
    replace_once(path, old_record, new_record)

    replace_once(
        path,
        '''            error_code=error_code,
            error_message=message,
        )
        self.storage.record_action_execution_result(
            action_id,
            execution_id,
            "account_switched",
''',
        '''            error_code=error_code,
            error_message=message,
            execution_mode=self._active_execution_mode,
            submission_state="blocked",
            verification_state="not_required",
            evidence_verified=False,
        )
        self.storage.record_action_execution_result(
            action_id,
            execution_id,
            "account_switched",
''',
    )

    replace_once(
        path,
        '''                    suggested_text=str(action.get("suggested_text") or ""),
                    status="pending",
                    risk_level=str(action.get("risk_level") or "medium"),
''',
        '''                    suggested_text="",
                    reason=f"fallback_from_action_id={str(action.get('id') or '')}",
                    status="pending",
                    risk_level=str(action.get("risk_level") or "medium"),
''',
    )


def patch_storage() -> None:
    path = ROOT / "ReachOps/intelligence/storage.py"

    replace_once(
        path,
        '''                    status TEXT DEFAULT 'pending',
                    profile_id TEXT DEFAULT '',
                    evidence_path TEXT DEFAULT '',
''',
        '''                    status TEXT DEFAULT 'pending',
                    execution_mode TEXT DEFAULT 'simulated',
                    submission_state TEXT DEFAULT 'not_attempted',
                    verification_state TEXT DEFAULT 'not_required',
                    evidence_verified INTEGER DEFAULT 0,
                    profile_id TEXT DEFAULT '',
                    evidence_path TEXT DEFAULT '',
''',
    )

    replace_once(
        path,
        '''            self._ensure_columns(conn, "outreach_executions", {"batch_id": "TEXT DEFAULT ''", "risk_gate_json": "TEXT DEFAULT ''"})
''',
        '''            self._ensure_columns(
                conn,
                "outreach_executions",
                {
                    "batch_id": "TEXT DEFAULT ''",
                    "risk_gate_json": "TEXT DEFAULT ''",
                    "execution_mode": "TEXT DEFAULT 'simulated'",
                    "submission_state": "TEXT DEFAULT 'not_attempted'",
                    "verification_state": "TEXT DEFAULT 'not_required'",
                    "evidence_verified": "INTEGER DEFAULT 0",
                },
            )
''',
    )

    replace_once(
        path,
        '''        error_message: str = "",
        risk_gate: Optional[Dict[str, Any]] = None,
    ) -> str:
''',
        '''        error_message: str = "",
        risk_gate: Optional[Dict[str, Any]] = None,
        execution_mode: str = "simulated",
        submission_state: str = "not_attempted",
        verification_state: str = "not_required",
        evidence_verified: bool = False,
    ) -> str:
''',
    )

    replace_once(
        path,
        '''                INSERT INTO outreach_executions
                (id, action_id, action_type, target_username, status, profile_id, evidence_path,
                 error_code, error_message, risk_gate_json, batch_id, started_at, completed_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
''',
        '''                INSERT INTO outreach_executions
                (id, action_id, action_type, target_username, status, execution_mode, submission_state,
                 verification_state, evidence_verified, profile_id, evidence_path, error_code, error_message,
                 risk_gate_json, batch_id, started_at, completed_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
''',
    )

    replace_once(
        path,
        '''                    status,
                    profile_id,
                    evidence_path,
                    error_code,
''',
        '''                    status,
                    str(execution_mode or "simulated"),
                    str(submission_state or "not_attempted"),
                    str(verification_state or "not_required"),
                    1 if evidence_verified else 0,
                    profile_id,
                    evidence_path,
                    error_code,
''',
    )

    replace_once(
        path,
        '''        return {str(row["status"] or ""): int(row["count"] or 0) for row in rows}

    def list_collection_batches(self, limit: int = 100, campaign_id: str = "") -> List[Dict[str, Any]]:
''',
        '''        return {str(row["status"] or ""): int(row["count"] or 0) for row in rows}

    def outreach_execution_truth_counts(self, batch_id: str = "") -> Dict[str, int]:
        batch_id = str(batch_id or "").strip()
        where = "WHERE batch_id=?" if batch_id else ""
        args = (batch_id,) if batch_id else ()
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT
                    SUM(CASE WHEN execution_mode='simulated' AND status='success' THEN 1 ELSE 0 END) AS simulated_success,
                    SUM(CASE WHEN execution_mode='dry_run' AND status='success' THEN 1 ELSE 0 END) AS dry_run_success,
                    SUM(CASE WHEN execution_mode='preflight' AND status='success' THEN 1 ELSE 0 END) AS preflight_passed,
                    SUM(CASE WHEN execution_mode='live' AND submission_state IN ('submitted', 'submitted_unverified', 'verified_success') THEN 1 ELSE 0 END) AS live_submitted,
                    SUM(CASE WHEN execution_mode='live'
                              AND submission_state='verified_success'
                              AND verification_state='verified'
                              AND evidence_verified=1
                              AND status='success'
                             THEN 1 ELSE 0 END) AS live_verified,
                    SUM(CASE WHEN execution_mode='live' AND status='failed' THEN 1 ELSE 0 END) AS live_failed
                FROM outreach_executions
                {where}
                """,
                args,
            ).fetchone()
        keys = ["simulated_success", "dry_run_success", "preflight_passed", "live_submitted", "live_verified", "live_failed"]
        return {key: int((row[key] if row else 0) or 0) for key in keys}

    def list_collection_batches(self, limit: int = 100, campaign_id: str = "") -> List[Dict[str, Any]]:
''',
    )


def patch_workflow_service() -> None:
    path = ROOT / "ReachOps/workbench/workflow_service.py"
    replace_once(
        path,
        '''        execution_status_counts = self.storage.outreach_execution_status_counts(batch_id) if batch_id else {}
        batch = progress.get("batch") or latest_batch or {}
''',
        '''        execution_status_counts = self.storage.outreach_execution_status_counts(batch_id) if batch_id else {}
        execution_truth_counts = self.storage.outreach_execution_truth_counts(batch_id) if batch_id else {}
        batch = progress.get("batch") or latest_batch or {}
''',
    )
    replace_once(
        path,
        '''                preflight_ok=int(execution_status_counts.get("success", 0) or 0),
                execution_success=int(execution_status_counts.get("success", 0) or 0),
''',
        '''                preflight_ok=int(execution_truth_counts.get("preflight_passed", 0) or 0),
                execution_success=int(execution_truth_counts.get("live_verified", 0) or 0),
''',
    )


def main() -> None:
    patch_action_router()
    patch_storage()
    patch_workflow_service()
    print("truthful execution P0 patch applied")


if __name__ == "__main__":
    main()
