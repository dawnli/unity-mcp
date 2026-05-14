import inspect
from types import SimpleNamespace

import pytest

from core.config import config
from .test_helpers import DummyContext


class CapturingMCP:
    def __init__(self):
        self.tools = {}
        self.resources = {}

    def tool(self, name=None, description=None, **kwargs):
        def decorator(fn):
            self.tools[name or fn.__name__] = fn
            return fn
        return decorator

    def resource(self, uri, name=None, description=None, **kwargs):
        def decorator(fn):
            self.resources[uri] = fn
            return fn
        return decorator

    def disable(self, *args, **kwargs):
        return None


async def _no_inject(_context, **_kwargs):
    return None


@pytest.mark.asyncio
async def test_tool_list_schema_exposes_required_unity_instance(monkeypatch):
    monkeypatch.setattr(config, "transport_mode", "stdio")

    import transport.unity_instance_middleware as middleware_mod

    middleware = middleware_mod.UnityInstanceMiddleware()
    monkeypatch.setattr(middleware, "_inject_unity_instance", _no_inject)
    monkeypatch.setattr(
        middleware_mod,
        "get_registered_tools",
        lambda: [
            {"name": "manage_scene", "unity_target": "manage_scene"},
            {"name": "execute_custom_tool", "unity_target": None},
            {"name": "set_active_instance", "unity_target": None},
        ],
    )

    listed_tools = [
        SimpleNamespace(name="manage_scene", parameters={"type": "object", "properties": {}}),
        SimpleNamespace(name="execute_custom_tool", parameters={"type": "object", "properties": {}}),
        SimpleNamespace(name="set_active_instance", parameters={"type": "object", "properties": {}}),
    ]

    async def call_next(_context):
        return listed_tools

    context = SimpleNamespace(
        fastmcp_context=DummyContext(),
        message=SimpleNamespace(arguments={}),
    )
    result = await middleware.on_list_tools(context, call_next)
    by_name = {tool.name: tool for tool in result}

    assert "unity_instance" in by_name["manage_scene"].parameters["properties"]
    assert "unity_instance" in by_name["manage_scene"].parameters["required"]
    assert "unity_instance" in by_name["execute_custom_tool"].parameters["properties"]
    assert "unity_instance" in by_name["execute_custom_tool"].parameters["required"]
    assert "unity_instance" not in by_name["set_active_instance"].parameters["properties"]


def test_resources_register_unity_instance_query_templates():
    from services.resources import register_all_resources

    mcp = CapturingMCP()
    register_all_resources(mcp)

    assert "mcpforunity://editor/state" in mcp.resources
    assert "mcpforunity://editor/state{?unity_instance}" in mcp.resources

    query_fn = mcp.resources["mcpforunity://editor/state{?unity_instance}"]
    query_params = inspect.signature(query_fn).parameters
    assert query_params["unity_instance"].default is None
    assert "unity_instance" in query_fn.__annotations__
