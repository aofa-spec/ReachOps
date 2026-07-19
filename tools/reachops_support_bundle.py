#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ReachOps.runtime_paths import RuntimePaths
from ReachOps.support_bundle import create_support_bundle, preview_support_bundle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview or create a redacted ReachOps diagnostic support bundle.")
    parser.add_argument("--base-dir", default="", help="ReachOps runtime base directory. Defaults to the local runtime path.")
    parser.add_argument("--output", default="", help="Output .zip path when --create is used.")
    parser.add_argument("--extra-path", action="append", default=[], help="Additional text diagnostic file to include after redaction.")
    parser.add_argument("--create", action="store_true", help="Create the support bundle zip. Preview is the default.")
    parser.add_argument("--confirm-customer-share", action="store_true", help="Required with --create; confirms the customer previewed and chose to share.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = RuntimePaths.build(args.base_dir or None).ensure_dirs()
    if args.create:
        output = args.output or str(Path(paths.reports_dir) / "reachops-support-bundle.zip")
        result = create_support_bundle(
            paths,
            output,
            extra_paths=args.extra_path,
            customer_confirmed_share=bool(args.confirm_customer_share),
        )
    else:
        result = preview_support_bundle(paths, extra_paths=args.extra_path)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status={result.get('status')}")
        print(f"schema_version={result.get('schema_version')}")
        print(f"file_count={result.get('file_count', 0)}")
        if result.get("path"):
            print(f"path={result.get('path')}")
    return 0 if result.get("status") in {"preview", "created"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
