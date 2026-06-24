# -*- coding: utf-8 -*-
from __future__ import annotations

from .schemas import CandidateUser
from .storage import GrowthStorage, new_id
from ReachOps.collectors.normalizer import (
    detect_text_language,
    is_comment_noise_text,
    is_placeholder_comment_text,
    normalize_comment_text,
    normalize_tiktok_username,
)


class CommentUserExtractor:
    def __init__(self, storage: GrowthStorage):
        self.storage = storage

    def save_candidates(self, content_id: str, comments: list[dict], diagnostics: dict | None = None) -> list[CandidateUser]:
        diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
        created = []
        seen_usernames = set()
        skipped_duplicate_user = 0
        for item in comments:
            username = normalize_tiktok_username(item.get("profile_url") or item.get("username") or "")
            if not username:
                continue
            comment_text = normalize_comment_text(item.get("comment_text") or "")
            if not comment_text or is_placeholder_comment_text(comment_text) or is_comment_noise_text(comment_text):
                continue
            username_key = username.lower()
            if username_key in seen_usernames:
                skipped_duplicate_user += 1
                continue
            seen_usernames.add(username_key)
            candidate = CandidateUser(
                id=new_id("cu"),
                content_id=content_id,
                username=username,
                profile_url=str(item.get("profile_url") or f"https://www.tiktok.com/@{username}"),
                comment_text=comment_text,
                comment_likes=int(item.get("comment_likes") or 0),
                reply_count=int(item.get("reply_count") or 0),
                comment_language=str(item.get("comment_language") or detect_text_language(comment_text)),
                author_profile_completed=bool(item.get("author_profile_completed")),
                collector_level=str(item.get("collector_level") or "selenium_dom"),
                source_path=str(item.get("source_path") or ""),
                repeat_seen_count=int(item.get("repeat_seen_count") or 1),
                raw_meta=item.get("raw_meta") if isinstance(item.get("raw_meta"), dict) else {},
            )
            saved, is_created = self.storage.upsert_candidate(candidate)
            if is_created:
                self.storage.log_event("candidate_user_created", saved.id, {"username": saved.username})
                created.append(saved)
        language_counts = {}
        completed_profiles = 0
        max_js_duplicate_rows = 0
        max_python_duplicate_rows = 0
        max_visible_nodes = 0
        max_scroll_rounds = 0
        max_growth_rounds = 0
        max_comment_open_attempts = 0
        max_comment_open_clicks = 0
        comment_panel_seen = False
        visible_node_history = []
        skipped_no_user = 0
        skipped_no_text = 0
        page_states = {}
        stop_reasons = {}
        for item in comments:
            language = str(item.get("comment_language") or detect_text_language(item.get("comment_text") or ""))
            language_counts[language] = language_counts.get(language, 0) + 1
            if item.get("author_profile_completed"):
                completed_profiles += 1
            raw_meta = item.get("raw_meta") if isinstance(item.get("raw_meta"), dict) else {}
            max_js_duplicate_rows = max(max_js_duplicate_rows, int(raw_meta.get("duplicate_count_before_row") or 0))
            max_python_duplicate_rows = max(max_python_duplicate_rows, int(raw_meta.get("duplicate_rows_in_python") or 0))
            max_visible_nodes = max(
                max_visible_nodes,
                int(raw_meta.get("visible_node_count") or 0),
                int(raw_meta.get("max_visible_nodes") or 0),
            )
            max_scroll_rounds = max(max_scroll_rounds, int(raw_meta.get("scroll_rounds") or 0))
            max_growth_rounds = max(max_growth_rounds, int(raw_meta.get("growth_rounds") or 0))
            max_comment_open_attempts = max(max_comment_open_attempts, int(raw_meta.get("comment_open_attempts") or 0))
            max_comment_open_clicks = max(max_comment_open_clicks, int(raw_meta.get("comment_open_clicks") or 0))
            comment_panel_seen = comment_panel_seen or bool(raw_meta.get("comment_panel_seen"))
            if isinstance(raw_meta.get("visible_node_history"), list) and len(raw_meta.get("visible_node_history")) > len(visible_node_history):
                visible_node_history = raw_meta.get("visible_node_history")
            skipped_no_user = max(skipped_no_user, int(raw_meta.get("skipped_no_user") or 0))
            skipped_no_text = max(skipped_no_text, int(raw_meta.get("skipped_no_text") or 0))
            page_state = str(raw_meta.get("comment_page_state") or "normal")
            stop_reason = str(raw_meta.get("stop_reason") or "")
            page_states[page_state] = page_states.get(page_state, 0) + 1
            if stop_reason:
                stop_reasons[stop_reason] = stop_reasons.get(stop_reason, 0) + 1
        if len(comments) == 0:
            code = str(diagnostics.get("error_code") or "COMMENT_SCAN_EMPTY")
            message = str(diagnostics.get("page_state") or "empty comment section")
            self.storage.log_error(
                code,
                message,
                creator_id=str(diagnostics.get("creator_id") or ""),
                source_id=str(diagnostics.get("source_id") or ""),
                profile_id=str(diagnostics.get("profile_id") or ""),
            )
        self.storage.log_event(
            "comments_collected",
            content_id,
            {
                "comment_count": len(comments),
                "new_candidates": len(created),
                "empty_comment_section": len(comments) == 0,
                "unique_comment_count": len({(item.get("username"), item.get("comment_text")) for item in comments}),
                "language_counts": language_counts,
                "profile_completed_count": completed_profiles,
                "profile_completion_rate": round(completed_profiles / len(comments), 4) if comments else 0,
                "duplicate_rows": max_js_duplicate_rows + max_python_duplicate_rows,
                "duplicate_rate": round(
                    (max_js_duplicate_rows + max_python_duplicate_rows)
                    / max(1, len(comments) + max_js_duplicate_rows + max_python_duplicate_rows),
                    4,
                ),
                "max_visible_nodes": max_visible_nodes,
                "max_scroll_rounds": max_scroll_rounds,
                "max_growth_rounds": max_growth_rounds,
                "comment_open_attempts": max_comment_open_attempts,
                "comment_open_clicks": max_comment_open_clicks,
                "comment_panel_seen": comment_panel_seen,
                "visible_node_history": visible_node_history,
                "skipped_no_user": skipped_no_user,
                "skipped_no_text": skipped_no_text,
                "skipped_duplicate_user": skipped_duplicate_user,
                "page_states": page_states,
                "stop_reasons": stop_reasons,
                "diagnostics": diagnostics,
            },
        )
        return created
