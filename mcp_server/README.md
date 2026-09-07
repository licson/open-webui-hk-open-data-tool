# HK Open Data — MCP Server

A thin reflective MCP adapter over [`../hk-open-data-tool.py`](../hk-open-data-tool.py). It
exposes the module's 30 public tool methods (`hko_`, `landsd_`, `epd_`, `ha_`, `dpo_`, `td_`
prefixes) to any MCP client. The tool list is derived from the `Tools` class by reflection, so
the MCP surface always matches the module — new tools appear automatically.

The server is for **local use** (stdio by default, or loopback-only HTTP). It has no
authentication and will never bind a public interface.

## Install

```bash
python3 -m venv .venv            # repo root
.venv/bin/pip install -r mcp_server/requirements.txt
```

## Run

```bash
# stdio (default)
.venv/bin/python -m mcp_server

# Streamable HTTP on 127.0.0.1:8765 (port via HKOD_MCP_PORT)
HKOD_MCP_TRANSPORT=http .venv/bin/python -m mcp_server

# Eagerly load the transit DB at startup instead of on the first td_* call
HKOD_MCP_PRELOAD_TRANSIT=1 .venv/bin/python -m mcp_server
```

The first `td_*` call lazy-downloads the hkbus transit database (~large, cached on disk);
set `HKOD_MCP_PRELOAD_TRANSIT=1` if you prefer paying that cost at launch.

## Client configuration

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "hk-open-data": {
      "command": "/abs/path/to/repo/.venv/bin/python",
      "args": ["-m", "mcp_server"],
      "cwd": "/abs/path/to/repo",
      "env": {}
    }
  }
}
```

opencode (`opencode.json`):

```json
{
  "mcp": {
    "hk-open-data": {
      "type": "local",
      "command": ["/abs/path/to/repo/.venv/bin/python", "-m", "mcp_server"],
      "cwd": "/abs/path/to/repo",
      "enabled": true
    }
  }
}
```

HTTP mode (point the client at `http://127.0.0.1:8765/mcp`):

```json
{
  "mcpServers": {
    "hk-open-data": {
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

## Configuration reference

Every field of the module's `Valves` model is overridable via `HKOD_MCP_<FIELD_NAME>`
(invalid values abort startup with the variable named). Common ones:

| Env var | Default | Meaning |
|---|---|---|
| `HKOD_MCP_CACHE_DIR` | `$TMPDIR/hk_open_data_cache` | Disk cache location |
| `HKOD_MCP_CACHE_TTL_S` | `86400` | General cache TTL (seconds) |
| `HKOD_MCP_ETA_CACHE_TTL_S` | `20` | ETA cache TTL (seconds) |
| `HKOD_MCP_MAX_CONCURRENCY` | `8` | Upstream request concurrency cap |
| `HKOD_MCP_HTTP_TIMEOUT_S` | `15` | Upstream HTTP timeout |
| `HKOD_MCP_HTTP_RETRIES` | `2` | Upstream retries |
| `HKOD_MCP_TRANSPORT` | `stdio` | `stdio` or `http` |
| `HKOD_MCP_PORT` | `8765` | HTTP port (HTTP mode only; always binds `127.0.0.1`) |
| `HKOD_MCP_PRELOAD_TRANSIT` | off | `1` loads the transit DB before serving |

## Behavior notes

- Tool descriptions are the methods' docstrings verbatim, including example calls.
- Results are JSON text. A result whose dict carries an `error` (top-level or nested in
  `data`) is returned with `isError: true`.
- The server reports the module's version (single-sourced from `Tools.meta()`).
- Open WebUI status-event plumbing (`__event_emitter__` params) is not exposed over MCP.

## Tests

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -v
```
