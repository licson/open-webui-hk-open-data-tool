# Proposal: add-test-suite

## Why

The repo ships a ~5k-line single-file Open WebUI tool with zero automated tests; every change is verified only by `python3 -m py_compile`, so regressions in the HTTP client contract, transit DB indexing, ETA normalization, trip planner, and the 31 public tools go undetected until runtime inside Open WebUI.

## What Changes

- Add an offline-first pytest suite (`tests/`, ~250 tests, 11 test modules) covering: pure module helpers, `HTTPClient` (caching/retry/error contract), the five department clients (HKO, LandsD, EPD, HA, ALS/DPO), `TransitDB` (index building, DB load path incl. fallbacks, GTFS ferry merge, all 9 ETA fetchers, `leg_next_departures` dispatch), `TripPlanner` (pure cost helpers + `plan()` on seeded mini-graphs), and all 31 public `Tools` methods including error paths.
- Add `tests/conftest.py` backbone: importlib loader for the hyphenated module, an `httpx.MockTransport`-based router covering the module's three HTTP paths (shared client, ALS direct client, GTFS ad-hoc client), seeded transit fixtures, module-state hygiene, and a status-event recorder.
- Add a version-sync regression test (manifest `version:` == User-Agent == `Tools.meta()`).
- Add an opt-in live-network smoke set (`@pytest.mark.live`, deselected by default).
- Add root `pytest.ini` (asyncio auto mode, `live` marker, strict markers) and document the new dev workflow (`pip install freezegun`, `python3 -m pytest`) in README and AGENTS.md.
- New dev dependency: `freezegun` (pytest + pytest-asyncio already present in env). No changes to `hk-open-data-tool.py` itself.

## Capabilities

### New Capabilities
- `test-infrastructure`: pytest scaffolding — module loading, HTTP mocking via `httpx.MockTransport` across all three HTTP paths, cache/transit fixtures, module-state hygiene, and runner configuration.
- `unit-coverage`: tests for pure/sync helpers, `HTTPClient` contract, client-side normalizers, `TransitDB` indexing and ETA fetchers, and `TripPlanner` cost helpers.
- `tool-coverage`: tests for all 31 public `hko_/landsd_/epd_/ha_/dpo_/td_` tool methods over mocked endpoints and seeded transit data, including error paths and event emission.
- `live-smoke`: opt-in real-network smoke tests, one call per client, deselected by default.

### Modified Capabilities

(none — no spec-level behavior of the tool module changes)

## Impact

- New files only: `pytest.ini`, `tests/**`, plus doc updates (README, AGENTS.md) and `.gitignore` entry for `.pytest_cache/`.
- Dev dependencies: freezegun (new), pytest/pytest-asyncio (already installed).
- `hk-open-data-tool.py` is NOT modified; the suite works entirely through existing seams (pre-set `_client`, disk-cache seeding, `projected_dt` args).
