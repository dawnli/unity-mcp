#!/usr/bin/env python3
"""Compute the Unity MCP project hash from an absolute Unity project path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os


def normalize_project_root(raw_path: str) -> str:
    if not raw_path or not raw_path.strip():
        raise SystemExit("Project path is required.")

    expanded = os.path.expanduser(raw_path.strip())
    if not os.path.isabs(expanded):
        raise SystemExit(f"Project path must be absolute: {raw_path}")

    normalized = os.path.abspath(expanded)
    normalized = os.path.normpath(normalized)
    normalized = normalized.replace("\\", "/").rstrip("/")

    if normalized.lower().endswith("/assets"):
        normalized = normalized[:-len("/assets")].rstrip("/")

    return normalized.lower()


def project_path_hash(project_path: str) -> str:
    normalized = normalize_project_root(project_path)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute the MCP for Unity project hash from an absolute project path."
    )
    parser.add_argument(
        "project_path",
        help="Absolute Unity project root path. An absolute Assets path is also accepted.",
    )
    parser.add_argument("--json", action="store_true", help="Print normalized_path and hash as JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    normalized = normalize_project_root(args.project_path)
    value = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]

    if args.json:
        print(json.dumps({"normalized_path": normalized, "hash": value}, indent=2))
    else:
        print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
