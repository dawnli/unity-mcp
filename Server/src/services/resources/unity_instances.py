"""
Resource to check whether the explicitly requested Unity Editor instance is available.
"""
from typing import Any

from fastmcp import Context

from core.config import config
from services.registry import mcp_for_unity_resource
from transport.legacy.unity_connection import get_unity_connection_pool
from transport.plugin_hub import PluginHub


def _project_hash_from_instance(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    if "@" in value:
        _, _, value = value.rpartition("@")
        value = value.strip()
    return value.lower() or None


@mcp_for_unity_resource(
    uri="mcpforunity://instances",
    name="unity_instances",
    description=(
        "Checks whether the requested Unity Editor instance is available. "
        "This resource requires ?unity_instance=<project-hash> and does not list instances.\n\n"
        "URI: mcpforunity://instances?unity_instance=<hash>"
    ),
)
async def unity_instances(ctx: Context) -> dict[str, Any]:
    """
    Return availability for only the instance named by the request's unity_instance hash.
    """
    unity_instance = await ctx.get_state("unity_instance")
    requested_hash = _project_hash_from_instance(unity_instance)
    if not requested_hash:
        return {
            "success": False,
            "error": "unity_instance is required. Append ?unity_instance=<hash> to this resource URI.",
            "available": False,
        }

    await ctx.info(f"Checking Unity instance availability for {requested_hash}")

    try:
        transport = (config.transport_mode or "stdio").lower()
        available = False

        if transport == "http":
            user_id = (await ctx.get_state("user_id")) if config.http_remote_hosted else None
            sessions_data = await PluginHub.get_sessions(user_id=user_id)
            sessions = sessions_data.sessions if sessions_data else {}
            available = any(
                _project_hash_from_instance(getattr(session, "hash", None)) == requested_hash
                for session in sessions.values()
            )
        else:
            pool = get_unity_connection_pool()
            instances = pool.discover_all_instances(force_refresh=False)
            available = any(
                _project_hash_from_instance(getattr(instance, "hash", None)) == requested_hash
                for instance in instances
            )

        return {
            "success": True,
            "transport": transport,
            "requested_hash": requested_hash,
            "available": available,
        }
    except Exception as e:
        await ctx.error(f"Error checking Unity instance availability: {e}")
        return {
            "success": False,
            "error": f"Failed to check Unity instance availability: {str(e)}",
            "requested_hash": requested_hash,
            "available": False,
        }
