"""MCP server adapter for hk-open-data-tool.

Thin reflective layer: instantiates the module's `Tools` class, registers
every public prefixed async method as an MCP tool (verbatim docstring as
description), maps error-dict results to `isError`, and configures the
shared `Valves` from `HKOD_MCP_*` environment variables.

Transports: stdio (default); Streamable HTTP hard-bound to 127.0.0.1 when
HKOD_MCP_TRANSPORT=http (port via HKOD_MCP_PORT, default 8765).
"""

from __future__ import annotations

import asyncio
import functools
import importlib.util
import inspect
import json
import os
import re
import sys
import typing
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

try:
    import mcp.types as mcp_types
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The 'mcp' package is required for the MCP server adapter. "
        "Install it with: pip install -r mcp_server/requirements.txt"
    ) from exc

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "hk-open-data-tool.py"
TOOL_PREFIX_RE = re.compile(r"^(hko_|landsd_|epd_|ha_|dpo_|td_)")
ENV_PREFIX = "HKOD_MCP_"
DEFAULT_HTTP_PORT = 8765
LOOPBACK_HOST = "127.0.0.1"
_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}
_VALID_TRANSPORTS = {"stdio", "http", "streamable-http"}


class ConfigError(RuntimeError):
    pass


def load_core_module():
    spec = importlib.util.spec_from_file_location("hkodt", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise ConfigError(f"cannot load module at {MODULE_PATH}")
    m = importlib.util.module_from_spec(spec)
    sys.modules["hkodt"] = m
    spec.loader.exec_module(m)
    return m


def _parse_env_value(raw: str, annotation: Any, env_name: str) -> Any:
    if annotation is bool:
        lowered = raw.strip().lower()
        if lowered in _TRUTHY:
            return True
        if lowered in _FALSY:
            return False
        raise ConfigError(
            f"{env_name}: invalid boolean {raw!r} (expected one of {sorted(_TRUTHY | _FALSY)})"
        )
    if annotation is int:
        try:
            return int(raw)
        except ValueError:
            raise ConfigError(f"{env_name}: invalid integer {raw!r}") from None
    if annotation is float:
        try:
            return float(raw)
        except ValueError:
            raise ConfigError(f"{env_name}: invalid number {raw!r}") from None
    return raw


def valves_from_env(mod, environ: Optional[Mapping[str, str]] = None):
    env = os.environ if environ is None else environ
    overrides: Dict[str, Any] = {}
    for name, field in mod.Valves.model_fields.items():
        env_name = ENV_PREFIX + name.upper()
        if env_name in env:
            annotation = field.annotation
            overrides[name] = _parse_env_value(env[env_name], annotation, env_name)
    try:
        return mod.Valves(**overrides)
    except Exception as exc:
        offenders = ", ".join(
            ENV_PREFIX + k.upper()
            for k in overrides
            if ENV_PREFIX + k.upper() in env
        )
        raise ConfigError(f"invalid HKOD_MCP_* configuration ({offenders}): {exc}") from exc


def make_tools(mod, valves):
    t = mod.Tools()
    t.valves.__dict__.update(valves.__dict__)
    t.http.cache_dir = valves.cache_dir
    mod.safe_mkdir(Path(valves.cache_dir))
    return t


def _wrap_tool_method(method: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(method)
    async def wrapper(*args: Any, **kwargs: Any):
        out = await method(*args, **kwargs)
        text = json.dumps(out, ensure_ascii=False, default=str)
        is_error = isinstance(out, dict) and (
            "error" in out
            or (isinstance(out.get("data"), dict) and "error" in out["data"])
        )
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=text)],
            is_error=is_error,
        )

    try:
        hints = typing.get_type_hints(method)
    except Exception:
        hints = {}
    wrapper.__signature__ = inspect.Signature(
        [
            p.replace(annotation=hints.get(p.name, p.annotation))
            for p in inspect.signature(method).parameters.values()
            if not p.name.startswith("_")
        ]
    )
    return wrapper


def public_tool_methods(tools) -> Dict[str, Callable[..., Any]]:
    found: Dict[str, Callable[..., Any]] = {}
    for name in dir(tools):
        if name.startswith("_") or not TOOL_PREFIX_RE.match(name):
            continue
        attr = getattr(tools, name)
        if asyncio.iscoroutinefunction(attr):
            found[name] = attr
    return found


def register_tools(server, tools) -> list:
    names = []
    for name, method in sorted(public_tool_methods(tools).items()):
        server.add_tool(
            _wrap_tool_method(method),
            name=name,
            description=method.__doc__,
            structured_output=False,
        )
        names.append(name)
    return names


def build_server(mod, tools):
    from mcp.server.mcpserver import MCPServer

    version = tools.meta()["version"]
    server = MCPServer(
        name="hk-open-data",
        title="Hong Kong Open Data",
        version=version,
        instructions=(
            "Hong Kong open-data tools. Tool names are prefixed by department: "
            "hko_ (weather/climate), landsd_ (geocoding), epd_ (air quality), "
            "ha_ (A&E waiting times), dpo_ (address lookup), td_ (transit)."
        ),
    )
    register_tools(server, tools)
    return server


def _env_flag(env: Mapping[str, str], name: str) -> bool:
    raw = env.get(ENV_PREFIX + name, "").strip().lower()
    if raw in _TRUTHY:
        return True
    if raw == "" or raw in _FALSY:
        return False
    raise ConfigError(f"{ENV_PREFIX}{name}: invalid boolean {raw!r}")


async def _maybe_preload(tools, env: Mapping[str, str]) -> None:
    if _env_flag(env, "PRELOAD_TRANSIT"):
        await tools.transit.ensure_loaded()


def resolve_transport(env: Mapping[str, str]) -> tuple:
    transport = env.get(ENV_PREFIX + "TRANSPORT", "stdio").strip().lower() or "stdio"
    if transport not in _VALID_TRANSPORTS:
        raise ConfigError(
            f"{ENV_PREFIX}TRANSPORT: invalid value {transport!r} (expected 'stdio' or 'http')"
        )
    if transport == "http":
        transport = "streamable-http"
    port = DEFAULT_HTTP_PORT
    if transport == "streamable-http":
        raw_port = env.get(ENV_PREFIX + "PORT")
        if raw_port is not None:
            try:
                port = int(raw_port)
            except ValueError:
                raise ConfigError(f"{ENV_PREFIX}PORT: invalid integer {raw_port!r}") from None
    return transport, port


def main(argv: Optional[list] = None) -> int:
    env = os.environ
    try:
        transport, port = resolve_transport(env)
        mod = load_core_module()
        valves = valves_from_env(mod, env)
        tools = make_tools(mod, valves)
        asyncio.run(_maybe_preload(tools, env))
        server = build_server(mod, tools)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=LOOPBACK_HOST, port=port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
