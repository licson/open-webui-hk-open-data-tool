# MCP Server Specification (delta)

## ADDED Requirements

### Requirement: Reflective tool registry
The MCP server SHALL expose exactly the public tool methods of `Tools` — every `async` method whose name matches `^(hko_|landsd_|epd_|ha_|dpo_|td_)` — and SHALL NOT expose internal helpers (names starting with `_`). The registry SHALL be derived by introspection at server startup so that adding a public method to `Tools` automatically adds it to the MCP tool list with no adapter change.

#### Scenario: Registry tracks Tools automatically
- **WHEN** the server builds its tool registry from a `Tools` instance
- **THEN** the registered tool names equal the set of public prefixed async methods, and no name begins with `_`

#### Scenario: Tool schemas preserve parameter semantics
- **WHEN** a tool with `Literal`-typed parameters (e.g. `lang: Literal["en","tc","sc"]`) is registered
- **THEN** the generated input schema expresses those parameters as enum-constrained, with defaults preserved

### Requirement: Verbatim docstring descriptions
Tool descriptions SHALL be the method docstrings delivered verbatim, preserving parameter notes and example calls, because they are written for LLM consumption.

#### Scenario: Description contains guidance and examples
- **WHEN** `tools/list` returns a tool registered from `hko_weather_forecast`
- **THEN** its description equals the method's docstring, including the `Examples` section

### Requirement: Error dict mapping
A tool result containing the key `"error"` SHALL be returned as an MCP tool result with `isError: true` and the full dict serialized as JSON content, so clients distinguish failures from successful payloads without string-sniffing.

#### Scenario: Upstream failure surfaces as isError
- **WHEN** a called method returns a dict containing `"error"`
- **THEN** the MCP result has `isError: true` and the dict as its content

#### Scenario: Nested error payload flags is_error
- **WHEN** a called method returns the nested surfacing style `{"meta": ..., "data": {"error": "request_failed", ...}}`
- **THEN** the MCP result has `isError: true`

#### Scenario: Success is not flagged
- **WHEN** a called method returns a dict without `"error"`
- **THEN** the MCP result has `isError: false`

### Requirement: Environment variable configuration
Every field of the base `Valves` model SHALL be overridable at server startup via an environment variable named `HKOD_MCP_<FIELD_NAME>` (e.g. `HKOD_MCP_CACHE_DIR`, `HKOD_MCP_ETA_CACHE_TTL_S`). Unset variables fall back to the `Valves` defaults. Invalid values (wrong type or failed validation) SHALL abort startup with an error message naming the offending variable. No configuration SHALL be accepted via CLI flags.

#### Scenario: Override applied
- **WHEN** the server starts with `HKOD_MCP_ETA_CACHE_TTL_S=45`
- **THEN** the constructed `Valves` has `eta_cache_ttl_s == 45`

#### Scenario: Default when unset
- **WHEN** the server starts with no `HKOD_MCP_*` variables set
- **THEN** `Valves` equals the model defaults

#### Scenario: Invalid value fails loudly
- **WHEN** the server starts with `HKOD_MCP_ETA_CACHE_TTL_S=not-a-number`
- **THEN** startup aborts and the error message includes `HKOD_MCP_ETA_CACHE_TTL_S`

### Requirement: Loopback-only HTTP transport
The server SHALL default to the stdio transport. When `HKOD_MCP_TRANSPORT=http`, it SHALL serve Streamable HTTP bound to `127.0.0.1` only (port via `HKOD_MCP_PORT`, default 8765). The server MUST NOT bind a non-loopback interface in any configuration, because it provides no authentication.

#### Scenario: stdio default
- **WHEN** the server starts with `HKOD_MCP_TRANSPORT` unset
- **THEN** it serves over stdio and opens no listening socket

#### Scenario: HTTP binds loopback only
- **WHEN** the server starts with `HKOD_MCP_TRANSPORT=http`
- **THEN** the listening socket address is `127.0.0.1`

### Requirement: Optional TransitDB preload
When `HKOD_MCP_PRELOAD_TRANSIT=1`, the server SHALL load the transit database at startup before serving; when unset, loading SHALL remain lazy on first `td_*` call, preserving current behavior.

#### Scenario: Preload enabled
- **WHEN** the server starts with `HKOD_MCP_PRELOAD_TRANSIT=1`
- **THEN** `TransitDB.ensure_loaded()` completes before the server accepts requests

### Requirement: Derived version reporting
The server SHALL report the tool version sourced from `Tools().meta()["version"]` rather than a separately maintained constant, so no fourth version-sync spot exists.

#### Scenario: Version matches Tools.meta
- **WHEN** the server reports its version (e.g. in server metadata or `--version`-style introspection)
- **THEN** it equals `Tools().meta()["version"]`
