"""Windows console color handling for server startup."""

import sys
from types import SimpleNamespace


def test_enable_windows_ansi_console_calls_colorama(monkeypatch):
    import main as server_main

    calls: list[bool] = []
    fake_colorama = SimpleNamespace(
        just_fix_windows_console=lambda: calls.append(True)
    )

    monkeypatch.setattr(server_main.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "colorama", fake_colorama)

    server_main._enable_windows_ansi_console()

    assert calls == [True]


def test_enable_windows_ansi_console_skips_non_windows(monkeypatch):
    import main as server_main

    calls: list[bool] = []
    fake_colorama = SimpleNamespace(
        just_fix_windows_console=lambda: calls.append(True)
    )

    monkeypatch.setattr(server_main.sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "colorama", fake_colorama)

    server_main._enable_windows_ansi_console()

    assert calls == []


def test_http_transport_leaves_uvicorn_color_detection_enabled(monkeypatch):
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
    assert "uvicorn_config" not in captured
