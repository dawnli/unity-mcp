"""
MCP Resources package - Auto-discovers and registers all resources in this directory.
"""
import functools
import inspect
import logging
from pathlib import Path

from fastmcp import FastMCP
from pydantic import BaseModel
from core.telemetry_decorator import telemetry_resource
from core.logging_decorator import log_execution

from services.registry import get_registered_resources
from utils.module_discovery import discover_modules

logger = logging.getLogger("mcp-for-unity-server")

# Export decorator for easy imports within tools
__all__ = ['register_all_resources']


def _serialize_pydantic(func, *, accepts_unity_instance: bool = False):
    """Wrap a resource function so Pydantic models are serialized to JSON strings.

    FastMCP 3.x expects resource functions to return str, bytes, or ResourceResult.
    Our resource functions return MCPResponse (a Pydantic BaseModel). This wrapper
    converts them to JSON strings automatically.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        if accepts_unity_instance:
            kwargs.pop("unity_instance", None)
        result = await func(*args, **kwargs)
        if isinstance(result, BaseModel):
            return result.model_dump_json()
        if isinstance(result, dict):
            import json
            return json.dumps(result)
        return result
    if accepts_unity_instance:
        _with_optional_unity_instance_signature(wrapper)
    return wrapper


def _with_unity_instance_query(uri: str) -> str | None:
    """Return a URI template variant that accepts ?unity_instance=... ."""
    if "unity_instance" in uri:
        return None
    if "{?" in uri:
        prefix, rest = uri.split("{?", 1)
        params, suffix = rest.split("}", 1)
        return prefix + "{?" + params + ",unity_instance}" + suffix
    return f"{uri}{{?unity_instance}}"


def _with_optional_unity_instance_signature(func):
    sig = inspect.signature(func)
    if "unity_instance" in sig.parameters:
        return func

    params = list(sig.parameters.values())
    unity_param = inspect.Parameter(
        "unity_instance",
        inspect.Parameter.KEYWORD_ONLY,
        default=None,
        annotation=str | None,
    )
    insert_at = next(
        (i for i, param in enumerate(params) if param.kind == inspect.Parameter.VAR_KEYWORD),
        len(params),
    )
    params.insert(insert_at, unity_param)
    annotations = dict(getattr(func, "__annotations__", {}))
    annotations["unity_instance"] = str | None
    func.__annotations__ = annotations
    func.__signature__ = sig.replace(parameters=params)
    return func


def register_all_resources(mcp: FastMCP, *, project_scoped_tools: bool = True):
    """
    Auto-discover and register all resources in the resources/ directory.

    Any .py file in this directory or subdirectories with @mcp_for_unity_resource decorated
    functions will be automatically registered.
    """
    logger.info("Auto-discovering MCP for Unity Server resources...")
    # Dynamic import of all modules in this directory
    resources_dir = Path(__file__).parent

    # Discover and import all modules
    list(discover_modules(resources_dir, __package__))

    resources = get_registered_resources()

    if not resources:
        logger.warning("No MCP resources registered!")
        return

    registered_count = 0
    for resource_info in resources:
        func = resource_info['func']
        uri = resource_info['uri']
        resource_name = resource_info['name']
        description = resource_info['description']
        kwargs = resource_info['kwargs']

        if not project_scoped_tools and resource_name == "custom_tools":
            logger.info(
                "Skipping custom_tools resource registration (project-scoped tools disabled)")
            continue

        # Check if URI contains query parameters (e.g., {?unity_instance})
        has_query_params = '{?' in uri

        if has_query_params:
            wrapped_template = _serialize_pydantic(func)
            wrapped_template = log_execution(resource_name, "Resource")(wrapped_template)
            wrapped_template = telemetry_resource(
                resource_name)(wrapped_template)
            wrapped_template = mcp.resource(
                uri=uri,
                name=resource_name,
                description=description,
                **kwargs,
            )(wrapped_template)
            logger.debug(
                f"Registered resource template: {resource_name} - {uri}")
            registered_count += 1
            resource_info['func'] = wrapped_template
        else:
            wrapped = _serialize_pydantic(func)
            wrapped = log_execution(resource_name, "Resource")(wrapped)
            wrapped = telemetry_resource(resource_name)(wrapped)
            wrapped = mcp.resource(
                uri=uri,
                name=resource_name,
                description=description,
                **kwargs,
            )(wrapped)
            resource_info['func'] = wrapped
            logger.debug(
                f"Registered resource: {resource_name} - {description}")
            registered_count += 1

        unity_instance_uri = _with_unity_instance_query(uri)
        if unity_instance_uri:
            wrapped_query = _serialize_pydantic(
                func,
                accepts_unity_instance=True,
            )
            wrapped_query = log_execution(resource_name, "Resource")(wrapped_query)
            wrapped_query = telemetry_resource(resource_name)(wrapped_query)
            wrapped_query = mcp.resource(
                uri=unity_instance_uri,
                name=resource_name,
                description=description,
                **kwargs,
            )(wrapped_query)
            logger.debug(
                f"Registered resource template: {resource_name} - {unity_instance_uri}")
            registered_count += 1

    logger.info(
        f"Registered {registered_count} MCP resources ({len(resources)} unique)")
