# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class OutreachCopySuggestion:
    action_type: str
    text: str
    angle: str = ""
    provider: str = "rules_copy_v1"
    risk_note: str = ""


class OutreachCopyRecommender(Protocol):
    name: str

    def recommend(self, action_type: str, row: dict, lead_type: str, priority: str, config=None) -> OutreachCopySuggestion:
        ...


class RuleBasedOutreachCopyRecommender:
    """Offline copy recommender for action queue generation."""

    name = "rules_copy_v1"

    def recommend(self, action_type: str, row: dict, lead_type: str, priority: str, config=None) -> OutreachCopySuggestion:
        action_type = str(action_type or "")
        if action_type == "comment_reply":
            return self._comment(row, lead_type, priority)
        if action_type == "follow_review":
            return self._follow(row, lead_type, priority)
        if action_type == "dm_review":
            return self._dm(row, lead_type, priority)
        return OutreachCopySuggestion(action_type=action_type, text="", angle="unsupported", provider=self.name)

    def _comment(self, row: dict, lead_type: str, priority: str) -> OutreachCopySuggestion:
        language = str(row.get("comment_language") or "").strip().lower()
        tags = " ".join(self._tags(row)).lower()
        comment = str(row.get("comment_text") or "").lower()
        if "intent_type:purchase" in tags or lead_type in {"找链接/入口", "购买意图"}:
            text = self._localized_comment_text(
                language,
                {
                    "en": "You can check the current product page first; details and price may change.",
                    "es": "Puedes revisar primero la pagina del producto; los detalles y el precio pueden cambiar.",
                    "pt": "Voce pode conferir primeiro a pagina do produto; detalhes e preco podem mudar.",
                    "zh": "可以先查看当前产品页面，详情和价格可能会变化。",
                },
            )
            angle = "answer purchase path"
        elif "price" in comment or lead_type in {"问价格", "优惠券", "折扣"}:
            text = self._localized_comment_text(
                language,
                {
                    "en": "Price and promos can change, so the product page is the safest source.",
                    "es": "El precio y las promociones pueden cambiar, asi que la pagina del producto es la fuente mas segura.",
                    "pt": "Preco e promocoes podem mudar, entao a pagina do produto e a fonte mais segura.",
                    "zh": "价格和优惠可能会变化，产品页面是最稳妥的信息来源。",
                },
            )
            angle = "answer price concern"
        elif any(token in comment for token in ["app", "download", "watch", "episode", "name"]):
            text = self._localized_comment_text(
                language,
                {
                    "en": "I would verify the exact source first so I do not point you to the wrong place.",
                    "es": "Primero verificaria la fuente exacta para no enviarte al lugar equivocado.",
                    "pt": "Eu verificaria a fonte exata primeiro para nao te indicar o lugar errado.",
                    "zh": "我会先确认准确来源，避免把你指到错误页面。",
                },
            )
            angle = "answer source lookup"
        else:
            text = self._localized_comment_text(
                language,
                {
                    "en": "Good question. I would check the latest product details before deciding.",
                    "es": "Buena pregunta. Revisaria los detalles mas recientes del producto antes de decidir.",
                    "pt": "Boa pergunta. Eu conferiria os detalhes mais recentes do produto antes de decidir.",
                    "zh": "这个问题不错，决定前建议先看最新产品详情。",
                },
            )
            angle = "neutral helpful reply"
        return OutreachCopySuggestion(action_type="comment_reply", text=text, angle=angle, provider=self.name, risk_note="avoid spam wording")

    def _follow(self, row: dict, lead_type: str, priority: str) -> OutreachCopySuggestion:
        username = str(row.get("username") or "").lstrip("@")
        text = f"复核 @{username} 是否为高意图用户，确认主页正常后再关注。"
        return OutreachCopySuggestion(action_type="follow_review", text=text, angle="operator review", provider=self.name, risk_note="follow only after profile preflight")

    def _dm(self, row: dict, lead_type: str, priority: str) -> OutreachCopySuggestion:
        username = str(row.get("username") or "").lstrip("@")
        if priority == "high":
            text = f"Hi @{username}, saw your comment about {lead_type}. I can share the details if you still need them."
        else:
            text = f"Hi @{username}, saw your comment. If you still need the details, I can help."
        return OutreachCopySuggestion(action_type="dm_review", text=text, angle="direct help", provider=self.name, risk_note="dm only when platform allows")

    def _tags(self, row: dict) -> list[str]:
        tags = row.get("intent_tags") or []
        if isinstance(tags, str):
            try:
                import json

                parsed = json.loads(tags)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except Exception:
                return [tags]
        return [str(item) for item in tags or []]

    def _localized_comment_text(self, language: str, variants: dict[str, str]) -> str:
        language = str(language or "").strip().lower()
        if language in {"zh-cn", "zh-hans", "chinese"}:
            language = "zh"
        if language in {"english"}:
            language = "en"
        if language in {"spanish"}:
            language = "es"
        if language in {"portuguese"}:
            language = "pt"
        return variants.get(language) or variants["en"]
