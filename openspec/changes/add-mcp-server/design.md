# Design: add-mcp-server

## Context

`hk-open-data-tool.py` is a single-file Open WebUI tool: a `Tools` class exposing 33 `async` methods (prefixes `hko_/landsd_/epd_/ha_/dpo_/td_`), `Literal` enum parameters, LLM-oriented docstrings with examples, dict returns, and an error-dict convention (`{"error": ...}` instead of raising). A hosted, multi-tenant MCP service was considered and deliberately deferred to a future separate repo (likely a rewrite). This change adds only a thin local MCP adapter in the same repo.

## Goals / Non-Goals

**Goals:**
- Expose every public tool method to MCP clients with zero duplication of the tool surface
- Work with any MCP client via stdio (default); optionally serve Streamable HTTP on loopback for browser-based clients
- Reuse the module's existing conventions (docstrings, error dicts, `Valves` config) unchanged
- Keep the root module byte-identical; preserve the copy-paste Open WebUI story

**Non-Goals:**
- Public/hosted deployment, authN/authZ (OAuth 2.1), rate limiting, multi-tenant isolation — future separate repo
- `td_plan_trip` CPU offload (event-loop blocking is harmless for local single-user use; deferred to the hosted rewrite)
- PyPI packaging; the adapter is run from the repo
- CLI flags for configuration (env-only)

## Decisions

### D1: Reflection registry over `Tools` (vs hand-written tool wrappers)
Introspect a `Tools()` instance; register every `async` method matching `^(hko_|landsd_|epd_|ha_|dpo_|td_)`. Alternative — writing 33 explicit wrapper functions — guarantees drift between surfaces and doubles maintenance. Reflection makes the registry *derived*, so new tools appear automatically and the adapter stays ~200 lines. Internal helpers are excluded by the `_`-prefix convention, which already exists and is spec'd.

### D2: Official `mcp` SDK's server class (vs standalone `fastmcp` package)
Use `mcp.server.mcpserver.MCPServer` from the official SDK (mcp 2.x renamed FastMCP to MCPServer; `mcp>=2.2.0` pinned). It generates input schemas from type hints, so `Literal` params become real JSON Schema enums and defaults carry through. Two PEP 563 realities required adapter care: the module uses `from __future__ import annotations`, so signature annotations are strings the SDK cannot resolve — the wrapper evaluates them eagerly via `typing.get_type_hints`; and the SDK rejects parameters starting with `_`, so Open WebUI plumbing params (`__event_emitter__` on `td_departures_nearby`/`td_plan_trip`) are stripped from the exposed signature (status events are an Open WebUI-only affordance; under MCP those calls simply skip emitting). The standalone `fastmcp` distro adds a third-party release cadence for features (middleware, auth) this change doesn't need.

### D3: Verbatim docstrings as descriptions
Docstrings are already written conversationally for LLMs (params, enum notes, example calls). Trimming them would shrink the `tools/list` payload (~30–50 KB total) but loses exactly the guidance that makes calls correct. Local clients tolerate the size; revisit only if a real client chokes.

### D4: Error dicts → `isError: true`
`HTTPClient.request` returns error dicts by convention, and tools surface them two ways: flat (`{"error": ..., "meta": ...}`, e.g. `dpo_*`) or nested under `data` (`{"meta": ..., "data": {"error": ...}}`, e.g. `hko_*`). The adapter wraps each call: if the result dict contains `"error"` at the top level or inside `data`, return an MCP result with `isError: true` and the full dict as JSON content (the SDK passes pre-built `CallToolResult`s through unchanged). This maps the module's convention onto the protocol's native error channel without touching the module.

### D5: Env-only config, `HKOD_MCP_<FIELD>` (vs CLI flags)
Every base-`Valves` field is overridable via `HKOD_MCP_<FIELD_NAME>` (e.g. `HKOD_MCP_CACHE_DIR`, `HKOD_MCP_ETA_CACHE_TTL_S`); invalid values abort startup naming the variable. Env vars are the standard MCP convention and need no arg-parsing surface. Build the `Valves` dict by iterating model fields — new valves become configurable automatically.

### D6: stdio default; HTTP binds `127.0.0.1` only
`HKOD_MCP_TRANSPORT=http` + `HKOD_MCP_PORT` (default 8765) enables Streamable HTTP. The bind address is hard-coded loopback: the server has no auth, so a non-loopback bind MUST be impossible rather than discouraged. stdio needs no sockets and is what Claude Desktop/opencode expect.

### D7: Version derived from `Tools().meta()["version"]`
The repo enforces a three-spot version sync (header manifest, User-Agent, `meta()`) by test. The adapter reads the version from `meta()` at runtime, introducing no fourth spot to keep in sync.

### D8: Directory named `mcp_server/`; module loaded via importlib
A directory literally named `mcp/` would shadow the `mcp` package import when anything runs from the repo root — so `mcp_server/`. The hyphenated root module is loaded with the same importlib trick `tests/conftest.py` already uses. Optional `HKOD_MCP_PRELOAD_TRANSIT=1` eagerly runs `TransitDB.ensure_loaded()` at startup for clients that prefer paying the load cost at launch instead of on first `td_*` call.

## Risks / Trade-offs

- [FastMCP dynamic-registration API surface] `add_tool`/`Tool.from_function` details vary across SDK versions → pin a minimum `mcp` version in `requirements.txt`; cover registry behavior in tests so breakage is caught offline.
- [33 tools × long docstrings is a heavy `tools/list` payload] Some small-context clients may degrade → accepted for local use (D3); splitting into per-department servers is a future escape hatch, not needed now.
- [SDK not yet installed in dev env] `mcp` must join the dev-dependency install (per `AGENTS.md`); adapter tests must import it — a missing-SDK test failure should be a clear "install mcp" error, not a mysterious skip.
- [Reflection could accidentally expose a future non-tool public coroutine] Any new public async method on `Tools` silently becomes an MCP tool → this is also the feature; the prefix convention plus the class docstring already police this boundary.
- [stdio spawns a fresh process per client session] TransitDB lazy-load means first `td_*` call pays a disk-cache read + parse each session → mitigated by `HKOD_MCP_PRELOAD_TRANSIT=1` for latency-sensitive setups; disk cache avoids re-downloads.

## Migration Plan

Additive only: new directory, new test module, one `AGENTS.md` line. No existing code, spec, or behavior changes; rollback is deleting `mcp_server/` and the test file.

## Open Questions

- None blocking. (HTTP transport is intentionally minimal: no TLS, no origin checks — acceptable because loopback-only.)
