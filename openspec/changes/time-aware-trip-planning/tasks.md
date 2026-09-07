## 1. Time resolution foundation

- [x] 1.1 Add `_resolve_clock_time(value, *, future_only, now_hk)` module helper in the helpers section: ISO-8601 `YYYY-MM-DD[T ]HH:MM[:SS][±HH:MM|Z]` or bare `HH:MM[:SS]`, naive → `HK_TZ`, bare clocks → next occurrence (roll to tomorrow when past), `None` return for unparseable input
- [x] 1.2 Add `plan_arrival_buffer_min` valve (default 5) to the base `Valves` model near the other planner knobs
- [x] 1.3 Add parse-table tests in `tests/test_unit_helpers.py`: naive ISO → +08:00, explicit offsets honored, bare clock today vs rolled-to-tomorrow, invalid strings, past-`arrive_at`/past-`start_at` handling via the tool layer contract
- [x] 1.4 Run suite; commit

## 2. Planner reference anchoring

- [x] 2.1 Extend `TripPlanner.plan` with tz-aware `start_at`/`arrive_at` params; compute the reference clock (`start_at` or now) and project `is_leg_active` schedule checks from `reference + board_time_minutes` (replaces `datetime.now(HK_TZ)` at hk-open-data-tool.py:2682)
- [x] 2.2 Make validation policy reference-conditional: ≈ now keeps the current bus-company policy with live-ETA rescue; future reference checks frequency-carrying legs of any company at projected board times with no rescue
- [x] 2.3 Make the first-leg live-ETA substitution (hk-open-data-tool.py:2887–2891) conditional on that itinerary's effective departure being ≈ now (≤ 2 min); future departures keep the modeled wait and empty `next_departures`
- [x] 2.4 Add planner tests: frozen clock + future `start_at` (no ETA fetch, anchored validation), leave-now path unchanged
- [x] 2.5 Run suite; commit

## 3. Arrival-target solve and timing output

- [ ] 3.1 Implement the per-itinerary departure derivation in `plan()`: `max(earliest_ref, arrive_at - plan_arrival_buffer_min - duration)`, offline freq re-check at the derived departure, one retry 30 min earlier bounded by `earliest_ref`, drop on second failure; count passes in `diagnostics.departure_solve_passes`
- [ ] 3.2 Add `{"error": "time_conflict"}` when `earliest_ref >= arrive_at`; add `summary.departure`/`summary.arrival` (ISO-8601 +08:00) and `arrival_status` (`at_target`/`overrun`) when a reference/target is in play; add the top-level `timing` echo (`mode`, resolved times, timezone); verify untimed calls produce byte-identical output shape
- [ ] 3.3 Add planner tests for arrive-by and window modes on a seeded freq-carrying (ferry-shaped) route: derived departure lands inside target, wide window departs at `start_at`, tight window → `overrun` (not an error), off-schedule shift-earlier and drop cases, `time_conflict`
- [ ] 3.4 Run suite; commit

## 4. Tool layer

- [ ] 4.1 Add `start_at`/`arrive_at` params to `td_plan_trip`: resolve via `_resolve_clock_time`, return `bad_time`/`time_conflict` without calling the planner, forward tz-aware datetimes to `plan()`, pass through `timing`-augmented results; update the docstring with accepted formats, enum-free examples (`"arrive_at": "18:30"`, `"start_at": "2026-09-08T07:00"`), and the estimates disclaimer (ferry legs schedule-checked; bus/MTR waits modeled)
- [ ] 4.2 Extend `tests/test_tools_td.py`: valid params forwarded (timing echo + clock fields present), `bad_time` naming the offending param with no planner call, `time_conflict` detail, untimed call output unchanged
- [ ] 4.3 Run suite; commit

## 5. Version bump and verification

- [ ] 5.1 Bump `0.6.0` → `0.7.0` at all three sync spots (manifest line ~9, User-Agent in `HTTPClient._get_client`, `Tools.meta()`) — the version-sync test enforces all three
- [ ] 5.2 Full verification: `python3 -m py_compile hk-open-data-tool.py` and `python3 -m pytest` green (offline suite, live set deselected); commit
- [ ] 5.3 Validate the change (`openspec validate --change time-aware-trip-planning` if available) and update this task list as completed
