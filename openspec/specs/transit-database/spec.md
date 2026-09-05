# Transit Database Specification

## Purpose

`TransitDB` aggregates Hong Kong public transport network data: the hkbus route/stop database (with download fallbacks), GTFS ferry merging, in-memory indices for lookups and walking transfers, and normalized real-time ETA fetchers for nine operators.

## Requirements

### Requirement: DB load resolution order
`ensure_loaded` SHALL resolve the hkbus DB in order: fresh disk cache (within `cache_ttl_s`) → primary source (data.hkbus.app) → fallback (hkbus.github.io) → stale disk cache → `RuntimeError`. Successful downloads SHALL be written to disk with their md5. Loading is lazy, lock-guarded, and runs the GTFS ferry merge before indexing.

#### Scenario: Primary failure falls back
- **WHEN** the primary source errors and the fallback serves the DB
- **THEN** loading completes with the fallback recorded as source

#### Scenario: Nothing available
- **WHEN** no disk cache exists and both sources fail
- **THEN** `ensure_loaded` raises RuntimeError

### Requirement: Index building
`_build_indices` SHALL build stop→route occurrences (skipping `stops` keys that are not declared operators, e.g. bound letters), route/company stop sequences and seq maps, per-stop degree, a 0.004° geo-grid, and walking transfer edges capped at 800 m with a top-30 cap plus up to 12 extra rail/ferry interchange edges. Holidays from the DB SHALL be tracked for schedule checks.

#### Scenario: Non-operator stops key ignored
- **WHEN** a route's `stops` dict carries a bound-letter key alongside real operators
- **THEN** only declared operators are indexed

### Requirement: GTFS ferry merge
`load_and_merge_gtfs_ferries` SHALL download the en/tc GTFS zips (its own HTTP client, 24 h disk cache), filter ferry route types (4/1000/1200), map agencies to hkbus operators, dedupe against existing ferry routes by normalized name fingerprint, derive day-of-week bitmasks, parse optional frequencies, order stops via stop_times, resolve route codes (Sunferry/Fortune Ferry/HKKF tables), merge under unified ids `route_code+1+orig+dest`, inject piers bilingually, and register operators as ferry mode.

#### Scenario: Sunferry route code resolution
- **WHEN** a merged trip runs Central Pier → Cheung Chau Pier under agency nwff
- **THEN** the merged route id starts with `CECC+1+`

#### Scenario: Missing frequencies tolerated
- **WHEN** the GTFS zip has no frequencies.txt
- **THEN** first departures become fixed-departure schedule entries instead

### Requirement: Lightweight lookups
`stop_lite`, `route_lite`, `stop_distance_to_point`, and `nearby_stop_ids` SHALL return compact LLM-friendly records; nearby results SHALL be radius-filtered, distance-sorted, and limit-capped.

#### Scenario: Nearby sorted by distance
- **WHEN** `nearby_stop_ids` is called with a radius and limit
- **THEN** results are ascending by distance within the radius

### Requirement: ETA fetchers
The nine fetchers (KMB, CTB, GMB, MTR train, LRT, MTR bus, Sunferry, Fortune Ferry, HKKF) SHALL normalize API payloads to rows with minutes/iso/text where available, sort None-minutes last via a sentinel, return `[]` on error or shape mismatch, cache via mem scope with short TTLs (ETA TTL for most, 30 s for ferries), apply KMB service-type fallback, treat MTR times as HK-local, compute ferry minutes from HH:MM against the payload timestamp, and require digit-only route ids for HKKF.

#### Scenario: Fetch error yields empty list
- **WHEN** an ETA endpoint fails
- **THEN** the fetcher returns `[]` without raising

### Requirement: leg_next_departures dispatch
`leg_next_departures` SHALL dispatch on the normalized operator to the matching fetcher, reading route number, bound, serviceType, and gtfsId from the route list, emitting the shared departure-row schema (`stop_id`, `route_id`, `route`, `company`, `mode`, `direction`, `service_type_used`, `eta{iso,minutes,text}`, bilingual `remark`, plus `platform`/`dest`/`url` for MTR). Unknown operators and missing prerequisites (e.g. GMB without gtfsId, non-numeric LRT stop) return `[]`.

#### Scenario: GMB without gtfsId
- **WHEN** a gmb route lacks `gtfsId`
- **THEN** no departures are returned
