# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def timestamp_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def unique_run_dir(base_dir: Path, run_id: str | None = None) -> tuple[str, Path]:
    base = Path(base_dir).resolve()
    root_id = str(run_id or timestamp_run_id()).strip()
    if not root_id:
        root_id = timestamp_run_id()
    for index in range(1000):
        candidate_id = root_id if index == 0 else f"{root_id}_{index:03d}"
        candidate_dir = base / candidate_id
        try:
            candidate_dir.mkdir(parents=True, exist_ok=False)
            return candidate_id, candidate_dir
        except FileExistsError:
            continue
    raise RuntimeError(f"unable to allocate unique run directory under {base} for {root_id}")
