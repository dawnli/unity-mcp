#!/usr/bin/env python3
"""Print the stable Unity MCP session hash for an absolute project path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os


def normalize_project_path(raw: str) -> str:
    path = os.path.expanduser(raw)
    if not os.path.isabs(path):
        raise SystemExit(f"Project path must be absolute: {raw}")
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def project_path_hash(project_path: str) -> str:
    normalized = normalize_project_path(project_path)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute the Unity MCP session hash for an absolute project path."
    )
    parser.add_argument("project_path", help="Absolute Unity project root path.")
    parser.add_argument("--json", action="store_true", help="Print normalized_path and hash as JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    normalized = normalize_project_path(args.project_path)
    value = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    if args.json:
        print(json.dumps({"normalized_path": normalized, "hash": value}, indent=2))
    else:
        print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
