# -*- coding: utf-8 -*-
from __future__ import annotations

from .schemas import ActionQueueItem, utc_now_iso
from .storage import GrowthStorage, new_id
from ReachOps.collectors.normalizer import normalize_language_text
from .outreach_copy import OutreachCopyRecommender, RuleBasedOutreachCopyRecommender


PURCHASE_INTENT = {
    "where": "找链接/入口",
    "link": "找链接/入口",
    "buy": "购买意图",
    "price": "问价格",
    "how much": "问价格",
    "coupon": "优惠券",
    "discount": "折扣",
    "ship": "物流/配送",
    "download": "下载/安装",
    "app": "App/工具",
    "name": "询问名称",
    "comprar": "购买意图",
    "quero comprar": "购买意图",
    "onde comprar": "找链接/入口",
    "me manda o link": "找链接/入口",
    "preço": "问价格",
    "preco": "问价格",
    "qual o preço": "问价格",
    "cupom": "优惠券",
    "cupon": "优惠券",
    "desconto": "折扣",
    "promocao": "优惠活动",
    "promoção": "优惠活动",
    "oferta": "优惠活动",
    "shopee": "电商购买意图",
    "frete": "物流/配送",
    "frete gratis": "物流/配送",
    "link do produto": "找链接/入口",
    "manda link": "找链接/入口",
    "me manda": "找链接/入口",
    "quero": "购买意图",
    "valor": "问价格",
}


class OperationLeadManager:
    def __init__(self, storage: GrowthStorage, copy_recommender: OutreachCopyRecommender | None = None):
        self.storage = storage
        self.copy_recommender = copy_recommender or RuleBasedOutreachCopyRecommender()

    def build_from_scored_candidates(self, config) -> dict:
        rows = self.storage.list_candidates_with_content(batch_id=getattr(config, "active_batch_id", "") or "")
        stats = {"intents": 0, "leads": 0, "actions": 0}
        for row in rows:
            score = int(row.get("qualify_score") or 0)
            intent_type, confidence, evidence = self.detect_intent(row, config)
            if intent_type:
                _, created = self.storage.upsert_audience_intent(row["id"], row["content_id"], intent_type, confidence, evidence)
                if created:
                    stats["intents"] += 1
                    self.storage.log_event("audience_intent_created", row["id"], {"intent_type": intent_type, "confidence": confidence})
            if score < 40 and confidence < 50:
                continue
            priority = "high" if score >= 70 or confidence >= 80 else "normal"
            lead_type = intent_type or "engaged_commenter"
            reason = evidence or f"qualify_score={score}"
            source_path = str(row.get("source_path") or row.get("content_source_path") or row.get("video_url") or "")
            lead_id, lead_created = self.storage.upsert_operation_lead(
                row["id"],
                lead_type,
                priority,
                max(score, confidence),
                reason,
                source_path=source_path,
            )
            if lead_created:
                stats["leads"] += 1
                self.storage.log_event("operation_lead_created", lead_id, {"username": row.get("username"), "priority": priority})
            if getattr(config, "enable_action_queue", True):
                stats["actions"] += self._create_actions(lead_id, row, lead_type, priority, config)
        return stats

    def detect_intent(self, row: dict, config=None) -> tuple[str, int, str]:
        text = normalize_language_text(str(row.get("comment_text") or "").lower())
        matched = []
        for keyword, intent in PURCHASE_INTENT.items():
            normalized_keyword = normalize_language_text(keyword)
            if normalized_keyword and normalized_keyword in text:
                matched.append(intent)
        custom_keywords = [normalize_language_text(str(item or "").strip().lower()) for item in getattr(config, "intent_keywords", []) or []]
        custom_hits = [keyword for keyword in custom_keywords if keyword and keyword in text]
        if custom_hits:
            matched.append("自定义高意向")
        if not matched:
            return "", 0, ""
        intent_type = matched[0]
        confidence = min(95, 50 + len(set(matched)) * 10 + len(set(custom_hits)) * 5 + int(row.get("comment_likes") or 0))
        evidence_parts = sorted(set(matched))
        if custom_hits:
            evidence_parts.append("自定义词:" + ", ".join(sorted(set(custom_hits))[:5]))
        return intent_type, confidence, f"评论命中意图: {', '.join(evidence_parts)}"

    def _create_actions(self, lead_id: str, row: dict, lead_type: str, priority: str, config) -> int:
        created_count = 0
        username = str(row.get("username") or "")
        profile_url = str(row.get("profile_url") or "")
        comment_target_url = str(row.get("source_path") or row.get("video_url") or profile_url)
        actions = []
        if getattr(config, "enable_comment_queue", True):
            suggestion = self.copy_recommender.recommend("comment_reply", row, lead_type, priority, config)
            actions.append(("comment_reply", comment_target_url, suggestion.text, "medium", suggestion))
        if getattr(config, "enable_follow_queue", True):
            follow_risk = "medium" if priority == "high" else "low"
            suggestion = self.copy_recommender.recommend("follow_review", row, lead_type, priority, config)
            actions.append(("follow_review", profile_url, suggestion.text, follow_risk, suggestion))
        if getattr(config, "enable_dm_queue", True):
            dm_risk = "high" if priority == "high" else "medium"
            suggestion = self.copy_recommender.recommend("dm_review", row, lead_type, priority, config)
            actions.append(("dm_review", profile_url, suggestion.text, dm_risk, suggestion))
        for action_type, target_url, text, risk, suggestion in actions:
            reason = " | ".join(
                item
                for item in [
                    f"lead_type={lead_type}",
                    f"copy_provider={getattr(suggestion, 'provider', '')}",
                    f"copy_angle={getattr(suggestion, 'angle', '')}",
                ]
                if item and not item.endswith("=")
            )
            item = ActionQueueItem(
                id=new_id("aq"),
                lead_id=lead_id,
                action_type=action_type,
                target_username=username,
                target_url=target_url,
                suggested_text=text,
                risk_level=risk,
                reason=reason,
                created_at=utc_now_iso(),
            )
            _, created = self.storage.upsert_action_queue_item(item)
            if created:
                created_count += 1
                self.storage.log_event("action_queue_created", item.id, {"action_type": action_type, "username": username})
        return created_count

    def _render_template(self, action_type: str, values: dict, fallback: str) -> str:
        body = self.storage.get_action_template_body(action_type, fallback)
        try:
            return body.format(**{key: value or "" for key, value in values.items()})
        except Exception:
            return body
