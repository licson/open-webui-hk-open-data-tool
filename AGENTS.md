# AGENTS.md

Single-file Python module `hk-open-data-tool.py` (~5k lines) shipped as an **Open WebUI tool** — it is copy-pasted into Open WebUI's tools menu, not packaged or run standalone. No tests, no CI, no package manager, no `__main__` entrypoint.

## Commits

- Commit after any meaningful unit of work (new tool, bug fix, refactor, docs). Keep changes focused and commit promptly, following the existing convention: short conventional prefixes (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`) with a scope for non-root files (`docs(readme): ...`).

## Verify a change

- Compile check: `python3 -m py_compile hk-open-data-tool.py`
- Test suite: `python3 -m pytest` (offline, fully mocked HTTP; ~350 tests). Requires `pip install --break-system-packages pytest pytest-asyncio freezegun` once (pytest/pytest-asyncio/httpx/pydantic usually already present).
- Opt-in live-network smoke tests: `python3 -m pytest -m live` (deselected by default; skips without network).
- No linters or typecheckers configured. Runtime env is Open WebUI's Python (needs `httpx`, `pydantic` v2 — note `Valves` uses `default_factory`/`Field`, i.e. pydantic v2 style).
- This is real-world proctoring: `from __future__ import annotations` is required for the `Literal[...]`/forward-ref typing under pydantic v2 — keep it.
- Test conventions: `tests/conftest.py` loads the hyphenated module via importlib and mocks ALL egress with `httpx.MockTransport` (never hit real APIs in offline tests); a version-sync test enforces the three-spot version bump — keep it green.

## Architecture (single file, in order)

`Data classes` → `constants/endpoints` → per-department clients (`HKOClient`, `LandsDClient`, `EPDClient`, `HAClient`, `ALSClient`) → shared `HTTPClient` → `Valves` (pydantic config) → `TransitDB` → `TripPlanner` → `Tools` (the class Open WebUI exposes).

## Conventions that matter

- **Public tool naming**: only methods prefixed `hko_`, `landsd_`, `epd_`, `ha_`, `dpo_`, `td_` are exposed to LLMs. Add new tools under the correct department prefix; internal helpers must start with `_`. Every public method needs a conversation-style docstring documenting all params, allowed enums, and an LLM-natural example call.
- **Do not add raw data-dump endpoints** — filter/curate responses to be LLM-friendly (project rule in README).
- **Syncing the version**: bump `version:` in the header manifest (line ~9), the User-Agent in `HTTPClient._get_client`, and `Tools.meta()` — all three currently say `0.6.0`.
- `Tools.Valves(Valves)` inner class is what surfaces knobs in the Open WebUI UI; new config options go in the base `Valves` model.

## Gotchas

- **`HTTPClient.request` returns an error dict** `{"error": "request_failed", ...}` on failure instead of raising. Callers must check `if "error" in result` before trusting data (some tools do; follow this pattern).
- **Caching is explicitly opt-in per request** via `cache_scope="mem"|"disk"|"none"`. `get_json`/`get_text` force `"none"` — for cached fetches route through `request()` with a `cache_ttl_s`. Disk cache lives in `cache_dir` (default `$TMPDIR/hk_open_data_cache`, honored in `.gitignore`).
- **ETAs are cached for only 20s** (`eta_cache_ttl_s`) vs the 24h general cache. Don't lump ETA fetches in with long-TTL data.
- **First `td_*` call lazy-downloads the transit DB** (`routeFareList.min.json`, ~large) from `data.hkbus.app` with `hkbus.github.io` fallback, cached to disk and merged with GTFS ferry data. Needs network on first run; offline runs rely on a stale disk cache. `TransitDB.ensure_loaded()` is the entrypoint.
- No test fixtures exist — validate tool behavior by calling an `async` client method directly under the `Tools` umbrella and inspecting the returned dict.