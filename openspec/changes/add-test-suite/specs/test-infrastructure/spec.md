# Spec Delta: test-infrastructure

## ADDED Requirements

### Requirement: Offline pytest scaffolding loads the hyphenated module
The test infrastructure SHALL load `hk-open-data-tool.py` via `importlib.util.spec_from_file_location` under a session-scoped fixture, without renaming the file or packaging it, and SHALL provide a runnable configuration via root `pytest.ini` with asyncio auto mode, strict markers, and a `live` marker deselected by default.

#### Scenario: Module loads and Tools constructs
- **WHEN** the session-scoped module fixture is evaluated and `Tools()` is constructed with a tmp `cache_dir`
- **THEN** the module imports cleanly and `Tools()` exposes `valves`, `http`, and all department client attributes

#### Scenario: Live tests deselected by default
- **WHEN** `python3 -m pytest` is run with no extra flags
- **THEN** tests marked `live` are deselected and all offline tests run

### Requirement: HTTP mocking covers all three HTTP paths
The test infrastructure SHALL intercept all module HTTP egress through `httpx.MockTransport` via a URL-pattern router with per-route call counting, injected (a) by pre-setting the shared `HTTPClient._client`, which also covers ALS's direct client use, and (b) by monkeypatching `httpx.AsyncClient` construction for the GTFS ferry-zip path. No test SHALL perform real network I/O unless marked `live`.

#### Scenario: Shared client requests hit the router
- **WHEN** any tool or client method performs a request through `HTTPClient`
- **THEN** the mock router serves the registered response and increments that route's call count

#### Scenario: GTFS zip download is intercepted
- **WHEN** `load_and_merge_gtfs_ferries` fetches the GTFS zip archives
- **THEN** the monkeypatched transport serves fixture zip bytes and no real connection is attempted

### Requirement: Transit fixtures seed the DB offline
The test infrastructure SHALL provide two seeding paths: (a) writing fresh-mtime `routeFareList.min.json`, its `.md5`, and `hk_gtfs_ferries_cache_v9.json` into a tmp `cache_dir` so `TransitDB.ensure_loaded()` completes with no network; and (b) a direct builder that runs `_build_indices` over a minimal hkbus-shaped dict (stops, routes, holidays).

#### Scenario: ensure_loaded from seeded disk cache
- **WHEN** `ensure_loaded()` runs with pre-seeded cache files
- **THEN** it completes without network access and reports the disk source

#### Scenario: Direct index seeding for graph tests
- **WHEN** the builder is given a stops/routes/holidays dict
- **THEN** lookups (`stop_lite`, `route_lite`, `nearby_stop_ids`) return seeded data

### Requirement: Per-test state hygiene
The infrastructure SHALL isolate module state per test: tmp `cache_dir` with `http_retries=0` and a short timeout, snapshot/restore of the `COMPANY_MODE` global, and teardown of mocked async clients. Clock-sensitive code SHALL be tested with freezegun or explicit injected time arguments.

#### Scenario: COMPANY_MODE mutations do not leak
- **WHEN** a test triggers ferry injection which mutates `COMPANY_MODE`
- **THEN** subsequent tests observe the original mapping
