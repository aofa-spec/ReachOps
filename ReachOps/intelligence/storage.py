# -*- coding: utf-8 -*-
"""SQLite storage for Growth Intelligence."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

from .schemas import (
    ActionQueueItem,
    AcquisitionCampaign,
    AcquisitionSource,
    AudiencePersona,
    CandidateUser,
    Checkpoint,
    CollectionBatch,
    CollectionTask,
    DataSource,
    DiscoveredContent,
    DiscoveredCreator,
    ProfileHealth,
    ScheduledScan,
    utc_now_iso,
)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def legacy_run_id_for_batch(batch_id: str) -> str:
    safe_batch = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(batch_id or "").strip())
    return f"legacy_run_{safe_batch or 'unknown'}"


class GrowthStorage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.active_collection_batch_id = ""
        self.active_campaign_run_id = ""
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.init_schema()

    def set_active_collection_batch(self, batch_id: str = ""):
        self.active_collection_batch_id = str(batch_id or "").strip()
        self.active_campaign_run_id = self.run_id_for_batch(self.active_collection_batch_id) if self.active_collection_batch_id else ""

    def _active_batch_id(self) -> str:
        return str(getattr(self, "active_collection_batch_id", "") or "")

    def _active_run_id(self) -> str:
        run_id = str(getattr(self, "active_campaign_run_id", "") or "")
        if run_id:
            return run_id
        batch_id = self._active_batch_id()
        return self.run_id_for_batch(batch_id) if batch_id else ""

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self):
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS data_sources (
                    id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    type TEXT NOT NULL,
                    value TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(platform, type, value)
                );
                CREATE TABLE IF NOT EXISTS discovered_creators (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    profile_url TEXT NOT NULL,
                    followers INTEGER DEFAULT 0,
                    likes_total INTEGER DEFAULT 0,
                    vertical TEXT DEFAULT 'general',
                    country TEXT DEFAULT '',
                    language TEXT DEFAULT 'unknown',
                    source_path TEXT DEFAULT '',
                    raw_meta TEXT DEFAULT '{}',
                    batch_id TEXT DEFAULT '',
                    run_id TEXT DEFAULT '',
                    status TEXT NOT NULL,
                    last_checked_at TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(source_id, username)
                );
                CREATE TABLE IF NOT EXISTS discovered_contents (
                    id TEXT PRIMARY KEY,
                    creator_id TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    video_url TEXT NOT NULL,
                    caption TEXT DEFAULT '',
                    views INTEGER DEFAULT 0,
                    likes INTEGER DEFAULT 0,
                    comments INTEGER DEFAULT 0,
                    shares INTEGER DEFAULT 0,
                    content_language TEXT DEFAULT 'unknown',
                    country TEXT DEFAULT '',
                    material_type TEXT DEFAULT 'creator_video',
                    collector_level TEXT DEFAULT 'selenium_dom',
                    source_path TEXT DEFAULT '',
                    raw_meta TEXT DEFAULT '{}',
                    batch_id TEXT DEFAULT '',
                    run_id TEXT DEFAULT '',
                    published_at TEXT,
                    collected_at TEXT NOT NULL,
                    UNIQUE(creator_id, video_id)
                );
                CREATE TABLE IF NOT EXISTS candidate_users (
                    id TEXT PRIMARY KEY,
                    content_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    profile_url TEXT NOT NULL,
                    comment_text TEXT DEFAULT '',
                    comment_likes INTEGER DEFAULT 0,
                    reply_count INTEGER DEFAULT 0,
                    qualify_score INTEGER DEFAULT 0,
                    intent_tags TEXT DEFAULT '[]',
                    batch_id TEXT DEFAULT '',
                    run_id TEXT DEFAULT '',
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(content_id, username, comment_text)
                );
                CREATE TABLE IF NOT EXISTS shop_products (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    platform TEXT DEFAULT 'tiktok',
                    product_id TEXT DEFAULT '',
                    product_url TEXT DEFAULT '',
                    title TEXT DEFAULT '',
                    shop_name TEXT DEFAULT '',
                    category TEXT DEFAULT '',
                    price TEXT DEFAULT '',
                    sales_text TEXT DEFAULT '',
                    rating TEXT DEFAULT '',
                    collected_at TEXT NOT NULL,
                    UNIQUE(source_id, product_id, product_url)
                );
                CREATE TABLE IF NOT EXISTS shop_contents (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    product_id TEXT DEFAULT '',
                    creator_username TEXT DEFAULT '',
                    video_id TEXT DEFAULT '',
                    video_url TEXT DEFAULT '',
                    caption TEXT DEFAULT '',
                    material_type TEXT DEFAULT 'unknown',
                    hook_text TEXT DEFAULT '',
                    views INTEGER DEFAULT 0,
                    likes INTEGER DEFAULT 0,
                    comments INTEGER DEFAULT 0,
                    shares INTEGER DEFAULT 0,
                    batch_id TEXT DEFAULT '',
                    run_id TEXT DEFAULT '',
                    collected_at TEXT NOT NULL,
                    UNIQUE(source_id, video_id, video_url)
                );
                CREATE TABLE IF NOT EXISTS material_signals (
                    id TEXT PRIMARY KEY,
                    content_id TEXT NOT NULL,
                    run_id TEXT DEFAULT '',
                    signal_type TEXT NOT NULL,
                    signal_score INTEGER DEFAULT 0,
                    signal_tags TEXT DEFAULT '[]',
                    evidence TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(content_id, signal_type)
                );
                CREATE TABLE IF NOT EXISTS audience_intents (
                    id TEXT PRIMARY KEY,
                    candidate_user_id TEXT NOT NULL,
                    content_id TEXT NOT NULL,
                    run_id TEXT DEFAULT '',
                    intent_type TEXT NOT NULL,
                    confidence INTEGER DEFAULT 0,
                    evidence TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(candidate_user_id, content_id, intent_type)
                );
                CREATE TABLE IF NOT EXISTS operation_leads (
                    id TEXT PRIMARY KEY,
                    candidate_user_id TEXT NOT NULL,
                    run_id TEXT DEFAULT '',
                    lead_type TEXT NOT NULL,
                    priority TEXT DEFAULT 'normal',
                    score INTEGER DEFAULT 0,
                    reason TEXT DEFAULT '',
                    lifecycle_stage TEXT DEFAULT 'new',
                    source_path TEXT DEFAULT '',
                    status TEXT DEFAULT 'new',
                    batch_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(candidate_user_id, lead_type)
                );
                CREATE TABLE IF NOT EXISTS action_queue (
                    id TEXT PRIMARY KEY,
                    lead_id TEXT NOT NULL,
                    run_id TEXT DEFAULT '',
                    action_type TEXT NOT NULL,
                    target_username TEXT NOT NULL,
                    target_url TEXT DEFAULT '',
                    suggested_text TEXT DEFAULT '',
                    reason TEXT DEFAULT '',
                    status TEXT DEFAULT 'pending_review',
                    risk_level TEXT DEFAULT 'medium',
                    batch_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(lead_id, action_type)
                );
                CREATE TABLE IF NOT EXISTS collection_batches (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT DEFAULT '',
                    run_id TEXT DEFAULT '',
                    status TEXT DEFAULT 'running',
                    total_sources INTEGER DEFAULT 0,
                    processed_sources INTEGER DEFAULT 0,
                    failed_sources INTEGER DEFAULT 0,
                    profile_group TEXT DEFAULT '',
                    config_json TEXT DEFAULT '{}',
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS campaign_runs (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL UNIQUE,
                    run_key TEXT NOT NULL UNIQUE,
                    status TEXT DEFAULT 'running',
                    profile_group TEXT DEFAULT '',
                    config_json TEXT DEFAULT '{}',
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS collection_tasks (
                    id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    run_id TEXT DEFAULT '',
                    source_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_value TEXT NOT NULL,
                    profile_id TEXT DEFAULT '',
                    status TEXT DEFAULT 'pending',
                    error_code TEXT DEFAULT '',
                    error_message TEXT DEFAULT '',
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS profile_health (
                    profile_id TEXT PRIMARY KEY,
                    group_name TEXT DEFAULT '',
                    health_score INTEGER DEFAULT 100,
                    status TEXT DEFAULT 'healthy',
                    consecutive_failures INTEGER DEFAULT 0,
                    last_error_code TEXT DEFAULT '',
                    last_error_message TEXT DEFAULT '',
                    last_used_at TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scheduled_scans (
                    id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    source_value TEXT NOT NULL,
                    profile_group TEXT DEFAULT '',
                    schedule_interval_minutes INTEGER DEFAULT 60,
                    next_run_at TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    max_videos INTEGER DEFAULT 5,
                    max_comments INTEGER DEFAULT 10,
                    min_views INTEGER DEFAULT 0,
                    min_comments INTEGER DEFAULT 0,
                    last_batch_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS acquisition_campaigns (
                    id TEXT PRIMARY KEY,
                    input_type TEXT NOT NULL,
                    input_value TEXT NOT NULL,
                    objective TEXT DEFAULT 'customer_acquisition',
                    target_market TEXT DEFAULT 'auto',
                    target_language TEXT DEFAULT 'auto',
                    product_name TEXT DEFAULT '',
                    category TEXT DEFAULT '',
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audience_personas (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL,
                    demographics_json TEXT DEFAULT '{}',
                    interests_json TEXT DEFAULT '[]',
                    pain_points_json TEXT DEFAULT '[]',
                    buying_triggers_json TEXT DEFAULT '[]',
                    intent_keywords_json TEXT DEFAULT '[]',
                    exclude_keywords_json TEXT DEFAULT '[]',
                    search_keywords_json TEXT DEFAULT '[]',
                    hashtags_json TEXT DEFAULT '[]',
                    competitor_terms_json TEXT DEFAULT '[]',
                    outreach_angles_json TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(campaign_id)
                );
                CREATE TABLE IF NOT EXISTS acquisition_sources (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_value TEXT NOT NULL,
                    reason TEXT DEFAULT '',
                    priority INTEGER DEFAULT 50,
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(campaign_id, source_type, source_value)
                );
                CREATE TABLE IF NOT EXISTS campaign_strategy_overrides (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL UNIQUE,
                    overrides_json TEXT DEFAULT '{}',
                    updated_by TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS action_templates (
                    id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS exclusion_rules (
                    id TEXT PRIMARY KEY,
                    target_username TEXT DEFAULT '',
                    target_url TEXT DEFAULT '',
                    reason TEXT DEFAULT '',
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(target_username, target_url)
                );
                CREATE TABLE IF NOT EXISTS growth_filter_presets (
                    id TEXT PRIMARY KEY,
                    view_name TEXT NOT NULL,
                    name TEXT NOT NULL,
                    filters_json TEXT DEFAULT '{}',
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(view_name, name)
                );
                CREATE TABLE IF NOT EXISTS outreach_daily_quota (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    quota_date TEXT NOT NULL,
                    used_count INTEGER DEFAULT 0,
                    limit_count INTEGER DEFAULT 20,
                    updated_at TEXT NOT NULL,
                    UNIQUE(profile_id, action_type, quota_date)
                );
                CREATE TABLE IF NOT EXISTS outreach_rate_limits (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_value TEXT NOT NULL,
                    window_key TEXT NOT NULL,
                    used_count INTEGER DEFAULT 0,
                    limit_count INTEGER DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    UNIQUE(profile_id, action_type, scope_type, scope_value, window_key)
                );
                CREATE TABLE IF NOT EXISTS execution_plans (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT DEFAULT '',
                    selected_count INTEGER DEFAULT 0,
                    planned_count INTEGER DEFAULT 0,
                    executable_count INTEGER DEFAULT 0,
                    skipped_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'planned',
                    plan_json TEXT DEFAULT '{}',
                    export_path TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS action_logs (
                    id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    note TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outreach_executions (
                    id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL,
                    run_id TEXT DEFAULT '',
                    action_type TEXT NOT NULL,
                    target_username TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    execution_mode TEXT DEFAULT 'simulated',
                    submission_state TEXT DEFAULT 'not_attempted',
                    verification_state TEXT DEFAULT 'not_required',
                    evidence_verified INTEGER DEFAULT 0,
                    profile_id TEXT DEFAULT '',
                    evidence_path TEXT DEFAULT '',
                    error_code TEXT DEFAULT '',
                    error_message TEXT DEFAULT '',
                    risk_gate_json TEXT DEFAULT '',
                    batch_id TEXT DEFAULT '',
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS checkpoints (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    creator_id TEXT NOT NULL,
                    last_video_id TEXT DEFAULT '',
                    last_checked_at TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_id, creator_id)
                );
                CREATE TABLE IF NOT EXISTS growth_events (
                    id TEXT PRIMARY KEY,
                    event TEXT NOT NULL,
                    entity_id TEXT DEFAULT '',
                    run_id TEXT DEFAULT '',
                    payload TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS growth_errors (
                    id TEXT PRIMARY KEY,
                    error_code TEXT NOT NULL,
                    message TEXT DEFAULT '',
                    source_id TEXT DEFAULT '',
                    creator_id TEXT DEFAULT '',
                    profile_id TEXT DEFAULT '',
                    batch_id TEXT DEFAULT '',
                    run_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_observations (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    campaign_id TEXT DEFAULT '',
                    batch_id TEXT DEFAULT '',
                    source_id TEXT DEFAULT '',
                    source_type TEXT DEFAULT '',
                    source_value TEXT DEFAULT '',
                    observation_key TEXT NOT NULL,
                    payload_json TEXT DEFAULT '{}',
                    observed_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, source_id, observation_key)
                );
                CREATE TABLE IF NOT EXISTS content_observations (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    campaign_id TEXT DEFAULT '',
                    batch_id TEXT DEFAULT '',
                    content_id TEXT DEFAULT '',
                    source_observation_id TEXT DEFAULT '',
                    observation_key TEXT NOT NULL,
                    payload_json TEXT DEFAULT '{}',
                    observed_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, content_id, observation_key)
                );
                CREATE TABLE IF NOT EXISTS comment_observations (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    campaign_id TEXT DEFAULT '',
                    batch_id TEXT DEFAULT '',
                    content_id TEXT DEFAULT '',
                    candidate_user_id TEXT DEFAULT '',
                    username TEXT DEFAULT '',
                    comment_text TEXT DEFAULT '',
                    observation_key TEXT NOT NULL,
                    payload_json TEXT DEFAULT '{}',
                    observed_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, content_id, username, observation_key)
                );
                CREATE TABLE IF NOT EXISTS candidate_observations (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    campaign_id TEXT DEFAULT '',
                    batch_id TEXT DEFAULT '',
                    candidate_user_id TEXT DEFAULT '',
                    comment_observation_id TEXT DEFAULT '',
                    username TEXT DEFAULT '',
                    score INTEGER DEFAULT 0,
                    intent_tags_json TEXT DEFAULT '[]',
                    observation_key TEXT NOT NULL,
                    payload_json TEXT DEFAULT '{}',
                    observed_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, candidate_user_id, observation_key)
                );
                CREATE TABLE IF NOT EXISTS lead_decisions (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    campaign_id TEXT DEFAULT '',
                    batch_id TEXT DEFAULT '',
                    candidate_user_id TEXT NOT NULL,
                    lead_id TEXT DEFAULT '',
                    decision_version INTEGER DEFAULT 1,
                    decision_type TEXT NOT NULL,
                    score INTEGER DEFAULT 0,
                    reason TEXT DEFAULT '',
                    payload_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, candidate_user_id, decision_version, decision_type)
                );
                """
            )
            self._ensure_columns(
                conn,
                "discovered_creators",
                {
                    "vertical": "TEXT DEFAULT 'general'",
                    "country": "TEXT DEFAULT ''",
                    "language": "TEXT DEFAULT 'unknown'",
                    "source_path": "TEXT DEFAULT ''",
                    "raw_meta": "TEXT DEFAULT '{}'",
                    "batch_id": "TEXT DEFAULT ''",
                    "run_id": "TEXT DEFAULT ''",
                },
            )
            self._ensure_columns(
                conn,
                "discovered_contents",
                {
                    "content_language": "TEXT DEFAULT 'unknown'",
                    "country": "TEXT DEFAULT ''",
                    "material_type": "TEXT DEFAULT 'creator_video'",
                    "collector_level": "TEXT DEFAULT 'selenium_dom'",
                    "source_path": "TEXT DEFAULT ''",
                    "raw_meta": "TEXT DEFAULT '{}'",
                    "batch_id": "TEXT DEFAULT ''",
                    "run_id": "TEXT DEFAULT ''",
                },
            )
            self._ensure_columns(
                conn,
                "action_queue",
                {
                    "review_status": "TEXT DEFAULT 'pending'",
                    "reviewed_by": "TEXT DEFAULT ''",
                    "reviewed_at": "TEXT",
                    "review_note": "TEXT DEFAULT ''",
                    "daily_quota_key": "TEXT DEFAULT ''",
                    "reason": "TEXT DEFAULT ''",
                    "execution_confirmed": "INTEGER DEFAULT 0",
                    "confirmed_by": "TEXT DEFAULT ''",
                    "confirmed_at": "TEXT",
                    "retry_count": "INTEGER DEFAULT 0",
                    "last_execution_id": "TEXT DEFAULT ''",
                    "last_error_code": "TEXT DEFAULT ''",
                    "last_error_message": "TEXT DEFAULT ''",
                    "last_executed_at": "TEXT",
                    "batch_id": "TEXT DEFAULT ''",
                    "run_id": "TEXT DEFAULT ''",
                },
            )
            self._ensure_columns(
                conn,
                "candidate_users",
                {
                    "comment_language": "TEXT DEFAULT 'unknown'",
                    "author_profile_completed": "INTEGER DEFAULT 0",
                    "collector_level": "TEXT DEFAULT 'selenium_dom'",
                    "source_path": "TEXT DEFAULT ''",
                    "repeat_seen_count": "INTEGER DEFAULT 1",
                    "raw_meta": "TEXT DEFAULT '{}'",
                    "batch_id": "TEXT DEFAULT ''",
                    "run_id": "TEXT DEFAULT ''",
                },
            )
            self._ensure_columns(conn, "shop_contents", {"batch_id": "TEXT DEFAULT ''", "run_id": "TEXT DEFAULT ''"})
            self._ensure_columns(conn, "collection_batches", {"campaign_id": "TEXT DEFAULT ''", "run_id": "TEXT DEFAULT ''"})
            self._ensure_columns(conn, "collection_tasks", {"run_id": "TEXT DEFAULT ''"})
            self._ensure_columns(conn, "material_signals", {"run_id": "TEXT DEFAULT ''"})
            self._ensure_columns(conn, "audience_intents", {"run_id": "TEXT DEFAULT ''"})
            self._ensure_columns(
                conn,
                "operation_leads",
                {
                    "lifecycle_stage": "TEXT DEFAULT 'new'",
                    "source_path": "TEXT DEFAULT ''",
                    "batch_id": "TEXT DEFAULT ''",
                    "run_id": "TEXT DEFAULT ''",
                    "updated_at": "TEXT DEFAULT ''",
                },
            )
            self._ensure_columns(
                conn,
                "outreach_executions",
                {
                    "batch_id": "TEXT DEFAULT ''",
                    "run_id": "TEXT DEFAULT ''",
                    "risk_gate_json": "TEXT DEFAULT ''",
                    "execution_mode": "TEXT DEFAULT 'simulated'",
                    "submission_state": "TEXT DEFAULT 'not_attempted'",
                    "verification_state": "TEXT DEFAULT 'not_required'",
                    "evidence_verified": "INTEGER DEFAULT 0",
                },
            )
            self._ensure_columns(conn, "growth_events", {"run_id": "TEXT DEFAULT ''"})
            self._ensure_columns(conn, "growth_errors", {"batch_id": "TEXT DEFAULT ''", "run_id": "TEXT DEFAULT ''"})
            self._ensure_campaign_runs_for_existing_batches(conn)
            self._seed_default_action_templates(conn)

    def _ensure_columns(self, conn, table_name: str, columns: Dict[str, str]):
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")

    def _ensure_campaign_runs_for_existing_batches(self, conn):
        now = utc_now_iso()
        rows = conn.execute(
            """
            SELECT cb.*
            FROM collection_batches cb
            LEFT JOIN campaign_runs cr ON cr.batch_id = cb.id
            WHERE cr.id IS NULL
            ORDER BY cb.created_at ASC, cb.rowid ASC
            """
        ).fetchall()
        for row in rows:
            batch_id = str(row["id"] or "")
            run_id = str(row["run_id"] or "") if "run_id" in row.keys() else ""
            is_legacy_backfill = not run_id
            run_id = run_id or legacy_run_id_for_batch(batch_id)
            campaign_id = str(row["campaign_id"] or "")
            created_at = str(row["created_at"] or now)
            started_at = row["started_at"] or created_at
            updated_at = str(row["updated_at"] or created_at)
            completed_at = row["completed_at"]
            status = str(row["status"] or "running")
            run_key = f"{'legacy' if is_legacy_backfill else campaign_id or 'uncampaign'}:{batch_id}"
            try:
                config = json.loads(str(row["config_json"] or "{}"))
            except Exception:
                config = {}
            if is_legacy_backfill:
                config.update(
                    {
                        "legacy_backfill": True,
                        "legacy_handling_strategy": "deterministic_legacy_run_id_for_existing_batch_only",
                        "legacy_original_batch_id": batch_id,
                    }
                )
            conn.execute(
                """
                INSERT OR IGNORE INTO campaign_runs
                (id, campaign_id, batch_id, run_key, status, profile_group, config_json,
                 started_at, completed_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    campaign_id,
                    batch_id,
                    run_key,
                    status,
                    str(row["profile_group"] or ""),
                    json.dumps(config, ensure_ascii=False),
                    started_at,
                    completed_at,
                    created_at,
                    updated_at,
                ),
            )
            conn.execute("UPDATE collection_batches SET run_id=? WHERE id=? AND COALESCE(run_id, '')=''", (run_id, batch_id))

    def _seed_default_action_templates(self, conn):
        now = utc_now_iso()
        defaults = [
            ("tpl_comment_reply_default", "comment_reply", "默认评论回复", "这个问题很典型，我整理一下关键信息再补充。"),
            ("tpl_follow_review_default", "follow_review", "默认关注复核", "复核该用户是否为高意图用户，确认后再关注。"),
            ("tpl_dm_review_default", "dm_review", "默认私信复核", "Hi @{username}, saw your comment about {lead_type}. I can share the details if you still need them."),
        ]
        for tpl_id, action_type, name, body in defaults:
            conn.execute(
                """
                INSERT OR IGNORE INTO action_templates (id, action_type, name, body, status, created_at)
                VALUES (?, ?, ?, ?, 'active', ?)
                """,
                (tpl_id, action_type, name, body, now),
            )

    def log_event(self, event: str, entity_id: str = "", payload: Optional[Dict[str, Any]] = None):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO growth_events (id, event, entity_id, run_id, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (new_id("evt"), event, entity_id, self._active_run_id(), json.dumps(payload or {}, ensure_ascii=False), utc_now_iso()),
            )

    def list_recent_events(self, event: str = "", limit: int = 200) -> List[Dict[str, Any]]:
        event_name = str(event or "").strip()
        with self.connect() as conn:
            if event_name:
                rows = conn.execute(
                    "SELECT * FROM growth_events WHERE event=? ORDER BY created_at DESC LIMIT ?",
                    (event_name, int(limit or 200)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM growth_events ORDER BY created_at DESC LIMIT ?",
                    (int(limit or 200),),
                ).fetchall()
        return [dict(row) for row in rows]

    def list_events_for_entities(self, entity_ids: List[str], limit: int = 300) -> List[Dict[str, Any]]:
        ids = [str(entity_id or "").strip() for entity_id in entity_ids or [] if str(entity_id or "").strip()]
        if not ids:
            return []
        placeholders = ",".join(["?"] * len(ids))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM growth_events
                WHERE entity_id IN ({placeholders})
                ORDER BY created_at ASC
                LIMIT ?
                """,
                tuple(ids + [int(limit or 300)]),
            ).fetchall()
        return [dict(row) for row in rows]

    def log_error(self, error_code: str, message: str = "", source_id: str = "", creator_id: str = "", profile_id: str = ""):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO growth_errors (id, error_code, message, source_id, creator_id, profile_id, batch_id, run_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (new_id("err"), error_code, message, source_id, creator_id, profile_id, self._active_batch_id(), self._active_run_id(), utc_now_iso()),
            )

    def create_campaign(
        self,
        input_type: str,
        input_value: str,
        objective: str = "customer_acquisition",
        target_market: str = "auto",
        target_language: str = "auto",
        product_name: str = "",
        category: str = "",
        status: str = "active",
    ) -> AcquisitionCampaign:
        now = utc_now_iso()
        item = AcquisitionCampaign(
            id=new_id("acq"),
            input_type=str(input_type or "keyword"),
            input_value=str(input_value or ""),
            objective=objective or "customer_acquisition",
            target_market=target_market or "auto",
            target_language=target_language or "auto",
            product_name=product_name or "",
            category=category or "",
            status=status or "active",
            created_at=now,
            updated_at=now,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO acquisition_campaigns
                (id, input_type, input_value, objective, target_market, target_language,
                 product_name, category, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.input_type,
                    item.input_value,
                    item.objective,
                    item.target_market,
                    item.target_language,
                    item.product_name,
                    item.category,
                    item.status,
                    item.created_at,
                    item.updated_at,
                ),
            )
        self.log_event("acquisition_campaign_created", item.id, item.__dict__)
        return item

    def upsert_audience_persona(self, persona: AudiencePersona) -> AudiencePersona:
        now = utc_now_iso()
        persona.updated_at = now
        with self.connect() as conn:
            row = conn.execute("SELECT id, created_at FROM audience_personas WHERE campaign_id=?", (persona.campaign_id,)).fetchone()
            if row:
                persona.id = row["id"]
                persona.created_at = row["created_at"]
                conn.execute(
                    """
                    UPDATE audience_personas
                    SET demographics_json=?, interests_json=?, pain_points_json=?, buying_triggers_json=?,
                        intent_keywords_json=?, exclude_keywords_json=?, search_keywords_json=?, hashtags_json=?,
                        competitor_terms_json=?, outreach_angles_json=?, updated_at=?
                    WHERE id=?
                    """,
                    self._persona_values(persona)[2:12] + (persona.updated_at, persona.id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO audience_personas
                    (id, campaign_id, demographics_json, interests_json, pain_points_json, buying_triggers_json,
                     intent_keywords_json, exclude_keywords_json, search_keywords_json, hashtags_json,
                     competitor_terms_json, outreach_angles_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._persona_values(persona),
                )
        self.log_event("audience_persona_created", persona.campaign_id, {"persona_id": persona.id})
        return persona

    def _persona_values(self, persona: AudiencePersona) -> tuple:
        return (
            persona.id,
            persona.campaign_id,
            json.dumps(persona.demographics or {}, ensure_ascii=False),
            json.dumps(persona.interests or [], ensure_ascii=False),
            json.dumps(persona.pain_points or [], ensure_ascii=False),
            json.dumps(persona.buying_triggers or [], ensure_ascii=False),
            json.dumps(persona.intent_keywords or [], ensure_ascii=False),
            json.dumps(persona.exclude_keywords or [], ensure_ascii=False),
            json.dumps(persona.search_keywords or [], ensure_ascii=False),
            json.dumps(persona.hashtags or [], ensure_ascii=False),
            json.dumps(persona.competitor_terms or [], ensure_ascii=False),
            json.dumps(persona.outreach_angles or [], ensure_ascii=False),
            persona.created_at,
            persona.updated_at,
        )

    def upsert_acquisition_source(self, source: AcquisitionSource) -> AcquisitionSource:
        now = utc_now_iso()
        source.updated_at = now
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id, created_at FROM acquisition_sources WHERE campaign_id=? AND source_type=? AND source_value=?",
                (source.campaign_id, source.source_type, source.source_value),
            ).fetchone()
            if row:
                source.id = row["id"]
                source.created_at = row["created_at"]
                conn.execute(
                    """
                    UPDATE acquisition_sources
                    SET reason=?, priority=?, status=?, updated_at=?
                    WHERE id=?
                    """,
                    (source.reason, int(source.priority or 50), source.status, source.updated_at, source.id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO acquisition_sources
                    (id, campaign_id, source_type, source_value, reason, priority, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source.id,
                        source.campaign_id,
                        source.source_type,
                        source.source_value,
                        source.reason,
                        int(source.priority or 50),
                        source.status,
                        source.created_at,
                        source.updated_at,
                    ),
                )
        self.log_event("acquisition_source_planned", source.campaign_id, source.__dict__)
        return source

    def list_campaigns(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM acquisition_campaigns ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (int(limit or 100),),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_campaign(self) -> Dict[str, Any]:
        rows = self.list_campaigns(limit=1)
        return rows[0] if rows else {}

    def run_id_for_batch(self, batch_id: str) -> str:
        batch = str(batch_id or "").strip()
        if not batch:
            return ""
        with self.connect() as conn:
            row = conn.execute("SELECT run_id FROM collection_batches WHERE id=?", (batch,)).fetchone()
            if row and str(row["run_id"] or "").strip():
                return str(row["run_id"] or "").strip()
            row = conn.execute("SELECT id FROM campaign_runs WHERE batch_id=?", (batch,)).fetchone()
            return str(row["id"] or "").strip() if row else ""

    def list_campaign_runs(self, campaign_id: str = "", limit: int = 100) -> List[Dict[str, Any]]:
        filters = []
        args: list[Any] = []
        if campaign_id:
            filters.append("campaign_id=?")
            args.append(str(campaign_id))
        where = "WHERE " + " AND ".join(filters) if filters else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM campaign_runs
                {where}
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                tuple(args + [int(limit or 100)]),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_campaign_run(self, run_id: str = "", batch_id: str = "") -> Dict[str, Any]:
        run = str(run_id or "").strip()
        batch = str(batch_id or "").strip()
        if not run and not batch:
            return {}
        with self.connect() as conn:
            if run:
                row = conn.execute("SELECT * FROM campaign_runs WHERE id=?", (run,)).fetchone()
            else:
                row = conn.execute("SELECT * FROM campaign_runs WHERE batch_id=?", (batch,)).fetchone()
        return dict(row) if row else {}

    def list_audience_personas(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audience_personas ORDER BY updated_at DESC LIMIT ?",
                (int(limit or 100),),
            ).fetchall()
        return [self._row_to_persona_dict(row) for row in rows]

    def get_audience_persona(self, campaign_id: str) -> Dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM audience_personas WHERE campaign_id=?", (campaign_id,)).fetchone()
        return self._row_to_persona_dict(row) if row else {}

    def list_acquisition_sources(self, campaign_id: str = "", limit: int = 200) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            if campaign_id:
                rows = conn.execute(
                    "SELECT * FROM acquisition_sources WHERE campaign_id=? ORDER BY priority DESC, created_at ASC, rowid ASC LIMIT ?",
                    (campaign_id, int(limit or 200)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM acquisition_sources ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (int(limit or 200),),
                ).fetchall()
        return [dict(row) for row in rows]

    def _run_context(self, conn, run_id: str = "", batch_id: str = "") -> Dict[str, Any]:
        run = str(run_id or "").strip()
        batch = str(batch_id or "").strip()
        if run:
            row = conn.execute("SELECT * FROM campaign_runs WHERE id=?", (run,)).fetchone()
        elif batch:
            row = conn.execute("SELECT * FROM campaign_runs WHERE batch_id=?", (batch,)).fetchone()
        else:
            active_run = self._active_run_id()
            row = conn.execute("SELECT * FROM campaign_runs WHERE id=?", (active_run,)).fetchone() if active_run else None
        if not row:
            raise ValueError("campaign run is required for immutable observation records")
        return dict(row)

    def record_source_observation(
        self,
        run_id: str,
        source_id: str,
        source_type: str,
        source_value: str,
        observation_key: str,
        payload: Optional[Dict[str, Any]] = None,
        observed_at: str = "",
    ) -> str:
        now = utc_now_iso()
        with self.connect() as conn:
            run = self._run_context(conn, run_id=run_id)
            item_id = new_id("sobs")
            conn.execute(
                """
                INSERT OR IGNORE INTO source_observations
                (id, run_id, campaign_id, batch_id, source_id, source_type, source_value,
                 observation_key, payload_json, observed_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    run["id"],
                    run.get("campaign_id") or "",
                    run.get("batch_id") or "",
                    str(source_id or ""),
                    str(source_type or ""),
                    str(source_value or ""),
                    str(observation_key or "source_observed"),
                    json.dumps(payload or {}, ensure_ascii=False),
                    observed_at or now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM source_observations WHERE run_id=? AND source_id=? AND observation_key=?",
                (run["id"], str(source_id or ""), str(observation_key or "source_observed")),
            ).fetchone()
            return row["id"] if row else item_id

    def record_content_observation(
        self,
        run_id: str,
        content_id: str,
        observation_key: str,
        payload: Optional[Dict[str, Any]] = None,
        source_observation_id: str = "",
        observed_at: str = "",
    ) -> str:
        now = utc_now_iso()
        with self.connect() as conn:
            run = self._run_context(conn, run_id=run_id)
            item_id = new_id("cobs")
            conn.execute(
                """
                INSERT OR IGNORE INTO content_observations
                (id, run_id, campaign_id, batch_id, content_id, source_observation_id,
                 observation_key, payload_json, observed_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    run["id"],
                    run.get("campaign_id") or "",
                    run.get("batch_id") or "",
                    str(content_id or ""),
                    str(source_observation_id or ""),
                    str(observation_key or "content_observed"),
                    json.dumps(payload or {}, ensure_ascii=False),
                    observed_at or now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM content_observations WHERE run_id=? AND content_id=? AND observation_key=?",
                (run["id"], str(content_id or ""), str(observation_key or "content_observed")),
            ).fetchone()
            return row["id"] if row else item_id

    def record_comment_observation(
        self,
        run_id: str,
        content_id: str,
        candidate_user_id: str,
        username: str,
        comment_text: str,
        observation_key: str,
        payload: Optional[Dict[str, Any]] = None,
        observed_at: str = "",
    ) -> str:
        now = utc_now_iso()
        with self.connect() as conn:
            run = self._run_context(conn, run_id=run_id)
            item_id = new_id("mobs")
            conn.execute(
                """
                INSERT OR IGNORE INTO comment_observations
                (id, run_id, campaign_id, batch_id, content_id, candidate_user_id, username,
                 comment_text, observation_key, payload_json, observed_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    run["id"],
                    run.get("campaign_id") or "",
                    run.get("batch_id") or "",
                    str(content_id or ""),
                    str(candidate_user_id or ""),
                    str(username or ""),
                    str(comment_text or ""),
                    str(observation_key or "comment_observed"),
                    json.dumps(payload or {}, ensure_ascii=False),
                    observed_at or now,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT id FROM comment_observations
                WHERE run_id=? AND content_id=? AND username=? AND observation_key=?
                """,
                (run["id"], str(content_id or ""), str(username or ""), str(observation_key or "comment_observed")),
            ).fetchone()
            return row["id"] if row else item_id

    def record_candidate_observation(
        self,
        run_id: str,
        candidate_user_id: str,
        username: str,
        score: int,
        intent_tags: List[str],
        observation_key: str,
        payload: Optional[Dict[str, Any]] = None,
        comment_observation_id: str = "",
        observed_at: str = "",
    ) -> str:
        now = utc_now_iso()
        with self.connect() as conn:
            run = self._run_context(conn, run_id=run_id)
            item_id = new_id("uobs")
            conn.execute(
                """
                INSERT OR IGNORE INTO candidate_observations
                (id, run_id, campaign_id, batch_id, candidate_user_id, comment_observation_id,
                 username, score, intent_tags_json, observation_key, payload_json, observed_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    run["id"],
                    run.get("campaign_id") or "",
                    run.get("batch_id") or "",
                    str(candidate_user_id or ""),
                    str(comment_observation_id or ""),
                    str(username or ""),
                    int(score or 0),
                    json.dumps(intent_tags or [], ensure_ascii=False),
                    str(observation_key or "candidate_observed"),
                    json.dumps(payload or {}, ensure_ascii=False),
                    observed_at or now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM candidate_observations WHERE run_id=? AND candidate_user_id=? AND observation_key=?",
                (run["id"], str(candidate_user_id or ""), str(observation_key or "candidate_observed")),
            ).fetchone()
            return row["id"] if row else item_id

    def record_lead_decision(
        self,
        run_id: str,
        candidate_user_id: str,
        decision_type: str,
        score: int = 0,
        reason: str = "",
        lead_id: str = "",
        payload: Optional[Dict[str, Any]] = None,
        decision_version: int = 0,
    ) -> str:
        now = utc_now_iso()
        with self.connect() as conn:
            run = self._run_context(conn, run_id=run_id)
            if int(decision_version or 0) <= 0:
                row = conn.execute(
                    """
                    SELECT COALESCE(MAX(decision_version), 0) AS latest_version
                    FROM lead_decisions
                    WHERE run_id=? AND candidate_user_id=? AND decision_type=?
                    """,
                    (run["id"], str(candidate_user_id or ""), str(decision_type or "lead_decision")),
                ).fetchone()
                decision_version = int(row["latest_version"] or 0) + 1
            item_id = new_id("ld")
            conn.execute(
                """
                INSERT INTO lead_decisions
                (id, run_id, campaign_id, batch_id, candidate_user_id, lead_id, decision_version,
                 decision_type, score, reason, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    run["id"],
                    run.get("campaign_id") or "",
                    run.get("batch_id") or "",
                    str(candidate_user_id or ""),
                    str(lead_id or ""),
                    int(decision_version or 1),
                    str(decision_type or "lead_decision"),
                    int(score or 0),
                    str(reason or ""),
                    json.dumps(payload or {}, ensure_ascii=False),
                    now,
                ),
            )
            return item_id

    def list_observations_for_run(self, run_id: str) -> Dict[str, List[Dict[str, Any]]]:
        run = str(run_id or "").strip()
        if not run:
            return {}
        with self.connect() as conn:
            return {
                "source_observations": [dict(row) for row in conn.execute("SELECT * FROM source_observations WHERE run_id=? ORDER BY created_at ASC", (run,)).fetchall()],
                "content_observations": [dict(row) for row in conn.execute("SELECT * FROM content_observations WHERE run_id=? ORDER BY created_at ASC", (run,)).fetchall()],
                "comment_observations": [dict(row) for row in conn.execute("SELECT * FROM comment_observations WHERE run_id=? ORDER BY created_at ASC", (run,)).fetchall()],
                "candidate_observations": [dict(row) for row in conn.execute("SELECT * FROM candidate_observations WHERE run_id=? ORDER BY created_at ASC", (run,)).fetchall()],
                "lead_decisions": [dict(row) for row in conn.execute("SELECT * FROM lead_decisions WHERE run_id=? ORDER BY decision_version ASC, created_at ASC", (run,)).fetchall()],
                "outreach_executions": [dict(row) for row in conn.execute("SELECT * FROM outreach_executions WHERE run_id=? ORDER BY created_at ASC", (run,)).fetchall()],
                "growth_events": [dict(row) for row in conn.execute("SELECT * FROM growth_events WHERE run_id=? ORDER BY created_at ASC", (run,)).fetchall()],
                "growth_errors": [dict(row) for row in conn.execute("SELECT * FROM growth_errors WHERE run_id=? ORDER BY created_at ASC", (run,)).fetchall()],
            }

    def upsert_campaign_strategy_overrides(self, campaign_id: str, overrides: Dict[str, Any], updated_by: str = "") -> Dict[str, Any]:
        campaign_id = str(campaign_id or "").strip()
        if not campaign_id:
            raise ValueError("campaign_id is required")
        now = utc_now_iso()
        payload = json.dumps(overrides or {}, ensure_ascii=False)
        with self.connect() as conn:
            row = conn.execute("SELECT id, created_at FROM campaign_strategy_overrides WHERE campaign_id=?", (campaign_id,)).fetchone()
            if row:
                item_id = row["id"]
                created_at = row["created_at"]
                conn.execute(
                    """
                    UPDATE campaign_strategy_overrides
                    SET overrides_json=?, updated_by=?, updated_at=?
                    WHERE id=?
                    """,
                    (payload, str(updated_by or ""), now, item_id),
                )
            else:
                item_id = new_id("cso")
                created_at = now
                conn.execute(
                    """
                    INSERT INTO campaign_strategy_overrides
                    (id, campaign_id, overrides_json, updated_by, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (item_id, campaign_id, payload, str(updated_by or ""), created_at, now),
                )
        self.log_event("campaign_strategy_overrides_saved", campaign_id, {"override_id": item_id, "updated_by": updated_by})
        return {
            "id": item_id,
            "campaign_id": campaign_id,
            "overrides": overrides or {},
            "updated_by": str(updated_by or ""),
            "created_at": created_at,
            "updated_at": now,
        }

    def get_campaign_strategy_overrides(self, campaign_id: str) -> Dict[str, Any]:
        campaign_id = str(campaign_id or "").strip()
        if not campaign_id:
            return {}
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM campaign_strategy_overrides WHERE campaign_id=?", (campaign_id,)).fetchone()
        if not row:
            return {}
        data = dict(row)
        try:
            data["overrides"] = json.loads(data.get("overrides_json") or "{}")
        except Exception:
            data["overrides"] = {}
        return data

    def upsert_datasource(self, platform: str, source_type: str, value: str, status: str = "active") -> DataSource:
        now = utc_now_iso()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM data_sources WHERE platform=? AND type=? AND value=?",
                (platform, source_type, value),
            ).fetchone()
            if row:
                conn.execute("UPDATE data_sources SET status=?, updated_at=? WHERE id=?", (status, now, row["id"]))
                return self._row_to_datasource(conn.execute("SELECT * FROM data_sources WHERE id=?", (row["id"],)).fetchone())
            ds = DataSource(id=new_id("ds"), platform=platform, type=source_type, value=value, status=status, created_at=now, updated_at=now)
            conn.execute(
                "INSERT INTO data_sources VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ds.id, ds.platform, ds.type, ds.value, ds.status, ds.created_at, ds.updated_at),
            )
            return ds

    def upsert_creator(self, creator: DiscoveredCreator) -> DiscoveredCreator:
        now = utc_now_iso()
        run_id = self._active_run_id()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM discovered_creators WHERE source_id=? AND username=?",
                (creator.source_id, creator.username),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE discovered_creators
                    SET profile_url=?, followers=?, likes_total=?, vertical=?, country=?, language=?,
                        source_path=?, raw_meta=?, status=?, last_checked_at=?
                    WHERE id=?
                    """,
                    (
                        creator.profile_url,
                        creator.followers,
                        creator.likes_total,
                        creator.vertical,
                        creator.country,
                        creator.language,
                        creator.source_path,
                        json.dumps(creator.raw_meta or {}, ensure_ascii=False),
                        creator.status,
                        now,
                        row["id"],
                    ),
                )
                return self._row_to_creator(conn.execute("SELECT * FROM discovered_creators WHERE id=?", (row["id"],)).fetchone())
            creator.last_checked_at = creator.last_checked_at or now
            conn.execute(
                """
                INSERT INTO discovered_creators
                (id, source_id, username, profile_url, followers, likes_total, vertical, country,
                 language, source_path, raw_meta, batch_id, run_id, status, last_checked_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    creator.id,
                    creator.source_id,
                    creator.username,
                    creator.profile_url,
                    creator.followers,
                    creator.likes_total,
                    creator.vertical,
                    creator.country,
                    creator.language,
                    creator.source_path,
                    json.dumps(creator.raw_meta or {}, ensure_ascii=False),
                    self._active_batch_id(),
                    run_id,
                    creator.status,
                    creator.last_checked_at,
                    creator.created_at,
                ),
            )
            return creator

    def upsert_content(self, content: DiscoveredContent) -> tuple[DiscoveredContent, bool]:
        run_id = self._active_run_id()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM discovered_contents WHERE creator_id=? AND video_id=?",
                (content.creator_id, content.video_id),
            ).fetchone()
            if row:
                return self._row_to_content(row), False
            conn.execute(
                """
                INSERT INTO discovered_contents
                (id, creator_id, video_id, video_url, caption, views, likes, comments, shares,
                 content_language, country, material_type, collector_level, source_path, raw_meta, batch_id, run_id,
                 published_at, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    content.id,
                    content.creator_id,
                    content.video_id,
                    content.video_url,
                    content.caption,
                    content.views,
                    content.likes,
                    content.comments,
                    content.shares,
                    content.content_language,
                    content.country,
                    content.material_type,
                    content.collector_level,
                    content.source_path,
                    json.dumps(content.raw_meta or {}, ensure_ascii=False),
                    self._active_batch_id(),
                    run_id,
                    content.published_at,
                    content.collected_at,
                ),
            )
            return content, True

    def upsert_candidate(self, candidate: CandidateUser) -> tuple[CandidateUser, bool]:
        run_id = self._active_run_id()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM candidate_users WHERE content_id=? AND username=? AND comment_text=?",
                (candidate.content_id, candidate.username, candidate.comment_text),
            ).fetchone()
            if row:
                repeat_count = int(row["repeat_seen_count"] or 1) + 1 if "repeat_seen_count" in row.keys() else 2
                conn.execute(
                    """
                    UPDATE candidate_users
                    SET repeat_seen_count=?, comment_likes=MAX(comment_likes, ?), reply_count=MAX(reply_count, ?),
                        profile_url=COALESCE(NULLIF(?, ''), profile_url),
                        author_profile_completed=MAX(author_profile_completed, ?)
                    WHERE id=?
                    """,
                    (
                        repeat_count,
                        candidate.comment_likes,
                        candidate.reply_count,
                        candidate.profile_url,
                        1 if candidate.author_profile_completed else 0,
                        row["id"],
                    ),
                )
                updated = conn.execute("SELECT * FROM candidate_users WHERE id=?", (row["id"],)).fetchone()
                return self._row_to_candidate(updated), False
            conn.execute(
                """
                INSERT INTO candidate_users
                (id, content_id, username, profile_url, comment_text, comment_likes, reply_count,
                 qualify_score, intent_tags, comment_language, author_profile_completed, collector_level,
                 source_path, repeat_seen_count, raw_meta, batch_id, run_id, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.id,
                    candidate.content_id,
                    candidate.username,
                    candidate.profile_url,
                    candidate.comment_text,
                    candidate.comment_likes,
                    candidate.reply_count,
                    candidate.qualify_score,
                    json.dumps(candidate.intent_tags, ensure_ascii=False),
                    candidate.comment_language,
                    1 if candidate.author_profile_completed else 0,
                    candidate.collector_level,
                    candidate.source_path,
                    int(candidate.repeat_seen_count or 1),
                    json.dumps(candidate.raw_meta or {}, ensure_ascii=False),
                    self._active_batch_id(),
                    run_id,
                    candidate.status,
                    candidate.created_at,
                ),
            )
            return candidate, True

    def update_candidate_score(self, candidate_id: str, score: int, tags: List[str], status: str):
        with self.connect() as conn:
            conn.execute(
                "UPDATE candidate_users SET qualify_score=?, intent_tags=?, status=? WHERE id=?",
                (score, json.dumps(tags, ensure_ascii=False), status, candidate_id),
            )

    def refresh_candidate_repeat_counts(self) -> Dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT LOWER(username) AS username_key, COUNT(DISTINCT content_id) AS seen_count
                FROM candidate_users
                WHERE username <> ''
                GROUP BY LOWER(username)
                """
            ).fetchall()
            counts = {row["username_key"]: int(row["seen_count"] or 1) for row in rows}
            for username_key, seen_count in counts.items():
                conn.execute(
                    "UPDATE candidate_users SET repeat_seen_count=? WHERE LOWER(username)=?",
                    (max(1, seen_count), username_key),
                )
            return counts

    def upsert_shop_product(self, source_id: str, data: Dict[str, Any]) -> tuple[str, bool]:
        now = utc_now_iso()
        product_id = str(data.get("product_id") or "").strip()
        product_url = str(data.get("product_url") or "").strip()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM shop_products WHERE source_id=? AND product_id=? AND product_url=?",
                (source_id, product_id, product_url),
            ).fetchone()
            if row:
                return row["id"], False
            item_id = new_id("sp")
            conn.execute(
                "INSERT INTO shop_products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item_id,
                    source_id,
                    data.get("platform") or "tiktok",
                    product_id,
                    product_url,
                    data.get("title") or "",
                    data.get("shop_name") or "",
                    data.get("category") or "",
                    data.get("price") or "",
                    data.get("sales_text") or "",
                    data.get("rating") or "",
                    now,
                ),
            )
            return item_id, True

    def upsert_commerce_signal(self, source_id: str, data: Dict[str, Any]) -> tuple[str, bool]:
        return self.upsert_shop_product(source_id, data)

    def upsert_shop_content(self, source_id: str, data: Dict[str, Any]) -> tuple[str, bool]:
        now = utc_now_iso()
        run_id = self._active_run_id()
        video_id = str(data.get("video_id") or "").strip()
        video_url = str(data.get("video_url") or "").strip()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM shop_contents WHERE source_id=? AND video_id=? AND video_url=?",
                (source_id, video_id, video_url),
            ).fetchone()
            if row:
                return row["id"], False
            item_id = new_id("sc")
            conn.execute(
                """
                INSERT INTO shop_contents
                (id, source_id, product_id, creator_username, video_id, video_url, caption,
                 material_type, hook_text, views, likes, comments, shares, batch_id, run_id, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    source_id,
                    data.get("product_id") or "",
                    data.get("creator_username") or "",
                    video_id,
                    video_url,
                    data.get("caption") or "",
                    data.get("material_type") or "unknown",
                    data.get("hook_text") or "",
                    int(data.get("views") or 0),
                    int(data.get("likes") or 0),
                    int(data.get("comments") or 0),
                    int(data.get("shares") or 0),
                    self._active_batch_id(),
                    run_id,
                    now,
                ),
            )
            return item_id, True

    def upsert_topic_content(self, source_id: str, data: Dict[str, Any]) -> tuple[str, bool]:
        return self.upsert_shop_content(source_id, data)

    def upsert_material_signal(self, content_id: str, signal_type: str, score: int, tags: List[str], evidence: str = ""):
        now = utc_now_iso()
        run_id = self._active_run_id()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM material_signals WHERE content_id=? AND signal_type=?",
                (content_id, signal_type),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE material_signals SET signal_score=?, signal_tags=?, evidence=?, created_at=? WHERE id=?",
                    (int(score), json.dumps(tags, ensure_ascii=False), evidence, now, row["id"]),
                )
                return row["id"], False
            item_id = new_id("ms")
            conn.execute(
                "INSERT INTO material_signals (id, content_id, run_id, signal_type, signal_score, signal_tags, evidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (item_id, content_id, run_id, signal_type, int(score), json.dumps(tags, ensure_ascii=False), evidence, now),
            )
            return item_id, True

    def upsert_audience_intent(self, candidate_id: str, content_id: str, intent_type: str, confidence: int, evidence: str):
        now = utc_now_iso()
        run_id = self._active_run_id()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM audience_intents WHERE candidate_user_id=? AND content_id=? AND intent_type=?",
                (candidate_id, content_id, intent_type),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE audience_intents SET confidence=?, evidence=?, created_at=? WHERE id=?",
                    (int(confidence), evidence, now, row["id"]),
                )
                return row["id"], False
            item_id = new_id("ai")
            conn.execute(
                "INSERT INTO audience_intents (id, candidate_user_id, content_id, run_id, intent_type, confidence, evidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (item_id, candidate_id, content_id, run_id, intent_type, int(confidence), evidence, now),
            )
            return item_id, True

    def upsert_operation_lead(
        self,
        candidate_id: str,
        lead_type: str,
        priority: str,
        score: int,
        reason: str,
        source_path: str = "",
    ):
        now = utc_now_iso()
        run_id = self._active_run_id()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM operation_leads WHERE candidate_user_id=? AND lead_type=?",
                (candidate_id, lead_type),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE operation_leads
                    SET priority=?, score=?, reason=?, source_path=COALESCE(NULLIF(?, ''), source_path),
                        updated_at=?
                    WHERE id=?
                    """,
                    (priority, int(score), reason, source_path or "", now, row["id"]),
                )
                return row["id"], False
            item_id = new_id("ol")
            conn.execute(
                """
                INSERT INTO operation_leads
                (id, candidate_user_id, run_id, lead_type, priority, score, reason, lifecycle_stage, source_path,
                 status, batch_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    candidate_id,
                    run_id,
                    lead_type,
                    priority,
                    int(score),
                    reason,
                    "new",
                    source_path or "",
                    "new",
                    self._active_batch_id(),
                    now,
                    now,
                ),
            )
            return item_id, True

    def upsert_action_queue_item(self, item: ActionQueueItem) -> tuple[str, bool]:
        run_id = self._active_run_id()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM action_queue WHERE lead_id=? AND action_type=?",
                (item.lead_id, item.action_type),
            ).fetchone()
            if row:
                return row["id"], False
            conn.execute(
                """
                INSERT INTO action_queue
                (id, lead_id, run_id, action_type, target_username, target_url, suggested_text, reason, status, risk_level,
                 batch_id, created_at, review_status, reviewed_by, reviewed_at, review_note, daily_quota_key,
                 execution_confirmed, confirmed_by, confirmed_at, retry_count, last_execution_id,
                 last_error_code, last_error_message, last_executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.lead_id,
                    run_id,
                    item.action_type,
                    item.target_username,
                    item.target_url,
                    item.suggested_text,
                    item.reason,
                    item.status,
                    item.risk_level,
                    self._active_batch_id(),
                    item.created_at,
                    "pending",
                    "",
                    None,
                    "",
                    "",
                    0,
                    "",
                    None,
                    0,
                    "",
                    "",
                    "",
                    None,
                ),
            )
            self._refresh_lead_lifecycle(conn, item.lead_id)
            return item.id, True

    def list_operation_leads(self, limit: int = 200, batch_id: str = "", run_id: str = "") -> List[Dict[str, Any]]:
        filters = []
        args: list[Any] = []
        if batch_id:
            filters.append("ol.batch_id=?")
            args.append(str(batch_id))
        if run_id:
            filters.append("ol.run_id=?")
            args.append(str(run_id))
        where = "WHERE " + " AND ".join(filters) if filters else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT ol.*,
                       cu.username,
                       cu.profile_url,
                       cu.comment_text,
                       cu.qualify_score,
                       cu.intent_tags,
                       cu.comment_language,
                       dc.video_url,
                       dc.video_id,
                       dc.caption,
                       dc.views,
                       dc.comments AS video_comments,
                       COALESCE(NULLIF(ol.source_path, ''), NULLIF(cu.source_path, ''), NULLIF(dc.source_path, ''), dc.video_url, '') AS resolved_source_path,
                       COUNT(aq.id) AS action_count,
                       SUM(CASE WHEN aq.status='pending_review' THEN 1 ELSE 0 END) AS pending_action_count,
                       SUM(CASE WHEN aq.status='approved' THEN 1 ELSE 0 END) AS approved_action_count,
                       SUM(CASE WHEN aq.status='completed' THEN 1 ELSE 0 END) AS completed_action_count,
                       SUM(CASE WHEN aq.status IN ('failed', 'retryable') THEN 1 ELSE 0 END) AS retryable_action_count
                FROM operation_leads ol
                LEFT JOIN candidate_users cu ON cu.id = ol.candidate_user_id
                LEFT JOIN discovered_contents dc ON dc.id = cu.content_id
                LEFT JOIN action_queue aq ON aq.lead_id = ol.id
                {where}
                GROUP BY ol.id
                ORDER BY ol.score DESC, ol.updated_at DESC, ol.created_at DESC
                LIMIT ?
                """,
                tuple(args + [limit]),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["source_path"] = item.get("resolved_source_path") or item.get("source_path") or ""
                result.append(item)
            return result

    def _refresh_lead_lifecycle(self, conn, lead_id: str):
        if not lead_id:
            return
        rows = conn.execute(
            "SELECT status, execution_confirmed FROM action_queue WHERE lead_id=?",
            (lead_id,),
        ).fetchall()
        if not rows:
            stage = "new"
        elif any(row["status"] in {"completed", "success"} for row in rows):
            stage = "contacted"
        elif any(row["status"] in {"failed", "retryable"} for row in rows):
            stage = "needs_retry"
        elif all(row["status"] == "rejected" for row in rows):
            stage = "rejected"
        elif any(int(row["execution_confirmed"] or 0) for row in rows):
            stage = "ready_to_execute"
        elif any(row["status"] == "approved" for row in rows):
            stage = "approved"
        else:
            stage = "pending_review"
        conn.execute(
            "UPDATE operation_leads SET lifecycle_stage=?, status=?, updated_at=? WHERE id=?",
            (stage, stage, utc_now_iso(), lead_id),
        )

    def create_outreach_execution(
        self,
        action_id: str,
        action_type: str,
        target_username: str,
        status: str = "pending",
        profile_id: str = "",
        evidence_path: str = "",
        error_code: str = "",
        error_message: str = "",
        risk_gate: Optional[Dict[str, Any]] = None,
        execution_mode: str = "simulated",
        submission_state: str = "not_attempted",
        verification_state: str = "not_required",
        evidence_verified: bool = False,
    ) -> str:
        now = utc_now_iso()
        item_id = new_id("oe")
        run_id = self._active_run_id()
        evidence_path = evidence_path or self._execution_evidence_uri(action_id, profile_id, error_code or status or "recorded")
        risk_gate_json = json.dumps(risk_gate or {}, ensure_ascii=False) if isinstance(risk_gate, dict) else ""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO outreach_executions
                (id, action_id, run_id, action_type, target_username, status, execution_mode, submission_state,
                 verification_state, evidence_verified, profile_id, evidence_path, error_code, error_message,
                 risk_gate_json, batch_id, started_at, completed_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    action_id,
                    run_id,
                    action_type,
                    target_username,
                    status,
                    str(execution_mode or "simulated"),
                    str(submission_state or "not_attempted"),
                    str(verification_state or "not_required"),
                    1 if evidence_verified else 0,
                    profile_id,
                    evidence_path,
                    error_code,
                    error_message,
                    risk_gate_json,
                    self._active_batch_id(),
                    now if status in {"running", "completed", "success", "failed", "skipped", "account_switched"} else None,
                    now if status in {"completed", "success", "failed", "skipped", "account_switched"} else None,
                    now,
                ),
            )
        return item_id

    def _execution_evidence_uri(self, action_id: str, profile_id: str = "", marker: str = "") -> str:
        safe_profile = str(profile_id or "unknown").strip() or "unknown"
        safe_action = str(action_id or "unknown").strip() or "unknown"
        safe_marker = str(marker or "recorded").strip() or "recorded"
        safe_marker = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in safe_marker)
        return f"evidence://growth_ops/{safe_profile}/{safe_action}/{safe_marker}"

    def create_collection_batch(
        self,
        total_sources: int,
        profile_group: str = "",
        config: Optional[Dict[str, Any]] = None,
        campaign_id: str = "",
        initial_status: str = "running",
    ) -> CollectionBatch:
        now = utc_now_iso()
        config = dict(config or {})
        if campaign_id:
            config.setdefault("campaign_id", campaign_id)
        if initial_status not in {"pending", "running"}:
            initial_status = "running"
        batch_id = new_id("gb")
        run_id = new_id("run")
        config.setdefault("run_id", run_id)
        item = CollectionBatch(
            id=batch_id,
            campaign_id=campaign_id or "",
            status=initial_status,
            total_sources=int(total_sources or 0),
            processed_sources=0,
            failed_sources=0,
            profile_group=profile_group or "",
            config_json=json.dumps(config or {}, ensure_ascii=False),
            run_id=run_id,
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO collection_batches
                (id, campaign_id, run_id, status, total_sources, processed_sources, failed_sources, profile_group,
                 config_json, started_at, completed_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    campaign_id or "",
                    item.run_id,
                    item.status,
                    item.total_sources,
                    item.processed_sources,
                    item.failed_sources,
                    item.profile_group,
                    json.dumps(config, ensure_ascii=False),
                    item.started_at,
                    item.completed_at,
                    item.created_at,
                    item.updated_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO campaign_runs
                (id, campaign_id, batch_id, run_key, status, profile_group, config_json,
                 started_at, completed_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    campaign_id or "",
                    batch_id,
                    f"{campaign_id or 'uncampaign'}:{batch_id}",
                    item.status,
                    item.profile_group,
                    json.dumps(config, ensure_ascii=False),
                    item.started_at,
                    item.completed_at,
                    item.created_at,
                    item.updated_at,
                ),
            )
        self.log_event("collection_batch_created", item.id, {"total_sources": item.total_sources, "profile_group": item.profile_group})
        return item

    def update_collection_batch(self, batch_id: str, status: str, processed_delta: int = 0, failed_delta: int = 0):
        now = utc_now_iso()
        completed_at = now if status in {"completed", "failed", "partial_failed"} else None
        with self.connect() as conn:
            row = conn.execute("SELECT processed_sources, failed_sources FROM collection_batches WHERE id=?", (batch_id,)).fetchone()
            if not row:
                return
            processed = int(row["processed_sources"] or 0) + int(processed_delta or 0)
            failed = int(row["failed_sources"] or 0) + int(failed_delta or 0)
            conn.execute(
                """
                UPDATE collection_batches
                SET status=?, processed_sources=?, failed_sources=?, completed_at=COALESCE(?, completed_at), updated_at=?
                WHERE id=?
                """,
                (status, processed, failed, completed_at, now, batch_id),
            )
            conn.execute(
                """
                UPDATE campaign_runs
                SET status=?, completed_at=COALESCE(?, completed_at), updated_at=?
                WHERE batch_id=?
                """,
                (status, completed_at, now, batch_id),
            )

    def update_collection_batch_total_sources(self, batch_id: str, total_sources: int):
        now = utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE collection_batches
                SET total_sources=?, updated_at=?
                WHERE id=?
                """,
                (max(0, int(total_sources or 0)), now, batch_id),
            )

    def create_collection_task(self, batch_id: str, source_id: str, source_type: str, source_value: str, profile_id: str = "") -> CollectionTask:
        now = utc_now_iso()
        run_id = self.run_id_for_batch(batch_id)
        item = CollectionTask(
            id=new_id("gt"),
            batch_id=batch_id,
            run_id=run_id,
            source_id=source_id,
            source_type=source_type,
            source_value=source_value,
            profile_id=profile_id,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO collection_tasks
                (id, batch_id, run_id, source_id, source_type, source_value, profile_id, status,
                 error_code, error_message, started_at, completed_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.batch_id,
                    run_id,
                    item.source_id,
                    item.source_type,
                    item.source_value,
                    item.profile_id,
                    item.status,
                    item.error_code,
                    item.error_message,
                    item.started_at,
                    item.completed_at,
                    item.created_at,
                    item.updated_at,
                ),
            )
        return item

    def update_collection_task(self, task_id: str, status: str, error_code: str = "", error_message: str = ""):
        now = utc_now_iso()
        started_at = now if status == "running" else None
        completed_at = now if status in {"completed", "failed", "skipped"} else None
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE collection_tasks
                SET status=?, error_code=?, error_message=?,
                    started_at=COALESCE(started_at, ?),
                    completed_at=COALESCE(?, completed_at),
                    updated_at=?
                WHERE id=?
                """,
                (status, error_code or "", error_message or "", started_at, completed_at, now, task_id),
            )
        if status == "running":
            self.log_event("collection_task_started", task_id, {})
        elif status in {"completed", "failed", "skipped"}:
            self.log_event("collection_task_completed", task_id, {"status": status, "error_code": error_code or ""})

    def record_profile_health(self, profile_id: str, group_name: str = "", ok: bool = True, error_code: str = "", error_message: str = "") -> ProfileHealth:
        profile_id = str(profile_id or "").strip()
        if not profile_id:
            profile_id = "unknown"
        now = utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO profile_health
                (profile_id, group_name, health_score, status, consecutive_failures,
                 last_error_code, last_error_message, last_used_at, updated_at)
                VALUES (?, ?, 100, 'healthy', 0, '', '', ?, ?)
                """,
                (profile_id, group_name or "", now, now),
            )
            row = conn.execute("SELECT * FROM profile_health WHERE profile_id=?", (profile_id,)).fetchone()
            transient_error_codes = {
                "PAGE_OPEN_FAILED",
                "PROFILE_PREFLIGHT_TIMEOUT",
                "PROFILE_START_TIMEOUT",
                "IXBROWSER_NETWORK_ERROR",
                "IXBROWSER_SERVER_BUSY",
            }
            hard_error_codes = {
                "LOGIN_REQUIRED",
                "IXBROWSER_KERNEL_MISMATCH",
                "CAPTCHA_DETECTED",
                "PROXY_FAILED",
                "ACCOUNT_RESTRICTED",
                "COMMENT_ACCESS_GATED",
            }
            old_status = str(row["status"] or "")
            old_failures = int(row["consecutive_failures"] or 0)
            error_code = str(error_code or "")
            transient_failure = (not ok) and error_code in transient_error_codes and old_failures <= 1 and old_status in {"healthy", "degraded"}
            failures = 0 if ok else (old_failures if transient_failure else old_failures + 1)
            score = int(row["health_score"] or 100)
            score = max(75, min(100, score + 25)) if ok else max(0, score - (5 if transient_failure else 20))
            status = "healthy"
            if (failures >= 3 or score < 40) and error_code in hard_error_codes:
                status = "cooldown"
            elif not ok or score < 70:
                status = "degraded"
            conn.execute(
                """
                UPDATE profile_health
                SET group_name=COALESCE(NULLIF(?, ''), group_name), health_score=?, status=?,
                    consecutive_failures=?, last_error_code=?, last_error_message=?,
                    last_used_at=?, updated_at=?
                WHERE profile_id=?
                """,
                (
                    group_name or "",
                    score,
                    status,
                    failures,
                    "" if ok else error_code,
                    "" if ok else error_message,
                    now,
                    now,
                    profile_id,
                ),
            )
            saved = conn.execute("SELECT * FROM profile_health WHERE profile_id=?", (profile_id,)).fetchone()
        self.log_event("profile_health_updated", profile_id, {"ok": ok, "status": status, "error_code": error_code or ""})
        return self._row_to_profile_health(saved)

    def force_profile_cooldown(self, profile_id: str, group_name: str = "", error_code: str = "", error_message: str = "") -> ProfileHealth:
        profile_id = str(profile_id or "").strip() or "unknown"
        now = utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO profile_health
                (profile_id, group_name, health_score, status, consecutive_failures,
                 last_error_code, last_error_message, last_used_at, updated_at)
                VALUES (?, ?, 20, 'cooldown', 3, ?, ?, ?, ?)
                """,
                (profile_id, group_name or "", error_code or "", error_message or error_code or "", now, now),
            )
            conn.execute(
                """
                UPDATE profile_health
                SET group_name=COALESCE(NULLIF(?, ''), group_name),
                    health_score=MIN(health_score, 20),
                    status='cooldown',
                    consecutive_failures=MAX(consecutive_failures, 3),
                    last_error_code=?,
                    last_error_message=?,
                    last_used_at=?,
                    updated_at=?
                WHERE profile_id=?
                """,
                (group_name or "", error_code or "", error_message or error_code or "", now, now, profile_id),
            )
            saved = conn.execute("SELECT * FROM profile_health WHERE profile_id=?", (profile_id,)).fetchone()
        self.log_event("profile_forced_cooldown", profile_id, {"error_code": error_code or "", "reason": error_message or ""})
        return self._row_to_profile_health(saved)

    def create_scheduled_scan(
        self,
        source_type: str,
        source_value: str,
        profile_group: str = "",
        schedule_interval_minutes: int = 60,
        next_run_at: Optional[str] = None,
        max_videos: int = 5,
        max_comments: int = 10,
        min_views: int = 0,
        min_comments: int = 0,
    ) -> ScheduledScan:
        now = utc_now_iso()
        item = ScheduledScan(
            id=new_id("ss"),
            source_type=source_type,
            source_value=source_value,
            profile_group=profile_group or "",
            schedule_interval_minutes=max(1, int(schedule_interval_minutes or 60)),
            next_run_at=next_run_at or now,
            status="active",
            max_videos=max(1, int(max_videos or 5)),
            max_comments=max(1, int(max_comments or 10)),
            min_views=max(0, int(min_views or 0)),
            min_comments=max(0, int(min_comments or 0)),
            created_at=now,
            updated_at=now,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO scheduled_scans
                (id, source_type, source_value, profile_group, schedule_interval_minutes,
                 next_run_at, status, max_videos, max_comments, min_views, min_comments,
                 last_batch_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.source_type,
                    item.source_value,
                    item.profile_group,
                    item.schedule_interval_minutes,
                    item.next_run_at,
                    item.status,
                    item.max_videos,
                    item.max_comments,
                    item.min_views,
                    item.min_comments,
                    item.last_batch_id,
                    item.created_at,
                    item.updated_at,
                ),
            )
        self.log_event("scheduled_scan_created", item.id, {"source_type": source_type, "profile_group": profile_group})
        return item

    def update_scheduled_scan_status(self, scan_id: str, status: str):
        now = utc_now_iso()
        with self.connect() as conn:
            conn.execute("UPDATE scheduled_scans SET status=?, updated_at=? WHERE id=?", (status, now, scan_id))
        event = "scheduled_scan_paused" if status == "paused" else "scheduled_scan_resumed" if status == "active" else "scheduled_scan_run"
        self.log_event(event, scan_id, {"status": status})

    def mark_scheduled_scan_run(self, scan_id: str, next_run_at: str, last_batch_id: str = ""):
        now = utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                "UPDATE scheduled_scans SET next_run_at=?, last_batch_id=?, updated_at=? WHERE id=?",
                (next_run_at, last_batch_id or "", now, scan_id),
            )
        self.log_event("scheduled_scan_run", scan_id, {"next_run_at": next_run_at, "last_batch_id": last_batch_id})

    def get_checkpoint(self, source_id: str, creator_id: str) -> Optional[Checkpoint]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM checkpoints WHERE source_id=? AND creator_id=?",
                (source_id, creator_id),
            ).fetchone()
            return self._row_to_checkpoint(row) if row else None

    def update_checkpoint(self, source_id: str, creator_id: str, last_video_id: str) -> Checkpoint:
        now = utc_now_iso()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM checkpoints WHERE source_id=? AND creator_id=?",
                (source_id, creator_id),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE checkpoints SET last_video_id=?, last_checked_at=?, updated_at=? WHERE id=?",
                    (last_video_id, now, now, row["id"]),
                )
                cp_id = row["id"]
            else:
                cp_id = new_id("cp")
                conn.execute(
                    "INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?, ?)",
                    (cp_id, source_id, creator_id, last_video_id, now, now),
                )
            return self._row_to_checkpoint(conn.execute("SELECT * FROM checkpoints WHERE id=?", (cp_id,)).fetchone())

    def list_contents(self, creator_id: Optional[str] = None) -> List[DiscoveredContent]:
        query = "SELECT * FROM discovered_contents"
        args: Iterable[Any] = ()
        if creator_id:
            query += " WHERE creator_id=?"
            args = (creator_id,)
        query += " ORDER BY collected_at DESC"
        with self.connect() as conn:
            return [self._row_to_content(row) for row in conn.execute(query, tuple(args)).fetchall()]

    def list_creators(self, limit: int = 100) -> List[DiscoveredCreator]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM discovered_creators ORDER BY last_checked_at DESC, created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_creator(row) for row in rows]

    def list_candidates(self) -> List[CandidateUser]:
        with self.connect() as conn:
            return [self._row_to_candidate(row) for row in conn.execute("SELECT * FROM candidate_users").fetchall()]

    def list_candidates_with_content(self, batch_id: str = "", run_id: str = "") -> List[Dict[str, Any]]:
        filters = []
        args: list[Any] = []
        if batch_id:
            filters.append("cu.batch_id=?")
            args.append(str(batch_id))
        if run_id:
            filters.append("cu.run_id=?")
            args.append(str(run_id))
        where = "WHERE " + " AND ".join(filters) if filters else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT cu.*, dc.video_url, dc.video_id, dc.views, dc.comments AS video_comments, dc.caption,
                       dc.content_language, dc.country AS content_country, dc.material_type,
                       dc.source_path AS content_source_path,
                       cr.vertical AS creator_vertical, cr.country AS creator_country, cr.language AS creator_language,
                       cr.source_path AS creator_source_path
                FROM candidate_users cu
                LEFT JOIN discovered_contents dc ON dc.id = cu.content_id
                LEFT JOIN discovered_creators cr ON cr.id = dc.creator_id
                {where}
                """
                ,
                tuple(args),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_top_topic_contents(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT sc.*, sp.title AS product_title, sp.shop_name, sp.price,
                       COALESCE(ms.signal_score, 0) AS signal_score,
                       COALESCE(ms.signal_tags, '[]') AS signal_tags
                FROM shop_contents sc
                LEFT JOIN shop_products sp ON sp.product_id = sc.product_id AND sp.source_id = sc.source_id
                LEFT JOIN material_signals ms ON ms.content_id = sc.id
                ORDER BY signal_score DESC, sc.views DESC, sc.comments DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            rows = [dict(row) for row in rows]
        for row in rows:
            row["content_kind"] = row.get("material_type") or "unknown"
            row["commerce_title"] = row.get("product_title") or ""
        return rows

    def list_action_queue(self, limit: int = 100, batch_id: str = "", run_id: str = "") -> List[Dict[str, Any]]:
        filters = []
        args: list[Any] = []
        if batch_id:
            filters.append("aq.batch_id=?")
            args.append(str(batch_id))
        if run_id:
            filters.append("aq.run_id=?")
            args.append(str(run_id))
        where = "WHERE " + " AND ".join(filters) if filters else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT aq.*, ol.lead_type, ol.priority, ol.score AS lead_score, ol.reason AS lead_reason,
                       ol.source_path,
                       cu.comment_language,
                       dc.country AS content_country
                FROM action_queue aq
                LEFT JOIN operation_leads ol ON ol.id = aq.lead_id
                LEFT JOIN candidate_users cu ON cu.id = ol.candidate_user_id
                LEFT JOIN discovered_contents dc ON dc.id = cu.content_id
                {where}
                ORDER BY ol.score DESC, aq.created_at DESC
                LIMIT ?
                """,
                tuple(args + [limit]),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_action_status(self, action_id: str, status: str, note: str = ""):
        now = utc_now_iso()
        with self.connect() as conn:
            action_row = conn.execute("SELECT lead_id FROM action_queue WHERE id=?", (action_id,)).fetchone()
            if status in {"approved", "rejected"}:
                conn.execute(
                    """
                    UPDATE action_queue
                    SET status=?, review_status=?, reviewed_by=?, reviewed_at=?, review_note=?
                    WHERE id=?
                    """,
                    (status, status, "operator", now, note or status, action_id),
                )
            else:
                conn.execute("UPDATE action_queue SET status=? WHERE id=?", (status, action_id))
            conn.execute(
                "INSERT INTO action_logs (id, action_id, status, note, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_id("alog"), action_id, status, note, now),
            )
            if action_row:
                self._refresh_lead_lifecycle(conn, action_row["lead_id"])

    def record_action_execution_result(
        self,
        action_id: str,
        execution_id: str,
        status: str,
        error_code: str = "",
        error_message: str = "",
        retryable: bool = False,
    ):
        now = utc_now_iso()
        action_status = status
        if status == "failed" and retryable:
            action_status = "retryable"
        with self.connect() as conn:
            row = conn.execute("SELECT retry_count, lead_id FROM action_queue WHERE id=?", (action_id,)).fetchone()
            retry_count = int(row["retry_count"] or 0) if row else 0
            if status == "failed":
                retry_count += 1
            conn.execute(
                """
                UPDATE action_queue
                SET status=?, retry_count=?, last_execution_id=?, last_error_code=?,
                    last_error_message=?, last_executed_at=?
                WHERE id=?
                """,
                (
                    action_status,
                    retry_count,
                    execution_id or "",
                    error_code or "",
                    error_message or "",
                    now,
                    action_id,
                ),
            )
            conn.execute(
                "INSERT INTO action_logs (id, action_id, status, note, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_id("alog"), action_id, action_status, error_message or error_code or status, now),
            )
            if row:
                self._refresh_lead_lifecycle(conn, row["lead_id"])
        self.log_event(
            "action_execution_result_recorded",
            action_id,
            {"execution_id": execution_id, "status": status, "retryable": retryable, "error_code": error_code or ""},
        )

    def reset_action_for_retry(self, action_id: str, note: str = ""):
        now = utc_now_iso()
        with self.connect() as conn:
            action_row = conn.execute("SELECT lead_id FROM action_queue WHERE id=?", (action_id,)).fetchone()
            conn.execute(
                """
                UPDATE action_queue
                SET status='approved', last_error_code='', last_error_message=''
                WHERE id=? AND status IN ('failed', 'retryable')
                """,
                (action_id,),
            )
            conn.execute(
                "INSERT INTO action_logs (id, action_id, status, note, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_id("alog"), action_id, "retry_scheduled", note or "scheduled for retry", now),
            )
            if action_row:
                self._refresh_lead_lifecycle(conn, action_row["lead_id"])
        self.log_event("action_retry_scheduled", action_id, {"note": note or ""})

    def confirm_action_execution(self, action_id: str, confirmed_by: str = "operator", note: str = ""):
        now = utc_now_iso()
        with self.connect() as conn:
            action_row = conn.execute("SELECT lead_id FROM action_queue WHERE id=?", (action_id,)).fetchone()
            conn.execute(
                """
                UPDATE action_queue
                SET execution_confirmed=1, confirmed_by=?, confirmed_at=?
                WHERE id=?
                """,
                (confirmed_by or "operator", now, action_id),
            )
            conn.execute(
                "INSERT INTO action_logs (id, action_id, status, note, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_id("alog"), action_id, "execution_confirmed", note or "execution confirmed", now),
            )
            if action_row:
                self._refresh_lead_lifecycle(conn, action_row["lead_id"])
        self.log_event("action_execution_confirmed", action_id, {"confirmed_by": confirmed_by or "operator", "note": note or ""})

    def list_action_templates(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM action_templates ORDER BY action_type, created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def upsert_action_template(self, action_type: str, name: str, body: str, status: str = "active") -> str:
        now = utc_now_iso()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM action_templates WHERE action_type=? AND name=?",
                (action_type, name),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE action_templates SET body=?, status=?, created_at=? WHERE id=?",
                    (body, status, now, row["id"]),
                )
                template_id = row["id"]
            else:
                template_id = new_id("tpl")
                conn.execute(
                    "INSERT INTO action_templates (id, action_type, name, body, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (template_id, action_type, name, body, status, now),
                )
        self.log_event("action_template_saved", template_id, {"action_type": action_type, "name": name})
        return template_id

    def get_action_template_body(self, action_type: str, fallback: str = "") -> str:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT body FROM action_templates
                WHERE action_type=? AND status='active'
                ORDER BY
                    CASE WHEN id IN ('tpl_comment_reply_default', 'tpl_follow_review_default', 'tpl_dm_review_default') THEN 1 ELSE 0 END,
                    created_at DESC
                LIMIT 1
                """,
                (action_type,),
            ).fetchone()
            return row["body"] if row else fallback

    def upsert_filter_preset(self, view_name: str, name: str, filters: Dict[str, Any], status: str = "active") -> str:
        now = utc_now_iso()
        view = str(view_name or "").strip()
        preset_name = str(name or "").strip() or "default"
        payload = json.dumps(filters or {}, ensure_ascii=False)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM growth_filter_presets WHERE view_name=? AND name=?",
                (view, preset_name),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE growth_filter_presets
                    SET filters_json=?, status=?, updated_at=?
                    WHERE id=?
                    """,
                    (payload, status or "active", now, row["id"]),
                )
                preset_id = row["id"]
            else:
                preset_id = new_id("gfp")
                conn.execute(
                    """
                    INSERT INTO growth_filter_presets
                    (id, view_name, name, filters_json, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (preset_id, view, preset_name, payload, status or "active", now, now),
                )
        self.log_event("growth_filter_preset_saved", preset_id, {"view_name": view, "name": preset_name})
        return preset_id

    def list_filter_presets(self, view_name: str = "", limit: int = 100) -> List[Dict[str, Any]]:
        view = str(view_name or "").strip()
        with self.connect() as conn:
            if view:
                rows = conn.execute(
                    """
                    SELECT * FROM growth_filter_presets
                    WHERE view_name=? AND status='active'
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (view, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM growth_filter_presets
                    WHERE status='active'
                    ORDER BY view_name, updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        presets = []
        for row in rows:
            item = dict(row)
            try:
                item["filters"] = json.loads(item.get("filters_json") or "{}")
            except Exception:
                item["filters"] = {}
            presets.append(item)
        return presets

    def get_filter_preset(self, view_name: str, name: str) -> Optional[Dict[str, Any]]:
        view = str(view_name or "").strip()
        preset_name = str(name or "").strip() or "default"
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM growth_filter_presets
                WHERE view_name=? AND name=? AND status='active'
                LIMIT 1
                """,
                (view, preset_name),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            item["filters"] = json.loads(item.get("filters_json") or "{}")
        except Exception:
            item["filters"] = {}
        return item

    def add_exclusion(self, target_username: str = "", target_url: str = "", reason: str = "") -> str:
        now = utc_now_iso()
        username = str(target_username or "").strip().lstrip("@")
        url = str(target_url or "").strip()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM exclusion_rules WHERE target_username=? AND target_url=?",
                (username, url),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE exclusion_rules SET reason=?, status='active', updated_at=? WHERE id=?",
                    (reason or "", now, row["id"]),
                )
                item_id = row["id"]
            else:
                item_id = new_id("ex")
                conn.execute(
                    "INSERT INTO exclusion_rules VALUES (?, ?, ?, ?, 'active', ?, ?)",
                    (item_id, username, url, reason or "", now, now),
                )
        self.log_event("exclusion_added", item_id, {"target_username": username, "target_url": url})
        return item_id

    def list_exclusions(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM exclusion_rules ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def is_target_excluded(self, target_username: str = "", target_url: str = "") -> bool:
        username = str(target_username or "").strip().lstrip("@").lower()
        url = str(target_url or "").strip().lower()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM exclusion_rules
                WHERE status='active'
                  AND ((LOWER(target_username)=? AND target_username!='') OR (LOWER(target_url)=? AND target_url!=''))
                LIMIT 1
                """,
                (username, url),
            ).fetchone()
            return bool(row)

    def check_daily_quota(self, profile_id: str, action_type: str, limit_count: int, quota_date: Optional[str] = None) -> tuple[bool, int, int]:
        from datetime import datetime

        quota_date = quota_date or datetime.utcnow().strftime("%Y-%m-%d")
        profile_id = str(profile_id or "")
        action_type = str(action_type or "")
        limit_count = max(0, int(limit_count or 0))
        with self.connect() as conn:
            row = conn.execute(
                "SELECT used_count, limit_count FROM outreach_daily_quota WHERE profile_id=? AND action_type=? AND quota_date=?",
                (profile_id, action_type, quota_date),
            ).fetchone()
            if not row:
                return limit_count > 0, 0, limit_count
            used = int(row["used_count"] or 0)
            limit = int(row["limit_count"] or limit_count)
            return used < limit, used, limit

    def increment_daily_quota(self, profile_id: str, action_type: str, limit_count: int, quota_date: Optional[str] = None):
        from datetime import datetime

        quota_date = quota_date or datetime.utcnow().strftime("%Y-%m-%d")
        now = utc_now_iso()
        profile_id = str(profile_id or "")
        action_type = str(action_type or "")
        item_id = new_id("dq")
        with self.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO outreach_daily_quota
                (id, profile_id, action_type, quota_date, used_count, limit_count, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(profile_id, action_type, quota_date)
                DO UPDATE SET
                    used_count = outreach_daily_quota.used_count + 1,
                    limit_count = excluded.limit_count,
                    updated_at = excluded.updated_at
                RETURNING id
                """,
                (item_id, profile_id, action_type, quota_date, int(limit_count or 0), now),
            ).fetchone()
            if row and row["id"]:
                item_id = row["id"]
        self.log_event("daily_quota_updated", item_id, {"profile_id": profile_id, "action_type": action_type})

    def check_rate_limit(
        self,
        profile_id: str,
        action_type: str,
        scope_type: str,
        scope_value: str,
        window_key: str,
        limit_count: int,
    ) -> tuple[bool, int, int]:
        profile_id = str(profile_id or "")
        action_type = str(action_type or "")
        scope_type = str(scope_type or "")
        scope_value = str(scope_value or "")
        window_key = str(window_key or "")
        limit_count = max(0, int(limit_count or 0))
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT used_count, limit_count FROM outreach_rate_limits
                WHERE profile_id=? AND action_type=? AND scope_type=? AND scope_value=? AND window_key=?
                """,
                (profile_id, action_type, scope_type, scope_value, window_key),
            ).fetchone()
            if not row:
                return limit_count > 0, 0, limit_count
            used = int(row["used_count"] or 0)
            limit = int(row["limit_count"] or limit_count)
            return used < limit, used, limit

    def increment_rate_limit(
        self,
        profile_id: str,
        action_type: str,
        scope_type: str,
        scope_value: str,
        window_key: str,
        limit_count: int,
    ):
        now = utc_now_iso()
        profile_id = str(profile_id or "")
        action_type = str(action_type or "")
        scope_type = str(scope_type or "")
        scope_value = str(scope_value or "")
        window_key = str(window_key or "")
        item_id = new_id("rl")
        with self.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO outreach_rate_limits
                (id, profile_id, action_type, scope_type, scope_value, window_key, used_count, limit_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(profile_id, action_type, scope_type, scope_value, window_key)
                DO UPDATE SET
                    used_count = outreach_rate_limits.used_count + 1,
                    limit_count = excluded.limit_count,
                    updated_at = excluded.updated_at
                RETURNING id
                """,
                (item_id, profile_id, action_type, scope_type, scope_value, window_key, int(limit_count or 0), now),
            ).fetchone()
            if row and row["id"]:
                item_id = row["id"]
        self.log_event(
            "rate_limit_updated",
            item_id,
            {"profile_id": profile_id, "action_type": action_type, "scope_type": scope_type, "scope_value": scope_value, "window_key": window_key},
        )

    def list_rate_limits(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM outreach_rate_limits ORDER BY updated_at DESC LIMIT ?",
                (int(limit or 200),),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_outreach_executions(self, limit: int = 100, batch_id: str = "", run_id: str = "") -> List[Dict[str, Any]]:
        filters = []
        args: list[Any] = []
        if batch_id:
            filters.append("batch_id=?")
            args.append(str(batch_id))
        if run_id:
            filters.append("run_id=?")
            args.append(str(run_id))
        where = "WHERE " + " AND ".join(filters) if filters else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM outreach_executions {where} ORDER BY created_at DESC LIMIT ?",
                tuple(args + [limit]),
            ).fetchall()
            items = [dict(row) for row in rows]
            for item in items:
                raw_gate = str(item.get("risk_gate_json") or "").strip()
                if raw_gate:
                    try:
                        parsed = json.loads(raw_gate)
                    except Exception:
                        parsed = {}
                    if isinstance(parsed, dict):
                        item["risk_gate"] = parsed
            return items

    def outreach_execution_status_counts(self, batch_id: str = "", run_id: str = "") -> Dict[str, int]:
        batch_id = str(batch_id or "").strip()
        run_id = str(run_id or "").strip()
        filters = []
        args: list[Any] = []
        if batch_id:
            filters.append("batch_id=?")
            args.append(batch_id)
        if run_id:
            filters.append("run_id=?")
            args.append(run_id)
        where = "WHERE " + " AND ".join(filters) if filters else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT status, COUNT(*) AS count
                FROM outreach_executions
                {where}
                GROUP BY status
                """,
                tuple(args),
            ).fetchall()
        return {str(row["status"] or ""): int(row["count"] or 0) for row in rows}

    def outreach_execution_truth_counts(self, batch_id: str = "", run_id: str = "") -> Dict[str, int]:
        batch_id = str(batch_id or "").strip()
        run_id = str(run_id or "").strip()
        filters = []
        args: list[Any] = []
        if batch_id:
            filters.append("batch_id=?")
            args.append(batch_id)
        if run_id:
            filters.append("run_id=?")
            args.append(run_id)
        where = "WHERE " + " AND ".join(filters) if filters else ""
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT
                    SUM(CASE WHEN execution_mode='simulated' AND status='success' THEN 1 ELSE 0 END) AS simulated_success,
                    SUM(CASE WHEN execution_mode='dry_run' AND status='success' THEN 1 ELSE 0 END) AS dry_run_success,
                    SUM(CASE WHEN execution_mode='preflight' AND status='success' THEN 1 ELSE 0 END) AS preflight_passed,
                    SUM(CASE WHEN execution_mode='live' AND submission_state IN ('submitted', 'submitted_unverified', 'verified_success') THEN 1 ELSE 0 END) AS live_submitted,
                    SUM(CASE WHEN execution_mode='live' AND submission_state='submitted_unverified' THEN 1 ELSE 0 END) AS submitted_unverified,
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
                tuple(args),
            ).fetchone()
        keys = ["simulated_success", "dry_run_success", "preflight_passed", "live_submitted", "submitted_unverified", "live_verified", "live_failed"]
        return {key: int((row[key] if row else 0) or 0) for key in keys}

    def list_collection_batches(self, limit: int = 100, campaign_id: str = "") -> List[Dict[str, Any]]:
        with self.connect() as conn:
            if campaign_id:
                rows = conn.execute(
                    "SELECT * FROM collection_batches WHERE campaign_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (campaign_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM collection_batches ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(row) for row in rows]

    def collection_window_metrics(self, start_at: str, end_at: str = "") -> Dict[str, int]:
        start = str(start_at or "").strip()
        end = str(end_at or "").strip() or utc_now_iso()
        if not start:
            return {}
        metrics: Dict[str, int] = {}
        with self.connect() as conn:
            metrics["new_creators"] = self._count_between(conn, "discovered_creators", "created_at", start, end)
            metrics["new_contents"] = self._count_between(conn, "discovered_contents", "collected_at", start, end)
            metrics["topic_contents"] = self._count_between(conn, "shop_contents", "collected_at", start, end)
            metrics["candidate_users"] = self._count_between(conn, "candidate_users", "created_at", start, end)
            metrics["high_value_candidates"] = self._count_between(
                conn,
                "candidate_users",
                "created_at",
                start,
                end,
                "qualify_score >= 70",
            )
            metrics["operation_leads"] = self._count_between(conn, "operation_leads", "created_at", start, end)
            metrics["action_queue"] = self._count_between(conn, "action_queue", "created_at", start, end)
            metrics["outreach_executions"] = self._count_between(conn, "outreach_executions", "created_at", start, end)
            metrics["errors"] = self._count_between(conn, "growth_errors", "created_at", start, end)
        return metrics

    def collection_batch_entity_metrics(self, batch_id: str) -> Dict[str, int]:
        batch = str(batch_id or "").strip()
        if not batch:
            return {}
        metrics: Dict[str, int] = {}
        with self.connect() as conn:
            metrics["new_creators"] = self._count_batch(conn, "discovered_creators", batch)
            metrics["new_contents"] = self._count_batch(conn, "discovered_contents", batch)
            metrics["topic_contents"] = self._count_batch(conn, "shop_contents", batch)
            metrics["candidate_users"] = self._count_batch(conn, "candidate_users", batch)
            metrics["high_value_candidates"] = self._count_batch(conn, "candidate_users", batch, "qualify_score >= 70")
            metrics["operation_leads"] = self._count_batch(conn, "operation_leads", batch)
            metrics["action_queue"] = self._count_batch(conn, "action_queue", batch)
            metrics["outreach_executions"] = self._count_batch(conn, "outreach_executions", batch)
            metrics["errors"] = self._count_batch(conn, "growth_errors", batch)
        return metrics

    def _count_batch(self, conn, table_name: str, batch_id: str, extra_where: str = "") -> int:
        allowed = {
            "discovered_creators",
            "discovered_contents",
            "shop_contents",
            "candidate_users",
            "operation_leads",
            "action_queue",
            "outreach_executions",
            "growth_errors",
        }
        if table_name not in allowed:
            raise ValueError(f"unsupported batch metric: {table_name}")
        where = "batch_id=?"
        if extra_where:
            where = f"{where} AND ({extra_where})"
        return int(conn.execute(f"SELECT COUNT(*) FROM {table_name} WHERE {where}", (batch_id,)).fetchone()[0])

    def _count_between(self, conn, table_name: str, column_name: str, start_at: str, end_at: str, extra_where: str = "") -> int:
        allowed = {
            ("discovered_creators", "created_at"),
            ("discovered_contents", "collected_at"),
            ("shop_contents", "collected_at"),
            ("candidate_users", "created_at"),
            ("operation_leads", "created_at"),
            ("action_queue", "created_at"),
            ("outreach_executions", "created_at"),
            ("growth_errors", "created_at"),
        }
        if (table_name, column_name) not in allowed:
            raise ValueError(f"unsupported window metric: {table_name}.{column_name}")
        where = f"{column_name}>=? AND {column_name}<=?"
        if extra_where:
            where = f"{where} AND ({extra_where})"
        return int(conn.execute(f"SELECT COUNT(*) FROM {table_name} WHERE {where}", (start_at, end_at)).fetchone()[0])

    def latest_collection_batch_id(self) -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM collection_batches ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
            return row["id"] if row else ""

    def latest_collection_batch_for_campaign(self, campaign_id: str) -> Dict[str, Any]:
        campaign_id = str(campaign_id or "").strip()
        if not campaign_id:
            return {}
        rows = self.list_collection_batches(limit=1, campaign_id=campaign_id)
        return rows[0] if rows else {}

    def list_collection_tasks(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT ct.*, cb.profile_group
                FROM collection_tasks ct
                LEFT JOIN collection_batches cb ON cb.id = ct.batch_id
                ORDER BY ct.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def collection_batch_progress(self, batch_id: str) -> Dict[str, Any]:
        batch_id = str(batch_id or "").strip()
        if not batch_id:
            return {}
        with self.connect() as conn:
            batch = conn.execute("SELECT * FROM collection_batches WHERE id=?", (batch_id,)).fetchone()
            if not batch:
                return {}
            status_rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM collection_tasks
                WHERE batch_id=?
                GROUP BY status
                ORDER BY count DESC, status ASC
                """,
                (batch_id,),
            ).fetchall()
            error_rows = conn.execute(
                """
                SELECT error_code, COUNT(*) AS count
                FROM collection_tasks
                WHERE batch_id=? AND COALESCE(error_code, '')!=''
                GROUP BY error_code
                ORDER BY count DESC, error_code ASC
                """,
                (batch_id,),
            ).fetchall()
            profile_rows = conn.execute(
                """
                SELECT profile_id, COUNT(*) AS count
                FROM collection_tasks
                WHERE batch_id=? AND COALESCE(profile_id, '')!=''
                GROUP BY profile_id
                ORDER BY count DESC, profile_id ASC
                """,
                (batch_id,),
            ).fetchall()
            recent_tasks = conn.execute(
                """
                SELECT *
                FROM collection_tasks
                WHERE batch_id=?
                ORDER BY updated_at DESC
                LIMIT 20
                """,
                (batch_id,),
            ).fetchall()
        return {
            "batch": dict(batch),
            "status_counts": {row["status"] or "unknown": int(row["count"] or 0) for row in status_rows},
            "error_counts": {row["error_code"]: int(row["count"] or 0) for row in error_rows},
            "profile_counts": {row["profile_id"]: int(row["count"] or 0) for row in profile_rows},
            "recent_tasks": [dict(row) for row in recent_tasks],
        }

    def list_failed_collection_tasks(self, batch_id: str = "", error_code: str = "", limit: int = 200) -> List[Dict[str, Any]]:
        filters = ["ct.status='failed'"]
        args: list[Any] = []
        if batch_id:
            filters.append("ct.batch_id=?")
            args.append(str(batch_id))
        if error_code:
            filters.append("ct.error_code=?")
            args.append(str(error_code))
        args.append(int(limit or 200))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT ct.*, cb.profile_group
                FROM collection_tasks ct
                LEFT JOIN collection_batches cb ON cb.id = ct.batch_id
                WHERE {' AND '.join(filters)}
                ORDER BY ct.updated_at DESC
                LIMIT ?
                """,
                tuple(args),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_collection_tasks_by_ids(self, task_ids: List[str]) -> List[Dict[str, Any]]:
        ids = [str(task_id or "").strip() for task_id in task_ids or [] if str(task_id or "").strip()]
        if not ids:
            return []
        placeholders = ",".join(["?"] * len(ids))
        order = {task_id: index for index, task_id in enumerate(ids)}
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT ct.*, cb.profile_group
                FROM collection_tasks ct
                LEFT JOIN collection_batches cb ON cb.id = ct.batch_id
                WHERE ct.id IN ({placeholders})
                """,
                tuple(ids),
            ).fetchall()
        return sorted([dict(row) for row in rows], key=lambda row: order.get(str(row.get("id") or ""), 0))

    def latest_failed_batch_for_error(self, error_code: str) -> Dict[str, Any]:
        rows = self.list_failed_collection_tasks(error_code=error_code, limit=1)
        return rows[0] if rows else {}

    def list_profile_health(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM profile_health ORDER BY health_score ASC, updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_scheduled_scans(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scheduled_scans ORDER BY status ASC, next_run_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_scheduled_scan(self, scan_id: str) -> Dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM scheduled_scans WHERE id=?", (scan_id,)).fetchone()
            return dict(row) if row else {}

    def list_due_scheduled_scans(self, now_iso: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        now_iso = now_iso or utc_now_iso()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM scheduled_scans
                WHERE status='active' AND next_run_at<=?
                ORDER BY next_run_at ASC
                LIMIT ?
                """,
                (now_iso, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_daily_quota(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM outreach_daily_quota ORDER BY quota_date DESC, updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def save_execution_plan(self, plan: Dict[str, Any], export_path: str = "") -> str:
        now = utc_now_iso()
        plan_id = str(plan.get("plan_id") or "") or new_id("plan")
        payload = dict(plan or {})
        payload["plan_id"] = plan_id
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO execution_plans
                (id, profile_id, selected_count, planned_count, executable_count, skipped_count,
                 status, plan_json, export_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM execution_plans WHERE id=?), ?), ?)
                """,
                (
                    plan_id,
                    str(payload.get("profile_id") or ""),
                    int(payload.get("selected_count") or 0),
                    int(payload.get("planned_count") or 0),
                    int(payload.get("executable_count") or 0),
                    int(payload.get("skipped_count") or 0),
                    str(payload.get("status") or "planned"),
                    json.dumps(payload, ensure_ascii=False),
                    str(export_path or payload.get("export_path") or ""),
                    plan_id,
                    now,
                    now,
                ),
            )
        self.log_event("execution_plan_saved", plan_id, {"profile_id": payload.get("profile_id", ""), "export_path": export_path or ""})
        return plan_id

    def update_execution_plan_export_path(self, plan_id: str, export_path: str):
        now = utc_now_iso()
        plan_id = str(plan_id or "")
        if not plan_id:
            return
        with self.connect() as conn:
            row = conn.execute("SELECT plan_json FROM execution_plans WHERE id=?", (plan_id,)).fetchone()
            payload = json.loads(row["plan_json"]) if row and row["plan_json"] else {}
            payload["export_path"] = export_path
            conn.execute(
                "UPDATE execution_plans SET plan_json=?, export_path=?, updated_at=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), str(export_path or ""), now, plan_id),
            )

    def update_execution_plan_status(self, plan_id: str, status: str, result: Optional[Dict[str, Any]] = None):
        now = utc_now_iso()
        plan_id = str(plan_id or "")
        if not plan_id:
            return
        with self.connect() as conn:
            row = conn.execute("SELECT plan_json FROM execution_plans WHERE id=?", (plan_id,)).fetchone()
            payload = json.loads(row["plan_json"]) if row and row["plan_json"] else {}
            payload["status"] = status
            if result is not None:
                payload["execution_result"] = result
            conn.execute(
                "UPDATE execution_plans SET status=?, plan_json=?, updated_at=? WHERE id=?",
                (str(status or "planned"), json.dumps(payload, ensure_ascii=False), now, plan_id),
            )

    def get_execution_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        plan_id = str(plan_id or "")
        if not plan_id:
            return None
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM execution_plans WHERE id=?", (plan_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            item["plan"] = json.loads(item.get("plan_json") or "{}")
        except Exception:
            item["plan"] = {}
        return item

    def list_execution_plans(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM execution_plans ORDER BY created_at DESC LIMIT ?",
                (int(limit or 100),),
            ).fetchall()
            return [dict(row) for row in rows]

    def count_table(self, table_name: str) -> int:
        allowed = {
            "data_sources",
            "discovered_creators",
            "discovered_contents",
            "candidate_users",
            "shop_products",
            "shop_contents",
            "material_signals",
            "audience_intents",
            "operation_leads",
            "action_queue",
            "outreach_executions",
            "collection_batches",
            "collection_tasks",
            "profile_health",
            "scheduled_scans",
            "action_templates",
            "exclusion_rules",
            "outreach_daily_quota",
            "outreach_rate_limits",
            "growth_filter_presets",
            "execution_plans",
            "acquisition_campaigns",
            "audience_personas",
            "acquisition_sources",
            "campaign_runs",
            "source_observations",
            "content_observations",
            "comment_observations",
            "candidate_observations",
            "lead_decisions",
        }
        if table_name not in allowed:
            raise ValueError(f"unsupported table: {table_name}")
        with self.connect() as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])

    def count_high_value_candidates(self) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM candidate_users WHERE qualify_score >= 70").fetchone()[0])

    def count_candidates_for_content(self, content_id: str) -> int:
        with self.connect() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM candidate_users WHERE content_id=?",
                    (str(content_id or ""),),
                ).fetchone()[0]
            )

    def error_counts(self) -> Dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute("SELECT error_code, COUNT(*) AS c FROM growth_errors GROUP BY error_code").fetchall()
            return {row["error_code"]: int(row["c"]) for row in rows}

    def list_errors(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM growth_errors ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_errors_for_context(
        self,
        batch_id: str = "",
        source_id: str = "",
        profile_id: str = "",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        filters = []
        args: list[Any] = []
        if batch_id:
            filters.append("batch_id=?")
            args.append(str(batch_id))
        if source_id:
            filters.append("source_id=?")
            args.append(str(source_id))
        if profile_id:
            filters.append("profile_id=?")
            args.append(str(profile_id))
        if not filters:
            return []
        args.append(int(limit or 100))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM growth_errors
                WHERE {' AND '.join(filters)}
                ORDER BY created_at ASC
                LIMIT ?
                """,
                tuple(args),
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_sources(self) -> List[DataSource]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM data_sources ORDER BY updated_at DESC").fetchall()
            return [self._row_to_datasource(row) for row in rows]

    def _row_to_datasource(self, row) -> DataSource:
        return DataSource(**dict(row))

    def _row_to_creator(self, row) -> DiscoveredCreator:
        data = dict(row)
        try:
            data["raw_meta"] = json.loads(data.get("raw_meta") or "{}")
        except Exception:
            data["raw_meta"] = {}
        return DiscoveredCreator(**data)

    def _row_to_content(self, row) -> DiscoveredContent:
        data = dict(row)
        try:
            data["raw_meta"] = json.loads(data.get("raw_meta") or "{}")
        except Exception:
            data["raw_meta"] = {}
        return DiscoveredContent(**data)

    def _row_to_candidate(self, row) -> CandidateUser:
        data = dict(row)
        data["intent_tags"] = json.loads(data.get("intent_tags") or "[]")
        try:
            data["raw_meta"] = json.loads(data.get("raw_meta") or "{}")
        except Exception:
            data["raw_meta"] = {}
        data["author_profile_completed"] = bool(data.get("author_profile_completed"))
        return CandidateUser(**data)

    def _row_to_checkpoint(self, row) -> Checkpoint:
        return Checkpoint(**dict(row))

    def _row_to_collection_batch(self, row) -> CollectionBatch:
        return CollectionBatch(**dict(row))

    def _row_to_collection_task(self, row) -> CollectionTask:
        return CollectionTask(**dict(row))

    def _row_to_profile_health(self, row) -> ProfileHealth:
        return ProfileHealth(**dict(row))

    def _row_to_scheduled_scan(self, row) -> ScheduledScan:
        return ScheduledScan(**dict(row))

    def _row_to_persona_dict(self, row) -> Dict[str, Any]:
        data = dict(row)
        mapping = {
            "demographics_json": "demographics",
            "interests_json": "interests",
            "pain_points_json": "pain_points",
            "buying_triggers_json": "buying_triggers",
            "intent_keywords_json": "intent_keywords",
            "exclude_keywords_json": "exclude_keywords",
            "search_keywords_json": "search_keywords",
            "hashtags_json": "hashtags",
            "competitor_terms_json": "competitor_terms",
            "outreach_angles_json": "outreach_angles",
        }
        for source_key, target_key in mapping.items():
            raw = data.pop(source_key, "{}" if target_key == "demographics" else "[]")
            try:
                data[target_key] = json.loads(raw or ("{}" if target_key == "demographics" else "[]"))
            except Exception:
                data[target_key] = {} if target_key == "demographics" else []
        return data
