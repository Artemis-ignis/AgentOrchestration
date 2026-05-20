#!/usr/bin/env python3
"""Fail CI when GitHub workflow actions use mutable refs."""

from __future__ import annotations

import re
import sys
from pathlib import Path


PINNED_SHA = re.compile(r"^[0-9a-f]{40}$")
USES_LINE = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)")


def workflow_files(paths: list[str]) -> list[Path]:
    if paths:
        return [Path(path) for path in paths]

    root = Path(".github/workflows")
    return sorted([*root.glob("*.yml"), *root.glob("*.yaml")])


def clean_uses_value(value: str) -> str:
    return value.strip().strip("'\"")


def is_local_action(value: str) -> bool:
    return value.startswith("./") or value.startswith(".\\")


def find_mutable_refs(path: Path) -> list[str]:
    violations: list[str] = []

    workflow_lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(workflow_lines, 1):
        match = USES_LINE.match(line)
        if not match:
            continue

        uses_value = clean_uses_value(match.group(1))
        if is_local_action(uses_value):
            continue

        if "@" not in uses_value:
            violations.append(
                f"{path}:{line_number}: missing immutable @<sha> ref: "
                f"{uses_value}"
            )
            continue

        _, ref = uses_value.rsplit("@", 1)
        if not PINNED_SHA.fullmatch(ref):
            violations.append(
                f"{path}:{line_number}: mutable action ref: {uses_value}"
            )

    return violations


def main(argv: list[str]) -> int:
    violations: list[str] = []
    for path in workflow_files(argv):
        violations.extend(find_mutable_refs(path))

    if violations:
        print("Mutable GitHub Actions refs detected:")
        for violation in violations:
            print(f"  - {violation}")
        return 1

    print("All external GitHub Actions refs are pinned to full commit SHAs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
