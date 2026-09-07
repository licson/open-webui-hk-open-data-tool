"""Offline tests for the mcp_server reflective adapter.

All egress is mocked via the shared conftest (httpx.MockTransport). Requires
the `mcp` package; a missing install surfaces as a clear ImportError from
mcp_server/__init__.py at collection time.
"""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server.mcpserver import MCPServer

from mcp_server.server import (
    ConfigError,
    _env_flag,
    _maybe_preload,
    build_server,
    make_tools,
    public_tool_methods,
    register_tools,
    resolve_transport,
    valves_from_env,
)


def _new_server() -> MCPServer:
    return MCPServer(name="test")


def _expected_public(mod, tools):
    import re

    rx = re.compile(r"^(hko_|landsd_|epd_|ha_|dpo_|td_)")
    out = set()
    for name in dir(tools):
        if name.startswith("_") or not rx.match(name):
            continue
        if asyncio.iscoroutinefunction(getattr(tools, name)):
            out.add(name)
    return out


# ------------------------------------------------------------------
# 4.1 Registry
# ------------------------------------------------------------------
class TestRegistry:
    def test_registry_equals_tools_class(self, mod, tools):
        expected = _expected_public(mod, tools)
        assert expected
        assert set(public_tool_methods(tools)) == expected
        assert not any(n.startswith("_") for n in expected)

    async def test_registered_names_match_class(self, mod, tools):
        srv = _new_server()
        names = register_tools(srv, tools)
        assert set(names) == _expected_public(mod, tools)
        listed = {t.name for t in await srv.list_tools()}
        assert listed == set(names)

    async def test_registry_tracks_new_tools(self, mod):
        class ToolsWithExtra(mod.Tools):
            async def hko_test_extra_tool(self, q: str = "x") -> dict:
                """An extra tool that must appear automatically."""
                return {"q": q}

        t = ToolsWithExtra()
        srv = _new_server()
        names = register_tools(srv, t)
        assert "hko_test_extra_tool" in names
        listed = {x.name for x in await srv.list_tools()}
        assert "hko_test_extra_tool" in listed

    async def test_no_underscore_names_registered(self, tools):
        srv = _new_server()
        register_tools(srv, tools)
        for t in await srv.list_tools():
            assert not t.name.startswith("_")


# ------------------------------------------------------------------
# 4.2 Schemas & descriptions
# ------------------------------------------------------------------
async def _get_tool(srv: MCPServer, name: str):
    return next(t for t in await srv.list_tools() if t.name == name)


class TestSchemas:
    async def test_literal_becomes_enum_with_default(self, tools):
        srv = _new_server()
        register_tools(srv, tools)
        t = await _get_tool(srv, "hko_weather_forecast")
        props = t.input_schema["properties"]
        assert props["lang"]["enum"] == ["en", "tc", "sc"]
        assert props["lang"]["default"] == "en"
        assert "rhrread" in props["data_type"]["enum"]

    async def test_description_is_verbatim_docstring(self, tools):
        srv = _new_server()
        register_tools(srv, tools)
        t = await _get_tool(srv, "hko_weather_forecast")
        doc_lines = [ln.strip() for ln in (tools.hko_weather_forecast.__doc__ or "").splitlines() if ln.strip()]
        desc = t.description or ""
        for ln in doc_lines:
            assert ln in desc
        assert "Examples" in desc

    async def test_openwebui_plumbing_params_hidden(self, tools):
        srv = _new_server()
        register_tools(srv, tools)
        for name in ("td_departures_nearby", "td_plan_trip"):
            t = await _get_tool(srv, name)
            assert not any(p.startswith("_") for p in t.input_schema["properties"])


# ------------------------------------------------------------------
# 4.3 Error mapping (real tool methods, mocked HTTP)
# ------------------------------------------------------------------
class TestErrorMapping:
    async def test_success_not_flagged(self, mod, mocked_tools, router):
        router.add(r"weather\.php", json={"rhrecord": "ok"})
        srv = _new_server()
        register_tools(srv, mocked_tools)
        out = await srv.call_tool("hko_weather_forecast", {"data_type": "rhrread"})
        assert out.is_error is False
        payload = json.loads(out.content[0].text)
        assert payload["data"] == {"rhrecord": "ok"}

    async def test_error_dict_flags_is_error(self, mocked_tools, router):
        router.add(r"weather\.php", status=500, json={"boom": True})
        srv = _new_server()
        register_tools(srv, mocked_tools)
        out = await srv.call_tool("hko_weather_forecast", {"data_type": "rhrread"})
        assert out.is_error is True
        payload = json.loads(out.content[0].text)
        assert "error" in payload["data"]

    async def test_flat_error_dict_flags_is_error(self, mocked_tools, router):
        router.add(r"lookup\.json", status=429, json={"reason": "rate"})
        srv = _new_server()
        register_tools(srv, mocked_tools)
        out = await srv.call_tool(
            "dpo_address_lookup", {"query": "Queen's Road Central", "limit": 5}
        )
        assert out.is_error is True
        payload = json.loads(out.content[0].text)
        assert "error" in payload


# ------------------------------------------------------------------
# 4.4 Configuration
# ------------------------------------------------------------------
class TestConfig:
    def test_override_applied(self, mod):
        v = valves_from_env(mod, {"HKOD_MCP_ETA_CACHE_TTL_S": "45"})
        assert v.eta_cache_ttl_s == 45

    def test_float_override(self, mod):
        v = valves_from_env(mod, {"HKOD_MCP_PLAN_MAX_RUNTIME_S": "0.5"})
        assert v.plan_max_runtime_s == 0.5

    def test_str_override(self, mod):
        v = valves_from_env(mod, {"HKOD_MCP_CACHE_DIR": "/tmp/opencode/hkod-mcp-test-cache"})
        assert v.cache_dir == "/tmp/opencode/hkod-mcp-test-cache"

    def test_unset_equals_defaults(self, mod):
        assert valves_from_env(mod, {}).model_dump() == mod.Valves().model_dump()

    def test_invalid_int_names_variable(self, mod):
        with pytest.raises(ConfigError) as ei:
            valves_from_env(mod, {"HKOD_MCP_ETA_CACHE_TTL_S": "not-a-number"})
        assert "HKOD_MCP_ETA_CACHE_TTL_S" in str(ei.value)

    def test_pydantic_validation_failure_names_variables(self, mod, monkeypatch):
        class StrictValves(mod.Valves):
            http_retries: int = mod.Field(ge=0)

        monkeypatch.setattr(mod, "Valves", StrictValves)
        with pytest.raises(ConfigError) as ei:
            valves_from_env(mod, {"HKOD_MCP_HTTP_RETRIES": "-5"})
        assert "HKOD_MCP_HTTP_RETRIES" in str(ei.value)

    def test_bool_flag_parsing(self):
        assert _env_flag({"HKOD_MCP_PRELOAD_TRANSIT": "1"}, "PRELOAD_TRANSIT") is True
        assert _env_flag({"HKOD_MCP_PRELOAD_TRANSIT": "0"}, "PRELOAD_TRANSIT") is False
        assert _env_flag({}, "PRELOAD_TRANSIT") is False
        with pytest.raises(ConfigError) as ei:
            _env_flag({"HKOD_MCP_PRELOAD_TRANSIT": "sure"}, "PRELOAD_TRANSIT")
        assert "HKOD_MCP_PRELOAD_TRANSIT" in str(ei.value)


# ------------------------------------------------------------------
# 4.5 Transports, preload, version, missing-SDK
# ------------------------------------------------------------------
class TestTransport:
    def test_stdio_default(self):
        transport, port = resolve_transport({})
        assert transport == "stdio"

    def test_http_transport_and_port(self):
        transport, port = resolve_transport({"HKOD_MCP_TRANSPORT": "http", "HKOD_MCP_PORT": "9000"})
        assert transport == "streamable-http"
        assert port == 9000

    def test_http_default_port(self):
        transport, port = resolve_transport({"HKOD_MCP_TRANSPORT": "http"})
        assert port == 8765

    def test_invalid_transport_rejected(self):
        with pytest.raises(ConfigError) as ei:
            resolve_transport({"HKOD_MCP_TRANSPORT": "ftp"})
        assert "HKOD_MCP_TRANSPORT" in str(ei.value)

    def test_invalid_port_rejected(self):
        with pytest.raises(ConfigError) as ei:
            resolve_transport({"HKOD_MCP_TRANSPORT": "http", "HKOD_MCP_PORT": "abc"})
        assert "HKOD_MCP_PORT" in str(ei.value)


class TestPreload:
    async def test_preload_enabled_calls_ensure_loaded(self):
        loaded = []

        class FakeTransit:
            async def ensure_loaded(self):
                loaded.append(True)

        class FakeTools:
            transit = FakeTransit()

        await _maybe_preload(FakeTools(), {"HKOD_MCP_PRELOAD_TRANSIT": "1"})
        assert loaded == [True]

    async def test_preload_disabled_skips(self):
        loaded = []

        class FakeTransit:
            async def ensure_loaded(self):
                loaded.append(True)

        class FakeTools:
            transit = FakeTransit()

        await _maybe_preload(FakeTools(), {})
        assert loaded == []


class TestVersion:
    def test_version_derived_from_meta(self, mod, tools):
        srv = build_server(mod, tools)
        assert srv.version == tools.meta()["version"] == mod.Tools().meta()["version"]


class TestMissingSdk:
    def test_missing_mcp_gives_clear_error(self):
        base = getattr(sys, "_base_executable", None) or sys.executable
        proc = subprocess.run(
            [base, "-c", "import mcp_server.server"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode != 0
        assert "pip install -r mcp_server/requirements.txt" in (proc.stderr + proc.stdout)


class TestHttpLoopback:
    def test_http_binds_loopback_only(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        env = {
            "HKOD_MCP_TRANSPORT": "http",
            "HKOD_MCP_PORT": str(port),
            "PATH": "/usr/bin:/bin",
        }
        proc = subprocess.Popen(
            [sys.executable, "-m", "mcp_server"],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 20
            up = False
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=1):
                        up = True
                        break
                except OSError:
                    time.sleep(0.25)
            assert up, "HTTP server never came up on 127.0.0.1"

            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect(("8.8.8.8", 80))
                external_ip = probe.getsockname()[0]
            if external_ip != "127.0.0.1":
                with pytest.raises(OSError):
                    socket.create_connection((external_ip, port), timeout=2)
        finally:
            proc.terminate()
            proc.wait(timeout=10)
