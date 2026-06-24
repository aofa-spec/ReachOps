# -*- coding: utf-8 -*-
"""Backward-compatible import for the first-stage ecommerce collector name."""

from .tiktok_topic_content_collector import TikTokTopicContentCollector


class TikTokShopMaterialCollector(TikTokTopicContentCollector):
    pass
