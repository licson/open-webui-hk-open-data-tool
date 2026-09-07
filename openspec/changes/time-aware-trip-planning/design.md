## Context

`TripPlanner.plan` (hk-open-data-tool.py:2548) is clock-agnostic: it finds Pareto-optimal paths with modeled durations (`mode_times` waits + walk speed), validates bus-company legs against `freq` schedules projected from `datetime.now(HK_TZ)` (line 2682), and replaces the first leg's modeled wait with a live now-based ETA (2887–2891). Output is pure durations (`summary.time_min_est`). `td_plan_trip` (4508) is a thin passthrough attaching `meta(source="td")`.

Data reality that constrains any time feature:
- Only GTFS-merged ferry routes carry `freq` (`{day_mask: {start_hhmm: [end_hhmm, headway] | None}}`); bus/MTR routes have none, so `is_operating_now` returns True for them and future waits can only be modeled, not scheduled.
- Live ETAs are real-time: meaningless for a departure an hour from now.
- `eta_minutes`, the search deadline, and validation read wall-clock now; the offline test suite controls time with freezegun and injected `projected_dt`.

## Goals / Non-Goals

**Goals:**
- `td_plan_trip(..., start_at=None, arrive_at=None)`: depart-by anchoring, arrive-by reverse solve, and window solving (both params).
- Keep the no-params path byte-identical to today (regression suite stays green unchanged).
- Honest output: per-itinerary departure/arrival clocks (ISO-8601 +08:00), `arrival_status` (`at_target`/`overrun`) when a target is set, and clear `bad_time`/`time_conflict` errors.
- Bounded compute: at most one A* search plus in-memory schedule re-checks; no live-ETA network calls for future references.

**Non-Goals:**
- Full time-dependent routing (per-stop timetables don't exist for bus/MTR in the DB).
- Schedule-derived next-departure waits for `freq`-carrying routes at future times (modeled waits kept; natural follow-up).
- Backward (destination→origin) graph search.
- Changing `preferences`, caching, or any other tool.

## Decisions

1. **Parse at the tool layer, pass datetimes to the planner.**
   New module helper `_resolve_clock_time(value, *, future_only, now_hk)`:
   - Accepts ISO-8601 (`YYYY-MM-DD[T ]HH:MM[:SS][±HH:MM|Z]`) or bare `HH:MM[:SS]`; naive values assume `HK_TZ`.
   - Bare clocks resolve to the next occurrence (rolls past midnight to tomorrow).
   - Past `start_at` clamps to now (echoed); past `arrive_at` → `bad_time`; unparseable → `bad_time` with `param` name.
   - `td_plan_trip` resolves strings and passes tz-aware datetimes into `plan(..., start_at=, arrive_at=)`. Planner stays string-free and unit-testable via injected datetimes.
   *Alternative*: parse inside the planner — rejected: couples LLM string handling into the search layer and complicates freezegun tests.

2. **Reference clock, not a shifted wall clock.**
   `plan()` computes `ref = start_at or now_hk`. `is_leg_active` projects `ref + board_time_minutes` (was `now + board_time_minutes`); `start_at` gating is inherent because board offsets include the origin walk. Leave-now (`ref == now`) reproduces current behavior exactly.
   Note: today `is_leg_active` only schedule-checks bus-company legs (kmb/ctb/nlb/gmb), so the GTFS-ferry `freq` data is never consulted. When the reference is in the future, the freq check extends to frequency-carrying legs of **any** company (ferries are the one carrier with real schedules and sparse fixed departures — exactly where a future departure matters); leave-now keeps the bus-only policy plus live-ETA rescue unchanged.
   *Alternative*: rewinding `datetime.now` — rejected: global state, breaks freezegun isolation.

3. **Live-ETA substitution becomes per-goal, reference-conditional.**
   Substituting the first leg's modeled wait with a live ETA (2887–2891) stays only when that itinerary's effective departure is ≈ now (tolerance ≤ 2 min). For future departures: no substitution, no `next_departures` on legs (a now-ETA next to a 07:00 departure misleads LLMs), modeled wait kept.
   *Alternative*: always substitute — rejected: live ETAs describe now, not the requested departure.

4. **Reverse solve = derive per-itinerary departures, re-validate in memory. One search, no re-runs.**
   `earliest_ref = max(now, start_at)`. If `earliest_ref >= arrive_at` → `time_conflict`.
   Single A* pass anchored at `earliest_ref` (the search is time-agnostic; only validation is clock-dependent). Then per validated goal with modeled duration `d_i`:
   - `dep_i = max(earliest_ref, arrive_at − plan_arrival_buffer_min − d_i)` (new valve, default 5 min so modeled arrivals land inside the target with margin).
   - Re-check each leg's `freq` schedule at `dep_i + board offsets` (pure CPU). Off-schedule at `dep_i` → retry once at `dep_i − 30 min` (bounded by `earliest_ref`); still failing → drop that goal (it cannot make the target).
   - `arrival_i = dep_i + d_i`; `arrival_status = at_target` if `arrival_i ≤ arrive_at` else `overrun` (overrun survives to output as best-effort — the window may simply be tight).
   For future `dep_i`, off-schedule legs get no live-ETA rescue (a now-ETA says nothing about a future departure): freq check only, so the solve stays offline and bounded. `diagnostics.departure_solve_passes` counts re-check rounds.
   *Alternative*: binary-search departures with repeated A* passes — rejected: 3–5× search cost for accuracy the data can't support; backward search — rejected: major refactor.

5. **Output contract additions, existing keys untouched.**
   - `summary.departure` / `summary.arrival`: ISO-8601 strings with +08:00, present only when a reference was supplied (`start_at` and/or `arrive_at`).
   - `summary.arrival_status`: `at_target` | `overrun`, only when `arrive_at` is set.
   - Top-level `timing` echo: `{mode: leave_now|depart_by|arrive_by|window, start_at, arrive_at, timezone}` so LLMs can relay interpreted times (next-occurrence rolls and past clamps are visible).
   - `time_min_est` unchanged.
   *Alternative*: always emit clocks — rejected: changes every existing response for no asked-for benefit.

6. **Version bump 0.6.0 → 0.7.0** at the three sync spots (manifest line 9, User-Agent line 1327, `Tools.meta()` line 2944); the version-sync test enforces all three.

## Risks / Trade-offs

- [Bus/MTR future waits are modeled, not scheduled] → docstring + design note label clocks as estimates; only ferry legs get schedule-validated at future times; `arrival_status` never claims precision.
- [Reverse-solve accuracy for tight windows] → `plan_arrival_buffer_min` valve (default 5) plus `overrun` best-effort output instead of silent failure.
- [Bare HH:MM next-occurrence may surprise ("18:30" at 18:31 → tomorrow)] → `timing` echo always reports the interpreted absolute time.
- [Behavior drift on the leave-now path] → no-params path must keep the exact current code shape; regression suite green is the gate.
- [freezegun + async planner deadline] → tests freeze the clock only within specific planner tests (established pattern in the suite).

## Migration Plan

Single-file Open WebUI tool: merge, run `python3 -m py_compile hk-open-data-tool.py` + `python3 -m pytest`, re-paste into Open WebUI tools menu. Rollback = revert the feat commit.

## Open Questions

- None blocking. Buffer default (5 min) and the single 30-min retry step are valve/constant-level choices, adjustable without spec changes.
