# add-mcp-server

## Why

The tool surface (30 public `hko_/landsd_/epd_/ha_/dpo_/td_` methods with LLM-oriented docstrings, `Literal` enum params, and dict returns) is an ideal MCP tool set, but it is currently reachable only by copy-pasting the module into Open WebUI. Exposing it as an MCP server makes it usable from any MCP client (Claude Desktop, opencode, Cursor, etc.) without maintaining a second tool surface: the adapter derives the tool registry from `Tools` by reflection, so the two surfaces cannot drift — a new public method appears in MCP automatically.

## What Changes

- New `mcp_server/` directory containing a thin reflective adapter over the existing module:
  - `mcp_server/server.py` — stdio MCP server (official `mcp` SDK's FastMCP) that instantiates `Tools`, reflects all public prefixed async methods, and registers them verbatim
  - `mcp_server/requirements.txt` — adapter-only deps (`mcp`, plus the module's `httpx`/`pydantic`)
  - `mcp_server/README.md` — usage plus client config snippets
- Config: every `Valves` field overridable via `HKOD_MCP_<FIELD>` env vars (env-only; no CLI flags)
- Error contract: tool results containing `{"error": ...}` surface as MCP `isError` results
- Optional Streamable HTTP transport, bound to `127.0.0.1` only (hard rule; the server has no auth and must never bind a public interface)
- Optional eager TransitDB preload at startup via `HKOD_MCP_PRELOAD_TRANSIT=1`
- Version reporting derived from `Tools().meta()["version"]` (no new version-sync spot)
- New offline tests `tests/test_mcp_server.py` reusing the `MockTransport` conftest
- `AGENTS.md`: add `mcp` to the one-time dev-dependencies install line

## Capabilities

### New Capabilities

- `mcp-server`: Reflective MCP adapter exposing the existing public tool methods over stdio (default) and loopback-only Streamable HTTP, with env-var configuration, error-dict-to-isError mapping, and derived version reporting.

### Modified Capabilities

<!-- None: the root module and all existing tool/test behavior are unchanged. -->

## Impact

- **Code**: new `mcp_server/` directory only; root `hk-open-data-tool.py` untouched (copy-paste Open WebUI story preserved)
- **Dependencies**: new dev/runtime dep `mcp` (official SDK) for the adapter and its tests; not added to the root module's Open WebUI `requirements:` header
- **Tests**: new `tests/test_mcp_server.py`; existing suite unaffected
- **Docs**: `mcp_server/README.md`, `AGENTS.md` dev-deps line
- **Out of scope** (deliberate, deferred to a future hosted-service repo rewrite): public deployment, auth/OAuth, rate limiting, multi-tenant concerns, and `td_plan_trip` CPU offload
