from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .config import CONFIG_NAME, discover_config, load_config
from .envsync import sync_env_files
from .gittools import GitError, create_worktree, current_branch, status_short
from .registry import Registry
from .runtime import (
    brief_for,
    hydrate_status,
    start_checkouts,
    start_services,
    stop_checkouts,
    stop_services,
)
from .utils import slugify, tail_lines


PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = {PROTOCOL_VERSION}
SERVER_ROOT: Path | None = None
INSTRUCTIONS = (
    "Switchyard exposes local runtime state for parallel agent worktrees. "
    "Prefer switchyard_brief first, then switchyard_where or switchyard_logs for focused context. "
    "Use switchyard_create when a requested branch runtime does not exist yet. "
    "switchyard_create, switchyard_up, switchyard_checkout, switchyard_uncheckout, and switchyard_down "
    "change local state and should be treated as user-visible actions."
)


class McpError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def object_schema(
    properties: dict[str, Any],
    required: list[str] | None = None,
    additional_properties: bool = False,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional_properties,
    }
    if required:
        schema["required"] = required
    return schema


def array_schema(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


def string_array_schema() -> dict[str, Any]:
    return array_schema({"type": "string"})


COMMON_CWD = {
    "cwd": {
        "type": "string",
        "description": (
            "Optional path under the MCP server project root, or a registered worktree path. "
            f"Defaults to the detected server project root containing {CONFIG_NAME}."
        ),
    }
}

READ_ONLY_TOOL = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
SERVICE_START_TOOL = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": True,
}
LOCAL_FORWARDER_TOOL = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
DESTRUCTIVE_LOCAL_TOOL = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": False,
}

NULLABLE_STRING = {"type": ["string", "null"]}
NULLABLE_INTEGER = {"type": ["integer", "null"]}
STRING_ARRAY = string_array_schema()

PROXY_OUTPUT_SCHEMA = object_schema(
    {
        "host": {"type": "string"},
        "port": {"type": "integer"},
        "tld": {"type": "string"},
    },
    ["host", "port", "tld"],
)
WORKTREE_RECORD_SCHEMA = object_schema(
    {
        "branch": {"type": "string"},
        "slug": {"type": "string"},
        "path": {"type": "string"},
        "updated_at": {"type": "string"},
    },
    additional_properties=True,
)
SERVICE_RECORD_SCHEMA = object_schema(
    {
        "service": {"type": "string"},
        "branch": {"type": "string"},
        "status": {"type": "string"},
        "url": {"type": "string"},
        "port": NULLABLE_INTEGER,
        "pid": {"type": "integer"},
        "log_file": {"type": "string"},
        "recent_errors": STRING_ARRAY,
    },
    additional_properties=True,
)
CHECKOUT_RECORD_SCHEMA = object_schema(
    {
        "service": {"type": "string"},
        "branch": {"type": "string"},
        "status": {"type": "string"},
        "listen_host": {"type": "string"},
        "listen_port": NULLABLE_INTEGER,
        "target_host": {"type": "string"},
        "target_port": NULLABLE_INTEGER,
        "log_file": {"type": "string"},
    },
    additional_properties=True,
)
RECENT_ERROR_SCHEMA = object_schema(
    {
        "service": NULLABLE_STRING,
        "line": {"type": "string"},
    },
    ["service", "line"],
)
LOG_ENTRY_SCHEMA = object_schema(
    {
        "service": {"type": "string"},
        "branch": {"type": "string"},
        "log_file": {"type": "string"},
        "lines": STRING_ARRAY,
    },
    ["service", "branch", "log_file", "lines"],
)
DOCTOR_OUTPUT_SCHEMA = object_schema(
    {
        "switchyard": {"type": "string"},
        "home": {"type": "string"},
        "project": {"type": "string"},
        "project_root": {"type": "string"},
        "config": {"type": "string"},
        "proxy": PROXY_OUTPUT_SCHEMA,
        "services": STRING_ARRAY,
    },
    ["switchyard", "home", "project", "project_root", "config", "proxy", "services"],
)
CREATE_OUTPUT_SCHEMA = object_schema(
    {
        "created": {"type": "boolean"},
        "branch": {"type": "string"},
        "worktree": {"type": "string"},
        "env": STRING_ARRAY,
        "message": {"type": "string"},
    },
    ["created", "branch", "worktree", "env"],
)
LIST_OUTPUT_SCHEMA = object_schema({"worktrees": array_schema(WORKTREE_RECORD_SCHEMA)}, ["worktrees"])
STATUS_OUTPUT_SCHEMA = object_schema({"services": array_schema(SERVICE_RECORD_SCHEMA)}, ["services"])
BRIEF_OUTPUT_SCHEMA = object_schema(
    {
        "project": {"type": "string"},
        "project_root": {"type": "string"},
        "branch": NULLABLE_STRING,
        "services": array_schema(SERVICE_RECORD_SCHEMA),
        "checkouts": array_schema(CHECKOUT_RECORD_SCHEMA),
        "changed_files": STRING_ARRAY,
        "recent_errors": array_schema(RECENT_ERROR_SCHEMA),
    },
    ["project", "project_root", "branch", "services", "checkouts", "changed_files", "recent_errors"],
)
LOGS_OUTPUT_SCHEMA = object_schema({"logs": array_schema(LOG_ENTRY_SCHEMA)}, ["logs"])
RUNTIME_ACTION_OUTPUT_SCHEMA = object_schema(
    {
        "branch": NULLABLE_STRING,
        "worktree": {"type": "string"},
        "messages": STRING_ARRAY,
    },
    ["messages"],
)
WHERE_OUTPUT_SCHEMA = SERVICE_RECORD_SCHEMA


TOOLS: dict[str, dict[str, Any]] = {
    "switchyard_doctor": {
        "title": "Inspect Switchyard project configuration",
        "description": "Return Switchyard version, project root, config path, proxy, and configured services.",
        "annotations": READ_ONLY_TOOL,
        "inputSchema": object_schema(COMMON_CWD),
        "outputSchema": DOCTOR_OUTPUT_SCHEMA,
    },
    "switchyard_status": {
        "title": "List Switchyard services",
        "description": "Return registered services with running/stale status, URLs, ports, logs, and recent errors.",
        "annotations": READ_ONLY_TOOL,
        "inputSchema": object_schema(
            {
                **COMMON_CWD,
                "branch": {"type": "string", "description": "Optional branch name or slug to filter services."},
            }
        ),
        "outputSchema": STATUS_OUTPUT_SCHEMA,
    },
    "switchyard_create": {
        "title": "Create a worktree runtime",
        "description": "Create a managed git worktree for a branch and sync configured env files.",
        "annotations": DESTRUCTIVE_LOCAL_TOOL,
        "inputSchema": object_schema(
            {
                **COMMON_CWD,
                "branch": {"type": "string", "description": "Branch name for the new worktree."},
                "base": {"type": "string", "description": "Optional git base revision when creating a new branch."},
                "force_env": {
                    "type": "boolean",
                    "description": "Replace existing env targets when syncing configured env files. Defaults to false.",
                },
            },
            ["branch"],
        ),
        "outputSchema": CREATE_OUTPUT_SCHEMA,
    },
    "switchyard_list": {
        "title": "List Switchyard worktrees",
        "description": "Return Switchyard-registered worktrees for this project.",
        "annotations": READ_ONLY_TOOL,
        "inputSchema": object_schema(COMMON_CWD),
        "outputSchema": LIST_OUTPUT_SCHEMA,
    },
    "switchyard_brief": {
        "title": "Get compact agent runtime brief",
        "description": "Return a bounded project summary with services, changed files, and recent error lines.",
        "annotations": READ_ONLY_TOOL,
        "inputSchema": object_schema(
            {
                **COMMON_CWD,
                "branch": {"type": "string", "description": "Optional branch name. Defaults to the current worktree."},
            }
        ),
        "outputSchema": BRIEF_OUTPUT_SCHEMA,
    },
    "switchyard_where": {
        "title": "Find one service",
        "description": "Return the URL, port, PID, worktree, and log path for one running service.",
        "annotations": READ_ONLY_TOOL,
        "inputSchema": object_schema(
            {
                **COMMON_CWD,
                "service": {"type": "string", "description": "Service name from switchyard.toml."},
                "branch": {"type": "string", "description": "Optional branch name. Defaults to the current worktree."},
            },
            ["service"],
        ),
        "outputSchema": WHERE_OUTPUT_SCHEMA,
    },
    "switchyard_logs": {
        "title": "Read service logs",
        "description": "Return the recent tail of one service log, or all logs for the selected branch.",
        "annotations": READ_ONLY_TOOL,
        "inputSchema": object_schema(
            {
                **COMMON_CWD,
                "service": {"type": "string", "description": "Optional service name."},
                "branch": {"type": "string", "description": "Optional branch name. Defaults to the current worktree."},
                "lines": {
                    "type": "integer",
                    "description": "Number of log lines to return. Defaults to 80, maximum 300.",
                    "minimum": 1,
                    "maximum": 300,
                },
            }
        ),
        "outputSchema": LOGS_OUTPUT_SCHEMA,
    },
    "switchyard_up": {
        "title": "Start services",
        "description": "Start configured local services for a branch or the current worktree.",
        "annotations": SERVICE_START_TOOL,
        "inputSchema": object_schema(
            {
                **COMMON_CWD,
                "branch": {"type": "string", "description": "Optional branch name. Defaults to the current worktree."},
                "services": {
                    "type": "array",
                    "description": "Optional service names. Empty starts every configured service.",
                    "items": {"type": "string"},
                },
            }
        ),
        "outputSchema": RUNTIME_ACTION_OUTPUT_SCHEMA,
    },
    "switchyard_checkout": {
        "title": "Map services to canonical ports",
        "description": "Forward a running branch runtime back to configured canonical service ports.",
        "annotations": LOCAL_FORWARDER_TOOL,
        "inputSchema": object_schema(
            {
                **COMMON_CWD,
                "branch": {"type": "string", "description": "Branch name for the running service runtime."},
                "services": {
                    "type": "array",
                    "description": "Optional service names. Empty checks out every running service for the branch.",
                    "items": {"type": "string"},
                },
            },
            ["branch"],
        ),
        "outputSchema": RUNTIME_ACTION_OUTPUT_SCHEMA,
    },
    "switchyard_uncheckout": {
        "title": "Stop canonical port mappings",
        "description": "Stop Switchyard-managed canonical port forwarders.",
        "annotations": DESTRUCTIVE_LOCAL_TOOL,
        "inputSchema": object_schema(
            {
                **COMMON_CWD,
                "branch": {"type": "string", "description": "Optional branch name. Omit to consider all branches."},
                "services": {
                    "type": "array",
                    "description": "Optional service names. Empty stops every matching checkout.",
                    "items": {"type": "string"},
                },
            }
        ),
        "outputSchema": RUNTIME_ACTION_OUTPUT_SCHEMA,
    },
    "switchyard_down": {
        "title": "Stop services",
        "description": "Stop Switchyard-managed services for a branch or selected service names.",
        "annotations": DESTRUCTIVE_LOCAL_TOOL,
        "inputSchema": object_schema(
            {
                **COMMON_CWD,
                "branch": {"type": "string", "description": "Optional branch name. Omit to consider all branches."},
                "services": {
                    "type": "array",
                    "description": "Optional service names. Empty stops every matching service.",
                    "items": {"type": "string"},
                },
            }
        ),
        "outputSchema": RUNTIME_ACTION_OUTPUT_SCHEMA,
    },
}


def cwd_from(arguments: dict[str, Any]) -> Path:
    root = SERVER_ROOT or Path.cwd().resolve()
    cwd = arguments.get("cwd")
    resolved = Path(str(cwd)).expanduser().resolve() if cwd else root
    if resolved != root and not resolved.is_relative_to(root) and not registered_worktree_cwd(root, resolved):
        raise McpError(-32602, f"cwd must stay under MCP server root or a registered worktree: {root}")
    return resolved


def set_server_root(root: Path | None) -> None:
    global SERVER_ROOT
    SERVER_ROOT = root.resolve() if root else None


def registered_worktree_cwd(root: Path, cwd: Path) -> bool:
    config_path = discover_config(root)
    if not config_path:
        return False
    config = load_config(config_path)
    registry = Registry(create=False)
    registered = registry.find_worktree_containing(cwd)
    if not registered:
        return False
    project, _ = registered
    return Path(str(project.get("root", ""))).resolve() == config.root.resolve()


def load_project(cwd: Path, ensure: bool = True):
    root = SERVER_ROOT or Path.cwd().resolve()
    if cwd != root and registered_worktree_cwd(root, cwd):
        config_path = discover_config(root)
        if not config_path:
            raise McpError(-32004, f"could not find {CONFIG_NAME} from {root}")
        config = load_config(config_path)
        registry = Registry(create=ensure)
        if ensure:
            registry.ensure_project(config)
        return config, registry
    config_path = discover_config(cwd)
    if not config_path:
        raise McpError(-32004, f"could not find {CONFIG_NAME} from {cwd}")
    config = load_config(config_path)
    registry = Registry(create=ensure)
    if ensure:
        registry.ensure_project(config)
    return config, registry


def resolve_branch_and_worktree(config, registry: Registry, branch: str | None, cwd: Path):
    if branch:
        record = registry.get_worktree(config.root, branch)
        if record:
            return str(record["branch"]), Path(str(record["path"]))
        if cwd.resolve() != config.root.resolve():
            return branch, cwd.resolve()
        return branch, registry.default_worktree_path(config, branch)
    registered = registry.find_worktree_containing(cwd)
    if registered:
        project, record = registered
        if Path(str(project.get("root", ""))).resolve() == config.root.resolve():
            return str(record["branch"]), Path(str(record["path"]))
    try:
        current = current_branch(cwd)
    except GitError:
        current = "current"
    record = registry.get_worktree(config.root, current)
    if record:
        return str(record["branch"]), Path(str(record["path"]))
    return current, cwd.resolve()


def branch_for_action(config, registry: Registry, requested: str | None, cwd: Path) -> str | None:
    if requested:
        return requested
    if cwd.resolve() == config.root.resolve():
        return None
    branch, _ = resolve_branch_and_worktree(config, registry, None, cwd)
    return branch


def json_text(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def tool_result(data: Any, text: str | None = None, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text if text is not None else json_text(data)}],
        "structuredContent": data,
        "isError": is_error,
    }


def normalize_services(value: Any) -> list[str] | None:
    if value in (None, []):
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise McpError(-32602, "services must be an array of strings")
    return value


def string_argument(arguments: dict[str, Any], key: str, required: bool = False) -> str | None:
    value = arguments.get(key)
    if value in (None, ""):
        if required:
            raise McpError(-32602, f"{key} is required")
        return None
    if not isinstance(value, str):
        raise McpError(-32602, f"{key} must be a string")
    return value


def bool_argument(arguments: dict[str, Any], key: str, default: bool = False) -> bool:
    value = arguments.get(key, default)
    if not isinstance(value, bool):
        raise McpError(-32602, f"{key} must be a boolean")
    return value


def tool_doctor(arguments: dict[str, Any]) -> dict[str, Any]:
    cwd = cwd_from(arguments)
    config, registry = load_project(cwd, ensure=False)
    data = {
        "switchyard": __version__,
        "home": str(registry.home),
        "project": config.name,
        "project_root": str(config.root),
        "config": str(config.path),
        "proxy": {"host": config.proxy.host, "port": config.proxy.port, "tld": config.proxy.tld},
        "services": sorted(config.services),
    }
    return tool_result(data)


def tool_create(arguments: dict[str, Any]) -> dict[str, Any]:
    cwd = cwd_from(arguments)
    config, registry = load_project(cwd)
    branch = string_argument(arguments, "branch", required=True)
    base = string_argument(arguments, "base")
    force_env = bool_argument(arguments, "force_env")
    assert branch is not None
    existing = registry.get_worktree(config.root, branch)
    if existing and existing.get("branch") != branch:
        raise McpError(-32602, f"branch names collide after slugging: {existing.get('branch')} and {branch}")
    if existing and Path(str(existing["path"])).exists():
        data = {
            "created": False,
            "branch": existing["branch"],
            "worktree": existing["path"],
            "env": [],
            "message": "worktree already registered",
        }
        return tool_result(data)
    path = registry.default_worktree_path(config, branch)
    create_worktree(config.root, path, branch, base)
    actions = sync_env_files(config.root, path, config.env, force=force_env)
    registry.upsert_worktree(config, branch, path)
    data = {"created": True, "branch": branch, "worktree": str(path), "env": actions}
    return tool_result(data)


def tool_list(arguments: dict[str, Any]) -> dict[str, Any]:
    cwd = cwd_from(arguments)
    config, registry = load_project(cwd, ensure=False)
    return tool_result({"worktrees": registry.list_worktrees(config.root)})


def tool_status(arguments: dict[str, Any]) -> dict[str, Any]:
    cwd = cwd_from(arguments)
    config, registry = load_project(cwd, ensure=False)
    branch_arg = str(arguments["branch"]) if arguments.get("branch") else None
    branch_filter = branch_arg
    if not branch_filter and cwd.resolve() != config.root.resolve():
        branch_filter, _ = resolve_branch_and_worktree(config, registry, None, cwd)
    data = hydrate_status(registry.services(config.root, branch_filter))
    return tool_result({"services": data})


def tool_brief(arguments: dict[str, Any]) -> dict[str, Any]:
    cwd = cwd_from(arguments)
    config, registry = load_project(cwd, ensure=False)
    branch_arg = str(arguments["branch"]) if arguments.get("branch") else None
    branch, worktree = resolve_branch_and_worktree(config, registry, branch_arg, cwd)
    changed = status_short(worktree) if worktree.exists() else []
    branch_filter = branch if branch_arg or worktree.resolve() != config.root.resolve() else None
    data = brief_for(config, registry, branch_filter, changed)
    return tool_result(data)


def tool_where(arguments: dict[str, Any]) -> dict[str, Any]:
    service = arguments.get("service")
    if not isinstance(service, str) or not service:
        raise McpError(-32602, "service is required")
    cwd = cwd_from(arguments)
    config, registry = load_project(cwd, ensure=False)
    branch_arg = str(arguments["branch"]) if arguments.get("branch") else None
    branch, _ = resolve_branch_and_worktree(config, registry, branch_arg, cwd)
    record = registry.find_service(config.root, slugify(service), branch)
    if not record:
        raise McpError(-32004, f"{service} is not running for {branch}")
    return tool_result(record)


def tool_logs(arguments: dict[str, Any]) -> dict[str, Any]:
    cwd = cwd_from(arguments)
    config, registry = load_project(cwd, ensure=False)
    branch_arg = str(arguments["branch"]) if arguments.get("branch") else None
    branch, _ = resolve_branch_and_worktree(config, registry, branch_arg, cwd)
    lines_value = arguments.get("lines", 80)
    if type(lines_value) is not int:
        raise McpError(-32602, "lines must be an integer")
    lines = lines_value
    if lines < 1 or lines > 300:
        raise McpError(-32602, "lines must be between 1 and 300")
    service = arguments.get("service")
    if service:
        record = registry.find_service(config.root, slugify(str(service)), branch)
        records = [record] if record else []
    else:
        records = registry.services(config.root, branch)
    if not records:
        raise McpError(-32004, "no matching logs")
    logs = []
    text_blocks = []
    for record in records:
        path = Path(str(record["log_file"]))
        tail = tail_lines(path, lines)
        item = {"service": record["service"], "branch": record["branch"], "log_file": str(path), "lines": tail}
        logs.append(item)
        text_blocks.append(f"==> {record['service']} ({record['branch']}) <==\n" + "\n".join(tail))
    return tool_result({"logs": logs}, "\n\n".join(text_blocks))


def tool_up(arguments: dict[str, Any]) -> dict[str, Any]:
    cwd = cwd_from(arguments)
    config, registry = load_project(cwd)
    branch_arg = str(arguments["branch"]) if arguments.get("branch") else None
    branch, worktree = resolve_branch_and_worktree(config, registry, branch_arg, cwd)
    if not worktree.exists():
        raise McpError(-32004, f"worktree does not exist: {worktree}")
    services = normalize_services(arguments.get("services"))
    messages = start_services(config, registry, branch, worktree, services)
    return tool_result({"branch": branch, "worktree": str(worktree), "messages": messages})


def tool_checkout(arguments: dict[str, Any]) -> dict[str, Any]:
    cwd = cwd_from(arguments)
    config, registry = load_project(cwd)
    branch = string_argument(arguments, "branch", required=True)
    services = normalize_services(arguments.get("services"))
    assert branch is not None
    messages = start_checkouts(config, registry, branch, services)
    return tool_result({"branch": branch, "messages": messages})


def tool_uncheckout(arguments: dict[str, Any]) -> dict[str, Any]:
    cwd = cwd_from(arguments)
    config, registry = load_project(cwd)
    branch = branch_for_action(config, registry, string_argument(arguments, "branch"), cwd)
    services = normalize_services(arguments.get("services"))
    messages = stop_checkouts(config, registry, branch, services)
    return tool_result({"branch": branch, "messages": messages})


def tool_down(arguments: dict[str, Any]) -> dict[str, Any]:
    cwd = cwd_from(arguments)
    config, registry = load_project(cwd)
    branch = branch_for_action(config, registry, string_argument(arguments, "branch"), cwd)
    services = normalize_services(arguments.get("services"))
    messages = stop_services(config, registry, branch, services)
    return tool_result({"branch": branch, "messages": messages})


TOOL_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "switchyard_doctor": tool_doctor,
    "switchyard_create": tool_create,
    "switchyard_list": tool_list,
    "switchyard_status": tool_status,
    "switchyard_brief": tool_brief,
    "switchyard_where": tool_where,
    "switchyard_logs": tool_logs,
    "switchyard_up": tool_up,
    "switchyard_checkout": tool_checkout,
    "switchyard_uncheckout": tool_uncheckout,
    "switchyard_down": tool_down,
}


def response(message_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def error_response(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    message_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        requested = str(message.get("params", {}).get("protocolVersion") or PROTOCOL_VERSION)
        negotiated = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        return response(
            message_id,
            {
                "protocolVersion": negotiated,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "switchyard", "title": "Switchyard", "version": __version__},
                "instructions": INSTRUCTIONS,
            },
        )
    if method == "ping":
        return response(message_id, {})
    if method == "tools/list":
        return response(message_id, {"tools": [{"name": name, **definition} for name, definition in TOOLS.items()]})
    if method == "tools/call":
        params = message.get("params", {})
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return error_response(message_id, -32602, "arguments must be an object")
        handler = TOOL_HANDLERS.get(str(name))
        if not handler:
            return error_response(message_id, -32602, f"unknown tool: {name}")
        try:
            return response(message_id, handler(arguments))
        except McpError as exc:
            return response(message_id, tool_result({"error": exc.message}, exc.message, is_error=True))
        except Exception as exc:
            return response(message_id, tool_result({"error": str(exc)}, str(exc), is_error=True))
    return error_response(message_id, -32601, f"method not found: {method}")


def serve_mcp(root: Path | None = None) -> int:
    set_server_root(root or Path.cwd())
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("message must be an object")
            result = handle_request(message)
        except json.JSONDecodeError as exc:
            result = error_response(None, -32700, f"parse error: {exc}")
        except Exception as exc:
            result = error_response(None, -32603, str(exc))
        if result is not None:
            print(json.dumps(result, separators=(",", ":")), flush=True)
    return 0
