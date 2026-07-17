# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT_DIR / "requirements.lock"
ROOT_REQUIREMENTS = ROOT_DIR / "requirements.txt"
WINDOWS_REQUIREMENTS = ROOT_DIR / "ReachOps" / "packaging" / "requirements-reachops.txt"
LICENSE_INVENTORY = ROOT_DIR / "ReachOps" / "packaging" / "dependency-license-inventory.json"

PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s#]+)$")
RANGE_RE = re.compile(r"(>=|<=|~=|>|<|!=)")


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _normalized_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _lock_packages(path: Path) -> tuple[dict[str, str], list[str]]:
    packages: dict[str, str] = {}
    failures: list[str] = []
    if not path.is_file():
        return packages, ["requirements_lock_missing"]
    for line_no, raw in enumerate(_read_lines(path), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN_RE.match(line)
        if not match:
            failures.append(f"requirements_lock_line_{line_no}_not_exact_pin")
            continue
        name, version = match.groups()
        key = _normalized_name(name)
        if key in packages:
            failures.append(f"requirements_lock_duplicate_{key}")
        packages[key] = version
    if not packages:
        failures.append("requirements_lock_empty")
    return packages, failures


def _requirements_reference(path: Path, expected: str) -> list[str]:
    if not path.is_file():
        return [f"{path.name}_missing"]
    content = "\n".join(line.strip() for line in _read_lines(path) if line.strip() and not line.strip().startswith("#"))
    failures: list[str] = []
    if content != expected:
        failures.append(f"{path.name}_does_not_reference_lock")
    if RANGE_RE.search(content) or "==" in content:
        failures.append(f"{path.name}_contains_direct_version_specifier")
    return failures


def _license_inventory_failures(path: Path, lock_packages: dict[str, str]) -> tuple[dict[str, Any], list[str]]:
    if not path.is_file():
        return {}, ["dependency_license_inventory_missing"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, [f"dependency_license_inventory_invalid_json:{type(exc).__name__}"]
    failures: list[str] = []
    if payload.get("schema_version") != "reachops.dependency_license_inventory.v1":
        failures.append("dependency_license_inventory_schema_mismatch")
    if payload.get("lock_file") != "requirements.lock":
        failures.append("dependency_license_inventory_lock_file_mismatch")
    dependencies = payload.get("dependencies") if isinstance(payload.get("dependencies"), list) else []
    inventory = {
        _normalized_name(str(row.get("name") or "")): row
        for row in dependencies
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    }
    for name, version in lock_packages.items():
        row = inventory.get(name)
        if not row:
            failures.append(f"dependency_license_inventory_missing_{name}")
            continue
        if str(row.get("version") or "") != version:
            failures.append(f"dependency_license_inventory_version_mismatch_{name}")
        if not str(row.get("license") or "").strip():
            failures.append(f"dependency_license_inventory_license_missing_{name}")
        if not str(row.get("purpose") or "").strip():
            failures.append(f"dependency_license_inventory_purpose_missing_{name}")
        if not row.get("runtime_scope"):
            failures.append(f"dependency_license_inventory_scope_missing_{name}")
    for name in inventory:
        if name not in lock_packages:
            failures.append(f"dependency_license_inventory_unlocked_{name}")
    return payload, failures


def build_report(root: Path = ROOT_DIR) -> dict[str, Any]:
    lock_packages, failures = _lock_packages(root / "requirements.lock")
    failures.extend(_requirements_reference(root / "requirements.txt", "-r requirements.lock"))
    failures.extend(
        _requirements_reference(
            root / "ReachOps" / "packaging" / "requirements-reachops.txt",
            "-r ../../requirements.lock",
        )
    )
    inventory, inventory_failures = _license_inventory_failures(
        root / "ReachOps" / "packaging" / "dependency-license-inventory.json",
        lock_packages,
    )
    failures.extend(inventory_failures)
    return {
        "schema_version": "reachops.dependency_baseline.v1",
        "status": "passed" if not failures else "failed",
        "passed": not failures,
        "root": str(root),
        "lock_file": str(root / "requirements.lock"),
        "root_requirements": str(root / "requirements.txt"),
        "windows_requirements": str(root / "ReachOps" / "packaging" / "requirements-reachops.txt"),
        "license_inventory": str(root / "ReachOps" / "packaging" / "dependency-license-inventory.json"),
        "locked_dependencies": [{"name": name, "version": version} for name, version in sorted(lock_packages.items())],
        "license_inventory_dependency_count": len(inventory.get("dependencies") or []) if isinstance(inventory, dict) else 0,
        "failures": failures,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify ReachOps deterministic dependency baseline.")
    parser.add_argument("--root", default=str(ROOT_DIR))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(Path(args.root).resolve())
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"ReachOps dependency baseline: {report['status']}")
        for failure in report["failures"]:
            print(f"- {failure}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
