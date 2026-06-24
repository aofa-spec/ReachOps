# -*- coding: utf-8 -*-
"""Reserved live-room active user collector.

The first implementation is intentionally parser-only and side-effect free.
It extracts visible live chat usernames/keywords from the current page so the
Growth Intelligence module can turn them into leads before any outreach action
is considered.
"""

from __future__ import annotations

import re
from typing import Any

from .base import CollectorAdapter


class TikTokLiveRoomCollector(CollectorAdapter):
    level = "selenium_dom"

    KEYWORD_PATTERN = re.compile(r"where|link|download|app|free|watch|name|episode|price|shop|buy", re.I)

    def collect(self, driver: Any, task: dict, context: dict):
        try:
            body_text = driver.execute_script("return document.body ? document.body.innerText : ''") or ""
        except Exception:
            body_text = ""
        users = []
        seen = set()
        for raw_line in str(body_text).splitlines():
            line = raw_line.strip()
            if not line or len(line) > 280:
                continue
            username = ""
            if line.startswith("@"):
                username = line.split()[0].lstrip("@")
            elif ":" in line:
                username = line.split(":", 1)[0].strip().lstrip("@")
            if not username or username.lower() in seen:
                continue
            seen.add(username.lower())
            users.append(
                {
                    "username": username,
                    "text": line,
                    "matched_keyword": bool(self.KEYWORD_PATTERN.search(line)),
                    "source": "live_room",
                }
            )
            if len(users) >= int(task.get("max_live_users") or context.get("max_live_users") or 100):
                break
        self.last_diagnostics = {"line_count": len(str(body_text).splitlines())}
        return {"active_users": users, "evidence": self.evidence(driver, len(users), str(body_text)[:500])}
