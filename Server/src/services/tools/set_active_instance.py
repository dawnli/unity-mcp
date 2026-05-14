from typing import Annotated, Any
from types import SimpleNamespace

from fastmcp import Context
from mcp.types import ToolAnnotations

from services.registry import mcp_for_unity_tool
from transport.legacy.unity_connection import get_unity_connection_pool
from transport.unity_instance_middleware import get_unity_instance_middleware
from transport.plugin_hub import PluginHub
from core.config import config


def _normalize_instance_token(instance_token: str) -> tuple[str | None, str | None]:
    if "@" in instance_token:
        name_part, _, hash_part = instance_token.partition("@")
        hash_part = hash_part.strip().lower()
        return (name_part or None), (hash_part or None)
    return None, instance_token.strip().lower()


@mcp_for_unity_tool(
    unity_target=None,
    group=None,
    description=(
        "Bind this MCP client session to the computed Unity project hash. "
        "This does not remove the requirement to pass unity_instance on every Unity request."
    ),
    annotations=ToolAnnotations(
        title="Set Active Instance",
    ),
)
async def set_active_instance(
        ctx: Context,
        instance: Annotated[str, "Target computed project hash or Name@hash"]
) -> dict[str, Any]:
    transport = (config.transport_mode or "stdio").lower()
    value = (instance or "").strip()
    if not value:
        return {
            "success": False,
            "error": "Instance identifier is required. Compute the project hash from the absolute Unity project path.",
        }
    if value.isdigit():
        return {
            "success": False,
            "error": "Port-based targeting is not supported. Provide the computed Unity project hash.",
        }

    _, requested_hash = _normalize_instance_token(value)
    if not requested_hash:
        return {
            "success": False,
            "error": "Instance identifier must include a Unity project hash.",
        }

    # Discover running instances based on transport
    if transport == "http":
        # In remote-hosted mode, filter sessions by user_id
        user_id = (await ctx.get_state(
            "user_id")) if config.http_remote_hosted else None
        sessions_data = await PluginHub.get_sessions(user_id=user_id)
        sessions = sessions_data.sessions
        instances = []
        for session_id, session in sessions.items():
            project = session.project or "Unknown"
            hash_value = session.hash
            if not hash_value:
                continue
            inst_id = f"{project}@{hash_value}"
            instances.append(SimpleNamespace(
                id=inst_id,
                hash=hash_value,
                name=project,
                session_id=session_id,
            ))
    else:
        pool = get_unity_connection_pool()
        instances = pool.discover_all_instances(force_refresh=True)

    resolved = next(
        (
            inst for inst in instances
            if str(getattr(inst, "hash", "")).lower() == requested_hash
            or getattr(inst, "id", None) == value
        ),
        None,
    )
    if resolved is None:
        return {
            "success": False,
            "error": f"Unity instance '{value}' is not available.",
        }

    if resolved is None:
        # Should be unreachable due to logic above, but satisfies static analysis
        return {
            "success": False,
            "error": "Internal error: Instance resolution failed."
        }

    middleware = get_unity_instance_middleware()
    try:
        await middleware.set_active_instance(ctx, resolved.id)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    session_key = await middleware.get_session_key(ctx)

    return {
        "success": True,
        "message": f"MCP client session bound to {resolved.id}",
        "data": {
            "instance": resolved.id,
            "session_key": session_key,
        },
    }
