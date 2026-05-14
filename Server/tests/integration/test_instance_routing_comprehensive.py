"""
Comprehensive tests for strict Unity instance routing.
"""
import pytest
from unittest.mock import AsyncMock, Mock
from fastmcp import Context

from services.tools import get_unity_instance_from_context
from transport.unity_instance_middleware import UnityInstanceMiddleware


class TestInstanceRoutingBasics:
    @pytest.mark.asyncio
    async def test_middleware_binds_and_retrieves_session_hash(self):
        middleware = UnityInstanceMiddleware()
        ctx = Mock(spec=Context)
        ctx.session_id = "test-session-1"
        ctx.client_id = "test-client-1"

        await middleware.set_active_instance(ctx, "TestProject@abc123")

        assert await middleware.get_active_instance(ctx) == "TestProject@abc123"

    @pytest.mark.asyncio
    async def test_middleware_rejects_session_hash_change(self):
        middleware = UnityInstanceMiddleware()
        ctx = Mock(spec=Context)
        ctx.session_id = "test-session-1"
        ctx.client_id = "test-client-1"

        await middleware.set_active_instance(ctx, "Project1@aaa")

        with pytest.raises(ValueError, match="already bound"):
            await middleware.set_active_instance(ctx, "Project2@bbb")

    @pytest.mark.asyncio
    async def test_middleware_allows_same_hash_with_different_format(self):
        middleware = UnityInstanceMiddleware()
        ctx = Mock(spec=Context)
        ctx.session_id = "test-session-1"
        ctx.client_id = "test-client-1"

        await middleware.set_active_instance(ctx, "Project1@aaa")
        await middleware.set_active_instance(ctx, "aaa")

        assert await middleware.get_active_instance(ctx) == "aaa"

    @pytest.mark.asyncio
    async def test_middleware_isolates_sessions(self):
        middleware = UnityInstanceMiddleware()
        ctx1 = Mock(spec=Context)
        ctx1.session_id = "session-1"
        ctx1.client_id = "client-1"
        ctx2 = Mock(spec=Context)
        ctx2.session_id = "session-2"
        ctx2.client_id = "client-2"

        await middleware.set_active_instance(ctx1, "Project1@aaa")
        await middleware.set_active_instance(ctx2, "Project2@bbb")

        assert await middleware.get_active_instance(ctx1) == "Project1@aaa"
        assert await middleware.get_active_instance(ctx2) == "Project2@bbb"


class TestInstanceRoutingIntegration:
    @pytest.mark.asyncio
    async def test_middleware_injects_inline_state_into_context(self):
        middleware = UnityInstanceMiddleware()
        state_storage = {}
        ctx = Mock(spec=Context)
        ctx.session_id = "test-session"
        ctx.set_state = AsyncMock(side_effect=lambda k, v: state_storage.__setitem__(k, v))
        ctx.get_state = AsyncMock(side_effect=lambda k, default=None: state_storage.get(k, default))

        middleware_ctx = Mock()
        middleware_ctx.fastmcp_context = ctx
        middleware_ctx.message = Mock()
        middleware_ctx.message.arguments = {"unity_instance": "TestProject@abc123"}
        middleware_ctx.message.name = "manage_scene"

        async def call_next(_context):
            return {"success": True}

        await middleware.on_call_tool(middleware_ctx, call_next)

        assert state_storage["unity_instance"] == "TestProject@abc123"

    @pytest.mark.asyncio
    async def test_middleware_rejects_call_without_inline_hash(self):
        middleware = UnityInstanceMiddleware()
        ctx = Mock(spec=Context)
        ctx.session_id = "test-session"
        ctx.set_state = AsyncMock()
        ctx.get_state = AsyncMock(return_value=None)

        middleware_ctx = Mock()
        middleware_ctx.fastmcp_context = ctx
        middleware_ctx.message = Mock()
        middleware_ctx.message.arguments = {}
        middleware_ctx.message.name = "manage_scene"

        async def call_next(_context):
            return {"success": True}

        with pytest.raises(ValueError, match="unity_instance is required"):
            await middleware.on_call_tool(middleware_ctx, call_next)

    @pytest.mark.asyncio
    async def test_get_unity_instance_from_context_checks_state(self):
        ctx = Mock(spec=Context)
        ctx.get_state = AsyncMock(side_effect=lambda k: {"unity_instance": "Project@state123"}.get(k))

        result = await get_unity_instance_from_context(ctx)

        assert result == "Project@state123"

    @pytest.mark.asyncio
    async def test_get_unity_instance_returns_none_when_not_set(self):
        ctx = Mock(spec=Context)
        ctx.get_state = AsyncMock(return_value=None)

        result = await get_unity_instance_from_context(ctx)

        assert result is None
