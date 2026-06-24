# -*- coding: utf-8 -*-
from __future__ import annotations

from .base import CollectorAdapter
from .normalizer import extract_username_from_url, parse_count


class TikTokProfileCollector(CollectorAdapter):
    def collect(self, driver, task, context):
        url = str(getattr(driver, "current_url", "") or task.get("source", {}).get("value") or "")
        data = {
            "username": extract_username_from_url(url),
            "profile_url": url,
            "followers": 0,
            "likes_total": 0,
            "status": "active",
        }
        try:
            js_data = driver.execute_script(
                """
                const text = document.body ? document.body.innerText : '';
                const username =
                  (location.pathname.match(/@([^/]+)/) || [])[1] ||
                  (document.querySelector('[data-e2e="user-title"]') || {}).innerText || '';
                const followers =
                  (document.querySelector('[data-e2e="followers-count"]') || {}).innerText || '';
                const likes =
                  (document.querySelector('[data-e2e="likes-count"]') || {}).innerText || '';
                return {username, followers, likes, text};
                """
            )
            if isinstance(js_data, dict):
                data["username"] = (js_data.get("username") or data["username"] or "").strip().lstrip("@")
                data["followers"] = parse_count(js_data.get("followers"))
                data["likes_total"] = parse_count(js_data.get("likes"))
        except Exception:
            pass
        return data
