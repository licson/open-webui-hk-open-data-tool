# Tasks: add-mcp-server

## 1. Environment & scaffold

- [x] 1.1 Create a Python venv (`.venv/`), install `mcp` (pinned minimum version), `httpx`, `pydantic`, `pytest`, `pytest-asyncio`, `freezegun`; record adapter deps in `mcp_server/requirements.txt`
- [x] 1.2 Scaffold `mcp_server/server.py`: importlib-load `hk-open-data-tool.py` from repo root (same technique as `tests/conftest.py`), `main()` entrypoint stub, `python -m mcp_server.server` runnable from repo root
- [x] 1.3 Add `mcp` to the one-time dev-dependencies install line in `AGENTS.md`

## 2. Reflective registry & error mapping

- [x] 2.1 Implement the reflection registry: iterate a `Tools()` instance's public async methods matching `^(hko_|landsd_|epd_|ha_|dpo_|td_)`, register each on FastMCP with the method's verbatim docstring as description
- [x] 2.2 Implement the call wrapper: result dict containing `"error"` → MCP result with `isError: true` + full dict as JSON content; otherwise normal JSON content
- [x] 2.3 Report server version from `Tools().meta()["version"]` (no new constant)

## 3. Configuration & transports

- [x] 3.1 Implement env-var config: build `Valves` overrides from `HKOD_MCP_<FIELD_NAME>` variables by iterating model fields; invalid values abort startup naming the offending variable
- [x] 3.2 Implement stdio default transport
- [x] 3.3 Implement `HKOD_MCP_TRANSPORT=http` + `HKOD_MCP_PORT` (default 8765) serving Streamable HTTP hard-bound to `127.0.0.1`
- [x] 3.4 Implement `HKOD_MCP_PRELOAD_TRANSIT=1` eager `TransitDB.ensure_loaded()` before serving

## 4. Tests (offline, `MockTransport` via existing conftest)

- [x] 4.1 Registry tests: registered names equal the public prefixed async methods of `Tools`; no `_`-prefixed names; count tracks the class
- [x] 4.2 Schema tests: a `Literal` param surfaces as an enum in the generated input schema with default preserved; description equals the verbatim docstring (assert the Examples section is present)
- [x] 4.3 Error-mapping tests: error-dict result → `isError: true`; non-error result → `isError: false` (drive a real tool method under mocked HTTP)
- [x] 4.4 Config tests: `HKOD_MCP_ETA_CACHE_TTL_S=45` applied; unset → defaults; invalid value aborts with the variable name in the error
- [x] 4.5 Transport tests: stdio default opens no socket; HTTP mode binds `127.0.0.1`; a clear error (not a mysterious skip) surfaces when `mcp` is missing

## 5. Docs & verification

- [x] 5.1 Write `mcp_server/README.md`: install (venv), env-var reference table, stdio config snippets for Claude Desktop / opencode / Cursor, HTTP mode usage, preload trade-off note
- [x] 5.2 Verify: `python3 -m py_compile hk-open-data-tool.py mcp_server/server.py` and full `python3 -m pytest` green (offline)
- [x] 5.3 Manual smoke: launch stdio server, issue `tools/list` + one `hko_weather_forecast` call and one error-path call from an MCP client or scripted JSON-RPC
