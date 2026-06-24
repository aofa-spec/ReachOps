# -*- coding: utf-8 -*-
from __future__ import annotations

PRODUCT_ID = "reachops"
PRODUCT_NAME = "ReachOps"
PRODUCT_NAME_CN = "增长获客工作台"
VERSION = "0.4.0"
BUILD_CHANNEL = "mvp"


def version_info() -> dict:
    return {
        "product_id": PRODUCT_ID,
        "product_name": PRODUCT_NAME,
        "product_name_cn": PRODUCT_NAME_CN,
        "version": VERSION,
        "channel": BUILD_CHANNEL,
    }
