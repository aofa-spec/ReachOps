# -*- coding: utf-8 -*-
from __future__ import annotations

import json

from .schemas import ActionQueueItem, utc_now_iso
from .storage import GrowthStorage, new_id
from ReachOps.collectors.normalizer import normalize_language_text
from .lead_quality import looks_like_seller_promo
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
            observation = self._record_runtime_observation(row, config)
            if observation:
                self._record_runtime_lead_decision(row, config, observation, intent_type, confidence, evidence)
            if intent_type:
                _, created = self.storage.upsert_audience_intent(row["id"], row["content_id"], intent_type, confidence, evidence)
                if created:
                    stats["intents"] += 1
                    self.storage.log_event("audience_intent_created", row["id"], {"intent_type": intent_type, "confidence": confidence})
            if score < 40 and confidence < 50 and not bool(getattr(config, "accept_low_intent_actions", False)):
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

    def _record_runtime_observation(self, row: dict, config) -> dict:
        campaign_id = str(getattr(config, "campaign_id", "") or row.get("campaign_id") or "").strip()
        run_id = str(getattr(config, "active_run_id", "") or row.get("run_id") or "").strip()
        if not campaign_id or not run_id:
            return {}
        candidate_id = str(row.get("id") or "").strip()
        if not candidate_id:
            return {}
        source_path = str(row.get("source_path") or row.get("content_source_path") or row.get("video_url") or "")
        evidence = self.storage.record_evidence_artifact(
            campaign_id=campaign_id,
            run_id=run_id,
            entity_type="candidate_observation",
            entity_id=candidate_id,
            local_path=source_path,
            sidecar={
                "candidate_user_id": candidate_id,
                "content_id": str(row.get("content_id") or ""),
                "source_id": str(row.get("source_id") or ""),
                "no_submit": True,
            },
        )
        return self.storage.record_candidate_observation(
            campaign_id=campaign_id,
            run_id=run_id,
            candidate_user_id=candidate_id,
            content_id=str(row.get("content_id") or ""),
            source_id=str(row.get("source_id") or ""),
            evidence_id=evidence["id"],
            collector_version=str(row.get("collector_level") or "collector_runtime"),
            classifier_version="operation_lead_manager.v1",
            feature_snapshot={
                "qualify_score": int(row.get("qualify_score") or 0),
                "intent_tags": self._intent_tags(row),
                "comment_language": str(row.get("comment_language") or ""),
                "source_path": source_path,
            },
            batch_id=str(getattr(config, "active_batch_id", "") or row.get("batch_id") or ""),
        )

    def _record_runtime_lead_decision(self, row: dict, config, observation: dict, intent_type: str, confidence: int, evidence: str) -> dict:
        campaign_id = str(getattr(config, "campaign_id", "") or "").strip()
        run_id = str(getattr(config, "active_run_id", "") or "").strip()
        observation_id = str((observation or {}).get("id") or "").strip()
        if not campaign_id or not run_id or not observation_id:
            return {}
        score = int(row.get("qualify_score") or 0)
        tags = self._intent_tags(row)
        return self.storage.record_lead_decision(
            campaign_id=campaign_id,
            run_id=run_id,
            candidate_observation_id=observation_id,
            intent_type=str(intent_type or "engaged_commenter"),
            intent_score=max(score, int(confidence or 0)),
            product_fit_score=score,
            contactability_score=50 if str(row.get("profile_url") or "") else 0,
            source_quality_score=min(100, int(row.get("views") or 0) // 1000 + int(row.get("video_comments") or 0)),
            total_lead_score=max(score, int(confidence or 0)),
            confidence=int(confidence or 0),
            reason_codes=[tag for tag in tags if tag] + ([evidence] if evidence else []),
            feature_snapshot={
                "qualify_score": score,
                "intent_tags": tags,
                "comment_language": str(row.get("comment_language") or ""),
            },
            classifier_provider_version="operation_lead_manager.v1",
            decision_key=str(row.get("id") or ""),
        )

    def _intent_tags(self, row: dict) -> list[str]:
        raw = row.get("intent_tags")
        if isinstance(raw, list):
            return [str(item) for item in raw if str(item or "").strip()]
        try:
            parsed = json.loads(raw or "[]")
        except Exception:
            parsed = []
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item or "").strip()]
        return []

    def detect_intent(self, row: dict, config=None) -> tuple[str, int, str]:
        raw_text = str(row.get("comment_text") or "")
        if looks_like_seller_promo(raw_text):
            return "", 0, "排除卖家/品牌自促评论"
        text = normalize_language_text(raw_text.lower())
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
        score = int(row.get("qualify_score") or 0)
        raw_min_action_score = getattr(config, "min_lead_score_for_action", 50)
        min_action_score = max(0, int(50 if raw_min_action_score is None else raw_min_action_score))
        standard_policy = bool(getattr(config, "enable_standard_outreach_policy", True))
        explicit_intent = bool(lead_type and lead_type != "engaged_commenter")
        if standard_policy and priority != "high" and not explicit_intent and score < min_action_score:
            self.storage.log_event(
                "action_queue_skipped_low_intent",
                str(lead_id or ""),
                {
                    "username": row.get("username"),
                    "score": score,
                    "min_score": min_action_score,
                    "lead_type": lead_type,
                    "explicit_intent": explicit_intent,
                },
            )
            return 0
        username = str(row.get("username") or "")
        profile_url = str(row.get("profile_url") or "")
        comment_target_url = str(row.get("source_path") or row.get("video_url") or profile_url)
        actions = []
        if getattr(config, "enable_comment_queue", True):
            suggestion = self.copy_recommender.recommend("comment_reply", row, lead_type, priority, config)
            actions.append(("comment_reply", comment_target_url, suggestion.text, "medium", suggestion))
        if getattr(config, "enable_follow_queue", True) and (not standard_policy or priority == "high"):
            follow_risk = "medium" if priority == "high" else "low"
            suggestion = self.copy_recommender.recommend("follow_review", row, lead_type, priority, config)
            actions.append(("follow_review", profile_url, suggestion.text, follow_risk, suggestion))
        if getattr(config, "enable_dm_queue", True) and (not standard_policy or priority == "high"):
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
            batch_id = str(getattr(config, "active_batch_id", "") or "").strip()
            if batch_id:
                try:
                    with self.storage.connect() as conn:
                        conn.execute(
                            "UPDATE action_queue SET batch_id=COALESCE(NULLIF(batch_id, ''), ?) WHERE id=?",
                            (batch_id, item.id),
                        )
                except Exception:
                    pass
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
