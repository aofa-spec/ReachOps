# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from ReachOps.collectors.normalizer import normalize_language_text


INTENT_KEYWORDS = {
    "where": ("where", "onde", "donde", "ou", "wo", "dove", "dimana", "dau", "哪里", "在哪", "どこ", "어디"),
    "link": ("link", "enlace", "lien", "tautan", "链接", "連結", "링크"),
    "download": ("download", "baixar", "descargar", "telecharger", "herunterladen", "scaricare", "unduh", "tai", "下载", "下載", "ダウンロード", "다운로드"),
    "app": ("app", "appli", "aplicativo", "aplicacion", "aplicacion", "aplikasi", "ung dung", "应用", "應用", "アプリ", "앱"),
    "free": ("free", "gratis", "gratuit", "kostenlos", "mien phi", "免费", "免費", "無料", "무료"),
    "watch": ("watch", "assistir", "ver", "regarder", "ansehen", "guardare", "nonton", "xem", "观看", "看", "見る", "보기"),
    "name": ("name", "nome", "nombre", "nom", "nama", "ten", "名字", "名称", "名前", "이름"),
    "episode": ("episode", "episodio", "episode", "folge", "tap", "剧集", "集", "エピソード", "에피소드"),
    "commerce": (
        "cupom",
        "cupon",
        "coupon",
        "desconto",
        "discount",
        "promocao",
        "promoção",
        "oferta",
        "shopee",
        "frete",
        "valor",
        "preco",
        "preço",
        "comprar",
        "quero",
    ),
}


@dataclass
class CommentIntentResult:
    intent_type: str
    confidence: float = 0.0
    matched_keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    score_delta: int = 0
    excluded: bool = False
    reason: str = ""
    provider: str = "rules_comment_intent_v1"


class CommentIntentClassifier(Protocol):
    name: str

    def classify(
        self,
        row: dict,
        custom_intent_keywords: list[str] | None = None,
        exclude_keywords: list[str] | None = None,
    ) -> CommentIntentResult:
        ...


class RuleBasedCommentIntentClassifier:
    """Offline classifier used until an AI provider is configured."""

    name = "rules_comment_intent_v1"

    def classify(
        self,
        row: dict,
        custom_intent_keywords: list[str] | None = None,
        exclude_keywords: list[str] | None = None,
    ) -> CommentIntentResult:
        text = str(row.get("comment_text") or "").lower()
        normalized_text = normalize_language_text(text)
        for keyword in exclude_keywords or []:
            if self._contains_intent(normalized_text, keyword):
                return CommentIntentResult(
                    intent_type="exclude",
                    confidence=0.95,
                    matched_keywords=[keyword],
                    tags=["excluded_keyword", f"intent_ai:{self.name}"],
                    score_delta=-100,
                    excluded=True,
                    reason="matched exclude keyword",
                    provider=self.name,
                )

        matched_intents: list[str] = []
        matched_keywords: list[str] = []
        for intent, keywords in INTENT_KEYWORDS.items():
            for keyword in keywords:
                normalized_keyword = normalize_language_text(keyword)
                if self._contains_intent(normalized_text, normalized_keyword):
                    matched_intents.append(intent)
                    matched_keywords.append(intent)
                    break

        custom_matches = []
        for keyword in custom_intent_keywords or []:
            if self._contains_intent(normalized_text, keyword):
                custom_matches.append(keyword)

        if custom_matches:
            matched_keywords.extend(custom_matches[:5])

        intent_type = self._intent_type(matched_intents, custom_matches)
        tags = [f"intent:{item}" for item in matched_intents]
        tags.extend([f"custom_intent:{item}" for item in custom_matches[:5]])
        tags.append(f"intent_ai:{self.name}")
        score_delta = 0
        if matched_intents:
            score_delta += min(40, 12 + len(matched_intents) * 6)
        if custom_matches:
            score_delta += min(35, 24 + len(custom_matches) * 6)
        confidence = 0.2
        if matched_intents:
            confidence = max(confidence, min(0.82, 0.42 + len(matched_intents) * 0.1))
        if custom_matches:
            confidence = max(confidence, min(0.9, 0.62 + len(custom_matches) * 0.08))
        return CommentIntentResult(
            intent_type=intent_type,
            confidence=confidence,
            matched_keywords=matched_keywords,
            tags=tags,
            score_delta=score_delta,
            excluded=False,
            reason="matched intent keywords" if matched_keywords else "no explicit intent",
            provider=self.name,
        )

    def _intent_type(self, matched_intents: list[str], custom_matches: list[str]) -> str:
        if custom_matches:
            return "purchase"
        if any(item in matched_intents for item in ["where", "link", "commerce", "free"]):
            return "purchase"
        if any(item in matched_intents for item in ["download", "app", "watch", "name", "episode"]):
            return "consult"
        return "low_intent"

    def _contains_intent(self, text: str, keyword: str) -> bool:
        if not text or not keyword:
            return False
        if re.search(r"[a-z0-9]", keyword):
            return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None
        return keyword in text
