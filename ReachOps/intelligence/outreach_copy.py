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
        tags = " ".join(self._tags(row)).lower()
        comment = str(row.get("comment_text") or "").lower()
        if "intent_type:purchase" in tags or lead_type in {"找链接/入口", "购买意图"}:
            text = "可以先看视频说明里的入口，具体款式/链接我整理后再补充。"
            angle = "answer purchase path"
        elif "price" in comment or lead_type in {"问价格", "优惠券", "折扣"}:
            text = "价格和优惠会随活动变化，建议先看当前商品页活动价。"
            angle = "answer price concern"
        elif any(token in comment for token in ["app", "download", "watch", "episode", "name"]):
            text = "你问的是名称/入口问题，我先确认准确来源后补充，避免发错。"
            angle = "answer source lookup"
        else:
            text = "这个问题很典型，我整理一下关键信息再补充。"
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
