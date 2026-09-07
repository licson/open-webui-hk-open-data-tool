## ADDED Requirements

### Requirement: Time input resolution
`td_plan_trip` SHALL accept optional `start_at` and `arrive_at` clock strings and resolve them with a single helper: ISO-8601 `YYYY-MM-DD[T ]HH:MM[:SS][±HH:MM|Z]` or bare `HH:MM[:SS]`. Naive values SHALL be assumed Hong Kong time (`UTC+08:00`); bare clocks SHALL resolve to the next occurrence of that time (rolling to tomorrow when already past). A past `start_at` SHALL clamp to now; an unparseable value or a past `arrive_at` SHALL return `{"error": "bad_time"}` naming the offending parameter. When both resolve and the (clamped) `start_at` is not before `arrive_at`, the call SHALL return `{"error": "time_conflict"}`.

#### Scenario: Bare clock resolves to next occurrence
- **WHEN** `arrive_at="18:30"` is passed at 17:00 HKT today
- **THEN** it is interpreted as today 18:30 HKT and echoed as an ISO-8601 +08:00 time in the response

#### Scenario: Past bare clock rolls to tomorrow
- **WHEN** `start_at="09:00"` is passed at 23:00 HKT
- **THEN** it is interpreted as tomorrow 09:00 HKT

#### Scenario: Naive datetime assumed Hong Kong time
- **WHEN** `start_at="2026-09-08T07:00"` is passed with no offset
- **THEN** it is interpreted as 2026-09-08 07:00 +08:00

#### Scenario: Unparseable input
- **WHEN** `start_at="next tuesday"` is passed
- **THEN** the response is `{"error": "bad_time"}` naming `start_at` and no planner call is made

#### Scenario: Past arrival target
- **WHEN** `arrive_at` resolves to a time before now
- **THEN** the response is `{"error": "bad_time"}` naming `arrive_at`

#### Scenario: Past departure clamps to now
- **WHEN** `start_at` resolves to 30 minutes ago
- **THEN** the reference departure is now and the response echoes the clamp

#### Scenario: Conflicting window
- **WHEN** `start_at` resolves after `arrive_at`
- **THEN** the response is `{"error": "time_conflict"}` with both interpreted times in the detail

### Requirement: Departure-time anchoring
When only `start_at` is supplied (depart-by), the planner SHALL use it as the reference clock: schedule projections SHALL use `reference + board_time_minutes` and no leg SHALL board before the reference (board offsets include the origin walk). When the reference is in the future, frequency-carrying legs of any company SHALL be schedule-checked at their projected board times without live-ETA rescue, and first-leg live-ETA substitution SHALL be skipped. When the reference is ≈ now, the leave-now validation and ETA substitution behavior SHALL apply unchanged.

#### Scenario: Future start skips live ETAs
- **WHEN** `start_at` is two hours in the future
- **THEN** no live ETA is substituted for any leg's wait, `next_departures` lists are empty, and each itinerary's `summary.departure` equals the reference

#### Scenario: Off-schedule leg at future reference
- **WHEN** a frequency-carrying ferry leg boards outside its service window at the projected board time
- **THEN** itineraries containing that leg are dropped

### Requirement: Arrival-target solve
When `arrive_at` is supplied (alone or with `start_at`), the planner SHALL derive a per-itinerary departure `max(earliest_ref, arrive_at - buffer - duration)` where `earliest_ref` is `max(now, start_at)` and the buffer defaults to a configurable valve (5 minutes), re-check frequency schedules at the derived departure, retry once 30 minutes earlier (bounded by `earliest_ref`) when a leg is off-schedule, and drop the itinerary when the retry also fails. Each solved itinerary SHALL report `arrival = departure + duration` and `arrival_status` = `at_target` when arrival is at or before `arrive_at`, else `overrun`. `earliest_ref >= arrive_at` SHALL return `{"error": "time_conflict"}`.

#### Scenario: Derived departure lands inside the target
- **WHEN** the fastest itinerary duration is 40 minutes and `arrive_at` is 18:30
- **THEN** its derived departure is 17:45 (18:30 minus the 5-minute buffer) and `arrival_status` is `at_target`

#### Scenario: Wide window delays the departure toward the target
- **WHEN** both `start_at` and `arrive_at` are given and the trip duration is much shorter than the window
- **THEN** the derived departure is later than `start_at` and arrival lands just ahead of `arrive_at` (after the buffer), so the traveller does not arrive unnecessarily early

#### Scenario: Tight window departs at start_at
- **WHEN** the trip duration nearly fills the window (arrive-by derivation would fall before `start_at`)
- **THEN** the derived departure equals `start_at` and can be reported as `overrun` if the modeled arrival still exceeds `arrive_at`

#### Scenario: Tight window is flagged, not failed
- **WHEN** every itinerary's derived arrival exceeds `arrive_at`
- **THEN** the itineraries are still returned with `arrival_status: "overrun"` rather than an error

#### Scenario: Off-schedule leg shifts departure earlier
- **WHEN** a frequency-carrying leg is off-schedule at the derived departure but in service 30 minutes earlier (still at or after `earliest_ref`)
- **THEN** the itinerary is solved with the earlier departure

#### Scenario: Off-schedule at both candidates drops the itinerary
- **WHEN** the retry departure is also off-schedule (or would fall before `earliest_ref`)
- **THEN** the itinerary is dropped from the solved set

### Requirement: Timing output contract
When either time parameter is supplied, the response SHALL include a top-level `timing` echo (`mode` ∈ `leave_now|depart_by|arrive_by|window`, resolved `start_at`/`arrive_at` as ISO-8601 +08:00, timezone) and each itinerary `summary` SHALL carry `departure` and `arrival` ISO-8601 (+08:00) clocks; `arrival_status` SHALL be present whenever `arrive_at` is set. `time_min_est` SHALL remain a duration with unchanged meaning. Diagnostics SHALL include `departure_solve_passes` when an arrival target was solved. Calls without time parameters SHALL return responses with no `timing` block and no clock fields, identical in shape to current output.

#### Scenario: Reference mode is echoed
- **WHEN** `start_at` is supplied alone
- **THEN** `timing.mode` is `depart_by` and the interpreted absolute times are echoed

#### Scenario: Untimed calls are unchanged
- **WHEN** neither time parameter is passed
- **THEN** the response has no `timing` block and itinerary summaries have no `departure`/`arrival`/`arrival_status` keys
