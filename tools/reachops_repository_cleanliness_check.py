# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "reports",
    "logs",
    "data",
    "config",
    ".codex-tmp",
}

FORBIDDEN_DIR_NAMES = {
    "__pycache__": "python_bytecode_cache",
    ".pytest_cache": "pytest_cache",
    ".mypy_cache": "mypy_cache",
    ".ruff_cache": "ruff_cache",
    ".cache": "tool_cache",
    "htmlcov": "coverage_html",
}

FORBIDDEN_FILE_PATTERNS = {
    "*.pyc": "python_bytecode",
    "*.pyo": "python_optimized_bytecode",
    ".DS_Store": "macos_finder_metadata",
    "*.tmp": "temporary_file",
    "*.bak": "backup_file",
    "*.orig": "merge_backup_file",
    "*~": "editor_backup_file",
    ".coverage": "coverage_data",
}


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _git_worktree_status(root: Path) -> dict[str, Any]:
    git_dir = root / ".git"
    if not git_dir.exists():
        return {
            "checked": False,
            "clean": True,
            "status": "not_git_repository",
            "dirty_count": 0,
            "dirty_items": [],
        }
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--ignore-submodules=dirty",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return {
            "checked": False,
            "clean": False,
            "status": "git_status_unavailable",
            "dirty_count": 1,
            "dirty_items": [{"path": "", "status": "git_status_unavailable", "detail": str(exc)}],
        }
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return {
            "checked": False,
            "clean": False,
            "status": "git_status_failed",
            "dirty_count": 1,
            "dirty_items": [{"path": "", "status": "git_status_failed", "detail": detail}],
        }
    dirty_items: list[dict[str, str]] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        dirty_items.append(
            {
                "path": line[3:].strip() if len(line) > 3 else "",
                "status": line[:2],
            }
        )
    return {
        "checked": True,
        "clean": not dirty_items,
        "status": "clean" if not dirty_items else "dirty",
        "dirty_count": len(dirty_items),
        "dirty_items": dirty_items,
    }


def scan_repository_cleanliness(
    root: Path,
    excluded_dirs: set[str] | None = None,
    *,
    require_clean_git: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    excluded = set(DEFAULT_EXCLUDED_DIRS)
    if excluded_dirs:
        excluded.update(excluded_dirs)

    findings: list[dict[str, str]] = []
    scanned_files = 0
    scanned_dirs = 0

    def visit(directory: Path) -> None:
        nonlocal scanned_files, scanned_dirs
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            findings.append(
                {
                    "path": _relative(directory, root),
                    "kind": "directory",
                    "reason": "scan_error",
                    "detail": str(exc),
                }
            )
            return

        for child in children:
            if child.is_dir():
                if child.name in excluded:
                    continue
                scanned_dirs += 1
                reason = FORBIDDEN_DIR_NAMES.get(child.name)
                if reason:
                    findings.append(
                        {
                            "path": _relative(child, root),
                            "kind": "directory",
                            "reason": reason,
                        }
                    )
                    continue
                visit(child)
                continue

            if child.is_file():
                scanned_files += 1
                for pattern, reason in FORBIDDEN_FILE_PATTERNS.items():
                    if fnmatch.fnmatch(child.name, pattern):
                        findings.append(
                            {
                                "path": _relative(child, root),
                                "kind": "file",
                                "reason": reason,
                            }
                        )
                        break

    visit(root)
    git_worktree = _git_worktree_status(root)
    passed = not findings and (bool(git_worktree.get("clean")) or not require_clean_git)
    return {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "require_clean_git": bool(require_clean_git),
        "root": str(root),
        "scanned_files": scanned_files,
        "scanned_dirs": scanned_dirs,
        "forbidden_count": len(findings),
        "forbidden_items": findings,
        "git_worktree": git_worktree,
        "excluded_dirs": sorted(excluded),
    }


def clean_generated_redundant_paths(root: Path, excluded_dirs: set[str] | None = None) -> dict[str, Any]:
    root = root.resolve()
    excluded = set(DEFAULT_EXCLUDED_DIRS)
    if excluded_dirs:
        excluded.update(excluded_dirs)
    removed: list[str] = []

    def visit(directory: Path) -> None:
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError:
            return
        for child in children:
            if child.is_dir():
                if child.name in excluded:
                    continue
                if child.name in FORBIDDEN_DIR_NAMES:
                    shutil.rmtree(child, ignore_errors=True)
                    removed.append(_relative(child, root))
                    continue
                visit(child)
                continue
            if child.is_file():
                for pattern in FORBIDDEN_FILE_PATTERNS:
                    if fnmatch.fnmatch(child.name, pattern):
                        try:
                            child.unlink()
                            removed.append(_relative(child, root))
                        except OSError:
                            pass
                        break

    visit(root)
    return {"removed_count": len(removed), "removed_items": removed}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check ReachOps repository cleanliness before delivery.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cleanup = clean_generated_redundant_paths(Path(args.root)) if args.clean else {}
    result = scan_repository_cleanliness(Path(args.root))
    if cleanup:
        result["cleanup"] = cleanup
    if args.json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
