import pytest

from .test_helpers import DummyContext
from transport.unity_instance_middleware import UnityInstanceMiddleware


@pytest.mark.asyncio
async def test_auto_select_is_disabled():
    middleware = UnityInstanceMiddleware()
    ctx = DummyContext()

    selected = await middleware._maybe_autoselect_instance(ctx)

    assert selected is None
    assert await middleware.get_active_instance(ctx) is None


@pytest.mark.asyncio
async def test_missing_inline_unity_instance_errors():
    middleware = UnityInstanceMiddleware()
    ctx = DummyContext()
    middleware_context = type(
        "DummyMiddlewareContext",
        (),
        {"fastmcp_context": ctx, "message": type("Message", (), {"arguments": {}})()},
    )()

    with pytest.raises(ValueError, match="unity_instance is required"):
        await middleware._inject_unity_instance(middleware_context)
