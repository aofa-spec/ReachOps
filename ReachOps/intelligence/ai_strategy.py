# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Protocol

from ReachOps.credentials import resolve_ai_api_key

from .schemas import AcquisitionCampaign
from .source_planner import split_operator_keywords


class AcquisitionIntelligenceProvider(Protocol):
    """Pluggable product/audience intelligence provider.

    Implementations can call an external AI service, a local model, or a rule
    engine. The rest of ReachOps only consumes the normalized dictionary
    returned by this contract.
    """

    name: str

    def analyze(
        self,
        campaign: AcquisitionCampaign,
        intent_keywords: list[str] | None = None,
        exclude_keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        ...


def build_default_acquisition_intelligence_provider(env: dict[str, str] | None = None) -> AcquisitionIntelligenceProvider:
    env = env or os.environ
    endpoint = str(env.get("REACHOPS_AI_ENDPOINT") or "").strip()
    if not endpoint:
        return RuleBasedAcquisitionIntelligenceProvider()
    api_key = resolve_ai_api_key(env=env)
    return HTTPAcquisitionIntelligenceProvider(
        endpoint=endpoint,
        api_key=api_key.value,
        model=str(env.get("REACHOPS_AI_MODEL") or "").strip() or "reachops-default",
        timeout_seconds=float(env.get("REACHOPS_AI_TIMEOUT_SECONDS") or 20),
        provider_name=str(env.get("REACHOPS_AI_PROVIDER_NAME") or "").strip() or "http_ai_provider",
    )


class HTTPAcquisitionIntelligenceProvider:
    """Configurable HTTP provider for external AI product/audience analysis.

    The provider accepts generic JSON responses and OpenAI-compatible chat
    responses. It never stores credentials; callers pass endpoint/key through
    runtime environment or explicit constructor args.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str = "",
        model: str = "reachops-default",
        timeout_seconds: float = 20,
        provider_name: str = "http_ai_provider",
        requester=None,
        fallback_provider: AcquisitionIntelligenceProvider | None = None,
    ):
        self.endpoint = str(endpoint or "").strip()
        self.api_key = str(api_key or "").strip()
        self.model = str(model or "reachops-default").strip()
        self.timeout_seconds = max(1.0, float(timeout_seconds or 20))
        self.name = str(provider_name or "http_ai_provider").strip()
        self.requester = requester or self._urllib_requester
        self.fallback_provider = fallback_provider or RuleBasedAcquisitionIntelligenceProvider()

    def analyze(
        self,
        campaign: AcquisitionCampaign,
        intent_keywords: list[str] | None = None,
        exclude_keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            payload = self._build_payload(campaign, intent_keywords or [], exclude_keywords or [])
            response = self.requester(self.endpoint, payload, self._headers(), self.timeout_seconds)
            normalized = self._normalize_response(response)
            self._validate_response(normalized)
            normalized["provider"] = str(normalized.get("provider") or self.name)
            normalized["mode"] = str(normalized.get("mode") or "http_ai")
            return normalized
        except Exception as exc:
            fallback = self.fallback_provider.analyze(campaign, intent_keywords=intent_keywords, exclude_keywords=exclude_keywords)
            fallback["provider"] = f"{self.name}_fallback_rules"
            fallback["mode"] = "http_ai_fallback"
            fallback["fallback_error"] = exc.__class__.__name__
            return fallback

    def _build_payload(self, campaign: AcquisitionCampaign, intent_keywords: list[str], exclude_keywords: list[str]) -> dict[str, Any]:
        schema_hint = {
            "product_analysis": {
                "category": "string",
                "product_name": "string",
                "customer_problem": "string",
                "primary_offer": "string",
                "keywords": ["string"],
            },
            "audience_profile": {
                "persona": "string",
                "interests": ["string"],
                "pain_points": ["string"],
                "buying_triggers": ["string"],
            },
            "intent_taxonomy": [
                {"intent_type": "purchase|consult|exclude", "keywords": ["string"], "score_hint": 0, "reason": "string"}
            ],
            "source_suggestions": [
                {"source_type": "keyword|hashtag|creator_url|content_url|live_room_url", "source_value": "string", "reason": "string", "priority": 80}
            ],
            "outreach_recommendations": [
                {"action_type": "comment_reply|follow_review|dm_review", "priority": 1, "template_angle": "string", "risk_level": "low|medium|high"}
            ],
        }
        return {
            "model": self.model,
            "task": "reachops_acquisition_intelligence",
            "campaign": {
                "id": campaign.id,
                "input_type": campaign.input_type,
                "input_value": campaign.input_value,
                "objective": campaign.objective,
                "target_market": campaign.target_market,
                "target_language": campaign.target_language,
                "product_name": campaign.product_name,
                "category": campaign.category,
            },
            "operator_keywords": {
                "intent_keywords": intent_keywords,
                "exclude_keywords": exclude_keywords,
            },
            "required_json_schema": schema_hint,
            "instruction": "Return only JSON matching required_json_schema. Optimize for social media customer acquisition.",
        }

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _urllib_requester(self, endpoint: str, payload: dict[str, Any], headers: dict[str, str], timeout_seconds: float) -> dict[str, Any]:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            raise RuntimeError(str(exc)) from exc
        return json.loads(body or "{}")

    def _normalize_response(self, response: Any) -> dict[str, Any]:
        if isinstance(response, bytes):
            response = response.decode("utf-8", errors="replace")
        if isinstance(response, str):
            response = json.loads(response)
        if not isinstance(response, dict):
            raise ValueError("AI response is not a JSON object")
        content = self._extract_content(response)
        if content is not None:
            if isinstance(content, str):
                return json.loads(self._strip_json_fence(content))
            if isinstance(content, dict):
                return content
        return response

    def _extract_content(self, response: dict[str, Any]) -> Any:
        if "product_analysis" in response:
            return None
        if isinstance(response.get("content"), (str, dict)):
            return response.get("content")
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] or {}
            message = first.get("message") if isinstance(first, dict) else {}
            if isinstance(message, dict) and "content" in message:
                return message.get("content")
            if isinstance(first, dict) and "text" in first:
                return first.get("text")
        return None

    def _strip_json_fence(self, text: str) -> str:
        value = str(text or "").strip()
        if value.startswith("```"):
            value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
            value = re.sub(r"\s*```$", "", value)
        return value.strip()

    def _validate_response(self, data: dict[str, Any]):
        if not isinstance(data.get("product_analysis"), dict):
            raise ValueError("missing product_analysis")
        if not isinstance(data.get("audience_profile"), dict):
            raise ValueError("missing audience_profile")
        if not isinstance(data.get("intent_taxonomy"), list):
            raise ValueError("missing intent_taxonomy")
        if not isinstance(data.get("source_suggestions"), list):
            raise ValueError("missing source_suggestions")
        if not isinstance(data.get("outreach_recommendations"), list):
            raise ValueError("missing outreach_recommendations")


class RuleBasedAcquisitionIntelligenceProvider:
    """Offline provider used when no AI service is configured."""

    name = "rules_ai_ready_v1"

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
    DIGITAL_TERMS = {"app", "download", "watch", "episode", "movie", "series", "tool", "software"}
    COMMERCE_TERMS = {"shop", "store", "buy", "coupon", "discount", "sale", "product", "tiktokshop"}

    def analyze(
        self,
        campaign: AcquisitionCampaign,
        intent_keywords: list[str] | None = None,
        exclude_keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        text = f"{campaign.input_value} {campaign.product_name} {campaign.category}".lower()
        category = self._category(text, fallback=campaign.category or "general")
        base_intent = self._intent_keywords(category)
        purchase_terms = ["where", "link", "buy", "price", "coupon", "discount"]
        consult_terms = ["how", "which", "recommend", "routine", "shipping", "size", "name"]
        if category == "digital_content":
            purchase_terms = ["watch", "download", "app", "name", "episode", "free"]
            consult_terms = ["where", "how", "link", "which", "install"]
        merged_intent = self._dedupe(base_intent + list(intent_keywords or []))
        merged_exclude = self._dedupe(["spam", "bot", "giveaway", "haha", "lol"] + list(exclude_keywords or []))
        source_suggestions = self._source_suggestions(campaign, category)
        return {
            "provider": self.name,
            "mode": "offline_rules",
            "confidence": 0.62,
            "product_analysis": {
                "category": category,
                "product_name": campaign.product_name or campaign.input_value,
                "customer_problem": self._customer_problem(category),
                "primary_offer": self._primary_offer(category),
                "market": campaign.target_market,
                "language": campaign.target_language,
                "keywords": self._dedupe(self._split_terms(campaign.product_name) + merged_intent[:8]),
            },
            "audience_profile": {
                "persona": self._persona(category),
                "interests": self._interests(category),
                "pain_points": self._pain_points(category),
                "buying_triggers": self._buying_triggers(category),
                "negative_signals": merged_exclude,
            },
            "intent_taxonomy": [
                {
                    "intent_type": "purchase",
                    "keywords": self._dedupe([item for item in merged_intent if item.lower() in purchase_terms] + purchase_terms),
                    "score_hint": 82,
                    "reason": "直接询问购买、链接、价格、优惠或获取入口。",
                },
                {
                    "intent_type": "consult",
                    "keywords": self._dedupe([item for item in merged_intent if item.lower() in consult_terms] + consult_terms),
                    "score_hint": 66,
                    "reason": "用户正在咨询使用方式、选择建议或产品名称。",
                },
                {
                    "intent_type": "exclude",
                    "keywords": merged_exclude,
                    "score_hint": 0,
                    "reason": "过滤娱乐、抽奖、垃圾或非客户型评论。",
                },
            ],
            "source_suggestions": source_suggestions,
            "outreach_recommendations": [
                {
                    "action_type": "comment_reply",
                    "priority": 1,
                    "template_angle": self._comment_angle(category),
                    "risk_level": "medium",
                },
                {
                    "action_type": "follow_review",
                    "priority": 2,
                    "template_angle": "仅对高意向用户执行关注预检，失败后保持线索状态。",
                    "risk_level": "medium",
                },
                {
                    "action_type": "dm_review",
                    "priority": 3,
                    "template_angle": "私信入口可用且授权允许时触达；失败自动降级评论。",
                    "risk_level": "high",
                },
            ],
        }

    def _category(self, text: str, fallback: str) -> str:
        if any(term in text for term in self.BEAUTY_TERMS):
            return "beauty"
        if any(term in text for term in self.DIGITAL_TERMS):
            return "digital_content"
        if any(term in text for term in self.COMMERCE_TERMS):
            return "social_commerce"
        return fallback or "general"

    def _intent_keywords(self, category: str) -> list[str]:
        if category == "beauty":
            return ["where", "link", "buy", "price", "shade", "routine", "does it work", "before after", "sensitive skin"]
        if category == "digital_content":
            return ["where", "watch", "download", "app", "free", "name", "episode", "link"]
        return ["where", "link", "buy", "price", "need", "name", "how to use", "recommend"]

    def _source_suggestions(self, campaign: AcquisitionCampaign, category: str) -> list[dict[str, Any]]:
        direct_value = str(campaign.input_value or "").strip()
        suggestions = []
        operator_keywords = split_operator_keywords(direct_value)
        if campaign.input_type in {"creator_url", "content_url", "live_room_url", "hashtag", "keyword"}:
            if campaign.input_type == "keyword" and operator_keywords:
                for index, keyword in enumerate(operator_keywords):
                    suggestions.append(
                        {
                            "source_type": "keyword",
                            "source_value": keyword,
                            "reason": "运营输入的关键词列表",
                            "priority": max(80, 100 - index * 2),
                        }
                    )
            else:
                suggestions.append(
                    {
                        "source_type": campaign.input_type,
                        "source_value": direct_value,
                        "reason": "运营输入的直接目标",
                        "priority": 100,
                    }
                )
        for keyword in self._search_keywords(campaign, category):
            suggestions.append({"source_type": "keyword", "source_value": keyword, "reason": "智能策略推荐搜索词", "priority": 82})
        for tag in self._hashtags(category):
            suggestions.append({"source_type": "hashtag", "source_value": tag, "reason": "智能策略推荐话题", "priority": 68})
        return suggestions

    def _search_keywords(self, campaign: AcquisitionCampaign, category: str) -> list[str]:
        operator_keywords = split_operator_keywords(campaign.input_value)
        name = campaign.product_name or (operator_keywords[0] if operator_keywords else campaign.input_value)
        if category == "beauty":
            return self._dedupe([*operator_keywords[:6], name, f"{name} review", "skincare routine", "beauty product review"])
        if category == "digital_content":
            return self._dedupe([name, f"{name} episode", f"{name} app", "where to watch"])
        return self._dedupe([name, f"{name} review", "best product", "tiktok shop finds"])

    def _hashtags(self, category: str) -> list[str]:
        if category == "beauty":
            return ["beauty", "skincare", "makeup", "beautyroutine"]
        if category == "digital_content":
            return ["movie", "series", "app", "watchonline"]
        return ["review", "shopping", "tiktokshop", "fyp"]

    def _persona(self, category: str) -> str:
        if category == "beauty":
            return "beauty buyer comparing products from creator comments"
        if category == "digital_content":
            return "viewer looking for content access, app name, or episode source"
        return "social commerce buyer looking for product proof and purchase path"

    def _interests(self, category: str) -> list[str]:
        if category == "beauty":
            return ["beauty routine", "skincare", "makeup review", "before after"]
        if category == "digital_content":
            return ["short drama", "streaming", "apps", "episode recommendations"]
        return ["product review", "shopping", "tips", "recommendations"]

    def _pain_points(self, category: str) -> list[str]:
        if category == "beauty":
            return ["skin concern", "shade match", "routine uncertainty", "trust before purchase"]
        if category == "digital_content":
            return ["cannot find source", "app name unclear", "episode missing", "free access uncertainty"]
        return ["price", "availability", "trust", "how to use"]

    def _buying_triggers(self, category: str) -> list[str]:
        if category == "beauty":
            return ["where to buy", "product name", "price", "does it work", "before after result"]
        if category == "digital_content":
            return ["where to watch", "download link", "app name", "episode name", "free access"]
        return ["where to buy", "link", "price", "need this", "product name"]

    def _customer_problem(self, category: str) -> str:
        if category == "beauty":
            return "用户被达人内容种草，但还缺购买入口、产品名、效果证明或适用建议。"
        if category == "digital_content":
            return "用户看到内容片段后想找到观看入口、应用名称或下一集。"
        return "用户有兴趣但缺少可信入口、价格、使用方式或购买路径。"

    def _primary_offer(self, category: str) -> str:
        if category == "beauty":
            return "提供产品入口、使用建议和可信内容证明。"
        if category == "digital_content":
            return "提供正确名称、观看入口或下载指引。"
        return "提供清晰入口、优惠信息和低风险咨询。"

    def _comment_angle(self, category: str) -> str:
        if category == "beauty":
            return "直接回答产品名/入口/适用问题，避免夸大功效。"
        if category == "digital_content":
            return "回答名称、入口或集数问题，避免重复刷屏。"
        return "回答用户正在问的问题，给出下一步入口。"

    def _split_terms(self, value: str) -> list[str]:
        return [item.strip() for item in re.split(r"[\s,，;；/_-]+", str(value or "")) if item.strip()]

    def _dedupe(self, rows: list[str]) -> list[str]:
        seen = set()
        out = []
        for row in rows or []:
            item = str(row or "").strip()
            key = item.lower()
            if item and key not in seen:
                seen.add(key)
                out.append(item)
        return out
