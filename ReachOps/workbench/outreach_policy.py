# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OutreachPolicy:
    require_review: bool = True
    require_execution_confirmation: bool = True
    allow_comment_execute: bool = False
    allow_follow_execute: bool = False
    allow_dm_execute: bool = False
    max_actions_per_profile_round: int = 10
    max_actions_per_profile_day: int = 20
    cooldown_after_failures: int = 3
    min_delay_seconds: int = 30
    max_delay_seconds: int = 90

    def is_execution_allowed(self, action_type: str, status: str) -> tuple[bool, str]:
        if self.require_review and status != "approved":
            return False, "ACTION_REQUIRES_REVIEW"
        if action_type == "comment_reply" and not self.allow_comment_execute:
            return False, "COMMENT_EXECUTION_DISABLED"
        if action_type == "follow_review" and not self.allow_follow_execute:
            return False, "FOLLOW_EXECUTION_DISABLED"
        if action_type == "dm_review" and not self.allow_dm_execute:
            return False, "DM_EXECUTION_DISABLED"
        return True, ""
