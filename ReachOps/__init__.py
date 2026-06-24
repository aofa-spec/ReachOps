# -*- coding: utf-8 -*-
"""ReachOps standalone product boundary."""

from .version import BUILD_CHANNEL, PRODUCT_ID, PRODUCT_NAME, PRODUCT_NAME_CN, VERSION, version_info
from .updater import ReachOpsUpdateInfo, ReachOpsUpdateManager

from .runtime_paths import RuntimePaths

__all__ = [
    "BUILD_CHANNEL",
    "PRODUCT_ID",
    "PRODUCT_NAME",
    "PRODUCT_NAME_CN",
    "ReachOpsUpdateInfo",
    "ReachOpsUpdateManager",
    "RuntimePaths",
    "VERSION",
    "version_info",
]
