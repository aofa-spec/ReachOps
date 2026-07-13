#!/usr/bin/env python3
"""Run the ReachOps unittest suite and persist the complete CI log.

GitHub's job-log API may truncate large outputs in review tooling. This wrapper
keeps the human-readable unittest stream in a downloadable artifact while still
returning the exact unittest process exit code to the workflow.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Path for the complete combined unittest log")
    parser.add_argument("--start-directory", default="tests")
    parser.add_argument("--pattern", default="test_*.py")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        args.start_directory,
        "-p",
        args.pattern,
        "-v",
    ]
    env = dict(os.environ)
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    env.setdefault("PYTHONUNBUFFERED", "1")

    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    output = completed.stdout or ""
    output_path.write_text(output, encoding="utf-8")
    sys.stdout.write(output)
    if output and not output.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
