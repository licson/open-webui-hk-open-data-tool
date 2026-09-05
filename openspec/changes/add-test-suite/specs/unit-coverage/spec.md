# Spec Delta: unit-coverage

## ADDED Requirements

### Requirement: Pure module helpers are table-tested
The suite SHALL table-test every pure/sync module helper: `normalize_text`, `norm_co`, `mode_of_company`, `coerce_float`, `haversine_m`, `parse_iso`, `parse_hk_dt`, `minutes_from_compact_text`, `eta_minutes_from_hhmm` (including midnight wrap), `strip_html`, `cursor_make`/`cursor_parse`, `limit_items`, and `sha256`.

#### Scenario: norm_co normalizes operator aliases
- **WHEN** `norm_co` receives `minibus`, `mtr-bus`, or `lightRail`
- **THEN** it returns `gmb`, `lrtfeeder`, and `lightrail` respectively

#### Scenario: eta_minutes_from_hhmm wraps past midnight
- **WHEN** the HH:MM ETA is earlier than the given HK now time
- **THEN** the returned minutes assume the next day

### Requirement: HTTPClient contract is verified
The suite SHALL verify `HTTPClient.request`: success for GET/POST with json/text expectations; mem-cache hits served without repeat transport calls; TTL expiry (frozen clock) re-fetches; disk-cache write/read and mtime-based expiry; disk write failures tolerated silently; 429/5xx retried with eventual success and error-dict `{"error": "request_failed", ...}` after exhaustion; non-2xx mapped to the error dict; cache keys distinguishing method/params/body; `get_json`/`get_text` returning `None` on error or type mismatch.

#### Scenario: Mem cache prevents duplicate fetch
- **WHEN** the same cached URL is requested twice within TTL
- **THEN** the router records exactly one transport call and both calls return identical data

#### Scenario: Retries exhausted return error dict
- **WHEN** the endpoint returns 500 on every attempt with `http_retries=2`
- **THEN** `request` returns a dict containing `error`, `detail`, `url`, `params`, and `method` keys

### Requirement: Client-side normalizers are table-tested
The suite SHALL table-test `EPDClient._normalize_station_name` / `_translate_health_risk` / `_get_station_info`, `HAClient._normalize_hospital_name`, and `ALSClient._format_address` (EN vs ZH word order) / `_parse_premises` / `_transform_suggestion`.

#### Scenario: Hospital aliases resolve
- **WHEN** `_normalize_hospital_name` receives aliases like `qeh`, `pym`, or a Chinese name
- **THEN** it returns the canonical hospital key

### Requirement: TransitDB indexing and lookups are verified
The suite SHALL verify `_build_indices` outputs (stop-to-routes including skipping non-operator `stops` keys, route/company stop indices and seq maps, stop degree, geo-grid cells, transfer edges ≤800 m with the top-30 cap) plus `stop_lite`/`route_lite` shapes, `stop_distance_to_point`, and `nearby_stop_ids` radius/sort/limit behavior.

#### Scenario: Nearby stops sorted by distance
- **WHEN** `nearby_stop_ids` is called with a radius and limit
- **THEN** only stops within the radius are returned, sorted ascending by distance and capped at the limit

### Requirement: hkbus DB load path and fallbacks are verified
The suite SHALL verify `_load_hkbus_db`/`ensure_loaded` resolution order: fresh disk cache short-circuits; stale disk triggers primary download; primary failure falls back to `hkbus.github.io`; total failure yields stale disk; nothing available raises `RuntimeError`.

#### Scenario: Primary source failure falls back
- **WHEN** `data.hkbus.app` requests fail and the fallback serves the DB
- **THEN** `ensure_loaded` completes and the DB source reflects the fallback

### Requirement: GTFS ferry merge is verified
The suite SHALL exercise `load_and_merge_gtfs_ferries` with in-memory zip fixtures: ferry route_type filtering, agency-to-operator mapping, dedupe against existing hkbus ferry routes, Mon..Sun day-mask encoding, frequencies parsing (optional file tolerated), stop_times ordering, and pier stop injection; and SHALL verify the seeded ferry-cache file path skips downloads.

#### Scenario: Ferry route merged with unified id
- **WHEN** a GTFS zip contains a sunferry route with two piers
- **THEN** the merged route uses the `route_code+1+orig+dest` id format and its stops appear in stop lookups

### Requirement: All nine ETA fetchers are verified
The suite SHALL verify KMB, CTB, GMB, MTR train, LRT, MTR bus, Sunferry, Fortune Ferry, and HKKF fetchers against realistic payloads: normalized row shapes, minutes computation, None-minutes sorted last, and error/shape-mismatch returning `[]`; plus HKKF's digit-only route validation and `leg_next_departures` dispatch for every operator branch (unknown → `[]`).

#### Scenario: ETA fetch error yields empty list
- **WHEN** an ETA endpoint returns the request-failed error dict
- **THEN** the fetcher returns `[]` without raising

### Requirement: TripPlanner pure helpers are verified
The suite SHALL table-test `transfer_penalty` (rail-rail, bus-bus, ferry, default), `mode_times` per mode, `mode_bit`, `walk_cost` rail-station discount branches, and `is_operating_now` with explicit `projected_dt` (day-mask hit/miss, pre-04:00 service-day rollback, holiday bits, midnight wrap, fixed-departure padding, invalid data → True).

#### Scenario: Early-morning uses previous service day
- **WHEN** `projected_dt` is 02:00 HKT and the freq day-mask covers only the previous weekday
- **THEN** `is_operating_now` returns True
