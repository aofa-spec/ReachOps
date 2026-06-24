# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import time

from .base import CollectorAdapter
from .normalizer import absolute_tiktok_url, detect_text_language, extract_video_id, parse_count


class TikTokVideoCollector(CollectorAdapter):
    def collect(self, driver, task, context):
        limit = min(int(getattr(context.get("config"), "max_videos_per_creator", 20) or 20), 20)
        self._warm_videos(driver, limit)
        rows = self._collect_dom_rows(driver)
        if not rows:
            rows = self._collect_script_rows(driver)
        videos = []
        for row in (rows or [])[:limit]:
            url = absolute_tiktok_url(row.get("video_url"))
            raw_text = row.get("raw_text") or ""
            videos.append(
                {
                    "video_id": extract_video_id(url),
                    "video_url": url,
                    "caption": row.get("caption") or "",
                    "views": parse_count(raw_text),
                    "likes": 0,
                    "comments": 0,
                    "shares": 0,
                    "content_language": row.get("content_language") or detect_text_language(row.get("caption") or raw_text),
                    "material_type": row.get("material_type") or "creator_video",
                    "collector_level": row.get("collector_level") or "selenium_dom",
                    "source_path": url,
                    "raw_meta": row.get("raw_meta") if isinstance(row.get("raw_meta"), dict) else {},
                    "published_at": None,
                }
            )
        return videos

    def _collect_dom_rows(self, driver):
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
                  const tile = a.closest('[data-e2e], article, div') || a;
                  const text = (tile.innerText || a.innerText || '').trim();
                  const img = tile.querySelector('img');
                  const caption = (a.getAttribute('title') || (img && img.alt) || text || '').trim();
                  out.push({
                    video_url: href,
                    caption,
                    raw_text: text,
                    collector_level: 'selenium_dom',
                    raw_meta: {source: 'anchor_dom'}
                  });
                }
                return out;
                """
            ) or []
            return rows if isinstance(rows, list) else []
        except Exception:
            return []

    def _collect_script_rows(self, driver):
        try:
            payload = driver.execute_script(
                """
                const scripts = Array.from(document.scripts || [])
                  .map(s => s.textContent || '')
                  .filter(t => t.includes('/video/') || t.includes('video/') || t.includes('VideoObject'))
                  .slice(0, 12)
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
        urls = []
        seen = set()
        patterns = [
            r"https?://(?:www\.)?tiktok\.com/@[^\s\"'<>\\]+/video/\d+",
            r"/@[^\s\"'<>\\]+/video/\d+",
        ]
        for pattern in patterns:
            for match in re.findall(pattern, text):
                url = absolute_tiktok_url(match)
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
        rows = []
        for url in urls:
            rows.append(
                {
                    "video_url": url,
                    "caption": "",
                    "raw_text": "",
                    "collector_level": "script_json",
                    "raw_meta": {"source": "script_or_document_links"},
                }
            )
        return rows

    def _warm_videos(self, driver, limit: int):
        previous_count = -1
        stable_rounds = 0
        try:
            driver.execute_script("window.scrollTo(0, 0);")
        except Exception:
            pass
        for _ in range(10):
            try:
                count = int(driver.execute_script("return document.querySelectorAll(\"a[href*='/video/']\").length") or 0)
                if count >= max(1, min(limit, 6)):
                    return
                if count == previous_count:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                previous_count = count
                driver.execute_script(
                    """
                    const step = Math.max(700, window.innerHeight || 900);
                    window.scrollBy(0, step);
                    const containers = Array.from(document.querySelectorAll('[data-e2e], main, div'))
                      .filter(el => el.scrollHeight && el.scrollHeight > el.clientHeight + 200)
                      .slice(0, 4);
                    for (const el of containers) el.scrollTop = Math.min(el.scrollHeight, el.scrollTop + step);
                    """
                )
                if stable_rounds >= 2 and count > 0:
                    return
            except Exception:
                pass
            time.sleep(1.2)
