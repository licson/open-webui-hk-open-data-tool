# Tasks: add-test-suite

## 1. Scaffolding

- [x] 1.1 Install freezegun; add root `pytest.ini` (asyncio auto mode, function loop scope, strict markers, `live` marker, `-m "not live"` addopts, testpaths=tests)
- [x] 1.2 Create `tests/conftest.py`: importlib module loader, Router/MockTransport injection for shared+ALS clients and GTFS ad-hoc client, `make_valves`/`tools` fixtures (tmp cache_dir, retries=0), COMPANY_MODE snapshot autouse fixture, emitter recorder, transit fixture builders (`seed_transit_files`, `build_transit`, `stop()`/`route()` helpers)
- [x] 1.3 Create `tests/test_smoke_version.py` (import, Tools() constructs, meta() shape, version-sync across manifest/UA/meta) and run the suite green
- [x] 1.4 Add `.pytest_cache/` to `.gitignore` if absent; commit scaffolding

## 2. Unit helpers + HTTP client

- [x] 2.1 Create `tests/test_unit_helpers.py`: table tests for all pure module helpers incl. freezegun-based `eta_minutes` cases
- [x] 2.2 Create `tests/test_http_client.py`: GET/POST success, mem cache hit/TTL expiry, disk cache round-trip + mtime expiry + write-failure tolerance, 429/5xx retry-then-success, exhausted retries error-dict shape, 4xx error dict, cache-key discrimination, get_json/get_text None-on-error
- [x] 2.3 Run suite; commit

## 3. TransitDB + TripPlanner

- [x] 3.1 Create `tests/test_transit_db.py` indices/lookups section: `_build_indices` outputs (non-operator key skip, degree, grid, transfer edges + cap), stop_lite/route_lite/nearby_stop_ids
- [x] 3.2 Add DB load-path tests: disk-fresh short-circuit, stale→primary, primary-fail→fallback, stale-disk fallback, RuntimeError when nothing available
- [x] 3.3 Add GTFS ferry merge tests with in-memory zips (route_type filter, agency map, dedupe, day-mask, frequencies optional, stop_times order, resolve_route_code tables, unified id) + seeded ferry cache path
- [x] 3.4 Add ETA fetcher tests for all 9 providers + `leg_next_departures` dispatch branches
- [x] 3.5 Create `tests/test_trip_planner.py`: pure helper tables (transfer_penalty, mode_times, mode_bit, walk_cost, is_operating_now with projected_dt)
- [x] 3.6 Add plan() tests on seeded mini-graphs (single-leg, transfer, error shapes, clamps, champions, first-leg ETA substitution, events, diagnostics)
- [x] 3.7 Run suite; commit

## 4. Tool-layer coverage

- [x] 4.1 Create `tests/test_tools_td.py`: all 8 td_* tools over seeded Tools incl. filters, pagination, error paths, concurrency fan-out, meta(source="td")
- [x] 4.2 Create `tests/test_tools_hko.py`: hko_opendata validation matrix + RYES cutoff/floor with freezegun; wrapper delegation for all 15 other hko_* tools; rhr alias; lunardate regex; request-failure passthrough
- [x] 4.3 Create `tests/test_clients_epd_ha_als.py`: normalizer tables + mocked fetches + ALS error mapping (400/413/429/406, geoaddress length rule)
- [x] 4.4 Create `tests/test_tools_landsd_epd_ha_dpo.py`: tool-layer wrappers, transform failure, HTML stripping, filters, sorting
- [x] 4.5 Run suite; commit

## 5. Live smoke + docs

- [x] 5.1 Create `tests/test_live_smoke.py` (live-marked, structural asserts, skip on no network); verify default run deselects them and `-m live` selects them
- [x] 5.2 Update README (dev/testing section) and AGENTS.md (verify-a-change section) with test commands and dev deps
- [x] 5.3 Full `python3 -m pytest` green run + `python3 -m py_compile hk-open-data-tool.py`; commit docs
- [x] 5.4 Validate OpenSpec change (`openspec validate --change add-test-suite` if available) and update this task list as completed
