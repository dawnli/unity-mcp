"""
Middleware for managing Unity instance selection per session.

This middleware intercepts all tool calls and injects the active Unity instance
into the request-scoped state, allowing tools to access it via ctx.get_state("unity_instance").
"""
from threading import RLock
import logging
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastmcp.server.middleware import Middleware, MiddlewareContext

from core.config import config
from services.registry import get_registered_tools
from transport.plugin_hub import PluginHub

logger = logging.getLogger("mcp-for-unity-server")
# Separate logger that propagates to root -> stderr so diagnostics show in console
_diag = logging.getLogger("transport.unity_instance_middleware")

UNITY_INSTANCE_PARAMETER_SCHEMA = {
    "type": "string",
    "description": (
        "Required Unity project hash, or Name@hash, used to route this call "
        "to a specific Unity Editor instance on the shared MCP server."
    ),
}
INSTANCE_ROUTED_SERVER_TOOLS = {"execute_custom_tool"}
SERVER_ONLY_TOOLS_WITHOUT_UNITY_INSTANCE = {"manage_tools", "set_active_instance"}
SERVER_ONLY_RESOURCES_WITHOUT_UNITY_INSTANCE = {"mcpforunity://tool-groups"}
UNITY_INSTANCE_REQUIRED_ERROR = (
    "unity_instance is required. Compute the project hash from the absolute "
    "Unity project path and pass unity_instance=\"<hash>\" on every Unity "
    "tool call, or append ?unity_instance=<hash> to every Unity resource URI."
)

# Store a global reference to the middleware instance so tools can interact
# with it to set or clear the active unity instance.
_unity_instance_middleware = None
_middleware_lock = RLock()


def get_unity_instance_middleware() -> 'UnityInstanceMiddleware':
    """Get the global Unity instance middleware."""
    global _unity_instance_middleware
    if _unity_instance_middleware is None:
        with _middleware_lock:
            if _unity_instance_middleware is None:
                # Auto-initialize if not set (lazy singleton) to handle import order or test cases
                _unity_instance_middleware = UnityInstanceMiddleware()

    return _unity_instance_middleware


def set_unity_instance_middleware(middleware: 'UnityInstanceMiddleware') -> None:
    """Replace the global middleware instance.

    This is a test seam: production code uses ``get_unity_instance_middleware()``
    which lazy-initialises the singleton.  Tests call this function to inject a
    mock or pre-configured middleware before exercising tool/resource code.
    """
    global _unity_instance_middleware
    _unity_instance_middleware = middleware


class UnityInstanceMiddleware(Middleware):
    """
    Middleware that manages per-session Unity instance selection.

    Stores active instance per session_id and injects it into request state
    for all tool and resource calls.
    """

    def __init__(self):
        super().__init__()
        self._active_by_key: dict[str, str] = {}
        self._lock = RLock()
        self._metadata_lock = RLock()
        self._unity_managed_tool_names: set[str] = set()
        self._tool_alias_to_unity_target: dict[str, str] = {}
        self._server_only_tool_names: set[str] = set()
        self._tool_visibility_signature: tuple[tuple[str, str], ...] = ()
        self._last_tool_visibility_refresh = 0.0
        self._tool_visibility_refresh_interval_seconds = 0.5
        self._has_logged_empty_registry_warning = False

    async def get_session_key(self, ctx) -> str:
        """
        Derive a stable key for the calling session.

        HTTP clients expose the MCP session through ctx.session_id. Use it
        first so multiple AI IDE clients sharing one MCP server keep separate
        compatibility selections. Fall back to older identifiers when a
        transport does not expose session_id.
        """
        try:
            session_id = getattr(ctx, "session_id", None)
        except RuntimeError:
            session_id = None
        if isinstance(session_id, str) and session_id:
            return session_id

        client_id = getattr(ctx, "client_id", None)
        if isinstance(client_id, str) and client_id:
            return client_id

        get_state_fn = getattr(ctx, "get_state", None)
        if callable(get_state_fn):
            user_id = await get_state_fn("user_id")
            if isinstance(user_id, str) and user_id:
                return f"user:{user_id}"

        # Fallback to global for local dev stability
        return "global"

    async def set_active_instance(self, ctx, instance_id: str) -> None:
        """Bind this MCP client session to a Unity project hash."""
        key = await self.get_session_key(ctx)
        project_hash = self._project_hash_from_instance_id(instance_id)
        if not project_hash:
            raise ValueError("Unity project hash must not be empty.")
        with self._lock:
            existing = self._active_by_key.get(key)
            existing_hash = self._project_hash_from_instance_id(existing)
            if existing and existing_hash != project_hash:
                raise ValueError(
                    "This MCP client session is already bound to Unity "
                    f"project hash '{existing_hash}'. Start a new MCP client "
                    f"session to target '{project_hash}'."
                )
            self._active_by_key[key] = instance_id

    async def get_active_instance(self, ctx) -> str | None:
        """Retrieve the active instance for this session."""
        key = await self.get_session_key(ctx)
        with self._lock:
            return self._active_by_key.get(key)

    async def clear_active_instance(self, ctx) -> None:
        """Clear the stored instance for this session."""
        key = await self.get_session_key(ctx)
        with self._lock:
            self._active_by_key.pop(key, None)

    @staticmethod
    def _project_hash_from_instance_id(instance_id: str | None) -> str | None:
        if not isinstance(instance_id, str):
            return None
        value = instance_id.strip()
        if not value:
            return None
        if "@" in value:
            _, _, suffix = value.rpartition("@")
            value = suffix.strip()
        return value.lower() or None

    async def _discover_instances(self, ctx) -> list:
        """
        Return running Unity instances across both HTTP (PluginHub) and stdio transports.

        Returns a list of objects with .id (Name@hash) and .hash attributes.
        """
        from types import SimpleNamespace
        transport = (config.transport_mode or "stdio").lower()
        results: list = []

        if PluginHub.is_configured():
            try:
                user_id = None
                get_state_fn = getattr(ctx, "get_state", None)
                if callable(get_state_fn) and config.http_remote_hosted:
                    user_id = await get_state_fn("user_id")
                sessions_data = await PluginHub.get_sessions(user_id=user_id)
                sessions = sessions_data.sessions or {}
                for session_info in sessions.values():
                    project = getattr(session_info, "project", None) or "Unknown"
                    hash_value = getattr(session_info, "hash", None)
                    if hash_value:
                        results.append(SimpleNamespace(
                            id=f"{project}@{hash_value}",
                            hash=hash_value,
                            name=project,
                        ))
            except Exception as exc:
                if isinstance(exc, (SystemExit, KeyboardInterrupt)):
                    raise
                logger.debug("PluginHub instance discovery failed (%s)", type(exc).__name__, exc_info=True)

        if not results and transport != "http":
            try:
                from transport.legacy.unity_connection import get_unity_connection_pool
                pool = get_unity_connection_pool()
                results = pool.discover_all_instances(force_refresh=True)
            except Exception as exc:
                if isinstance(exc, (SystemExit, KeyboardInterrupt)):
                    raise
                logger.debug("Stdio instance discovery failed (%s)", type(exc).__name__, exc_info=True)

        return results

    async def _resolve_instance_value(self, value: str, ctx) -> str:
        """
        Resolve a unity_instance string to a validated instance identifier.

        Accepts:
          - Full project hash
          - "Name@hash" exact target

        Raises ValueError with a user-friendly message on failure.
        """
        value = value.strip()
        if not value:
            raise ValueError("unity_instance value must not be empty.")

        if value.isdigit():
            raise ValueError(
                "Port-based Unity targeting is not supported. Compute the "
                "project hash from the absolute Unity project path and pass "
                "unity_instance=\"<hash>\"."
            )

        if "@" in value:
            _, _, hash_value = value.rpartition("@")
            if not hash_value.strip():
                raise ValueError("unity_instance must include a project hash after '@'.")
            return value

        return value

    async def _maybe_autoselect_instance(self, ctx) -> str | None:
        """
        Auto-selection is intentionally disabled.

        Unity requests must name their target project hash explicitly so an
        unavailable editor cannot cause the client to drift to another instance.
        """
        return None

    async def _resolve_user_id(self) -> str | None:
        """Extract user_id from the current HTTP request's API key."""
        if not config.http_remote_hosted:
            return None
        # Lazy import to avoid circular dependencies (same pattern as _maybe_autoselect_instance).
        from transport.unity_transport import _resolve_user_id_from_request
        return await _resolve_user_id_from_request()

    def _extract_inline_unity_instance(self, context: MiddlewareContext) -> str | None:
        """
        Extract per-call routing from tool arguments or resource URI query.

        Tool calls carry unity_instance in arguments. Resource reads carry it
        in the URI query string, which is removed before FastMCP resolves the
        registered resource.
        """
        message = getattr(context, "message", None)
        msg_args = getattr(message, "arguments", None)
        if isinstance(msg_args, dict) and "unity_instance" in msg_args:
            raw = msg_args.pop("unity_instance")
            return "" if raw is None else str(raw).strip()

        raw_uri = getattr(message, "uri", None)
        if raw_uri is None:
            return None

        uri = str(raw_uri)
        parts = urlsplit(uri)
        if not parts.query:
            return None

        pairs = parse_qsl(parts.query, keep_blank_values=True)
        values = [value.strip() for key, value in pairs if key == "unity_instance"]
        if not values:
            return None

        remaining = [(key, value) for key, value in pairs if key != "unity_instance"]
        new_query = urlencode(remaining, doseq=True)
        cleaned_uri = urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
        try:
            setattr(message, "uri", cleaned_uri)
        except Exception:
            logger.debug("Could not strip unity_instance from resource URI", exc_info=True)

        return next((value for value in values if value), "")

    async def _inject_unity_instance(
        self,
        context: MiddlewareContext,
        *,
        require_unity_instance: bool = True,
    ) -> None:
        """Inject active Unity instance and user_id into context if available."""
        ctx = context.fastmcp_context

        # Resolve user_id from the HTTP request's API key header
        user_id = await self._resolve_user_id()
        if config.http_remote_hosted and user_id is None:
            raise RuntimeError(
                "API key authentication required. Provide a valid X-API-Key header."
            )
        if user_id:
            await ctx.set_state("user_id", user_id)

        # Per-call routing: check if this request explicitly specifies unity_instance.
        # Tool calls use arguments; resource reads use the URI query string.
        active_instance: str | None = None
        raw_inline_instance = self._extract_inline_unity_instance(context)
        if raw_inline_instance is not None:
            # Raises ValueError with a user-friendly message on invalid input.
            active_instance = await self._resolve_instance_value(raw_inline_instance, ctx)
            await self.set_active_instance(ctx, active_instance)
            logger.debug("Per-call unity_instance resolved to: %s", active_instance)
        elif not require_unity_instance:
            active_instance = await self.get_active_instance(ctx)

        if require_unity_instance and not active_instance:
            raise ValueError(UNITY_INSTANCE_REQUIRED_ERROR)

        if active_instance:
            # If using HTTP transport (PluginHub configured), validate session
            # But for stdio transport (no PluginHub needed or maybe partially configured),
            # we should be careful not to clear instance just because PluginHub can't resolve it.
            # The 'active_instance' (Name@hash) might be valid for stdio even if PluginHub fails.

            session_id: str | None = None
            # Only validate via PluginHub if we are actually using HTTP transport.
            # For stdio transport, skip PluginHub entirely - we only need the instance ID.
            from transport.unity_transport import _is_http_transport
            if _is_http_transport() and PluginHub.is_configured():
                try:
                    # resolving session_id might fail if the plugin disconnected
                    # We only need session_id for HTTP transport routing.
                    # For stdio, we just need the instance ID.
                    # Pass user_id for remote-hosted mode session isolation
                    session_id = await PluginHub._resolve_session_id(active_instance, user_id=user_id)
                except (ConnectionError, ValueError, KeyError, TimeoutError) as exc:
                    # If resolution fails, it means the Unity instance is not reachable via HTTP/WS.
                    # If we are in stdio mode, this might still be fine if the user is just setting state?
                    # But usually if PluginHub is configured, we expect it to work.
                    # Let's LOG the error but NOT clear the instance immediately to avoid flickering,
                    # or at least debug why it's failing.
                    logger.debug(
                        "PluginHub session resolution failed for %s: %s; leaving active_instance unchanged",
                        active_instance,
                        exc,
                        exc_info=True,
                    )
                except Exception as exc:
                    # Re-raise unexpected system exceptions to avoid swallowing critical failures
                    if isinstance(exc, (SystemExit, KeyboardInterrupt)):
                        raise
                    logger.error(
                        "Unexpected error during PluginHub session resolution for %s: %s",
                        active_instance,
                        exc,
                        exc_info=True
                    )

            await ctx.set_state("unity_instance", active_instance)
            if session_id is not None:
                await ctx.set_state("unity_session_id", session_id)

    def _context_requires_unity_instance(self, context: MiddlewareContext) -> bool:
        message = getattr(context, "message", None)
        tool_name = getattr(message, "name", None)
        if isinstance(tool_name, str) and tool_name in SERVER_ONLY_TOOLS_WITHOUT_UNITY_INSTANCE:
            return False

        raw_uri = getattr(message, "uri", None)
        if raw_uri is not None:
            uri = str(raw_uri).split("?", 1)[0]
            if uri in SERVER_ONLY_RESOURCES_WITHOUT_UNITY_INSTANCE:
                return False

        return True

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        """Inject active Unity instance into tool context if available."""
        await self._inject_unity_instance(
            context,
            require_unity_instance=self._context_requires_unity_instance(context),
        )
        return await call_next(context)

    async def on_read_resource(self, context: MiddlewareContext, call_next):
        """Inject active Unity instance into resource context if available."""
        await self._inject_unity_instance(
            context,
            require_unity_instance=self._context_requires_unity_instance(context),
        )
        return await call_next(context)

    async def on_list_tools(self, context: MiddlewareContext, call_next):
        """Filter MCP tool listing to the Unity-enabled set when session data is available."""
        try:
            await self._inject_unity_instance(context, require_unity_instance=False)
        except Exception as exc:
            # Re-raise authentication errors so callers get a proper auth failure
            if isinstance(exc, RuntimeError) and "authentication" in str(exc).lower():
                raise
            _diag.warning(
                "on_list_tools: _inject_unity_instance failed (%s: %s), continuing without instance",
                type(exc).__name__, exc,
            )

        tools = await call_next(context)

        tool_names_from_fastmcp = sorted(getattr(t, "name", "?") for t in tools)
        _diag.debug(
            "on_list_tools: FastMCP returned %d tools: %s",
            len(tools), tool_names_from_fastmcp,
        )

        self._refresh_tool_visibility_metadata_from_registry()

        if not self._should_filter_tool_listing():
            _diag.debug("on_list_tools: skipping middleware filter (not HTTP or PluginHub not configured)")
            self._add_unity_instance_parameter_to_tools(tools)
            return tools

        enabled_tool_names = await self._resolve_enabled_tool_names_for_context(context)
        if enabled_tool_names is None:
            _diag.debug("on_list_tools: no Unity session data, returning %d tools from FastMCP as-is", len(tools))
            self._add_unity_instance_parameter_to_tools(tools)
            return tools

        filtered = []
        for tool in tools:
            tool_name = getattr(tool, "name", None)
            if self._is_tool_visible(tool_name, enabled_tool_names):
                filtered.append(tool)

        _diag.debug(
            "on_list_tools: filtered %d/%d tools visible (Unity register_tools). "
            "enabled_names=%s",
            len(filtered), len(tools), sorted(enabled_tool_names),
        )
        self._add_unity_instance_parameter_to_tools(filtered)
        return filtered

    def _add_unity_instance_parameter_to_tools(self, tools) -> None:
        for tool in tools:
            tool_name = getattr(tool, "name", None)
            if not self._tool_accepts_unity_instance(tool_name):
                continue

            parameters = getattr(tool, "parameters", None)
            if not isinstance(parameters, dict):
                continue

            properties = parameters.setdefault("properties", {})
            if not isinstance(properties, dict):
                continue

            properties.setdefault("unity_instance", dict(UNITY_INSTANCE_PARAMETER_SCHEMA))
            required = parameters.get("required")
            if not isinstance(required, list):
                required = []
                parameters["required"] = required
            if "unity_instance" not in required:
                required.append("unity_instance")

    def _tool_accepts_unity_instance(self, tool_name: str | None) -> bool:
        if not isinstance(tool_name, str) or not tool_name:
            return False
        if tool_name in self._server_only_tool_names:
            return tool_name in INSTANCE_ROUTED_SERVER_TOOLS
        return (
            tool_name in self._unity_managed_tool_names
            or tool_name in self._tool_alias_to_unity_target
        )

    def _should_filter_tool_listing(self) -> bool:
        transport = (config.transport_mode or "stdio").lower()
        return transport == "http" and PluginHub.is_configured()

    async def _resolve_enabled_tool_names_for_context(
        self,
        context: MiddlewareContext,
    ) -> set[str] | None:
        ctx = context.fastmcp_context
        user_id = (await ctx.get_state("user_id")) if config.http_remote_hosted else None
        active_instance = await ctx.get_state("unity_instance")
        project_hashes = self._resolve_candidate_project_hashes(active_instance)
        if not project_hashes:
            return None

        try:
            sessions_data = await PluginHub.get_sessions(user_id=user_id)
            sessions = sessions_data.sessions if sessions_data else {}
        except Exception as exc:
            logger.debug(
                "Failed to fetch sessions for tool filtering (user_id=%s, %s)",
                user_id,
                type(exc).__name__,
                exc_info=True,
            )
            return None

        session_hashes = {
            getattr(session, "hash", None)
            for session in sessions.values()
            if getattr(session, "hash", None)
        }

        if project_hashes:
            active_hash = project_hashes[0]
            # Stale active_instance should not hide all Unity-managed tools.
            if active_hash not in session_hashes:
                return None

        if not project_hashes:
            return None

        enabled_tool_names: set[str] = set()
        resolved_any_project = False
        for project_hash in project_hashes:
            try:
                registered_tools = await PluginHub.get_tools_for_project(project_hash, user_id=user_id)
                # Only mark as resolved if tools are actually registered.
                # An empty list means register_tools hasn't been sent yet.
                if registered_tools:
                    resolved_any_project = True
            except Exception as exc:
                logger.debug(
                    "Failed to fetch tools for project hash %s (user_id=%s, %s)",
                    project_hash,
                    user_id,
                    type(exc).__name__,
                    exc_info=True,
                )
                continue

            for tool in registered_tools:
                tool_name = getattr(tool, "name", None)
                if isinstance(tool_name, str) and tool_name:
                    enabled_tool_names.add(tool_name)

        if not resolved_any_project:
            return None

        return enabled_tool_names

    def _refresh_tool_visibility_metadata_from_registry(self) -> None:
        now = time.monotonic()
        if now - self._last_tool_visibility_refresh < self._tool_visibility_refresh_interval_seconds:
            return

        with self._metadata_lock:
            now = time.monotonic()
            if now - self._last_tool_visibility_refresh < self._tool_visibility_refresh_interval_seconds:
                return

            try:
                registry_tools = get_registered_tools()
            except Exception:
                logger.warning(
                    "Failed to refresh tool visibility metadata from registry; keeping previous metadata.",
                    exc_info=True,
                )
                self._last_tool_visibility_refresh = now
                return

            if not registry_tools and not self._has_logged_empty_registry_warning:
                logger.warning(
                    "Tool registry is empty during tool-list filtering; treating tools as unknown/visible."
                )
                self._has_logged_empty_registry_warning = True
            elif registry_tools:
                self._has_logged_empty_registry_warning = False

            unity_managed_tool_names: set[str] = set()
            tool_alias_to_unity_target: dict[str, str] = {}
            server_only_tool_names: set[str] = set()
            signature_entries: list[tuple[str, str]] = []

            for tool_info in registry_tools:
                tool_name = tool_info.get("name")
                if not isinstance(tool_name, str) or not tool_name:
                    continue

                unity_target = tool_info.get("unity_target", tool_name)
                if unity_target is None:
                    server_only_tool_names.add(tool_name)
                    signature_entries.append((tool_name, "<server-only>"))
                    continue

                if not isinstance(unity_target, str) or not unity_target:
                    logger.debug(
                        "Skipping tool visibility metadata with invalid unity_target: %s",
                        tool_info,
                    )
                    continue

                if unity_target == tool_name:
                    unity_managed_tool_names.add(tool_name)
                    signature_entries.append((tool_name, unity_target))
                    continue

                tool_alias_to_unity_target[tool_name] = unity_target
                unity_managed_tool_names.add(unity_target)
                signature_entries.append((tool_name, unity_target))

            signature = tuple(sorted(signature_entries, key=lambda item: item[0]))
            if signature == self._tool_visibility_signature:
                self._last_tool_visibility_refresh = now
                return

            self._unity_managed_tool_names = unity_managed_tool_names
            self._tool_alias_to_unity_target = tool_alias_to_unity_target
            self._server_only_tool_names = server_only_tool_names
            self._tool_visibility_signature = signature
            self._last_tool_visibility_refresh = now

    @staticmethod
    def _resolve_candidate_project_hashes(active_instance: str | None) -> list[str]:
        if not active_instance:
            return []

        if "@" in active_instance:
            _, _, suffix = active_instance.rpartition("@")
            return [suffix] if suffix else []

        return [active_instance]

    def _is_tool_visible(self, tool_name: str | None, enabled_tool_names: set[str]) -> bool:
        if not isinstance(tool_name, str) or not tool_name:
            return True

        if tool_name in self._server_only_tool_names:
            return True

        if tool_name in enabled_tool_names:
            return True

        unity_target = self._tool_alias_to_unity_target.get(tool_name)
        if unity_target:
            return unity_target in enabled_tool_names

        # Keep unknown tools visible for forward compatibility.
        if tool_name not in self._unity_managed_tool_names:
            return True

        return False
