"""TripPlanner tests: pure cost helpers + plan() on seeded mini-graphs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from conftest import mini_db, helpers

HK = timezone(timedelta(hours=8))


@pytest.fixture()
def planner(mod, tdb_planner_parts):
    transit, landsd, valves = tdb_planner_parts
    return mod.TripPlanner(transit, landsd, valves)


@pytest.fixture()
def tdb_planner_parts(mod, seeded_tools):
    return seeded_tools.transit, seeded_tools.landsd, seeded_tools.valves


def geocode(monkeypatch, landsd, origin, dest):
    """Stub the planner's geocoder with fixed coordinates."""

    async def fake_location_search(q, limit=10):
        pt = origin if "ORIGIN" in q.upper() else dest
        if pt is None:
            return []
        return [{"wgs84": {"lat": pt[0], "lon": pt[1]}}]

    monkeypatch.setattr(landsd, "location_search", fake_location_search)


NEAR_S_A = (22.2799, 114.1501)  # ~15 m from S_A
NEAR_S_D = (22.2921, 114.1500)  # ~11 m from S_D


# ------------------------------------------------------------------
# Pure helpers
# ------------------------------------------------------------------
class TestTransferPenalty:
    @pytest.mark.parametrize(
        ("frm", "to", "expected"),
        [
            (None, "bus", 0.0),
            ("rail", "rail", 3.0),
            ("bus", "bus", 10.0),
            ("mtr_bus", "minibus", 10.0),  # both contain "bus"
            ("ferry", "bus", 6.0),
            ("bus", "ferry", 6.0),
            ("rail", "bus", 8.0),
            ("rail", "ferry", 6.0),
        ],
    )
    def test_cases(self, planner, frm, to, expected):
        assert planner.transfer_penalty(frm, to) == expected


class TestModeTimes:
    @pytest.mark.parametrize(
        ("company", "wait", "per_stop"),
        [
            ("mtr", 3.0, 1.8),
            ("lightrail", 3.0, 1.8),  # mode_of_company(lightrail) == "rail"
            ("kmb", 8.0, 2.5),
            ("gmb", 6.0, 1.5),
            ("starferry", 30.0, 12.0),
            ("sunferry", 30.0, 12.0),
            ("hkkf", 60.0, 15.0),  # non-star/sun ferry
        ],
    )
    def test_cases(self, planner, company, wait, per_stop):
        w, ride = planner.mode_times(company, 2)
        assert w == wait
        assert ride == pytest.approx(per_stop * 2)


class TestModeBit:
    @pytest.mark.parametrize(
        ("co", "bit"), [("mtr", 1), ("lightrail", 1), ("kmb", 2), ("ctb", 2), ("sunferry", 4), ("gmb", 8)]
    )
    def test_cases(self, planner, co, bit):
        assert planner.mode_bit(co) == bit


class TestWalkCost:
    def test_plain_stop(self, planner):
        # 400 m at 80 m/min, weight 1.5 -> 7.5
        assert planner.walk_cost(400.0, "S_A") == pytest.approx(400 / 80 * 1.5)

    def test_rail_discount(self, planner):
        # S_B is an MTR station: 400 m -> effective max(50, 400-250)=150
        assert planner.walk_cost(400.0, "S_B") == pytest.approx(150 / 80 * 1.5)

    def test_rail_short_walk_undiscounted(self, planner):
        # <=150 m: effective stays the raw distance (max(50, -100) = 50)
        assert planner.walk_cost(100.0, "S_B") == pytest.approx(100 / 80 * 1.5)

    def test_is_rail_station(self, planner):
        assert planner.is_rail_station("S_B") is True
        assert planner.is_rail_station("S_A") is False


class TestIsOperatingNow:
    SAT_NOON = datetime(2026, 9, 5, 12, 0, tzinfo=HK)  # Saturday

    def test_empty_freq_is_operating(self, planner):
        assert planner.is_operating_now({}) is True
        assert planner.is_operating_now(None) is True

    def test_window_hit_and_miss(self, planner):
        freq = {"127": {"0700": ["1900", 20]}}
        assert planner.is_operating_now(freq, projected_dt=self.SAT_NOON) is True
        late = datetime(2026, 9, 5, 20, 30, tzinfo=HK)
        assert planner.is_operating_now(freq, projected_dt=late) is False

    def test_day_mask_filtering(self, planner):
        freq = {"64": {"0000": ["2359", 10]}}  # Sunday only
        sun = datetime(2026, 9, 6, 12, 0, tzinfo=HK)
        assert planner.is_operating_now(freq, projected_dt=sun) is True
        assert planner.is_operating_now(freq, projected_dt=self.SAT_NOON) is False

    def test_pre_4am_uses_previous_service_day(self, planner):
        # Sun 02:00 HKT belongs to Saturday's service day; hour rolls to 26
        freq = {"32": {"2500": ["2900", 30]}}  # Saturday 25:00-29:00
        wee = datetime(2026, 9, 6, 2, 0, tzinfo=HK)
        assert planner.is_operating_now(freq, projected_dt=wee) is True

    def test_holiday_follows_sunday_schedule(self, mod, planner):
        planner.transit._holidays.add("20261001")  # Thursday, National Day
        freq = {"64": {"0900": ["1800", 15]}}  # Sunday schedule
        hol = datetime(2026, 10, 1, 12, 0, tzinfo=HK)
        assert planner.is_operating_now(freq, projected_dt=hol) is True
        planner.transit._holidays.discard("20261001")
        assert planner.is_operating_now(freq, projected_dt=hol) is False

    def test_midnight_wrap_window(self, planner):
        freq = {"127": {"2330": ["0030", 20]}}  # wraps past midnight
        night = datetime(2026, 9, 5, 23, 50, tzinfo=HK)
        assert planner.is_operating_now(freq, projected_dt=night) is True

    def test_fixed_departures_padded(self, planner):
        freq = {"127": {"0700": None, "1900": None}}
        after_last = datetime(2026, 9, 5, 19, 50, tzinfo=HK)
        assert planner.is_operating_now(freq, projected_dt=after_last) is True  # within +100 pad
        too_late = datetime(2026, 9, 5, 21, 0, tzinfo=HK)
        assert planner.is_operating_now(freq, projected_dt=too_late) is False

    def test_invalid_day_mask_returns_true(self, planner):
        assert planner.is_operating_now({"junk": {"0700": ["1900", 10]}}, projected_dt=self.SAT_NOON) is True


# ------------------------------------------------------------------
# plan() on the mini graph
# ------------------------------------------------------------------
class TestPlan:
    async def test_single_leg_itinerary(self, mod, seeded_tools, monkeypatch, emitter):
        geocode(monkeypatch, seeded_tools.landsd, NEAR_S_A, NEAR_S_D)
        out = await seeded_tools.planner.plan("ORIGIN place", "DEST place", __event_emitter__=emitter)
        assert "error" not in out, out
        assert out["origin"]["label"] == "ORIGIN place"
        itins = out["itineraries"]
        assert itins, "expected at least one itinerary"
        one_leg = [i for i in itins if len(i["legs"]) == 1]
        assert one_leg, f"expected a direct itinerary, got {[len(i['legs']) for i in itins]}"
        leg = one_leg[0]["legs"][0]
        assert leg["board_stop"]["stop_id"] == "S_A"
        assert leg["alight_stop"]["stop_id"] == "S_D"
        assert leg["route"]["route"] == "3"
        assert leg["mode"] in ("bus", "minibus")

    async def test_itinerary_schema(self, mod, seeded_tools, monkeypatch):
        geocode(monkeypatch, seeded_tools.landsd, NEAR_S_A, NEAR_S_D)
        out = await seeded_tools.planner.plan("ORIGIN", "DEST")
        i = out["itineraries"][0]
        for key in ("tags", "score", "summary", "legs"):
            assert key in i, key
        for key in ("transfers", "walk_m", "time_min_est"):
            assert key in i["summary"], key
        for key in ("mode", "operator", "route", "board_stop", "alight_stop", "next_departures"):
            assert key in i["legs"][0], key
        assert "diagnostics" in out
        for key in ("expansions", "goals_found", "goals_valid", "deadline_hit", "eta_checks"):
            assert key in out["diagnostics"], key
        assert "fastest" in i["tags"] or any("fastest" in x["tags"] for x in out["itineraries"])

    async def test_transfer_itinerary(self, mod, seeded_tools, monkeypatch):
        # remove the direct GMB route -> best options need a transfer
        seeded_tools.transit._route_list.pop("3+gmb+direct")
        seeded_tools.transit._build_indices(
            {"stopList": seeded_tools.transit._stop_list, "routeList": seeded_tools.transit._route_list, "holidays": []}
        )
        geocode(monkeypatch, seeded_tools.landsd, NEAR_S_A, NEAR_S_D)
        out = await seeded_tools.planner.plan("ORIGIN", "DEST")
        assert "error" not in out
        multi = [i for i in out["itineraries"] if len(i["legs"]) == 2]
        assert multi, f"expected a transfer itinerary, got {[len(i['legs']) for i in out['itineraries']]}"

    async def test_location_not_found(self, seeded_tools, monkeypatch, emitter):
        geocode(monkeypatch, seeded_tools.landsd, NEAR_S_A, None)
        out = await seeded_tools.planner.plan("ORIGIN", "NOWHERE", __event_emitter__=emitter)
        assert out["error"] == "location_not_found"
        assert emitter.events[0]["data"]["done"] is False
        assert emitter.events[-1]["data"]["done"] is True

    async def test_no_nearby_stops(self, seeded_tools, monkeypatch):
        geocode(monkeypatch, seeded_tools.landsd, NEAR_S_A, (10.0, 10.0))  # far from HK
        out = await seeded_tools.planner.plan("ORIGIN", "DEST")
        assert out["error"] == "no_nearby_stops"
        assert "destination" in out["detail"]

    async def test_limit_clamped_to_5(self, seeded_tools, monkeypatch):
        geocode(monkeypatch, seeded_tools.landsd, NEAR_S_A, NEAR_S_D)
        out = await seeded_tools.planner.plan("ORIGIN", "DEST", limit=99)
        assert len(out["itineraries"]) <= 5

    async def test_max_transfers_one_forces_direct(self, seeded_tools, monkeypatch):
        # max_transfers caps boardings (legs = transfers + 1), see Valves note
        geocode(monkeypatch, seeded_tools.landsd, NEAR_S_A, NEAR_S_D)
        out = await seeded_tools.planner.plan("ORIGIN", "DEST", max_transfers=1)
        assert "error" not in out
        assert all(len(i["legs"]) == 1 for i in out["itineraries"])

    async def test_status_events_sequence(self, seeded_tools, monkeypatch, emitter):
        geocode(monkeypatch, seeded_tools.landsd, NEAR_S_A, NEAR_S_D)
        await seeded_tools.planner.plan("ORIGIN", "DEST", __event_emitter__=emitter)
        assert len(emitter.events) >= 2
        assert all(e["type"] == "status" for e in emitter.events)
        assert emitter.events[0]["data"]["description"].startswith("Resolving")
        assert emitter.events[-1]["data"]["description"] == "Done."
        assert emitter.events[-1]["data"]["done"] is True

    async def test_first_leg_live_eta_substitution(self, seeded_tools, monkeypatch):
        geocode(monkeypatch, seeded_tools.landsd, NEAR_S_A, NEAR_S_D)
        calls = []

        async def fake_departures(company, route_id, board_stop_id, board_seq, limit_etas=2, lang="en"):
            calls.append((company, route_id, board_stop_id))
            return [{"eta": {"minutes": 25, "iso": None, "text": "25 min"}}]

        monkeypatch.setattr(seeded_tools.transit, "leg_next_departures", fake_departures)
        out = await seeded_tools.planner.plan("ORIGIN", "DEST")
        assert calls, "planner should fetch a live ETA for the first leg"
        for i in out["itineraries"]:
            assert i["summary"]["time_min_est"] >= 25.0

    async def test_champion_tags(self, seeded_tools, monkeypatch):
        geocode(monkeypatch, seeded_tools.landsd, NEAR_S_A, NEAR_S_D)
        out = await seeded_tools.planner.plan("ORIGIN", "DEST", limit=5)
        all_tags = {t for i in out["itineraries"] for t in i["tags"]}
        assert "fastest" in all_tags
        if len(out["itineraries"]) > 1:
            assert "fewest_transfers" in all_tags

    async def test_td_plan_trip_passthrough(self, seeded_tools, monkeypatch, emitter):
        geocode(monkeypatch, seeded_tools.landsd, NEAR_S_A, NEAR_S_D)
        out = await seeded_tools.td_plan_trip("ORIGIN", "DEST", __event_emitter__=emitter)
        assert "error" not in out
        assert out["meta"]["data_source"] == "hkbus DB + Transport Department APIs"
        assert out["itineraries"]


def ferry_only_db(freq=None) -> dict:
    """Mini graph whose only S_A->S_D option is a freq-carrying ferry."""
    db = mini_db()
    db["routeList"] = {
        "FT+1+o+d": helpers.route(
            "FT+1+o+d",
            ["sunferry"],
            {"sunferry": ["S_A", "S_D"]},
            route_no="FT",
            orig_en="South",
            dest_en="North",
            bound={"sunferry": "O"},
            freq=freq if freq is not None else {"127": {"0600": ["0800", 20]}},  # service 06:00-08:00 daily
        ),
    }
    return db


class TestPlanTimeReference:
    FROZEN = datetime(2026, 9, 6, 6, 0, tzinfo=HK)  # Sun 06:00 HKT
    IN_WINDOW = datetime(2026, 9, 6, 7, 0, tzinfo=HK)   # ferry service 06:00-08:00
    OUTSIDE = datetime(2026, 9, 6, 20, 0, tzinfo=HK)    # outside ferry service

    def _time_tools(self, mod, tmp_cache):
        valves = helpers.make_valves(mod, tmp_cache)
        tdb = helpers.build_transit(mod, ferry_only_db())
        landsd = mod.LandsDClient(tdb.http)
        return mod.TripPlanner(tdb, landsd, valves)

    def _geocode(self, monkeypatch, planner):
        async def fake_location_search(q, limit=10):
            pt = NEAR_S_A if "ORIGIN" in q.upper() else NEAR_S_D
            return [{"wgs84": {"lat": pt[0], "lon": pt[1]}}]

        monkeypatch.setattr(planner.landsd, "location_search", fake_location_search)

    def _no_eras(self, monkeypatch, planner):
        calls = []

        async def fake_departures(*a, **k):
            calls.append(a)
            return []

        monkeypatch.setattr(planner.transit, "leg_next_departures", fake_departures)
        return calls

    async def test_leave_now_ignores_freq_for_ferry(self, mod, tmp_cache, monkeypatch, emitter, freezer):
        # Legacy leave-now: ferry legs are NOT schedule-checked, so a plan is
        # found even with the clock (frozen inside the service window) would
        # otherwise matter; and a near-now departure DOES fetch a live ETA.
        planner = self._time_tools(mod, tmp_cache)
        self._geocode(monkeypatch, planner)
        calls = self._no_eras(monkeypatch, planner)
        freezer.freeze(self.FROZEN)
        out = await planner.plan("ORIGIN", "DEST", __event_emitter__=emitter)
        assert "error" not in out
        assert any(i["legs"][0]["operator"] == "sunferry" for i in out["itineraries"])

    async def test_future_start_skips_live_eta_and_anchors_validation(self, mod, tmp_cache, monkeypatch, emitter, freezer):
        # A future start_at: (a) must not call the live ETA API, (b) anchors
        # freq validation at the reference clock (07:00 is inside the window).
        planner = self._time_tools(mod, tmp_cache)
        self._geocode(monkeypatch, planner)
        calls = self._no_eras(monkeypatch, planner)
        freezer.freeze(self.FROZEN)
        out = await planner.plan("ORIGIN", "DEST", start_at=self.IN_WINDOW, __event_emitter__=emitter)
        assert "error" not in out
        assert calls == [], "future reference must not fetch live ETAs"
        for i in out["itineraries"]:
            for leg in i["legs"]:
                assert leg["next_departures"] == []

    async def test_future_start_outside_window_drops_ferry(self, mod, tmp_cache, monkeypatch, emitter, freezer):
        planner = self._time_tools(mod, tmp_cache)
        self._geocode(monkeypatch, planner)
        calls = self._no_eras(monkeypatch, planner)
        freezer.freeze(self.FROZEN)
        out = await planner.plan("ORIGIN", "DEST", start_at=self.OUTSIDE, __event_emitter__=emitter)
        assert out["error"] == "no_route_found"
        assert calls == [], "no live-ETA attempt for a future off-schedule departure"


# ------------------------------------------------------------------
# Arrive-by / window reverse solve over the freq-carrying ferry graph
# ------------------------------------------------------------------
class TestPlanArrivalTarget:
    # Ferry service window 06:00-08:00 daily.
    FROZEN = datetime(2026, 9, 6, 6, 0, tzinfo=HK)     # Sun 06:00 HKT

    def _time_tools(self, mod, tmp_cache, freq=None):
        valves = helpers.make_valves(mod, tmp_cache)
        tdb = helpers.build_transit(mod, ferry_only_db(freq))
        landsd = mod.LandsDClient(tdb.http)
        return mod.TripPlanner(tdb, landsd, valves)

    def _geocode(self, monkeypatch, planner):
        async def fake_location_search(q, limit=10):
            pt = NEAR_S_A if "ORIGIN" in q.upper() else NEAR_S_D
            return [{"wgs84": {"lat": pt[0], "lon": pt[1]}}]

        monkeypatch.setattr(planner.landsd, "location_search", fake_location_search)

    def _no_eras(self, monkeypatch, planner):
        async def fake_departures(*a, **k):
            return []

        monkeypatch.setattr(planner.transit, "leg_next_departures", fake_departures)

    def plan(self, planner, **kw):
        return planner.plan("ORIGIN", "DEST", **kw)

    async def test_time_conflict(self, mod, tmp_cache, monkeypatch, freezer):
        planner = self._time_tools(mod, tmp_cache)
        self._geocode(monkeypatch, planner)
        self._no_eras(monkeypatch, planner)
        freezer.freeze(self.FROZEN)
        # arrive earlier than the earliest possible departure (now)
        out = await self.plan(planner, start_at=self.FROZEN + timedelta(hours=1), arrive_at=self.FROZEN + timedelta(minutes=30))
        assert out["error"] == "time_conflict"

    async def test_derived_departure_lands_inside_target(self, mod, tmp_cache, monkeypatch, freezer, emitter):
        planner = self._time_tools(mod, tmp_cache)
        self._geocode(monkeypatch, planner)
        self._no_eras(monkeypatch, planner)
        freezer.freeze(self.FROZEN)
        # ferry ~47 min modeled ride (30 min wait + fixed). arrive in 1h45.
        arrive = self.FROZEN + timedelta(minutes=105)
        out = await self.plan(planner, arrive_at=arrive, __event_emitter__=emitter)
        assert "error" not in out
        i = out["itineraries"][0]
        assert i["summary"]["arrival_status"] == "at_target"
        dep = datetime.fromisoformat(i["summary"]["departure"])
        arr = datetime.fromisoformat(i["summary"]["arrival"])
        assert arr <= arrive, "modeled arrival must meet the target"

    async def test_wide_window_delays_departure_toward_target(self, mod, tmp_cache, monkeypatch, freezer):
        planner = self._time_tools(mod, tmp_cache)
        self._geocode(monkeypatch, planner)
        self._no_eras(monkeypatch, planner)
        freezer.freeze(self.FROZEN)
        start = self.FROZEN + timedelta(hours=1)  # 07:00, inside ferry window
        arrive = self.FROZEN + timedelta(hours=2)  # 08:00; trip ~42 min
        out = await self.plan(planner, start_at=start, arrive_at=arrive)
        assert "error" not in out
        i = out["itineraries"][0]
        dep = datetime.fromisoformat(i["summary"]["departure"])
        assert dep > start, "a wide window should delay the departure past start_at"
        assert i["summary"]["arrival_status"] == "at_target"
        arr = datetime.fromisoformat(i["summary"]["arrival"])
        assert arr <= arrive, "arrival must stay inside the target"

    async def test_tight_window_departs_at_start_at(self, mod, tmp_cache, monkeypatch, freezer):
        # Trip ~42 min fills the 40-min window: departs right at start_at and is
        # flagged overrun, not an error.
        planner = self._time_tools(mod, tmp_cache)
        self._geocode(monkeypatch, planner)
        self._no_eras(monkeypatch, planner)
        freezer.freeze(self.FROZEN)
        start = self.FROZEN + timedelta(hours=1)   # 07:00
        arrive = self.FROZEN + timedelta(hours=1, minutes=40)  # 07:40
        out = await self.plan(planner, start_at=start, arrive_at=arrive)
        assert "error" not in out
        i = out["itineraries"][0]
        dep = datetime.fromisoformat(i["summary"]["departure"])
        assert dep == start
        assert i["summary"]["arrival_status"] == "overrun"

    async def test_tight_window_is_overrun_not_error(self, mod, tmp_cache, monkeypatch, freezer):
        planner = self._time_tools(mod, tmp_cache)
        self._geocode(monkeypatch, planner)
        self._no_eras(monkeypatch, planner)
        freezer.freeze(self.FROZEN)
        arrive = self.FROZEN + timedelta(minutes=10)  # tighter than even the modeled ride
        out = await self.plan(planner, arrive_at=arrive)
        assert "error" not in out, "tight windows are best-effort, not an error"
        assert all(i["summary"]["arrival_status"] == "overrun" for i in out["itineraries"])

    async def test_off_schedule_derived_departure_retries_earlier(self, mod, tmp_cache, monkeypatch, freezer):
        # Derived departure (~07:45) is outside the 06:00-07:20 window, but 30
        # minutes earlier (~07:15) is in service -> the solve must step back.
        planner = self._time_tools(mod, tmp_cache, freq={"127": {"0600": ["0720", 20]}})
        self._geocode(monkeypatch, planner)
        self._no_eras(monkeypatch, planner)
        freezer.freeze(self.FROZEN)
        arrive = self.FROZEN + timedelta(hours=2, minutes=32)  # 08:32 -> dep ~07:45
        out = await self.plan(planner, arrive_at=arrive)
        assert "error" not in out
        i = out["itineraries"][0]
        dep = datetime.fromisoformat(i["summary"]["departure"])
        assert dep < self.FROZEN + timedelta(hours=1, minutes=30), "solve should retry earlier"
        assert i["summary"]["arrival_status"] == "at_target"
        assert out["diagnostics"]["departure_solve_passes"] >= 2, "expected a retry pass"

    async def test_off_schedule_at_both_candidates_drops_goal(self, mod, tmp_cache, monkeypatch, freezer):
        # Neither the derived departure (~07:13) nor 30 min earlier is in the
        # 12:00-14:00 window -> the goal is dropped and no route is returned.
        planner = self._time_tools(mod, tmp_cache, freq={"127": {"1200": ["1400", 20]}})  # far window
        self._geocode(monkeypatch, planner)
        self._no_eras(monkeypatch, planner)
        freezer.freeze(self.FROZEN)
        arrive = self.FROZEN + timedelta(hours=2)
        out = await self.plan(planner, arrive_at=arrive)
        assert out["error"] == "no_route_found"
