"""Startup logging behavior for the MCP HTTP server."""

import sys


def test_http_transport_disables_uvicorn_colors(monkeypatch):
    """Uvicorn color codes render as raw ESC bytes in some Windows terminals."""
    import main as server_main

    captured: dict[str, object] = {}

    class FakeMCP:
        def run(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main",
            "--transport",
            "http",
            "--http-url",
            "http://127.0.0.1:18080",
        ],
    )
    monkeypatch.setattr(
        server_main,
        "_should_start_http_server",
        lambda _host, _port, _version: True,
    )
    monkeypatch.setattr(
        server_main,
        "create_mcp_server",
        lambda _project_scoped_tools: FakeMCP(),
    )

    server_main.main()

    assert captured["transport"] == "http"
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 18080
    assert captured["uvicorn_config"] == {"use_colors": False}
