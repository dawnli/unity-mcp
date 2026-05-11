# Shared Server Multi-Client Routing Tests

These manual tests validate the fixed shared endpoint flow:

- One MCP server endpoint: `http://127.0.0.1:8080/mcp`
- One or more Unity Editors with the Unity MCP plugin enabled
- One or more AI IDE MCP clients pointed at the same endpoint
- Per-call routing by the normalized absolute project path hash

## Setup

1. Open two Unity projects, called Project A and Project B below.
2. Start or reuse one MCP server on `http://127.0.0.1:8080/mcp`.
3. Configure every AI IDE MCP client to use that same URL.
4. Compute project hashes:

```powershell
python unity-mcp-skill\scripts\project_path_hash.py "D:\absolute\path\ProjectA"
python unity-mcp-skill\scripts\project_path_hash.py "D:\absolute\path\ProjectA\Assets"
python unity-mcp-skill\scripts\project_path_hash.py "D:\absolute\path\ProjectB"
```

The Project A root path and Project A `Assets` path must print the same hash.
Project A and Project B must print different hashes.

If an AI IDE does not show `unity_instance` in Unity-managed tool schemas, reload
or restart that MCP connection so it refreshes `list_tools`.

## Test 1: Same Project, Two AI IDE Sessions

Use two separate AI IDE sessions connected to the same MCP server.

Session A:

```text
manage_scene(action="get_active", unity_instance="<hashA>")
```

Session B:

```text
manage_scene(action="get_active", unity_instance="<hashA>")
```

Expected:

- Both calls succeed.
- Both responses describe Project A.
- The sessions do not overwrite each other's MCP session state.

## Test 2: Different Projects, Two AI IDE Sessions

Session A:

```text
manage_scene(action="get_active", unity_instance="<hashA>")
```

Session B:

```text
manage_scene(action="get_active", unity_instance="<hashB>")
```

Expected:

- Session A routes to Project A.
- Session B routes to Project B.
- Repeating Session A after Session B still routes to Project A.

## Test 3: Alternating Projects In One AI IDE Session

In one AI IDE session, alternate explicit per-call routing:

```text
manage_scene(action="get_active", unity_instance="<hashA>")
manage_scene(action="get_active", unity_instance="<hashB>")
manage_scene(action="get_active", unity_instance="<hashA>")
```

Expected:

- Each call routes to the hash supplied on that call.
- No previous call changes the next explicitly routed call.

## Test 4: Resource Routing

Read resources with the hash in the URI query:

```text
mcpforunity://editor/state?unity_instance=<hashA>
mcpforunity://project/info?unity_instance=<hashA>
mcpforunity://editor/state?unity_instance=<hashB>
mcpforunity://project/info?unity_instance=<hashB>
```

Expected:

- Project A resource reads return Project A state/info.
- Project B resource reads return Project B state/info.
- Resource reads without `unity_instance` should only be used for compatibility
  after `set_active_instance`, not for the normal shared-server flow.

## Test 5: Compatibility Fallback

Use this only to verify old clients still work.

Session A:

```text
set_active_instance(instance="<hashA>")
manage_scene(action="get_active")
```

Session B:

```text
set_active_instance(instance="<hashB>")
manage_scene(action="get_active")
```

Expected:

- Session A routes to Project A.
- Session B routes to Project B.
- `debug_request_context` should show different derived session keys if the AI
  IDE preserves separate MCP session IDs.

## Test 6: Diagnostics Fallback

Only if computed-hash routing fails, read:

```text
mcpforunity://instances
```

Expected:

- The reported hash for each project matches `project_path_hash.py`.
- If it does not match, the plugin and the skill script are not using the same
  normalized path/hash algorithm.
