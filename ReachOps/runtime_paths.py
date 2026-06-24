# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimePaths:
    """Independent ReachOps runtime path layout."""

    base_dir: str
    data_dir: str
    config_dir: str
    logs_dir: str
    module_dir: str
    reports_dir: str
    db_path: str
    activation_status_path: str

    @classmethod
    def build(cls, base_dir: str | None = None, cwd: str | None = None) -> "RuntimePaths":
        root = cls._default_base_dir(base_dir=base_dir, cwd=cwd)
        data_dir = os.path.join(root, "data")
        config_dir = os.path.join(root, "config")
        logs_dir = os.path.join(root, "logs")
        module_dir = os.path.join(data_dir, "growth_intelligence")
        reports_dir = os.path.join(module_dir, "reports")
        return cls(
            base_dir=root,
            data_dir=data_dir,
            config_dir=config_dir,
            logs_dir=logs_dir,
            module_dir=module_dir,
            reports_dir=reports_dir,
            db_path=os.path.join(module_dir, "growth_intelligence.db"),
            activation_status_path=os.path.join(config_dir, "reachops_activation_status.json"),
        )

    def ensure_dirs(self) -> "RuntimePaths":
        for path in [self.base_dir, self.data_dir, self.config_dir, self.logs_dir, self.module_dir, self.reports_dir]:
            os.makedirs(path, exist_ok=True)
        return self

    @classmethod
    def _default_base_dir(cls, base_dir: str | None = None, cwd: str | None = None) -> str:
        if base_dir:
            return os.path.abspath(os.path.expanduser(base_dir))
        explicit = os.environ.get("REACHOPS_DATA_DIR") or os.environ.get("INTELLIOPS_GROWTH_DATA_DIR")
        if explicit:
            return os.path.abspath(os.path.expanduser(explicit))
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return os.path.abspath(os.path.join(local_app_data, "ReachOps"))
        app_data = os.environ.get("APPDATA")
        if app_data:
            return os.path.abspath(os.path.join(app_data, "ReachOps"))
        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        if xdg_data_home:
            return os.path.abspath(os.path.join(xdg_data_home, "ReachOps"))
        home = os.path.expanduser("~")
        if home and home != "~":
            return os.path.abspath(os.path.join(home, ".reachops"))
        root = cwd or os.getcwd()
        return os.path.abspath(os.path.join(root, "data", "reachops"))
