from __future__ import annotations

import re
import sys
from pathlib import Path

PATTERN = re.compile(r"^(?:ERROR|FAIL):\s+([^\s]+)", re.MULTILINE)
SUMMARY = re.compile(r"Ran\s+(\d+)\s+tests?", re.MULTILINE)


def test_failures(path: str) -> set[str]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return set(PATTERN.findall(text))


def test_count(path: str) -> int:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    matches = SUMMARY.findall(text)
    return int(matches[-1]) if matches else 0


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: compare_regression_failures.py BASELINE_LOG PATCHED_LOG", file=sys.stderr)
        return 2
    baseline_path, patched_path = sys.argv[1], sys.argv[2]
    baseline = test_failures(baseline_path)
    patched = test_failures(patched_path)
    unexpected = sorted(patched - baseline)
    resolved = sorted(baseline - patched)
    baseline_count = test_count(baseline_path)
    patched_count = test_count(patched_path)
    print(f"baseline_tests={baseline_count}")
    print(f"patched_tests={patched_count}")
    print(f"baseline_failures={len(baseline)}")
    print(f"patched_failures={len(patched)}")
    print(f"resolved_failures={resolved}")
    print(f"unexpected_failures={unexpected}")
    if baseline_count <= 0 or patched_count <= 0:
        print("missing unittest summary in one or both logs", file=sys.stderr)
        return 3
    if patched_count < baseline_count:
        print("patched suite executed fewer tests than baseline", file=sys.stderr)
        return 4
    if unexpected:
        print("truthful execution patch introduced new regression failures", file=sys.stderr)
        return 1
    print("regression delta accepted: no failures beyond main baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
