# TD Tools Specification

## Purpose

The eight public `td_*` tools exposing the transit layer to LLMs: DB status, stop search/nearby, route lookup/search, departures by stop and nearby, and trip planning — all returning compact, curated responses over the lazily loaded TransitDB.

## Requirements

### Requirement: Lazy loading
Every `td_*` tool SHALL ensure the transit DB is loaded (network on first call, disk cache thereafter) before answering.

#### Scenario: First call loads the DB
- **WHEN** a fresh Tools instance serves its first td_* request
- **THEN** the hkbus DB is fetched or read from cache before the response is built

### Requirement: Catalog status
`td_catalog_status` SHALL report the DB source/md5 state and the operators and modes present.

#### Scenario: Seeded graph
- **WHEN** the DB contains kmb/mtr/gmb/lightrail routes
- **THEN** those operators and their modes are listed

### Requirement: Stop and route search
`td_stop_search` SHALL match normalized EN/ZH stop names and `td_route_search` route numbers/origins/destinations, both with limit clamping (≤50) and cursor pagination (`q:{offset}`); empty queries return empty results. `td_route_get` returns the route or `route_not_found`.

#### Scenario: Cursor pagination
- **WHEN** a search returns more hits than the limit
- **THEN** a `next_cursor` continues at the next offset without overlap

### Requirement: Stop nearby resolution
`td_stop_nearby` SHALL accept exactly one of `place_name` (resolved via LandsD search) or `wgs84`; neither yields `bad_request`, unresolvable places yield `resolve_failed`. `radius_m` floors at 50; results carry `distance_m`.

#### Scenario: Neither input
- **WHEN** called without place or coordinates
- **THEN** `{"error": "bad_request"}` is returned

### Requirement: Departures by stop
`td_departures_by_stop` SHALL return `stop_not_found` for unknown stops, normalize `operators` (e.g. `lightRail` → `lightrail`) and lowercase `modes`, fetch ETAs only for the ETA-capable set (kmb, ctb, gmb, mtr, lightrail, lrtfeeder, sunferry, hkkf, fortuneferry), call MTR per line and LRT once per station, fan out remaining services under a `max_concurrency` semaphore, dedupe by (route_id, company), and clamp `limit_routes` (≤20) / `limit_etas_per_route` (≤4).

#### Scenario: Operator alias normalization
- **WHEN** `operators=["lightRail"]` at a Light Rail stop
- **THEN** lightrail departures are returned

#### Scenario: ETA endpoint failure
- **WHEN** ETA APIs fail for every service at a stop
- **THEN** the tool still returns the stop with an empty departures list

### Requirement: Departures nearby
`td_departures_nearby` SHALL reuse stop resolution, fetch departures per nearby stop concurrently, forward resolution errors, and emit status events (start and `Done.`).

#### Scenario: Events emitted
- **WHEN** called with an event emitter
- **THEN** a start event and a terminal `done: true` event are recorded

### Requirement: Trip planning passthrough
`td_plan_trip` SHALL forward its arguments to the planner, attach `meta(source="td")` (including DB state), and pass through planner results and errors.

#### Scenario: td meta
- **WHEN** a plan succeeds
- **THEN** the response meta carries `data_source` and DB cache fields
