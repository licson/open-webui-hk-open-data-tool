# Spec Delta: tool-coverage

## ADDED Requirements

### Requirement: TripPlanner.plan is verified on seeded graphs
The suite SHALL verify `plan()` over seeded mini-graphs with stubbed geocoding: single-leg and transfer itineraries with correct schema (`meta`, `origin`, `destination`, `itineraries` with legs referencing `stop_lite`/`route_lite`, `diagnostics`); error shapes `location_not_found`, `no_nearby_stops`, `no_route_found`; champion tags (`fastest`, `fewest_transfers`, `least_walking`); limit/max-transfer clamping; first-leg live-ETA substitution; and status-event emission via an injected event emitter.

#### Scenario: Single-leg itinerary
- **WHEN** origin and destination both resolve next to one shared route's stops
- **THEN** a one-leg itinerary is returned whose board/alight stops are seeded stops

#### Scenario: Destination not geocodable
- **WHEN** the geocoder stub returns no result for the destination
- **THEN** `plan()` returns `{"error": "location_not_found", ...}` and no itinerary

### Requirement: All 31 public tools are exercised with mocked endpoints
The suite SHALL exercise every public tool method offline: 16 `hko_*`, 2 `landsd_*`, 8 `td_*`, 2 `epd_*`, 1 `ha_*`, 2 `dpo_*` — happy paths asserting response schemas (meta, data/items/suggestions/departures/itineraries) and param plumbing, plus failure paths (request failures surfaced as error dicts, bad inputs as `bad_request`).

#### Scenario: HKO wrapper tools delegate with correct dataset
- **WHEN** `hko_tide_high_low` is called with a station and year
- **THEN** the router observes an opendata request for dataset `HLT` with the given params and the tool returns meta plus data

#### Scenario: Operator filter normalizes aliases
- **WHEN** `td_departures_by_stop` receives `operators=["lightRail"]`
- **THEN** departures are filtered using the normalized operator `lightrail`

### Requirement: hko_opendata validation matrix is covered
The suite SHALL cover `hko_opendata`'s pure validation: year 1800–2100, month 1–12, day 1–31, hour 1–24; parameter hierarchy (month needs year, day needs year+month, hour needs year+month+day); per-dataset rejection of inapplicable params; station whitelist enforcement (case-insensitive) for HHOT/HLT/CLMTEMP/CLMMAXT/CLMMINT/RYES; rformat json/csv; and RYES date normalization including the 01:30 HKT publication cutoff (frozen clock) and the 20190910 floor.

#### Scenario: Hour without full date rejected
- **WHEN** `hko_opendata` is called with `hour=12` but no year/month/day
- **THEN** it returns `{"error": "bad_request", ...}` without any HTTP call

### Requirement: td_* tools are verified over seeded transit data
The suite SHALL verify `td_catalog_status`, `td_stop_search` (query, cursor pagination, empty query), `td_stop_nearby` (place vs wgs84 vs neither, `resolve_failed`), `td_route_get`/`td_route_search` (matching + `route_not_found`), `td_departures_by_stop` (`stop_not_found`, mode/operator filters, ETA-capable routing, dedupe), `td_departures_nearby` (per-stop structure, event emission, error forwarding), and `td_plan_trip` passthrough with `meta(source="td")`.

#### Scenario: stop_nearby requires exactly one location input
- **WHEN** `td_stop_nearby` is called with neither `place_name` nor `wgs84`
- **THEN** it returns `{"error": "bad_request"}`

### Requirement: LandsD/EPD/HA/DPO tools are verified with mocked payloads
The suite SHALL verify `landsd_location_search` (schema, limit cap), `landsd_search_nearby` (success, transform-failure error shape, HTML stripping), `epd_aqhi_current` (fuzzy station, type_filter, roadside inference, aqhi-descending sort, city summary), `epd_aqhi_forecast` (type filter, A.M.-first sort), `ha_aed_waiting_time` (hospital alias, triage filters t1–t5/all, `"2.5 hours"`-style parsing, T3-median sort), `dpo_address_lookup` (param plumbing, error passthrough), and `dpo_geoaddress_lookup` (19-char validation, happy path).

#### Scenario: AED waiting time parses hour-based durations
- **WHEN** HA payload contains `"2.5 hours"` for a t3 median
- **THEN** the tool's ordering follows the parsed 150 minutes

### Requirement: Version consistency is regression-tested
The suite SHALL assert the version string agrees across the manifest header, the `HTTPClient` User-Agent, and `Tools.meta()` (via source inspection), matching the repo's version-sync convention.

#### Scenario: Version bump stays in sync
- **WHEN** any of the three version occurrences is changed in isolation
- **THEN** the version-sync test fails
