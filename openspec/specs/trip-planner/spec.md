# Trip Planner Specification

## Purpose

`TripPlanner.plan` computes door-to-door itineraries over the transit graph: geocodes endpoints via LandsD, walks to/from stops, and runs a Pareto-label A* search over transit legs with mode-aware costs, then validates candidates against schedules and live ETAs.

## Requirements

### Requirement: Endpoint resolution
Origins and destinations SHALL be geocoded via `landsd.location_search`; unresolvable endpoints return `{"error": "location_not_found"}`. Stop candidates are the 25 nearest stops within 800 m, widening to 5 stops within 4 km; if either side has none, `{"error": "no_nearby_stops"}` is returned naming the offending endpoint.

#### Scenario: Ocean coordinates
- **WHEN** the destination resolves far from any stop
- **THEN** the error names the destination

### Requirement: Search semantics
The search SHALL use Pareto labels (walk distance, perceived cost, transfers, mode bitmask) per stop, walk only via transfer edges and never twice consecutively, board any route not just ridden, scan a bounded alight window, and cost legs with mode-specific wait/ride times, transfer penalties (rail→rail 3, bus→bus 10, ferry-involved 6, else 8), and a rail-station walking discount. It SHALL respect `limit` (1–5), `max_transfers` (semantics: boardings, capped by `plan_max_transfers_cap`, default `plan_default_max_transfers`), `plan_max_expansions`, and the `plan_max_runtime_s` wall-clock deadline.

#### Scenario: Direct-only when boardings capped at one
- **WHEN** `max_transfers=1`
- **THEN** every returned itinerary has exactly one leg

### Requirement: Post-search validation
Candidates SHALL be validated after the search (top 80 by perceived cost, stopping at 30 valid) against the plan's reference clock: schedule projections SHALL use `reference + board_time_minutes`. When the reference is ≈ now, bus-company legs (kmb/ctb/nlb/gmb) must be scheduled per frequency data (with route numbers ending in `R` skipped) or rescued by a live ETA, and other modes pass. When the reference is in the future, frequency-carrying legs of any company must be scheduled at their projected board times with no live-ETA rescue. Validation results are cached per (company, route, bound, time bucket).

#### Scenario: Off-schedule leg rescued by live ETA
- **WHEN** a bus leg is outside its frequency window but the ETA API shows an imminent departure
- **THEN** the itinerary remains valid

#### Scenario: Future reference gets no live-ETA rescue
- **WHEN** the reference clock is in the future and a frequency-carrying leg boards outside its window at the projected time
- **THEN** the itinerary is invalid without any ETA API call

### Requirement: Itinerary output
Successful plans SHALL return `origin`/`destination` labels and itineraries sorted by estimated time, each with champion `tags` (fastest, fewest_transfers, least_walking, balanced), a `summary` (transfers, walk_m, time_min_est), legs referencing `route_lite`/`stop_lite` records, and `diagnostics` (expansions, goals_found, goals_valid, deadline_hit, eta_checks). The first leg's modeled wait SHALL be replaced by a live ETA only when that itinerary's effective departure is ≈ now; for future departures the modeled wait is kept and `next_departures` lists are empty. When a time reference is supplied, summaries SHALL additionally carry the `departure`/`arrival` clocks and `arrival_status` defined by the trip-time-planning capability, and `diagnostics` SHALL include `departure_solve_passes` when an arrival target was solved. No feasible route yields `{"error": "no_route_found"}` with diagnostics.

#### Scenario: Champion tags
- **WHEN** multiple itineraries are returned
- **THEN** at least `fastest` is tagged and direct routes are tagged `fewest_transfers`

#### Scenario: Future departure keeps the modeled wait
- **WHEN** an itinerary's effective departure is in the future
- **THEN** its first leg keeps the modeled wait, its legs carry empty `next_departures`, and `summary.time_min_est` is unaffected by live ETAs

### Requirement: Status events
When an event emitter is supplied, the planner SHALL emit `status` events: location resolution, periodic progress, and a terminal `done: true` event.

#### Scenario: Event sequence
- **WHEN** a plan succeeds
- **THEN** the first event reports location resolution and the last is `Done.` with `done: true`

### Requirement: Deterministic schedule checks
`is_operating_now` SHALL interpret hkbus frequency data as day-mask → start → [end, headway] with: service day rolling back before 04:00 HKT, holiday dates following Sunday/holiday masks (64|128), past-midnight window wrapping (+2400), fixed departures padded by 100 minutes, and missing/invalid data treated as operating. Callers may inject `projected_dt` for determinism.

#### Scenario: Pre-04:00 belongs to yesterday's service day
- **WHEN** the projected time is Sunday 02:00 and only Saturday's mask has service
- **THEN** the route is considered operating
