# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import time

from .base import CollectorAdapter
from .normalizer import absolute_tiktok_url, detect_text_language, extract_video_id, parse_count


class TikTokSearchCollector(CollectorAdapter):
    """Collect TikTok search result videos from DOM and embedded page data."""

    def collect(self, driver, task, context):
        limit = int(context.get("limit") or 20)
        self._warm_results(driver, limit)
        rows = self._collect_dom_rows(driver)
        if not rows:
            rows = self._collect_script_rows(driver)
        materials = []
        for row in (rows or [])[:limit]:
            url = absolute_tiktok_url(row.get("video_url") or row.get("href") or "")
            if "/video/" not in url:
                continue
            raw_text = str(row.get("raw_text") or row.get("text") or "")
            caption = str(row.get("caption") or raw_text or "").strip()
            materials.append(
                {
                    "commerce": {},
                    "content": {
                        "creator_username": self._extract_creator(url),
                        "video_id": extract_video_id(url),
                        "video_url": url,
                        "caption": caption[:500],
                        "material_type": "search_video",
                        "hook_text": caption[:160],
                        "views": parse_count(raw_text),
                        "likes": 0,
                        "comments": 0,
                        "shares": 0,
                        "content_language": detect_text_language(caption or raw_text),
                        "collector_level": row.get("collector_level") or "search_dom",
                        "source_path": str(task.get("source", {}).get("value") or getattr(driver, "current_url", "") or ""),
                        "raw_meta": row.get("raw_meta") if isinstance(row.get("raw_meta"), dict) else {},
                    },
                }
            )
        self.last_diagnostics = {
            "result_count": len(materials),
            "final_url": str(getattr(driver, "current_url", "") or ""),
            "collector": self.__class__.__name__,
        }
        return materials

    def _warm_results(self, driver, limit: int):
        previous_count = -1
        stable_rounds = 0
        for _ in range(10):
            try:
                count = int(driver.execute_script("return document.querySelectorAll(\"a[href*='/video/']\").length") or 0)
                if count >= max(1, min(limit, 6)):
                    return
                stable_rounds = stable_rounds + 1 if count == previous_count else 0
                previous_count = count
                driver.execute_script(
                    """
                    window.scrollBy(0, Math.max(700, window.innerHeight || 900));
                    const containers = Array.from(document.querySelectorAll('main, div'))
                      .filter(el => el.scrollHeight && el.scrollHeight > el.clientHeight + 200)
                      .slice(0, 6);
                    for (const el of containers) el.scrollTop = Math.min(el.scrollHeight, el.scrollTop + Math.max(700, window.innerHeight || 900));
                    """
                )
                if stable_rounds >= 3 and count > 0:
                    return
            except Exception:
                pass
            time.sleep(1.2)

    def _collect_dom_rows(self, driver) -> list[dict]:
        try:
            rows = driver.execute_script(
                """
                const anchors = Array.from(document.querySelectorAll('a[href*="/video/"]'));
                const seen = new Set();
                const out = [];
                for (const a of anchors) {
                  const href = a.href || a.getAttribute('href') || '';
                  if (!href || seen.has(href)) continue;
                  seen.add(href);
                  const card = a.closest('[data-e2e], article, div') || a;
                  const text = (card.innerText || a.innerText || '').trim();
                  const img = card.querySelector('img');
                  const caption = (a.getAttribute('title') || (img && img.alt) || text || '').trim();
                  out.push({
                    video_url: href,
                    caption,
                    raw_text: text,
                    collector_level: 'search_dom',
                    raw_meta: {source: 'search_anchor_dom'}
                  });
                }
                return out;
                """
            ) or []
            return rows if isinstance(rows, list) else []
        except Exception:
            return []

    def _collect_script_rows(self, driver) -> list[dict]:
        try:
            payload = driver.execute_script(
                """
                const scripts = Array.from(document.scripts || [])
                  .map(s => s.textContent || '')
                  .filter(t => t.includes('/video/') || t.includes('video/'))
                  .slice(0, 20)
                  .join('\\n');
                const links = Array.from(document.links || [])
                  .map(a => a.href || '')
                  .filter(h => h.includes('/video/'))
                  .join('\\n');
                return {scripts, links, url: location.href};
                """
            ) or {}
        except Exception:
            payload = {}
        text = "\n".join([str(payload.get("links") or ""), str(payload.get("scripts") or "")]).replace("\\/", "/")
        if not text:
            return []
        seen = set()
        rows = []
        for pattern in [
            r"https?://(?:www\.)?tiktok\.com/@[^\s\"'<>\\]+/video/\d+",
            r"/@[^\s\"'<>\\]+/video/\d+",
        ]:
            for match in re.findall(pattern, text):
                url = absolute_tiktok_url(match)
                if url in seen:
                    continue
                seen.add(url)
                rows.append(
                    {
                        "video_url": url,
                        "caption": "",
                        "raw_text": "",
                        "collector_level": "search_script",
                        "raw_meta": {"source": "search_script_or_links"},
                    }
                )
        return rows

    def _extract_creator(self, url: str) -> str:
        try:
            for part in str(url or "").split("/"):
                if part.startswith("@"):
                    return part.lstrip("@").split("?")[0]
        except Exception:
            pass
        return ""
