# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.runtime_paths import RuntimePaths
from ReachOps.workbench.local_backup import (
    BACKUP_FILE_EXTENSION,
    BackupError,
    build_backup_preview,
    create_encrypted_backup,
    inspect_encrypted_backup,
    restore_encrypted_backup,
)


def _passphrase(args: argparse.Namespace, *, required: bool) -> str:
    env_name = str(args.passphrase_env or "REACHOPS_BACKUP_PASSPHRASE")
    value = os.environ.get(env_name, "")
    if value:
        return value
    if required:
        return getpass.getpass("ReachOps backup password: ")
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create, inspect, preview, or restore local ReachOps backups.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--passphrase-env", default="REACHOPS_BACKUP_PASSPHRASE", help="Environment variable containing the backup password.")
    sub = parser.add_subparsers(dest="command", required=True)

    preview = sub.add_parser("preview", help="Preview files selected for backup.")
    preview.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Print JSON output.")
    preview.add_argument("--source", default="", help="Runtime root. Defaults to RuntimePaths.")
    preview.add_argument("--full", action="store_true", help="Include selected evidence files.")

    create = sub.add_parser("create", help=f"Create an encrypted {BACKUP_FILE_EXTENSION} archive.")
    create.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Print JSON output.")
    create.add_argument("--source", default="", help="Runtime root. Defaults to RuntimePaths.")
    create.add_argument("--output", required=True, help="Output .reachops-backup path.")
    create.add_argument("--full", action="store_true", help="Include selected evidence files.")

    inspect = sub.add_parser("inspect", help="Authenticate and inspect an encrypted backup.")
    inspect.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Print JSON output.")
    inspect.add_argument("--backup", required=True, help="Backup path.")

    restore = sub.add_parser("restore", help="Restore an encrypted backup atomically.")
    restore.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Print JSON output.")
    restore.add_argument("--backup", required=True, help="Backup path.")
    restore.add_argument("--destination", required=True, help="Destination runtime root.")
    restore.add_argument("--preview-only", action="store_true", help="Only show restore plan.")

    args = parser.parse_args(argv)
    try:
        if args.command == "preview":
            source = args.source or RuntimePaths.build().base_dir
            result = build_backup_preview(source, full=bool(args.full))
        elif args.command == "create":
            source = args.source or RuntimePaths.build().base_dir
            result = create_encrypted_backup(source, args.output, _passphrase(args, required=True), full=bool(args.full))
        elif args.command == "inspect":
            result = inspect_encrypted_backup(args.backup, _passphrase(args, required=True))
        elif args.command == "restore":
            result = restore_encrypted_backup(args.backup, args.destination, _passphrase(args, required=True), preview_only=bool(args.preview_only))
        else:
            parser.error("unknown command")
    except (BackupError, FileNotFoundError, ValueError) as exc:
        result = {
            "status": "failed",
            "error": type(exc).__name__,
            "message": str(exc),
            "no_browser_started": True,
            "no_submit": True,
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result.get('status', 'ok')}: {result.get('path') or result.get('destination_dir') or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
