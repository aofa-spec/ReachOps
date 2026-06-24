# -*- coding: utf-8 -*-
from __future__ import annotations

from .base import CollectorAdapter
from .normalizer import absolute_tiktok_url, extract_video_id, parse_count


class TikTokTopicContentCollector(CollectorAdapter):
    """Collect topic/content signals from TikTok search, hashtag, content, or commerce pages."""

    def collect(self, driver, task, context):
        limit = int(context.get("limit") or 20)
        try:
            rows = driver.execute_script(
                """
                const anchors = Array.from(document.querySelectorAll('a[href]'));
                const seen = new Set();
                const out = [];
                for (const a of anchors) {
                  const href = a.href || a.getAttribute('href') || '';
                  if (!href || seen.has(href)) continue;
                  const lower = href.toLowerCase();
                  const isVideo = lower.includes('/video/');
                  const isCommerce = lower.includes('/shop/') || lower.includes('/product/') || lower.includes('tiktok.com/t/');
                  if (!isVideo && !isCommerce) continue;
                  seen.add(href);
                  const card = a.closest('[data-e2e], article, div') || a;
                  const text = (card.innerText || a.innerText || '').trim();
                  const img = card.querySelector('img');
                  const caption = (a.getAttribute('title') || (img && img.alt) || text || '').trim();
                  out.push({href, text, caption, isVideo, isCommerce});
                }
                return out;
                """
            )
        except Exception:
            rows = []
        materials = []
        for row in (rows or [])[:limit]:
            href = absolute_tiktok_url(row.get("href"))
            raw_text = row.get("text") or ""
            caption = row.get("caption") or raw_text
            if row.get("isCommerce") and not row.get("isVideo") and not self._valid_commerce_href(href, caption):
                continue
            commerce = {}
            if row.get("isCommerce"):
                commerce = {
                    "product_id": href.rstrip("/").split("/")[-1],
                    "product_url": href,
                    "title": caption[:180],
                    "shop_name": "",
                    "category": "",
                    "price": self._extract_price(raw_text),
                    "sales_text": raw_text[:180],
                }
            content = {
                "product_id": commerce.get("product_id", ""),
                "creator_username": self._extract_creator(href),
                "video_id": extract_video_id(href) if row.get("isVideo") else "",
                "video_url": href if row.get("isVideo") else "",
                "caption": caption[:500],
                "material_type": "topic_video" if row.get("isVideo") else "commerce_card",
                "hook_text": self._extract_hook(caption),
                "views": parse_count(raw_text),
                "likes": 0,
                "comments": 0,
                "shares": 0,
            }
            materials.append({"commerce": commerce, "content": content})
        return materials

    def _valid_commerce_href(self, href: str, caption: str = "") -> bool:
        value = str(href or "").rstrip("/").lower()
        if not value or value.endswith("/shop") or value.endswith("/shop/"):
            return False
        if not any(token in value for token in ["/shop/", "/product/", "tiktok.com/t/"]):
            return False
        return bool(str(caption or "").strip() or value.rsplit("/", 1)[-1])

    def _extract_price(self, text: str) -> str:
        import re

        match = re.search(r"([$¥€£]\s?\d+(?:\.\d+)?)", text or "")
        return match.group(1) if match else ""

    def _extract_creator(self, href: str) -> str:
        try:
            for part in href.split("/"):
                if part.startswith("@"):
                    return part.lstrip("@")
        except Exception:
            pass
        return ""

    def _extract_hook(self, caption: str) -> str:
        caption = (caption or "").strip()
        if not caption:
            return ""
        for sep in [".", "!", "?", "\n"]:
            if sep in caption:
                return caption.split(sep)[0][:160]
        return caption[:160]
