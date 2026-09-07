## MODIFIED Requirements

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
