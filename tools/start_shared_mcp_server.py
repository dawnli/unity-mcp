#!/usr/bin/env python3
"""Start the shared Unity MCP HTTP server on a fixed host and port."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
BASE_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
HEALTH_URL = f"{BASE_URL}/health"
START_TIMEOUT_SECONDS = 15.0
POLL_INTERVAL_SECONDS = 0.25


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the shared Unity MCP HTTP server.")
    parser.add_argument("--server-dir", type=Path, default=Path(__file__).resolve().parents[1] / "Server")
    parser.add_argument("--uv", default="uv")
    return parser.parse_args()


def probe_existing_server() -> tuple[str, str]:
    request = urllib.request.Request(HEALTH_URL, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=1.0) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return "occupied", f"{HEALTH_URL} returned HTTP {exc.code}"
    except urllib.error.URLError:
        return "missing", ""
    except TimeoutError:
        return "occupied", f"{HEALTH_URL} timed out"
    except OSError as exc:
        return "occupied", f"{HEALTH_URL} is not reachable: {exc}"

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return "occupied", f"{HEALTH_URL} did not return JSON health data"

    if payload.get("status") == "healthy" and "MCP for Unity" in str(payload.get("message", "")):
        return "running", ""
    return "occupied", f"{HEALTH_URL} is not a Unity MCP server"


def build_command(args: argparse.Namespace) -> list[str]:
    return [
        args.uv,
        "run",
        "--extra",
        "dev",
        "python",
        "src/main.py",
        "--transport",
        "http",
        "--http-url",
        BASE_URL,
    ]


def start_background_server(command: list[str], server_dir: Path) -> tuple[subprocess.Popen, Path]:
    log_dir = Path.home() / ".unity-mcp"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "shared-server.log"
    log_handle = open(log_path, "ab", buffering=0)
    kwargs: dict = {
        "cwd": str(server_dir),
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    log_handle.close()
    return process, log_path


def wait_until_healthy(process: subprocess.Popen, log_path: Path) -> int:
    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        status, detail = probe_existing_server()
        if status == "running":
            print(f"Shared Unity MCP server started at {BASE_URL}")
            print(f"Logs: {log_path}")
            return 0
        if status == "occupied":
            print(f"Cannot start shared Unity MCP server: {detail}", file=sys.stderr)
            return 2
        exit_code = process.poll()
        if exit_code is not None:
            print(
                f"Shared Unity MCP server exited before becoming healthy (exit code {exit_code}). Logs: {log_path}",
                file=sys.stderr,
            )
            return exit_code or 1
        time.sleep(POLL_INTERVAL_SECONDS)

    print(
        f"Shared Unity MCP server did not become healthy within {START_TIMEOUT_SECONDS:.0f}s. Logs: {log_path}",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    args = parse_args()
    server_dir = args.server_dir.expanduser().resolve()
    status, detail = probe_existing_server()
    if status == "running":
        print(f"Shared Unity MCP server already running at {BASE_URL}")
        return 0
    if status == "occupied":
        print(f"Cannot start shared Unity MCP server: {detail}", file=sys.stderr)
        return 2

    process, log_path = start_background_server(build_command(args), server_dir)
    return wait_until_healthy(process, log_path)


if __name__ == "__main__":
    raise SystemExit(main())
