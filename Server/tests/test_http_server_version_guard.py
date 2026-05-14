import pytest

import main


MCP_HEALTH_MESSAGE = "MCP for Unity server is running"


def test_should_start_http_server_returns_false_for_same_version(monkeypatch):
    monkeypatch.setattr(
        main,
        "_read_existing_http_server_health",
        lambda host, port: {"version": "v1.2.3", "pid": 1234, "message": MCP_HEALTH_MESSAGE},
    )

    assert main._should_start_http_server("127.0.0.1", 8080, "1.2.3") is False


def test_should_start_http_server_stops_different_version(monkeypatch):
    stopped = []
    monkeypatch.setattr(
        main,
        "_read_existing_http_server_health",
        lambda host, port: {"version": "1.2.2", "pid": 1234, "message": MCP_HEALTH_MESSAGE},
    )
    monkeypatch.setattr(
        main,
        "_terminate_existing_http_server",
        lambda host, port, health: stopped.append((port, health["pid"])) or True,
    )

    assert main._should_start_http_server("127.0.0.1", 8080, "1.2.3") is True
    assert stopped == [(8080, 1234)]


def test_should_start_http_server_treats_three_part_running_version_as_older(monkeypatch):
    stopped = []
    monkeypatch.setattr(
        main,
        "_read_existing_http_server_health",
        lambda host, port: {"version": "9.6.9", "pid": 1234, "message": MCP_HEALTH_MESSAGE},
    )
    monkeypatch.setattr(
        main,
        "_terminate_existing_http_server",
        lambda host, port, health: stopped.append((port, health["version"])) or True,
    )

    assert main._should_start_http_server("127.0.0.1", 8080, "9.6.8.1") is True
    assert stopped == [(8080, "9.6.9")]


def test_should_start_http_server_keeps_four_part_running_version_for_three_part_expected(monkeypatch):
    stopped = []
    monkeypatch.setattr(
        main,
        "_read_existing_http_server_health",
        lambda host, port: {"version": "9.6.8.1", "pid": 1234, "message": MCP_HEALTH_MESSAGE},
    )
    monkeypatch.setattr(
        main,
        "_terminate_existing_http_server",
        lambda host, port, health: stopped.append((port, health["version"])) or True,
    )

    assert main._should_start_http_server("127.0.0.1", 8080, "9.6.9") is False
    assert stopped == []


def test_should_start_http_server_compares_four_part_revisions(monkeypatch):
    stopped = []
    monkeypatch.setattr(
        main,
        "_read_existing_http_server_health",
        lambda host, port: {"version": "9.6.8.1", "pid": 1234, "message": MCP_HEALTH_MESSAGE},
    )
    monkeypatch.setattr(
        main,
        "_terminate_existing_http_server",
        lambda host, port, health: stopped.append((port, health["version"])) or True,
    )

    assert main._should_start_http_server("127.0.0.1", 8080, "9.6.8.2") is True
    assert stopped == [(8080, "9.6.8.1")]


def test_should_start_http_server_exits_when_different_version_cannot_stop(monkeypatch):
    monkeypatch.setattr(
        main,
        "_read_existing_http_server_health",
        lambda host, port: {"version": "1.2.2", "pid": 1234, "message": MCP_HEALTH_MESSAGE},
    )
    monkeypatch.setattr(main, "_terminate_existing_http_server", lambda host, port, health: False)

    with pytest.raises(SystemExit) as exc:
        main._should_start_http_server("127.0.0.1", 8080, "1.2.3")

    assert exc.value.code == 1


def test_should_start_http_server_ignores_unrelated_health_payload(monkeypatch):
    monkeypatch.setattr(
        main,
        "_read_existing_http_server_health",
        lambda host, port: {"version": "1.2.3", "message": "other service"},
    )

    assert main._should_start_http_server("127.0.0.1", 8080, "1.2.3") is True


def test_build_health_url_uses_loopback_for_bind_all():
    assert main._build_health_url("0.0.0.0", 8080) == "http://127.0.0.1:8080/health"
