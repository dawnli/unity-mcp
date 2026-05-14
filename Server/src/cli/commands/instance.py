"""Instance CLI commands for managing Unity instances."""

import click
from typing import Optional

from cli.utils.config import get_config
from cli.utils.output import format_output, print_error, print_success, print_info
from cli.utils.connection import run_command, run_list_instances, handle_unity_errors


@click.group()
def instance():
    """Unity instance management - check and bind explicit project hashes."""
    pass


@instance.command("list")
@handle_unity_errors
def list_instances():
    """Check whether the configured Unity instance is available.

    \\b
    Examples:
        unity-mcp --instance <hash> instance list
    """
    config = get_config()

    result = run_list_instances(config)
    if not isinstance(result, dict) or not result.get("available"):
        print_info(f"Unity instance {config.unity_instance} is not available")
        return

    print_success(
        f"Unity instance {result.get('requested_hash', config.unity_instance)} is available"
    )


@instance.command("set")
@click.argument("instance_id")
@handle_unity_errors
def set_instance(instance_id: str):
    """Set the active Unity instance.

    INSTANCE_ID should be the computed project hash.

    \\b
    Examples:
        unity-mcp instance set "<hash>"
        unity-mcp instance set <hash>
    """
    config = get_config()

    result = run_command("set_active_instance", {
        "instance": instance_id,
    }, config)
    click.echo(format_output(result, config.format))
    if result.get("success"):
        data = result.get("data", {})
        active = data.get("instance", instance_id)
        print_success(f"MCP client session bound to: {active}")


@instance.command("current")
def current_instance():
    """Show the currently selected Unity instance.

    \\b
    Examples:
        unity-mcp instance current
    """
    config = get_config()

    # The current instance is typically shown in telemetry or needs to be tracked
    # For now, we can show the configured instance from CLI options
    if config.unity_instance:
        click.echo(f"Configured instance: {config.unity_instance}")
    else:
        print_info("No Unity project hash configured.")
        print_info("Set UNITY_MCP_INSTANCE or pass --instance <hash>.")
