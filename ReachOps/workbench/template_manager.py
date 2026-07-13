# -*- coding: utf-8 -*-
from __future__ import annotations

import random
from dataclasses import dataclass

from ReachOps.intelligence.storage import GrowthStorage


ACTION_TYPE_ALIASES = {
    "comment": "comment_reply",
    "follow": "follow_review",
    "dm": "dm_review",
}


@dataclass
class RenderedTemplate:
    template_body: str
    rendered_text: str
    variant_count: int = 0
    action_type: str = ""
    template_name: str = ""


class TemplateManager:
    """Template library for automated outreach action text.

    Templates can include variants separated by ``||`` and simple variables:
    ``{username}``, ``{lead_type}``, ``{score}``, ``{reason}``, and
    ``{country}``. Country/group-specific templates are stored as separate
    template names while keeping the same action type.
    """

    def __init__(self, storage: GrowthStorage, seed: int | None = None):
        self.storage = storage
        self.random = random.Random(seed)

    def normalize_action_type(self, action_type: str) -> str:
        return ACTION_TYPE_ALIASES.get(str(action_type or ""), str(action_type or ""))

    def save(
        self,
        action_type: str,
        name: str,
        body: str,
        country: str = "",
        status: str = "active",
    ) -> str:
        normalized = self.normalize_action_type(action_type)
        template_name = str(name or "运营模板").strip()
        if country:
            template_name = f"{country.upper()} - {template_name}"
        return self.storage.upsert_action_template(normalized, template_name, body, status=status)

    def render(self, action: dict, profile: dict | None = None) -> RenderedTemplate:
        normalized = self.normalize_action_type(str(action.get("action_type") or ""))
        fallback = str(action.get("suggested_text") or "")
        profile = profile or {}
        template = {} if fallback.strip() else self._select_template(normalized, action, profile)
        body = fallback if fallback.strip() else str(template.get("body") or "") if template else self.storage.get_action_template_body(normalized, fallback=fallback)
        variants = [item.strip() for item in str(body or fallback or "").split("||") if item.strip()]
        selected = self.random.choice(variants) if variants else fallback
        values = {
            "username": str(action.get("target_username") or "").lstrip("@"),
            "lead_type": str(action.get("lead_type") or ""),
            "score": str(action.get("lead_score") or action.get("score") or ""),
            "reason": str(action.get("reason") or ""),
            "country": str(profile.get("group_name") or profile.get("country") or ""),
            "language": str(action.get("comment_language") or profile.get("language") or ""),
        }
        try:
            rendered = selected.format(**values)
        except Exception:
            rendered = selected
        return RenderedTemplate(
            template_body=body,
            rendered_text=rendered,
            variant_count=len(variants),
            action_type=normalized,
            template_name=str(template.get("name") or "") if template else "",
        )

    def _select_template(self, action_type: str, action: dict, profile: dict) -> dict:
        rows = [
            row
            for row in self.storage.list_action_templates(limit=500)
            if str(row.get("status") or "") == "active" and str(row.get("action_type") or "") == action_type
        ]
        if not rows:
            return {}
        token_weights = self._group_token_weights(action, profile)
        if token_weights:
            matched = []
            for row in rows:
                name_tokens = self._template_name_tokens(str(row.get("name") or ""))
                score = sum(token_weights.get(token, 0) for token in name_tokens)
                if score > 0:
                    matched.append((score, str(row.get("created_at") or ""), row))
            if matched:
                return sorted(matched, key=lambda item: (item[0], item[1]), reverse=True)[0][2]
        generic = [row for row in rows if not self._template_name_tokens(str(row.get("name") or ""))]
        if generic:
            return sorted(
                generic,
                key=lambda row: (
                    0 if str(row.get("name") or "").startswith("默认") else 1,
                    str(row.get("created_at") or ""),
                ),
                reverse=True,
            )[0]
        return sorted(rows, key=lambda row: str(row.get("created_at") or ""), reverse=True)[0]

    def _group_token_weights(self, action: dict, profile: dict) -> dict[str, int]:
        weighted_values = [
            (action.get("comment_language"), 100),
            (action.get("content_country"), 80),
            (profile.get("country"), 70),
            (profile.get("language"), 70),
            (profile.get("group_name"), 50),
            (profile.get("group_id"), 40),
        ]
        weights: dict[str, int] = {}
        for value, weight in weighted_values:
            for token in self._clean_tokens(value):
                weights[token] = max(weights.get(token, 0), weight)
        return weights

    def _template_name_tokens(self, name: str) -> set[str]:
        value = str(name or "")
        if " - " not in value:
            return set()
        prefix = value.split(" - ", 1)[0].strip()
        if not prefix or prefix.startswith("默认"):
            return set()
        tokens = set()
        for clean in self._clean_tokens(prefix):
            tokens.add(clean)
        return tokens

    def _clean_tokens(self, value: str) -> set[str]:
        tokens = set()
        for part in str(value or "").replace("_", " ").replace("-", " ").replace("/", " ").split():
            clean = "".join(ch for ch in part.lower() if ch.isalnum())
            if clean:
                tokens.add(clean)
        return tokens
