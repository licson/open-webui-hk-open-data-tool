"""td_* tool-layer tests over the seeded mini transit graph."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


def freeze_utc(*args):
    from freezegun import freeze_time

    return freeze_time(datetime(*args, tzinfo=timezone.utc))


@pytest.fixture()
def eta_router(router):
    """KMB + GMB + LRT ETA payloads for the mini graph (10/12-min departures)."""
    router.add(
        r"etabus\.gov\.hk/v1/transport/kmb/eta/S_A/1/1",
        json={"data": [
            {"eta": "2026-09-05T20:10:00+08:00", "dir": "O", "rmk_en": "", "rmk_tc": ""},
            {"eta": "2026-09-05T20:12:00+08:00", "dir": "O", "rmk_en": "", "rmk_tc": ""},
        ]},
    )
    router.add(
        r"etagmb\.gov\.hk/eta/stop/S_A/2006-1",
        json={"data": [{"eta": "2026-09-05T20:11:00+08:00", "rmk_en": "", "rmk_tc": ""}]},
    )
    router.add(
        r"mtr/lrt/getSchedule",
        json={"platform_list": [{"platform_id": "3", "route_list": [
            {"route_no": "507", "dest_en": "Tin Shui Wai", "dest_ch": "天水圍", "time_en": "6 min"},
        ]}]},
    )
    return router


class TestTdCatalogStatus:
    async def test_operators_and_modes(self, seeded_tools):
        out = await seeded_tools.td_catalog_status()
        assert set(out["operators_seen"]) >= {"kmb", "mtr", "gmb", "lightrail"}
        assert set(out["modes"]) >= {"bus", "rail", "minibus"}
        assert out["meta"]["tool"] == "Hong Kong Open Data"


class TestTdStopSearch:
    async def test_search_by_english_name(self, seeded_tools):
        out = await seeded_tools.td_stop_search("gate")
        names = [i["display"] for i in out["items"]]
        assert "North Gate" in names and "East Gate" in names

    async def test_search_by_chinese_name(self, seeded_tools):
        out = await seeded_tools.td_stop_search("北門")
        assert [i["stop_id"] for i in out["items"]] == ["S_C"]

    async def test_empty_query(self, seeded_tools):
        out = await seeded_tools.td_stop_search("")
        assert out["items"] == [] and out["next_cursor"] is None

    async def test_pagination_cursor(self, seeded_tools):
        first = await seeded_tools.td_stop_search("gate", limit=1)
        assert len(first["items"]) == 1
        assert first["next_cursor"] is not None
        second = await seeded_tools.td_stop_search("gate", limit=1, cursor=first["next_cursor"])
        assert len(second["items"]) == 1
        assert second["items"][0]["stop_id"] != first["items"][0]["stop_id"]


class TestTdStopNearby:
    async def test_by_wgs84(self, seeded_tools):
        out = await seeded_tools.td_stop_nearby(wgs84={"lat": 22.2800, "lon": 114.1500}, radius_m=300)
        assert "error" not in out
        assert out["items"][0]["stop_id"] == "S_A"
        assert out["items"][0]["distance_m"] == pytest.approx(0.0, abs=2.0)
        assert out["radius_m"] == 300

    async def test_neither_input_is_bad_request(self, seeded_tools):
        out = await seeded_tools.td_stop_nearby()
        assert out["error"] == "bad_request"

    async def test_radius_floors_at_50(self, seeded_tools):
        out = await seeded_tools.td_stop_nearby(wgs84={"lat": 22.2800, "lon": 114.1500}, radius_m=1)
        assert out["radius_m"] == 50

    async def test_by_place_name_via_landsd(self, seeded_tools, router):
        router.add(r"map\.gov\.hk/gs/api/v1\.0\.0/locationSearch",
                   json=[{"nameEN": "Test Place", "x": 830000, "y": 820000}])
        router.add(r"geodetic\.gov\.hk/transform/v2/", json={"wgsLat": 22.2800, "wgsLong": 114.1500})
        out = await seeded_tools.td_stop_nearby(place_name="Test Place", radius_m=300)
        assert "error" not in out
        assert out["resolved_location"]["details"]["input"]["place_name"] == "Test Place"
        assert out["items"][0]["stop_id"] == "S_A"

    async def test_place_name_unresolvable(self, seeded_tools, router):
        router.add(r"map\.gov\.hk/gs/api/v1\.0\.0/locationSearch", json=[])
        out = await seeded_tools.td_stop_nearby(place_name="Nowhere Special")
        assert out["error"] == "resolve_failed"


class TestTdRouteGet:
    async def test_found(self, seeded_tools):
        out = await seeded_tools.td_route_get("1+kmb+south+north")
        assert out["route"]["route"] == "1"
        assert out["route"]["co"] == ["kmb"]

    async def test_not_found(self, seeded_tools):
        out = await seeded_tools.td_route_get("zzz")
        assert out["error"] == "route_not_found"


class TestTdRouteSearch:
    async def test_by_route_number(self, seeded_tools):
        out = await seeded_tools.td_route_search("1")
        routes = [r["route"] for r in out["items"]]
        assert "1" in routes

    async def test_by_destination_name(self, seeded_tools):
        out = await seeded_tools.td_route_search("north terminus")
        assert any(r["route_id"] == "3+gmb+direct" for r in out["items"])

    async def test_empty_query(self, seeded_tools):
        out = await seeded_tools.td_route_search("")
        assert out["items"] == []

    async def test_pagination(self, seeded_tools):
        first = await seeded_tools.td_route_search("north", limit=2)
        assert len(first["items"]) == 2 and first["next_cursor"]
        second = await seeded_tools.td_route_search("north", limit=2, cursor=first["next_cursor"])
        ids1 = {r["route_id"] for r in first["items"]}
        ids2 = {r["route_id"] for r in second["items"]}
        assert not (ids1 & ids2)


class TestTdDeparturesByStop:
    async def test_stop_not_found(self, seeded_tools):
        out = await seeded_tools.td_departures_by_stop("NOPE")
        assert out["error"] == "stop_not_found"

    async def test_kmb_and_gmb_departures(self, seeded_tools, eta_router):
        with freeze_utc(2026, 9, 5, 12, 0):
            out = await seeded_tools.td_departures_by_stop("S_A")
        assert "error" not in out
        assert out["meta"]["data_source"]  # source="td" meta
        rows = {(d["company"], d["route"]) for d in out["departures"]}
        assert rows == {("kmb", "1"), ("gmb", "3")}
        kmb_rows = [d for d in out["departures"] if d["company"] == "kmb"]
        assert len(kmb_rows) == 2  # both ETAs, sorted
        assert kmb_rows[0]["eta"]["minutes"] == 10
        assert kmb_rows[0]["eta"]["text"] == "10 min"

    async def test_operator_filter(self, seeded_tools, eta_router):
        with freeze_utc(2026, 9, 5, 12, 0):
            out = await seeded_tools.td_departures_by_stop("S_A", operators=["KMB"])
        assert {d["company"] for d in out["departures"]} == {"kmb"}
        assert eta_router.calls("etagmb") == []

    async def test_mode_filter(self, seeded_tools, eta_router):
        with freeze_utc(2026, 9, 5, 12, 0):
            out = await seeded_tools.td_departures_by_stop("S_A", modes=["minibus"])
        assert {d["company"] for d in out["departures"]} == {"gmb"}

    async def test_lightrail_operator_alias(self, seeded_tools, eta_router):
        out = await seeded_tools.td_departures_by_stop("1520", operators=["lightRail"])
        assert "error" not in out
        assert out["departures"], "lightrail rows expected via the normalized alias"
        assert all(d["company"] == "lightrail" for d in out["departures"])
        assert out["departures"][0]["route"] == "507"
        assert out["departures"][0]["platform"] == "3"

    async def test_limit_routes(self, seeded_tools, eta_router):
        with freeze_utc(2026, 9, 5, 12, 0):
            out = await seeded_tools.td_departures_by_stop("S_A", limit_routes=1)
        assert len(out["departures"]) <= 1

    async def test_eta_error_yields_no_departures(self, seeded_tools, router):
        router.add(r"etabus\.gov\.hk", status=500, json={})
        router.add(r"etagmb\.gov\.hk", status=500, json={})
        out = await seeded_tools.td_departures_by_stop("S_A")
        assert out["departures"] == []


class TestTdDeparturesNearby:
    async def test_structure_and_events(self, seeded_tools, eta_router, emitter):
        with freeze_utc(2026, 9, 5, 12, 0):
            out = await seeded_tools.td_departures_nearby(
                wgs84={"lat": 22.2800, "lon": 114.1500}, radius_m=300, __event_emitter__=emitter
            )
        assert "error" not in out
        assert out["stops"], "expected nearby stops"
        for entry in out["stops"]:
            assert "stop" in entry and "departures" in entry
        descriptions = [e["data"]["description"] for e in emitter.events]
        assert descriptions[0].startswith("Fetching departures")
        assert descriptions[-1] == "Done."

    async def test_error_forwarded(self, seeded_tools, emitter):
        out = await seeded_tools.td_departures_nearby(__event_emitter__=emitter)
        assert out["error"] == "bad_request"
