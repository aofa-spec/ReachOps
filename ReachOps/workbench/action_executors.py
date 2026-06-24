# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class PlatformActionExecutor(Protocol):
    def execute(self, action: dict, profile: dict, rendered_text: str, dry_run: bool = True) -> dict:
        ...


@dataclass
class ActionExecutionRequest:
    action: dict
    profile: dict
    rendered_text: str
    dry_run: bool = True


class BaseActionExecutor:
    action_type = ""

    def __init__(self, platform_executor: PlatformActionExecutor):
        self.platform_executor = platform_executor

    def execute(self, request: ActionExecutionRequest) -> dict:
        action = dict(request.action or {})
        action["action_type"] = self.action_type or str(action.get("action_type") or "")
        return self.platform_executor.execute(action, request.profile, request.rendered_text, dry_run=request.dry_run)


class CommentExecutor(BaseActionExecutor):
    """Executes or preflights comment actions on the source video page."""

    action_type = "comment_reply"


class FollowExecutor(BaseActionExecutor):
    """Executes or preflights follow actions on the target profile page."""

    action_type = "follow_review"


class DMExecutor(BaseActionExecutor):
    """Executes or preflights DM actions when the platform exposes an entry."""

    action_type = "dm_review"


class ActionExecutorRegistry:
    def __init__(self, platform_executor: PlatformActionExecutor):
        self.executors = {
            "comment_reply": CommentExecutor(platform_executor),
            "follow_review": FollowExecutor(platform_executor),
            "dm_review": DMExecutor(platform_executor),
        }

    def execute(self, action: dict, profile: dict, rendered_text: str, dry_run: bool = True) -> dict:
        action_type = str(action.get("action_type") or "")
        executor = self.executors.get(action_type)
        if not executor:
            return {
                "status": "failed",
                "error_code": "UNSUPPORTED_ACTION_TYPE",
                "error_message": f"unsupported action_type: {action_type}",
                "evidence_path": "",
            }
        return executor.execute(ActionExecutionRequest(action, profile, rendered_text, dry_run=dry_run))
