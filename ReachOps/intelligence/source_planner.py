# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

from .schemas import AcquisitionCampaign, AcquisitionSource, AcquisitionStrategy, AudiencePersona
from .storage import GrowthStorage, new_id


def split_operator_keywords(value: str, limit: int = 12) -> list[str]:
    text = str(value or "").strip()
    if not re.search(r"[,，;；\n]", text):
        return []
    seen = set()
    keywords = []
    for part in re.split(r"[,，;；\n]+", text):
        item = re.sub(r"\s+", " ", str(part or "").strip().lstrip("#"))
        key = item.lower()
        if not item or key in seen:
            continue
        if item.startswith(("http://", "https://", "@")):
            continue
        seen.add(key)
        keywords.append(item[:80])
        if len(keywords) >= limit:
            break
    return keywords


def looks_like_url(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if re.search(r"^https?://", text, flags=re.IGNORECASE):
        return True
    try:
        parsed = urlparse(text if "://" in text else f"https://{text}")
    except Exception:
        return False
    return bool(parsed.netloc and "." in parsed.netloc)


class CampaignAnalyzer:
    """Rule-based product and audience analyzer for ReachOps MVP."""

    BEAUTY_TERMS = {
        "beauty",
        "beautytok",
        "makeup",
        "skincare",
        "skintok",
        "skinbarrier",
        "glassskin",
        "glowingskin",
        "serum",
        "cosmetic",
        "hair",
        "hairtok",
        "haircare",
        "nail",
        "lip",
        "anti aging",
        "antiaging",
        "acne",
        "darkspots",
        "hyperpigmentation",
        "retinol",
        "vitaminc",
        "niacinamide",
        "hyaluronicacid",
        "sunscreen",
        "kbeauty",
        "jbeauty",
        "glowup",
    }
    SHOP_TERMS = {"shop", "store", "tiktokshop", "buy", "sale", "coupon", "product"}
    MARKETPLACE_DOMAINS = {
        "amazon.",
        "amzn.",
        "walmart.",
        "etsy.",
        "ebay.",
        "shopify.",
        "myshopify.",
        "shop.app",
        "temu.",
        "aliexpress.",
        "shopee.",
        "lazada.",
        "target.",
        "bestbuy.",
        "costco.",
        "sephora.",
        "ulta.",
        "iherb.",
        "wayfair.",
        "shein.",
    }
    PRODUCT_PATH_MARKERS = {"dp", "gp", "product", "products", "itm", "item", "ip", "listing", "p", "goods"}

    def detect_input_type(self, value: str) -> str:
        text = str(value or "").strip()
        lower = text.lower()
        if self._is_url(text):
            if "live" in lower and "tiktok.com" in lower:
                return "live_room_url"
            if "tiktok.com" in lower and "/@" in lower and "/video/" not in lower:
                return "creator_url"
            if "tiktok.com" in lower and "/video/" in lower:
                return "content_url"
            if self._is_marketplace_url(text) or self._has_product_path_hint(text):
                return "product_url"
            return "product_url"
        if text.startswith("@"):
            return "creator_url"
        if text.startswith("#"):
            return "hashtag"
        return "keyword"

    def build_campaign(self, value: str, target_market: str = "auto", target_language: str = "auto") -> AcquisitionCampaign:
        input_type = self.detect_input_type(value)
        product_name = self._product_name(value)
        return AcquisitionCampaign(
            id=new_id("acq"),
            input_type=input_type,
            input_value=str(value or "").strip(),
            product_name=product_name,
            category=self._category(value),
            target_market=target_market or "auto",
            target_language=target_language or "auto",
        )

    def build_persona(
        self,
        campaign: AcquisitionCampaign,
        extra_intent: list[str] | None = None,
        extra_exclude: list[str] | None = None,
        intelligence: dict | None = None,
    ) -> AudiencePersona:
        text = f"{campaign.input_value} {campaign.product_name} {campaign.category}".lower()
        is_beauty = any(term in text for term in self.BEAUTY_TERMS)
        base_keywords = ["where", "link", "buy", "price", "need", "name", "how to use", "does it work"]
        consult_keywords = ["help", "recommend", "which", "how", "routine", "sensitive", "size", "shipping"]
        exclude = ["haha", "lol", "meme", "fake", "spam", "giveaway"]
        ai_audience = (intelligence or {}).get("audience_profile") or {}
        ai_product = (intelligence or {}).get("product_analysis") or {}
        ai_taxonomy = (intelligence or {}).get("intent_taxonomy") or []
        ai_intent_keywords = []
        ai_exclude_keywords = []
        for row in ai_taxonomy:
            if str(row.get("intent_type") or "") == "exclude":
                ai_exclude_keywords.extend(row.get("keywords") or [])
            else:
                ai_intent_keywords.extend(row.get("keywords") or [])
        if is_beauty:
            interests = ["beauty routine", "skincare", "makeup review", "product demo"]
            pain_points = ["skin concern", "shade match", "before after", "routine uncertainty"]
            triggers = ["where to buy", "product name", "price", "does it work", "before after result"]
            searches = [*split_operator_keywords(campaign.input_value), campaign.product_name, "beauty review", "skincare routine", "makeup must haves"]
            hashtags = ["beauty", "skincare", "makeup", "beautyroutine"]
        else:
            interests = ["product review", "shopping", "tips", "recommendations"]
            pain_points = ["price", "availability", "trust", "how to use"]
            triggers = ["where to buy", "link", "price", "need this", "product name"]
            if campaign.input_type in {"product_url", "shop_url"}:
                searches = [campaign.product_name, f"{campaign.product_name} review" if campaign.product_name else ""]
            else:
                searches = [*split_operator_keywords(campaign.input_value), campaign.product_name, str(campaign.input_value or ""), "review", "best product"]
            hashtags = ["review", "shopping", "tiktokshop", "fyp"]
        merged_intent = self._dedupe(base_keywords + consult_keywords + triggers + ai_intent_keywords + (extra_intent or []))
        merged_exclude = self._dedupe(exclude + ai_exclude_keywords + (extra_exclude or []))
        interests = self._dedupe((ai_audience.get("interests") or []) + interests)
        pain_points = self._dedupe((ai_audience.get("pain_points") or []) + pain_points)
        triggers = self._dedupe((ai_audience.get("buying_triggers") or []) + triggers)
        searches = self._dedupe((ai_product.get("keywords") or []) + searches)
        return AudiencePersona(
            id=new_id("ap"),
            campaign_id=campaign.id,
            demographics={
                "market": campaign.target_market,
                "language": campaign.target_language,
                "persona": ai_audience.get("persona") or "social commerce buyer",
                "intelligence_provider": (intelligence or {}).get("provider", "rules_v1"),
            },
            interests=self._dedupe(interests),
            pain_points=self._dedupe(pain_points),
            buying_triggers=self._dedupe(triggers),
            intent_keywords=merged_intent,
            exclude_keywords=merged_exclude,
            search_keywords=self._dedupe([item for item in searches if item]),
            hashtags=self._dedupe(hashtags),
            competitor_terms=[],
            outreach_angles=["answer the question directly", "mention useful detail", "invite profile visit without spam"],
        )

    def _is_url(self, value: str) -> bool:
        try:
            parsed = urlparse(value if "://" in value else f"https://{value}")
        except Exception:
            return False
        return bool(parsed.netloc and "." in parsed.netloc)

    def _product_name(self, value: str) -> str:
        text = str(value or "").strip()
        if self._is_url(text):
            parsed = urlparse(text if "://" in text else f"https://{text}")
            name = self._query_product_name(parsed) or self._marketplace_product_slug(parsed) or self._domain_product_name(parsed)
            return (name or parsed.netloc)[:80]
        keyword_list = split_operator_keywords(text, limit=1)
        if keyword_list:
            return keyword_list[0]
        return text[:80]

    def _category(self, value: str) -> str:
        lower = str(value or "").lower()
        if any(term in lower for term in self.BEAUTY_TERMS):
            return "beauty"
        if self._is_url(value) and self._is_marketplace_url(value):
            return "marketplace_product"
        if any(term in lower for term in self.SHOP_TERMS):
            return "social_commerce"
        return "general"

    def _is_marketplace_url(self, value: str) -> bool:
        try:
            parsed = urlparse(value if "://" in value else f"https://{value}")
        except Exception:
            return False
        host = parsed.netloc.lower()
        return any(domain in host for domain in self.MARKETPLACE_DOMAINS)

    def _has_product_path_hint(self, value: str) -> bool:
        try:
            parsed = urlparse(value if "://" in value else f"https://{value}")
        except Exception:
            return False
        parts = [part.lower() for part in parsed.path.split("/") if part]
        return any(part in self.PRODUCT_PATH_MARKERS for part in parts)

    def _query_product_name(self, parsed) -> str:
        query = parse_qs(parsed.query)
        for key in ["title", "name", "product_name", "product", "q"]:
            values = query.get(key) or []
            for value in values:
                name = self._clean_product_slug(value)
                if name and not self._looks_like_identifier(name):
                    return name
        return ""

    def _marketplace_product_slug(self, parsed) -> str:
        parts = [part for part in parsed.path.split("/") if part]
        if not parts:
            return ""
        for index, part in enumerate(parts):
            marker = part.lower()
            if marker in {"product", "products", "ip", "itm", "item", "listing", "p", "goods"}:
                name = self._first_named_segment(parts[index + 1 :])
                if name:
                    return name
            if marker in {"dp", "gp"}:
                name = self._first_named_segment(parts[:index])
                if name:
                    return name
        return self._first_named_segment(parts)

    def _domain_product_name(self, parsed) -> str:
        return self._first_named_segment([part for part in parsed.path.split("/") if part])

    def _first_named_segment(self, parts: list[str]) -> str:
        candidates = []
        for part in parts:
            lower = part.lower()
            if lower in self.PRODUCT_PATH_MARKERS or lower in {"gp", "buy", "store", "collections", "category"}:
                continue
            name = self._clean_product_slug(part)
            if not name or self._looks_like_identifier(name):
                continue
            candidates.append(name)
        if not candidates:
            return ""
        return max(candidates, key=len)

    def _clean_product_slug(self, value: str) -> str:
        slug = unquote(str(value or ""))
        slug = re.sub(r"\.html?$", "", slug, flags=re.IGNORECASE)
        slug = re.sub(r"[-_+]+", " ", slug)
        slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff ]+", " ", slug)
        slug = re.sub(r"\s+\d{5,}$", "", slug).strip()
        return self._humanize_product_name(" ".join(slug.split()))

    def _humanize_product_name(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if re.search(r"[A-Z]", text):
            return text
        return " ".join(word.capitalize() if re.search(r"[A-Za-z]", word) else word for word in text.split())

    def _looks_like_identifier(self, value: str) -> bool:
        text = str(value or "").strip()
        compact = re.sub(r"\s+", "", text)
        if not compact:
            return True
        if len(text.split()) >= 3:
            return False
        if compact.isdigit():
            return True
        if re.search(r"\d", compact) and re.fullmatch(r"[A-Z0-9]{8,18}", compact, flags=re.IGNORECASE):
            return True
        return bool(
            re.search(r"\d", compact)
            and len(compact) > 18
            and re.fullmatch(r"[A-Z0-9]+", compact, flags=re.IGNORECASE)
        )

    def _dedupe(self, rows: list[str]) -> list[str]:
        seen = set()
        result = []
        for row in rows or []:
            item = str(row or "").strip()
            key = item.lower()
            if item and key not in seen:
                seen.add(key)
                result.append(item)
        return result


class SourcePlanner:
    """Turns a campaign and persona into executable acquisition sources."""

    def __init__(self, storage: GrowthStorage):
        self.storage = storage

    def plan(self, campaign: AcquisitionCampaign, persona: AudiencePersona, max_sources: int = 5, intelligence: dict | None = None) -> list[AcquisitionSource]:
        sources: list[AcquisitionSource] = []
        value = str(campaign.input_value or "").strip()
        intelligence_sources = self._intelligence_sources(campaign.id, intelligence or {})
        direct_source_types = {"creator_url", "content_url", "live_room_url", "hashtag"}
        if campaign.input_type in direct_source_types and value:
            sources.append(self._source(campaign.id, campaign.input_type, self._normalize_direct_value(campaign.input_type, value), "运营输入的直接获客目标", 100))
        if self._should_prioritize_intelligence_sources(intelligence or {}) and campaign.input_type not in direct_source_types:
            sources.extend(intelligence_sources[:max_sources])
        if campaign.input_type in direct_source_types:
            pass
        elif len(sources) < max_sources and campaign.input_type in {"product_url", "keyword"}:
            sources.extend(self._rule_based_acquisition_sources(campaign, persona, max_sources - len(sources)))
        elif len(sources) < max_sources:
            sources.append(self._source(campaign.id, "keyword", value, "根据推广目标生成的关键词", 90))
        if not self._should_prioritize_intelligence_sources(intelligence or {}):
            for source in intelligence_sources:
                if len(sources) >= max_sources:
                    break
                sources.append(source)
        for keyword in self._expanded_search_keywords(campaign, persona):
            if len(sources) >= max_sources:
                break
            sources.append(self._source(campaign.id, "keyword", keyword, "受众画像推荐搜索词", 70))
        for tag in persona.hashtags:
            if len(sources) >= max_sources:
                break
            sources.append(self._source(campaign.id, "hashtag", tag, "受众画像推荐话题标签", 60))
        saved: list[AcquisitionSource] = []
        seen = set()
        for source in sources:
            key = (source.source_type, source.source_value.lower())
            if source.source_value and key not in seen:
                seen.add(key)
                saved.append(self.storage.upsert_acquisition_source(source))
        return saved

    def _source(self, campaign_id: str, source_type: str, source_value: str, reason: str, priority: int) -> AcquisitionSource:
        return AcquisitionSource(
            id=new_id("as"),
            campaign_id=campaign_id,
            source_type=source_type,
            source_value=source_value,
            reason=reason,
            priority=priority,
        )

    def _intelligence_sources(self, campaign_id: str, intelligence: dict) -> list[AcquisitionSource]:
        sources: list[AcquisitionSource] = []
        for row in intelligence.get("source_suggestions") or []:
            source_type = str(row.get("source_type") or "").strip()
            source_value = str(row.get("source_value") or "").strip()
            if not source_type or not source_value:
                continue
            if source_type == "keyword" and looks_like_url(source_value):
                continue
            sources.append(
                self._source(
                    campaign_id,
                    source_type,
                    self._normalize_direct_value(source_type, source_value),
                    str(row.get("reason") or "智能策略推荐来源"),
                    int(row.get("priority") or 70),
                )
            )
        return sources

    def _should_prioritize_intelligence_sources(self, intelligence: dict) -> bool:
        provider = str((intelligence or {}).get("provider") or "")
        mode = str((intelligence or {}).get("mode") or "")
        return bool(provider and provider not in {"rules_ai_ready_v1", "configured_ai_fallback_rules"} and mode != "offline_rules")

    def _rule_based_acquisition_sources(self, campaign: AcquisitionCampaign, persona: AudiencePersona, limit: int) -> list[AcquisitionSource]:
        if limit <= 0:
            return []
        product = str(campaign.product_name or campaign.input_value or "").strip()
        is_beauty = str(campaign.category or "").lower() == "beauty"
        candidates: list[tuple[str, str, str, int]] = []
        operator_keywords = split_operator_keywords(campaign.input_value, limit=limit)
        for index, keyword in enumerate(operator_keywords):
            candidates.append(("keyword", keyword, "运营输入的关键词列表", max(80, 100 - index * 2)))
        if product:
            candidates.append(("keyword", product, "核心产品词：先找最直接相关内容", 100))
            candidates.append(("keyword", f"{product} review", "评测内容：评论区更容易出现购买咨询", 94))
            if is_beauty:
                candidates.append(("keyword", f"{product} before after", "效果对比内容：优先捕获高意向评论", 92))
                candidates.append(("keyword", f"{product} routine", "使用场景内容：捕获咨询型客户", 88))
            else:
                candidates.append(("keyword", f"{product} where to buy", "购买入口意图：优先捕获找链接用户", 92))
                candidates.append(("keyword", f"{product} best", "对比选择内容：捕获决策期用户", 88))
            candidates.append(("keyword", f"{product} tiktok shop", "社媒购物场景：匹配平台内种草内容", 84))
            tag = self._compact_hashtag(product)
            if tag:
                candidates.append(("hashtag", tag, "产品话题标签：扫描同类话题热门内容", 80))
        for keyword in self._expanded_search_keywords(campaign, persona):
            candidates.append(("keyword", keyword, "受众画像推荐搜索词", 74))
        for tag in persona.hashtags:
            candidates.append(("hashtag", tag, "行业话题标签：扩展同类内容评论区", 68))
        return [
            self._source(campaign.id, source_type, self._normalize_direct_value(source_type, source_value), reason, priority)
            for source_type, source_value, reason, priority in candidates[:limit]
            if str(source_value or "").strip()
        ]

    def _expanded_search_keywords(self, campaign: AcquisitionCampaign, persona: AudiencePersona) -> list[str]:
        product = str(campaign.product_name or "").strip()
        rows = []
        for item in [*split_operator_keywords(campaign.input_value), product, *list(persona.search_keywords or [])]:
            text = str(item or "").strip()
            if not text:
                continue
            if looks_like_url(text):
                continue
            if campaign.input_type in {"product_url", "shop_url"} and text.lower() in {"review", "best product"}:
                continue
            if campaign.input_type in {"product_url", "shop_url"} and not self._is_useful_product_keyword(text):
                continue
            if text:
                rows.append(text)
        return self._dedupe(rows)

    def _is_useful_product_keyword(self, value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        words = [word for word in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", text) if word]
        if len(words) >= 2:
            return True
        lowered = text.lower()
        if lowered in {"count", "pcs", "pc", "pack", "set", "best", "review", "buy", "link", "price", "shop"}:
            return False
        if re.search(r"\d", text):
            return False
        return len(text) >= 8

    def _compact_hashtag(self, value: str) -> str:
        words = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", str(value or ""))
        if not words:
            return ""
        if any(re.search(r"[\u4e00-\u9fff]", word) for word in words):
            return "".join(words[:4])[:30]
        useful = [word.lower() for word in words if len(word) > 2]
        return "".join(useful[:4])[:30]

    def _dedupe(self, rows: list[str]) -> list[str]:
        seen = set()
        result = []
        for row in rows or []:
            item = str(row or "").strip()
            key = item.lower()
            if item and key not in seen:
                seen.add(key)
                result.append(item)
        return result

    def _normalize_direct_value(self, source_type: str, value: str) -> str:
        if source_type == "creator_url" and value.startswith("@"):
            return f"https://www.tiktok.com/{value}"
        if source_type == "hashtag":
            return value.lstrip("#")
        return value


class StrategyBuilder:
    """Builds an editable acquisition strategy from campaign and persona data."""

    def build(
        self,
        campaign: AcquisitionCampaign,
        persona: AudiencePersona,
        sources: list[AcquisitionSource],
        intelligence: dict | None = None,
    ) -> AcquisitionStrategy:
        intelligence = intelligence or {}
        source_expansion = [
            {
                "source_type": source.source_type,
                "source_value": source.source_value,
                "priority": source.priority,
                "reason": source.reason,
                "editable": True,
            }
            for source in sources
        ]
        product_analysis = {
            "input_type": campaign.input_type,
            "product_name": campaign.product_name,
            "category": campaign.category or "general",
            "objective": campaign.objective,
            "market": campaign.target_market,
            "language": campaign.target_language,
            "confidence": "rule_based",
        }
        product_analysis.update(intelligence.get("product_analysis") or {})
        product_analysis["input_type"] = campaign.input_type
        product_analysis["objective"] = campaign.objective
        product_analysis["market"] = campaign.target_market
        product_analysis["language"] = campaign.target_language
        product_analysis["intelligence_provider"] = intelligence.get("provider", "rules_v1")
        audience_profile = {
            "demographics": persona.demographics,
            "interests": persona.interests,
            "pain_points": persona.pain_points,
            "buying_triggers": persona.buying_triggers,
        }
        if intelligence.get("audience_profile"):
            audience_profile.update(intelligence.get("audience_profile") or {})
            audience_profile["demographics"] = persona.demographics
        intent_taxonomy = intelligence.get("intent_taxonomy") or [
            {
                "intent_type": "purchase",
                "keywords": self._pick_keywords(persona.intent_keywords, ["where", "buy", "price", "link", "coupon"]),
                "score_hint": 80,
                "operator_note": "优先进入客户池，并生成评论/关注/私信预检动作。",
            },
            {
                "intent_type": "consult",
                "keywords": self._pick_keywords(persona.intent_keywords, ["how", "which", "recommend", "routine", "shipping"]),
                "score_hint": 65,
                "operator_note": "适合通过评论回答问题，再观察主页或私信入口。",
            },
            {
                "intent_type": "exclude",
                "keywords": persona.exclude_keywords,
                "score_hint": 0,
                "operator_note": "过滤娱乐、垃圾或无关评论。",
            },
        ]
        outreach_recommendations = intelligence.get("outreach_recommendations") or [
            {
                "action_type": "comment_reply",
                "priority": 1,
                "template_angle": "回答用户问题，避免硬广。",
                "risk_level": "medium",
            },
            {
                "action_type": "follow_review",
                "priority": 2,
                "template_angle": "仅对高意向且主页正常的用户进入关注复核。",
                "risk_level": "medium",
            },
            {
                "action_type": "dm_review",
                "priority": 3,
                "template_angle": "私信入口可用且授权允许时再执行；失败降级评论。",
                "risk_level": "high",
            },
        ]
        return AcquisitionStrategy(
            campaign_id=campaign.id,
            product_analysis=product_analysis,
            audience_profile=audience_profile,
            intent_taxonomy=intent_taxonomy,
            source_expansion=source_expansion,
            outreach_recommendations=outreach_recommendations,
            editable_fields=[
                "intent_taxonomy",
                "source_expansion",
                "outreach_recommendations",
                "audience_profile.interests",
                "audience_profile.pain_points",
                "product_analysis.customer_problem",
                "product_analysis.primary_offer",
            ],
            generator=intelligence.get("provider", "rules_v1"),
        )

    def _pick_keywords(self, keywords: list[str], preferred: list[str]) -> list[str]:
        by_lower = {str(item).lower(): str(item) for item in keywords or []}
        picked = [by_lower[item] for item in preferred if item in by_lower]
        for item in keywords or []:
            if len(picked) >= 8:
                break
            value = str(item or "").strip()
            if value and value not in picked:
                picked.append(value)
        return picked
