"""
Tests for strict per-call unity_instance routing.
"""
from types import SimpleNamespace

import pytest

from .test_helpers import DummyContext
from core.config import config
from transport.unity_instance_middleware import UnityInstanceMiddleware


class DummyMiddlewareContext:
    def __init__(
        self,
        ctx,
        arguments: dict | None = None,
        uri: str | None = None,
        name: str | None = "manage_scene",
    ):
        self.fastmcp_context = ctx
        self.message = SimpleNamespace(
            arguments=arguments if arguments is not None else {},
            name=name,
        )
        if uri is not None:
            self.message.uri = uri


@pytest.mark.asyncio
async def test_unity_instance_is_popped_from_arguments(monkeypatch):
    monkeypatch.setattr(config, "transport_mode", "stdio")
    mw = UnityInstanceMiddleware()
    ctx = DummyContext()
    args = {"action": "get_active", "unity_instance": "abc123"}

    await mw._inject_unity_instance(DummyMiddlewareContext(ctx, arguments=args))

    assert args == {"action": "get_active"}
    assert await ctx.get_state("unity_instance") == "abc123"
    assert await mw.get_active_instance(ctx) == "abc123"


@pytest.mark.asyncio
async def test_missing_unity_instance_errors_and_does_not_autoselect():
    mw = UnityInstanceMiddleware()
    ctx = DummyContext()
    args = {"action": "get_active"}

    with pytest.raises(ValueError, match="unity_instance is required"):
        await mw._inject_unity_instance(DummyMiddlewareContext(ctx, arguments=args))

    assert args == {"action": "get_active"}
    assert await mw.get_active_instance(ctx) is None


@pytest.mark.asyncio
async def test_same_session_may_repeat_same_project_hash():
    mw = UnityInstanceMiddleware()
    ctx = DummyContext()

    await mw._inject_unity_instance(
        DummyMiddlewareContext(ctx, arguments={"unity_instance": "Project@abc123"})
    )
    await mw._inject_unity_instance(
        DummyMiddlewareContext(ctx, arguments={"unity_instance": "abc123"})
    )

    assert await ctx.get_state("unity_instance") == "abc123"
    assert await mw.get_active_instance(ctx) == "abc123"


@pytest.mark.asyncio
async def test_same_session_cannot_change_project_hash():
    mw = UnityInstanceMiddleware()
    ctx = DummyContext()

    await mw._inject_unity_instance(
        DummyMiddlewareContext(ctx, arguments={"unity_instance": "ProjectA@aaa111"})
    )

    with pytest.raises(ValueError, match="already bound"):
        await mw._inject_unity_instance(
            DummyMiddlewareContext(ctx, arguments={"unity_instance": "ProjectB@bbb222"})
        )


@pytest.mark.asyncio
async def test_empty_unity_instance_errors():
    mw = UnityInstanceMiddleware()
    ctx = DummyContext()

    with pytest.raises(ValueError, match="must not be empty"):
        await mw._inject_unity_instance(
            DummyMiddlewareContext(ctx, arguments={"unity_instance": "  "})
        )


@pytest.mark.asyncio
async def test_port_number_targeting_errors():
    mw = UnityInstanceMiddleware()
    ctx = DummyContext()

    with pytest.raises(ValueError, match="Port-based Unity targeting is not supported"):
        await mw._inject_unity_instance(
            DummyMiddlewareContext(ctx, arguments={"unity_instance": "6401"})
        )


@pytest.mark.asyncio
async def test_resource_uri_query_routes_and_strips_query():
    mw = UnityInstanceMiddleware()
    ctx = DummyContext()
    resource_ctx = DummyMiddlewareContext(
        ctx,
        uri="mcpforunity://editor/state?unity_instance=bbb222",
        name=None,
    )

    await mw._inject_unity_instance(resource_ctx)

    assert await ctx.get_state("unity_instance") == "bbb222"
    assert resource_ctx.message.uri == "mcpforunity://editor/state"


@pytest.mark.asyncio
async def test_resource_without_query_errors():
    mw = UnityInstanceMiddleware()
    ctx = DummyContext()

    with pytest.raises(ValueError, match="unity_instance is required"):
        await mw._inject_unity_instance(
            DummyMiddlewareContext(ctx, uri="mcpforunity://editor/state", name=None)
        )


@pytest.mark.asyncio
async def test_tool_groups_resource_does_not_require_unity_instance():
    mw = UnityInstanceMiddleware()
    ctx = DummyContext()
    resource_ctx = DummyMiddlewareContext(
        ctx,
        uri="mcpforunity://tool-groups",
        name=None,
    )

    async def call_next(_context):
        return {}

    await mw.on_read_resource(resource_ctx, call_next)


@pytest.mark.asyncio
async def test_list_tools_marks_unity_instance_required(monkeypatch):
    mw = UnityInstanceMiddleware()

    def fake_registry():
        return [
            {"name": "manage_scene", "unity_target": "manage_scene"},
            {"name": "set_active_instance", "unity_target": None},
        ]

    monkeypatch.setattr("transport.unity_instance_middleware.get_registered_tools", fake_registry)

    ctx = DummyContext()
    tools = [
        SimpleNamespace(name="manage_scene", parameters={"type": "object", "properties": {}}),
        SimpleNamespace(name="set_active_instance", parameters={"type": "object", "properties": {}}),
    ]

    async def call_next(_context):
        return tools

    result = await mw.on_list_tools(DummyMiddlewareContext(ctx), call_next)

    manage_schema = result[0].parameters
    server_schema = result[1].parameters
    assert "unity_instance" in manage_schema["properties"]
    assert "unity_instance" in manage_schema["required"]
    assert "unity_instance" not in server_schema["properties"]


@pytest.mark.asyncio
async def test_set_active_instance_rejects_port(monkeypatch):
    monkeypatch.setattr(config, "transport_mode", "stdio")

    from services.tools.set_active_instance import set_active_instance

    result = await set_active_instance(DummyContext(), instance="6401")

    assert result["success"] is False
    assert "Port-based targeting is not supported" in result["error"]


@pytest.mark.asyncio
async def test_batch_execute_rejects_inner_unity_instance():
    from services.tools.batch_execute import batch_execute

    ctx = DummyContext()
    ctx._state["unity_instance"] = "Proj@abc123"
    commands = [
        {"tool": "manage_scene", "params": {"action": "get_active", "unity_instance": "6402"}},
    ]

    with pytest.raises(ValueError, match="Per-command instance routing is not supported inside batch_execute"):
        await batch_execute(ctx, commands=commands)
