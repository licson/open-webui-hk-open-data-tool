## Why

`td_plan_trip` can only plan as-if-departing-now: schedule checks project from `datetime.now(HK_TZ)`, the first leg's wait is replaced by a live "right now" ETA, and results are pure durations (`time_min_est`) with no clock times. LLM users cannot ask "what if I leave at 7am tomorrow?" or "when should I leave to arrive by 18:30?" — the two most common real trip-planning questions.

## What Changes

- Add optional `start_at` and `arrive_at` clock-string parameters to `td_plan_trip`.
  - `start_at` = depart no earlier than: the planner's reference clock shifts to it, schedule checks project from it, and nothing boards before it.
  - `arrive_at` = arrive by: a reverse solve derives a departure whose modeled arrival lands at/before the target.
  - Both together = solve the window: earliest departure ≥ `start_at` with arrival ≤ `arrive_at`; best-effort with an explicit `overrun` flag when infeasible (never a hard error).
- New time-input parsing: ISO-8601 or bare `HH:MM[:SS]`, naive values assumed Hong Kong time, bare clocks resolve to their next occurrence; invalid input returns `{"error": "bad_time"}`, a `start_at` beyond `arrive_at` returns `{"error": "time_conflict"}`.
- Time-aware validation: `is_operating_now` projections and first-leg live-ETA substitution become conditional on the reference clock (live ETAs are only meaningful when departing ≈ now).
- Itinerary output gains `departure` / `arrival` ISO-8601 (+08:00) clock estimates and an `arrival_status` (`at_target` / `overrun`) when an arrival target is set; `time_min_est` semantics unchanged. Diagnostics gain `departure_solve_passes`.
- Version bump `0.6.0` → `0.7.0` across the three sync spots (manifest, User-Agent, `Tools.meta()`).
- Offline tests for parsing, anchoring, reverse solve, window solving, error shapes, and passthrough.

Honest-accuracy note (carried into docstrings): only GTFS-ferry routes carry `freq` schedules; bus/MTR waits for future departures remain modeled estimates, so absolute clocks are labeled as estimates.

## Capabilities

### New Capabilities
- `trip-time-planning`: time-reference resolution (accepted formats, HK timezone default, next-occurrence rule, error shapes), reference-anchored schedule validation, reverse departure solve for `arrive_at`, window solving when both parameters are given, and the resulting clock/arrival-status output contract.

### Modified Capabilities
- `td-tools`: the Trip planning passthrough requirement now accepts `start_at`/`arrive_at`, resolves/validates them, passes timezone-aware datetimes to the planner, echoes interpreted times, and passes `bad_time`/`time_conflict` errors through.
- `trip-planner`: post-search validation projections anchor to the plan's reference clock instead of wall-clock now; the first-leg live-ETA substitution only applies when the reference is ≈ now; itinerary summaries gain departure/arrival clocks and `arrival_status`.

## Impact

- Code: `hk-open-data-tool.py` — new `_resolve_clock_time` helper (module helpers section), `TripPlanner.plan` (reference anchoring, ETA policy, reverse solve `_solve_departure`, output clocks), `Tools.td_plan_trip` (params, parsing, passthrough), three-spot version bump.
- Tests: `tests/test_unit_helpers.py` (parse table), `tests/test_trip_planner.py` (anchoring, reverse solve, window, ETA policy), `tests/test_tools_td.py` (param passthrough, error shapes).
- No new dependencies; runtime env unchanged (httpx, pydantic v2).
- Existing behavior preserved: calls without time parameters take the current "leave now" path unchanged.
