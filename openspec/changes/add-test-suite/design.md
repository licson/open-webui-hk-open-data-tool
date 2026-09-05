# Design: add-test-suite

## Context

`hk-open-data-tool.py` (5,136 lines, v0.6.0) is a single-file Open WebUI tool wrapping HKO, LandsD, EPD, HA, ALS/DPO and a transit layer (hkbus DB + GTFS ferries) with an A* trip planner. There is no test infrastructure; verification is `py_compile` only. The module has three distinct HTTP paths, several wall-clock dependencies, one module-level mutable global (`COMPANY_MODE`), and a hyphenated filename that prevents a normal `import`.

Runtime env: Python 3.12, httpx 0.28.1, pydantic 2.13.4, pytest 9.1.1, pytest-asyncio 1.4.0 installed; freezegun missing (to be installed).

## Goals / Non-Goals

**Goals:**
- Fully offline, deterministic pytest suite (~250 tests) covering pure helpers, `HTTPClient`, all five clients, `TransitDB` + GTFS merge + ETA fetchers, `TripPlanner`, and all 30 public tools, including error paths.
- Zero changes to `hk-open-data-tool.py`.
- Opt-in live-network smoke set (`live` marker) deselected by default.

**Non-Goals:**
- Refactoring the module for testability (e.g., extracting nested functions like `_normalize_ryes_date`, `extract_minutes`).
- Coverage targets or CI pipelines.
- Performance/load testing.

## Decisions

1. **HTTP mocking: `httpx.MockTransport` only (no respx).**
   The repo has no package manager; pytest/pytest-asyncio already exist in the env. A tiny in-conftest `Router` (URL-pattern registry → `httpx.Response`/`Exception`, with per-route call counts) wrapped in `MockTransport` covers all needs. The three HTTP paths are handled as:
   - shared `HTTPClient`: pre-set `tools.http._client = httpx.AsyncClient(transport=...)` before first use (bypasses lazy `_get_client`);
   - ALS direct `http._get_client().get()`: covered by the same pre-set client;
   - GTFS ad-hoc `httpx.AsyncClient(...)`: monkeypatch the module's `httpx.AsyncClient` constructor to inject the transport.
   *Alternative*: respx intercepts globally with less code but adds a dependency the runtime env lacks.

2. **Time control: freezegun + explicit args.**
   `eta_minutes`, mem-cache TTL, RYES 01:30 HKT cutoff, `meta()["ts"]` and the planner wall-clock deadline read the real clock. freezegun handles these; where the code already accepts injected time (`projected_dt` for `is_operating_now`, `now_hk` for `eta_minutes_from_hhmm`, fixture `generated_timestamp` for ferries) tests pass explicit values. Disk-cache TTL uses `os.utime` aging instead of freezing (mtime-based).
   *Alternative*: monkeypatch `now_s` everywhere — brittle against the several distinct clock call sites.

3. **Module loading: `importlib.util.spec_from_file_location`.**
   The filename contains hyphens. A session-scoped `mod` fixture loads it once under the name `hkodt`.

4. **Transit seeding: two layers.**
   - `seed_transit_files()`: writes fresh-mtime `routeFareList.min.json`, `.md5`, and `hk_gtfs_ferries_cache_v9.json` into a tmp `cache_dir` so `ensure_loaded()` runs fully offline (source `"disk"`, ferry merge from cache).
   - `build_transit(db_dict)`: constructs a `TransitDB` and drives `_build_indices` directly with a minimal hkbus-shaped dict (stops/routes/holidays) for graph-level tests; routes without `freq` keep `is_leg_active` off the network.

5. **State hygiene: autouse fixtures.**
   `Tools.__init__` mkdirs `cache_dir` → every test gets a tmp `cache_dir` with `http_retries=0`, `http_timeout_s=1`. `COMPANY_MODE` (mutated by `_inject_ferry_data_to_memory`) is snapshotted/restored per test. Mocked transports are `aclose()`d on teardown.

6. **Planner determinism: tiny graphs + frozen clock.**
   `plan()` has a wall-clock deadline (`plan_max_runtime_s`, default 20 s) — fixtures use ~10-stop graphs so the search finishes in milliseconds; freezegun pins the clock so `deadline_hit` diagnostics stay stable. `landsd.location_search` is stubbed (monkeypatch) for geocoding.

7. **GTFS zip fixtures built in code** via `zipfile` into `BytesIO` (routes/trips/calendar/frequencies/stop_times/stops as CSV text) so the ferry-merge parser is exercised end-to-end without binary fixtures in git.

## Risks / Trade-offs

- [MockTransport bypasses `_get_client()`'s User-Agent header] → assert User-Agent only via source inspection in the version-sync test, not via mock headers.
- [freezegun + pytest-asyncio can conflict on event-loop time] → freeze only within specific tests, never session-wide; async fixture loop scope pinned to `function`.
- [Fixtures can drift from live API shapes] → payloads copied from each API's documented schema; live smoke set exists precisely to catch drift.
- [Planner search-space behavior may change as the module evolves] → planner tests assert structural contracts (error shapes, itinerary schema, champion tags, event sequence), not exact costs.
- [Pre-existing uncommitted module edits in the working tree] → suite targets the working tree; tests avoid asserting on lines known to be in flux (`is_operating_now` tested only via its public contract).
