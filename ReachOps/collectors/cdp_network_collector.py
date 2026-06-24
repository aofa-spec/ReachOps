# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Iterable

from .base import CollectorAdapter
from .normalizer import absolute_tiktok_url, detect_text_language, is_comment_noise_text, is_placeholder_comment_text, parse_count


class CDPNetworkCollector(CollectorAdapter):
    """Best-effort network evidence collector.

    Selenium drivers backed by Chrome can expose performance logs when enabled.
    This adapter extracts matching response URLs and leaves full API parsing to a
    later platform-specific implementation.
    """

    level = "cdp_network"

    def __init__(self, url_keywords: Iterable[str] | None = None):
        self.url_keywords = [str(item).lower() for item in (url_keywords or ["comment", "item_list", "api"])]

    def collect(self, driver, task, context):
        try:
            logs = driver.get_log("performance")
        except Exception:
            return []
        rows = []
        for entry in logs or []:
            try:
                message = json.loads(entry.get("message") or "{}").get("message") or {}
                if message.get("method") != "Network.responseReceived":
                    continue
                params = message.get("params", {})
                response = params.get("response", {})
                url = str(response.get("url") or "")
                lower = url.lower()
                if any(keyword in lower for keyword in self.url_keywords):
                    parsed = self._parse_response_body(driver, params.get("requestId"), url, task)
                    if parsed:
                        rows.extend(parsed)
                    else:
                        rows.append({"url": url, "status": response.get("status"), "mime_type": response.get("mimeType")})
            except Exception:
                continue
        return rows

    def _parse_response_body(self, driver, request_id: str, url: str, task: dict) -> list[dict]:
        if not request_id or not hasattr(driver, "execute_cdp_cmd"):
            return []
        try:
            body_result = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id}) or {}
            body = body_result.get("body") or ""
            payload = json.loads(body)
        except Exception:
            return []
        comments = []
        for item in self._find_comment_objects(payload):
            comment = self._normalize_comment(item, url, task)
            if comment:
                comments.append(comment)
        return comments

    def _find_comment_objects(self, payload) -> list[dict]:
        found = []
        stack = [payload]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                user = item.get("user") or item.get("author")
                text = item.get("text") or item.get("comment_text") or item.get("comment") or item.get("content")
                if isinstance(user, dict) and text:
                    found.append(item)
                    continue
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
        return found

    def _normalize_comment(self, item: dict, url: str, task: dict) -> dict:
        user = item.get("user") or item.get("author") or {}
        username = (
            user.get("unique_id")
            or user.get("uniqueId")
            or user.get("nickname")
            or user.get("name")
            or item.get("username")
            or ""
        )
        username = str(username or "").strip().lstrip("@")
        text = str(item.get("text") or item.get("comment_text") or item.get("comment") or item.get("content") or "").strip()
        if not username or not text or is_placeholder_comment_text(text) or is_comment_noise_text(text):
            return {}
        profile_url = absolute_tiktok_url(user.get("profile_url") or user.get("share_info", {}).get("share_url") or f"/@{username}")
        language = detect_text_language(text)
        return {
            "username": username,
            "profile_url": profile_url,
            "comment_text": text,
            "comment_likes": parse_count(item.get("digg_count") or item.get("like_count") or item.get("likes") or 0),
            "reply_count": parse_count(item.get("reply_comment_total") or item.get("reply_count") or item.get("replyCount") or 0),
            "comment_language": language,
            "author_profile_completed": bool(profile_url and f"/@{username}" in profile_url),
            "collector_level": self.level,
            "source_path": str(task.get("content", {}).get("video_url") or task.get("content", {}).get("id") or url or ""),
            "raw_meta": {
                "network_url": url,
                "comment_id": item.get("cid") or item.get("id") or item.get("comment_id") or "",
                "language": language,
                "profile_completed": bool(profile_url and f"/@{username}" in profile_url),
            },
        }
