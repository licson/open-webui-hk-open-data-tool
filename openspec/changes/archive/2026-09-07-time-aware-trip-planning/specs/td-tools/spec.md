## MODIFIED Requirements

### Requirement: Trip planning passthrough
`td_plan_trip` SHALL forward its arguments to the planner, attach `meta(source="td")` (including DB state), and pass through planner results and errors. It SHALL accept optional `start_at` and `arrive_at` clock strings, resolve them per the trip-time-planning capability, pass timezone-aware datetimes to the planner, return `{"error": "bad_time"}` or `{"error": "time_conflict"}` (naming the offending parameter or times) without calling the planner, and pass through timing-augmented results otherwise.

#### Scenario: td meta
- **WHEN** a plan succeeds
- **THEN** the response meta carries `data_source` and DB cache fields

#### Scenario: Bad time parameter short-circuits
- **WHEN** `td_plan_trip` is called with `start_at="not a time"`
- **THEN** the response is `{"error": "bad_time"}` naming `start_at` and no planner call is made

#### Scenario: Time parameters reach the planner
- **WHEN** `td_plan_trip` is called with valid `start_at` and `arrive_at` strings
- **THEN** the response carries the `timing` echo and per-itinerary clock fields from the planner result
