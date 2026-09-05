"""TransitDB tests: indices, lookups, DB load path, GTFS ferry merge, ETA fetchers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from conftest import (
    Router,
    build_transit,
    gtfs_zip_bytes,
    make_valves,
    mini_db,
    patch_async_client,
    route as mk_route,
    seed_ferry_cache,
    seed_transit_files,
    stop as mk_stop,
)

HK = timezone(timedelta(hours=8))


@pytest.fixture()
async def tdb_factory(mod, router):
    made = []

    def make(db: dict | None = None):
        tdb = build_transit(mod, db if db is not None else mini_db())
        tdb.http.valves.http_retries = 0
        tdb.http._client = httpx.AsyncClient(transport=router.transport)
        made.append(tdb)
        return tdb

    yield make
    for t in made:
        if t.http._client is not None:
            await t.http._client.aclose()


# ------------------------------------------------------------------
# Indices & lookups
# ------------------------------------------------------------------
class TestBuildIndices:
    async def test_stop_to_routes_and_seq(self, mod, tdb_factory):
        tdb = tdb_factory()
        occs = {(o.route_id, o.company): o.seq for o in tdb._stop_to_routes["S_B"]}
        assert occs["1+kmb+south+north", "kmb"] == 1  # S_A,S_B,S_C -> seq 1
        assert occs["ISL+1+a+b", "mtr"] == 0

    async def test_non_operator_stops_keys_skipped(self, mod, tdb_factory):
        db = mini_db()
        db["routeList"]["ferryish+1+x+y"] = mk_route(
            "ferryish+1+x+y",
            ["sunferry"],
            {"sunferry": ["S_A", "S_C"], "O": ["JUNK1", "JUNK2"]},
            route_no="CECC",
        )
        tdb = tdb_factory(db)
        assert ("ferryish+1+x+y", "sunferry") in tdb._route_company_stops
        assert ("ferryish+1+x+y", "o") not in tdb._route_company_stops
        junk_occ = [o for o in tdb._stop_to_routes.get("JUNK1", [])]
        assert junk_occ == []

    async def test_stop_degree_counts_distinct_company_routes(self, mod, tdb_factory):
        tdb = tdb_factory()
        # S_B serves kmb route 1 + mtr ISL -> degree 2
        assert tdb._stop_degree["S_B"] == 2
        # S_A serves kmb 1 + gmb 3 -> degree 2
        assert tdb._stop_degree["S_A"] == 2

    async def test_grid_cells(self, mod, tdb_factory):
        tdb = tdb_factory()
        cell = (int(22.2800 / 0.004), int(114.1500 / 0.004))
        assert "S_A" in tdb._grid[cell]

    async def test_transfer_edges_within_800m(self, mod, tdb_factory):
        tdb = tdb_factory()
        edges = dict(tdb._transfer_edges["S_A"])
        assert "S_B" in edges  # ~445 m
        assert "S_D" not in edges  # ~1.3 km

    async     def test_transfer_edge_cap_30(self, mod, tdb_factory):
        db = {"stopList": {}, "routeList": {}, "holidays": []}
        # a rail route makes R an interchange; F01..F35 are plain fillers
        rail_stops = ["R"]
        for i in range(1, 36):
            sid = f"F{i:02d}"
            db["stopList"][sid] = mk_stop(sid, f"Filler {i}", 22.2800 + i * 0.0001, 114.1500)
        db["stopList"]["R"] = mk_stop("R", "Rail Far", 22.2800 + 36 * 0.0001, 114.1500)
        db["routeList"]["rail+1+x+y"] = mk_route("rail+1+x+y", ["mtr"], {"mtr": rail_stops})
        tdb = tdb_factory(db)
        # R's own neighbors are all plain fillers -> hard cap at 30
        assert len(tdb._transfer_edges["R"]) == 30
        # F01 keeps its 30 nearest fillers PLUS the rail interchange R
        f01 = dict(tdb._transfer_edges["F01"])
        assert len(f01) == 31
        assert "R" in f01

    async def test_holidays_loaded(self, mod, tdb_factory):
        db = mini_db()
        db["holidays"] = ["20261001", "20261225"]
        tdb = tdb_factory(db)
        assert tdb._holidays == {"20261001", "20261225"}


class TestLookups:
    async def test_stop_lite_shape(self, mod, tdb_factory):
        tdb = tdb_factory()
        s = tdb.stop_lite("S_A")
        assert s["stop_id"] == "S_A"
        assert s["name"]["en"] == "South Terminus"
        assert s["name"]["zh"] == "南端總站"
        assert isinstance(s["location"]["lat"], float)
        assert s["display"] == "South Terminus"

    async def test_stop_lite_unknown(self, mod, tdb_factory):
        assert tdb_factory().stop_lite("NOPE") is None

    async def test_route_lite_shape(self, mod, tdb_factory):
        r = tdb_factory().route_lite("1+kmb+south+north")
        assert r["route"] == "1"
        assert r["co"] == ["kmb"]
        assert r["bound"] == {"kmb": "O"}
        assert r["orig"]["en"] == "South Terminus"

    async def test_route_lite_unknown(self, mod, tdb_factory):
        assert tdb_factory().route_lite("NOPE") is None

    async def test_nearby_sorted_and_limited(self, mod, tdb_factory):
        tdb = tdb_factory()
        near = tdb.nearby_stop_ids(22.2800, 114.1500, radius_m=600, limit=10)
        assert [s for s, _ in near][0] == "S_A"
        assert "S_B" in [s for s, _ in near]
        d = dict(near)
        assert d["S_A"] == pytest.approx(0.0, abs=1.0)
        near1 = tdb.nearby_stop_ids(22.2800, 114.1500, radius_m=600, limit=1)
        assert len(near1) == 1

    async def test_nearby_radius_filter(self, mod, tdb_factory):
        near = tdb_factory().nearby_stop_ids(22.2800, 114.1500, radius_m=100, limit=10)
        assert [s for s, _ in near] == ["S_A"]

    async def test_stop_distance_to_point(self, mod, tdb_factory):
        d = tdb_factory().stop_distance_to_point("S_A", 22.2800, 114.1500)
        assert d == pytest.approx(0.0, abs=1.0)
        assert tdb_factory().stop_distance_to_point("NOPE", 0, 0) is None


# ------------------------------------------------------------------
# DB load path (disk / primary / fallback / stale / failure)
# ------------------------------------------------------------------
def empty_ferry_cache(cache_dir: Path) -> None:
    seed_ferry_cache(cache_dir, {"stops": {}, "routes": {}, "route_stops": {}})


class TestLoadPath:
    async def test_disk_fresh_short_circuits(self, mod, tmp_cache, router):
        seed_transit_files(tmp_cache, mini_db(), fresh=True)
        empty_ferry_cache(tmp_cache)
        valves = make_valves(mod, tmp_cache)
        tdb = mod.TransitDB(mod.HTTPClient(valves, valves.cache_dir), valves)
        tdb.http._client = httpx.AsyncClient(transport=router.transport)
        try:
            await tdb.ensure_loaded()
            assert tdb._db_source == "disk"
            assert tdb._db_loaded is True
            assert "S_A" in tdb._stop_list
            assert router.calls("hkbus") == []
        finally:
            await tdb.http._client.aclose()

    async def test_stale_disk_downloads_from_primary(self, mod, tmp_cache, router):
        seed_transit_files(tmp_cache, mini_db(), fresh=False)
        empty_ferry_cache(tmp_cache)
        router.add(r"data\.hkbus\.app/routeFareList\.md5", text="aaaabbbbccccdddd")
        router.add(r"data\.hkbus\.app/routeFareList\.min\.json", json=mini_db())
        valves = make_valves(mod, tmp_cache)
        tdb = mod.TransitDB(mod.HTTPClient(valves, valves.cache_dir), valves)
        tdb.http._client = httpx.AsyncClient(transport=router.transport)
        try:
            await tdb.ensure_loaded()
            assert tdb._db_source == "https://data.hkbus.app"
            assert tdb._db_md5 == "aaaabbbbccccdddd"
        finally:
            await tdb.http._client.aclose()

    async def test_primary_failure_falls_back(self, mod, tmp_cache, router):
        seed_transit_files(tmp_cache, mini_db(), fresh=False)
        empty_ferry_cache(tmp_cache)
        router.add(r"data\.hkbus\.app/routeFareList\.md5", status=500, json={})
        router.add(r"hkbus\.github\.io/hk-bus-crawling/routeFareList\.md5", text="fallbackmd5")
        router.add(r"hkbus\.github\.io/hk-bus-crawling/routeFareList\.min\.json", json=mini_db())
        valves = make_valves(mod, tmp_cache)
        tdb = mod.TransitDB(mod.HTTPClient(valves, valves.cache_dir), valves)
        tdb.http._client = httpx.AsyncClient(transport=router.transport)
        try:
            await tdb.ensure_loaded()
            assert tdb._db_source == "https://hkbus.github.io/hk-bus-crawling"
        finally:
            await tdb.http._client.aclose()

    async def test_all_fail_uses_stale_disk(self, mod, tmp_cache, router):
        seed_transit_files(tmp_cache, mini_db(), fresh=False)
        empty_ferry_cache(tmp_cache)
        valves = make_valves(mod, tmp_cache)
        tdb = mod.TransitDB(mod.HTTPClient(valves, valves.cache_dir), valves)
        tdb.http._client = httpx.AsyncClient(transport=router.transport)
        try:
            db, source, _ = await tdb._load_hkbus_db()
            assert source == "disk_stale"
            assert "S_A" in db["stopList"]
        finally:
            await tdb.http._client.aclose()

    async def test_nothing_available_raises(self, mod, tmp_cache, router):
        valves = make_valves(mod, tmp_cache)
        tdb = mod.TransitDB(mod.HTTPClient(valves, valves.cache_dir), valves)
        tdb.http._client = httpx.AsyncClient(transport=router.transport)
        try:
            with pytest.raises(RuntimeError, match="hkbus"):
                await tdb.ensure_loaded()
        finally:
            await tdb.http._client.aclose()


# ------------------------------------------------------------------
# GTFS ferry merge
# ------------------------------------------------------------------
def gtfs_files(*, monday_only: bool = False, with_frequencies: bool = True, with_dup: bool = False) -> dict:
    cal_days = "1,0,0,0,0,0,0" if monday_only else "1,1,1,1,1,1,1"
    routes = "SF1,nwff,Central - Cheung Chau,Central - Cheung Chau,4\nBUS1,kmb,1,Random Bus,3\n"
    trips = "T1,SF1,0,S1\nT2,SF1,1,S1\nT3,BUS1,0,S1\n"
    stop_times = "T1,P1,1,07:00:00\nT1,P2,2,07:20:00\nT2,P2,1,07:30:00\nT2,P1,2,07:50:00\n"
    if with_dup:
        # same display name as SF1 -> collides unless deduped by fingerprint
        routes += "SF2,nwff,Central - Cheung Chau,Central - Cheung Chau,4\n"
        trips += "T4,SF2,0,S1\n"
        stop_times += "T4,P1,1,08:00:00\nT4,P2,2,08:20:00\n"
    files = {
        "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type\n" + routes,
        "trips.txt": "trip_id,route_id,direction_id,service_id\n" + trips,
        "calendar.txt": (
            f"service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday\nS1,{cal_days}\n"
        ),
        "stop_times.txt": "trip_id,stop_id,stop_sequence,departure_time\n" + stop_times,
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "P1,Central Pier,22.2878,114.1571\n"
            "P2,Cheung Chau Pier,22.2017,114.0289\n"
        ),
    }
    if with_frequencies:
        files["frequencies.txt"] = (
            "trip_id,start_time,end_time,headway_secs\nT1,07:00:00,19:00:00,1800\n"
        )
    return files


def serve_gtfs(router: Router, files: dict, *, tc_stops: str | None = None) -> None:
    en = gtfs_zip_bytes(files)
    tc_files = dict(files)
    tc_files["stops.txt"] = tc_stops or (
        "stop_id,stop_name,stop_lat,stop_lon\nP1,中環碼頭,22.2878,114.1571\nP2,長洲碼頭,22.2017,114.0289\n"
    )
    tc = gtfs_zip_bytes(tc_files)
    router.add(r"pt-headway-en/gtfs\.zip", content=en)
    router.add(r"pt-headway-tc/gtfs\.zip", content=tc)


class TestGtfsFerryMerge:
    async def test_merge_end_to_end(self, mod, tmp_cache, router, monkeypatch):
        patch_async_client(monkeypatch, mod, router)
        serve_gtfs(router, gtfs_files())
        valves = make_valves(mod, tmp_cache)
        tdb = mod.TransitDB(mod.HTTPClient(valves, valves.cache_dir), valves)
        await tdb.load_and_merge_gtfs_ferries()

        # two directions merged under unified ids with resolved route code CECC
        assert "CECC+1+Central Pier+Cheung Chau Pier" in tdb._route_list
        assert "CECC+1+Cheung Chau Pier+Central Pier" in tdb._route_list

        r = tdb._route_list["CECC+1+Central Pier+Cheung Chau Pier"]
        assert r["co"] == ["sunferry"]
        assert r["route"] == "CECC"
        assert r["stops"]["sunferry"] == ["P1", "P2"]
        assert r["orig"]["zh"] == "中環碼頭"
        # frequency window from frequencies.txt (30-min headway 07:00-19:00)
        assert r["freq"]["127"]["0700"] == ["1900", 30]
        # opposite direction: fixed departure at 07:30 (no frequency row)
        r2 = tdb._route_list["CECC+1+Cheung Chau Pier+Central Pier"]
        assert r2["freq"]["127"]["0730"] is None

        # bus route filtered, duplicate-name ferry filtered
        assert all("BUS1" not in rid for rid in tdb._route_list)

        # piers injected into stop list + indices
        assert tdb._stop_list["P1"]["name"]["zh"] == "中環碼頭"
        companies = {o.company for o in tdb._stop_to_routes["P1"]}
        assert companies == {"sunferry"}

        # ferry cache written
        cache_file = tmp_cache / "hk_gtfs_ferries_cache_v9.json"
        assert cache_file.exists()
        cached = json.loads(cache_file.read_text())
        assert "CECC+1+Central Pier+Cheung Chau Pier" in cached["routes"]

    async def test_duplicate_existing_fingerprint_skipped(self, mod, tmp_cache, router, monkeypatch):
        patch_async_client(monkeypatch, mod, router)
        serve_gtfs(router, gtfs_files(with_dup=True))
        valves = make_valves(mod, tmp_cache)
        tdb = mod.TransitDB(mod.HTTPClient(valves, valves.cache_dir), valves)
        # pre-seed an existing sunferry route with the same display name
        tdb._route_list["cc-exists+1+x+y"] = mk_route(
            "cc-exists+1+x+y", ["sunferry"], {"sunferry": ["OLD1", "OLD2"]}, route_no="Central - Cheung Chau"
        )
        await tdb.load_and_merge_gtfs_ferries()
        # SF1 and SF2 share the normalized name "Central-CheungChau" -> both skipped
        assert not any("CECC+1+" in rid for rid in tdb._route_list)

    async def test_monday_only_daymask(self, mod, tmp_cache, router, monkeypatch):
        patch_async_client(monkeypatch, mod, router)
        serve_gtfs(router, gtfs_files(monday_only=True))
        valves = make_valves(mod, tmp_cache)
        tdb = mod.TransitDB(mod.HTTPClient(valves, valves.cache_dir), valves)
        await tdb.load_and_merge_gtfs_ferries()
        r = tdb._route_list["CECC+1+Central Pier+Cheung Chau Pier"]
        assert "1" in r["freq"]  # Monday-only bitmask encoded as "1"

    async def test_missing_frequencies_tolerated(self, mod, tmp_cache, router, monkeypatch):
        patch_async_client(monkeypatch, mod, router)
        serve_gtfs(router, gtfs_files(with_frequencies=False))
        valves = make_valves(mod, tmp_cache)
        tdb = mod.TransitDB(mod.HTTPClient(valves, valves.cache_dir), valves)
        await tdb.load_and_merge_gtfs_ferries()
        r = tdb._route_list["CECC+1+Central Pier+Cheung Chau Pier"]
        assert r["freq"]["127"]["0700"] is None  # fixed 07:00 departure

    async def test_seeded_cache_skips_download(self, mod, tmp_cache, router, monkeypatch):
        patch_async_client(monkeypatch, mod, router)
        ferry = {
            "stops": {"Q1": {"stop_id": "Q1", "name": {"en": "Q Pier", "zh": "Q碼頭"}, "lat": 22.3, "lng": 114.2}},
            "routes": {
                "QC+1+Q+R": {
                    "gtfsId": "QC", "route_id": "QC+1+Q+R", "route": "QC", "company": "coralsea",
                    "co": ["coralsea"], "orig_tc": "Q", "orig_en": "Q Pier", "dest_tc": "R", "dest_en": "R Pier",
                    "orig": {"en": "Q Pier", "zh": "Q"}, "dest": {"en": "R Pier", "zh": "R"},
                    "service_type": 1, "serviceType": "1", "bound": {"coralsea": "O"},
                    "stops": {"coralsea": ["Q1"]}, "freq": {},
                }
            },
            "route_stops": {"QC+1+Q+R": ["Q1"]},
        }
        seed_ferry_cache(tmp_cache, ferry)
        valves = make_valves(mod, tmp_cache)
        tdb = mod.TransitDB(mod.HTTPClient(valves, valves.cache_dir), valves)
        await tdb.load_and_merge_gtfs_ferries()
        assert "QC+1+Q+R" in tdb._route_list
        assert tdb._stop_list["Q1"]["name"]["en"] == "Q Pier"
        assert mod.COMPANY_MODE["coralsea"] == "ferry"
        assert router.calls("gtfs") == []


# ------------------------------------------------------------------
# ETA fetchers
# ------------------------------------------------------------------
class TestEtaFetchers:
    async def test_kmb_filter_and_sort(self, mod, router, tdb_factory):
        router.add(
            r"etabus\.gov\.hk/v1/transport/kmb/eta/S_A/1/1",
            json={
                "data": [
                    {"eta": "2026-09-05T20:10:00+08:00", "dir": "O", "rmk_en": "ok"},
                    {"eta": "2026-09-05T20:05:00+08:00", "dir": "O"},
                    {"eta": "2026-09-05T20:07:00+08:00", "dir": "I"},
                ]
            },
        )
        tdb = tdb_factory()
        out = await tdb.fetch_kmb_etas("S_A", "1", "O", 0, "1")
        assert [e["eta"] for e in out] == ["2026-09-05T20:05:00+08:00", "2026-09-05T20:10:00+08:00"]

    async def test_kmb_service_type_fallback(self, mod, router, tdb_factory):
        r1 = router.add(r"etabus\.gov\.hk/v1/transport/kmb/eta/S_A/9/1", json={"data": []})
        r2 = router.add(r"etabus\.gov\.hk/v1/transport/kmb/eta/S_A/9/2", json={"data": [{"eta": "2026-09-05T21:00:00+08:00", "dir": "O"}]})
        tdb = tdb_factory()
        out = await tdb.fetch_kmb_etas("S_A", "9", "O", 0, "2")
        assert len(out) == 1
        assert len(r1.calls) == 1 and len(r2.calls) == 1

    async def test_ctb(self, mod, router, tdb_factory):
        router.add(
            r"citybus/eta/CTB/S_E/2",
            json={"data": [{"eta": "2026-09-05T18:30:00+08:00", "dir": "O"}, {"eta": "2026-09-05T18:40:00+08:00", "dir": "I"}]},
        )
        tdb = tdb_factory()
        out = await tdb.fetch_ctb_etas("S_E", "2", "O", 0)
        assert len(out) == 1 and out[0]["dir"] == "O"

    async def test_gmb(self, mod, router, tdb_factory):
        router.add(
            r"etagmb\.gov\.hk/eta/stop/S_A/2006-1",
            json={"data": [{"eta": "2026-09-05T19:00:00+08:00", "rmk_en": ""}]},
        )
        tdb = tdb_factory()
        out = await tdb.fetch_gmb_etas("S_A", "2006-1", "O", 0)
        assert len(out) == 1

    async def test_mtr_trains(self, mod, router, tdb_factory):
        router.add(
            r"mtr/getSchedule",
            json={
                "status": 1,
                "data": {
                    "ISL-S_B": {
                        "UP": [
                            {"valid": "Y", "ttnt": "3", "time": "2026-09-05 15:03:00", "dest": "CHW", "plat": "2", "seq": "1"},
                            {"valid": "N", "ttnt": "1", "time": "2026-09-05 15:01:00"},
                            {"valid": "Y", "ttnt": "", "time": "2026-09-05 15:20:00", "dest": "HKD", "plat": "1"},
                        ],
                        "DOWN": [{"valid": "Y", "ttnt": "6", "time": "2026-09-05 15:06:00", "dest": "HKD", "plat": "1"}],
                    }
                },
            },
        )
        tdb = tdb_factory()
        out = await tdb.fetch_mtr_next_trains("ISL", "S_B")
        assert len(out) == 3  # invalid entry dropped
        assert out[0]["minutes"] == 3 and out[0]["direction"] == "UP"
        assert out[-1]["minutes"] is None  # empty ttnt sorts last
        assert out[0]["iso"].startswith("2026-09-05T15:03:00+08:00")

    async def test_mtr_status_zero_message(self, mod, router, tdb_factory):
        router.add(r"mtr/getSchedule", json={"status": 0, "message": "Service delayed", "url": "https://mtr"})
        tdb = tdb_factory()
        out = await tdb.fetch_mtr_next_trains("ISL", "S_B")
        assert len(out) == 1
        assert out[0]["message"] == "Service delayed"
        assert out[0]["minutes"] is None

    async def test_mtr_empty_line(self, mod, tdb_factory):
        assert await tdb_factory().fetch_mtr_next_trains("", "S_B") == []

    async def test_lrt(self, mod, router, tdb_factory):
        router.add(
            r"mtr/lrt/getSchedule",
            json={
                "platform_list": [
                    {
                        "platform_id": "1",
                        "route_list": [
                            {"route_no": "507", "dest_en": "Tin Shui Wai", "dest_ch": "天水圍", "time_en": "5 min", "train_length": "2", "arrival_departure": "A"},
                            {"route_no": "610", "dest_en": "Yuen Long", "dest_ch": "元朗", "time_en": "3 min", "train_length": "1", "arrival_departure": "D"},
                        ],
                    }
                ]
            },
        )
        tdb = tdb_factory()
        out = await tdb.fetch_lrt_next_trains(1520)
        assert [x["route_no"] for x in out] == ["610", "507"]  # 3 min before 5 min
        assert out[0]["minutes"] == 3 and out[0]["platform"] == "1"

    async def test_lrt_nonpositive_station(self, mod, tdb_factory):
        assert await tdb_factory().fetch_lrt_next_trains(0) == []

    async def test_mtr_bus(self, mod, router, tdb_factory):
        r = router.add(
            r"mtr/bus/getSchedule",
            json={
                "busStop": [
                    {
                        "busStopId": "HP01",
                        "bus": [
                            {"departureTimeInSecond": "240", "departureTimeText": "4 min", "isDelayed": False, "isScheduled": True, "busRemark": "", "lineRef": "K14", "busId": "X1"},
                            {"departureTimeInSecond": "abc", "departureTimeText": "arriving", "busRemark": "late", "lineRef": "K14", "busId": "X2"},
                        ],
                    },
                    {"busStopId": "OTHER", "bus": [{"departureTimeInSecond": "60"}]},
                ]
            },
        )
        tdb = tdb_factory()
        out = await tdb.fetch_mtr_bus_next_buses("K14", "HP01")
        assert len(out) == 2
        assert out[0]["minutes"] == 4
        assert out[1]["minutes"] is None and out[1]["remark"] == "late"
        import json as j

        assert j.loads(r.calls[0].read()) == {"language": "en", "routeName": "K14"}
        assert r.calls[0].method == "POST"

    async def test_sunferry(self, mod, router, tdb_factory):
        router.add(
            r"sunferry\.com\.hk/eta/",
            json={
                "generated_timestamp": "2026-09-05T11:00:00+08:00",
                "data": [
                    {"eta": "11:15", "depart_time": "11:10", "route_en": "Central - Cheung Chau", "rmk_en": "", "vesselcode": "V1"},
                    {"eta": "11:05", "depart_time": "11:00", "route_en": "Central - Cheung Chau", "rmk_en": "x"},
                ],
            },
        )
        tdb = tdb_factory()
        out = await tdb.fetch_sunferry_next_trip("CECC")
        assert [x["minutes"] for x in out] == [5, 15]
        assert out[0]["eta_hhmm"] == "11:05"

    async def test_fortuneferry(self, mod, router, tdb_factory):
        router.add(
            r"hongkongwatertaxi\.com\.hk/eta/",
            json={
                "generated_timestamp": "2026-09-05T11:00:00+08:00",
                "data": [{"eta": "11:40", "depart_time": "11:35", "route_en": "Central - Hung Hom", "rmk_tc": "延誤"}],
            },
        )
        tdb = tdb_factory()
        out = await tdb.fetch_fortuneferry_next_trip("7059", lang="tc")
        assert out[0]["minutes"] == 40
        assert out[0]["remark"] == "延誤"

    async def test_hkkf(self, mod, router, tdb_factory, freezer):
        from freezegun import freeze_time

        router.add(
            r"hkkfeta\.com/opendata/eta/123/outbound",
            json={"data": [{"ETA": "2026-09-05T20:30:00+08:00", "route_id": "123", "direction": "outbound", "session_time": "20:30", "date": "2026-09-05"}]},
        )
        tdb = tdb_factory()
        with freeze_time(datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)):
            out = await tdb.fetch_hkkf_next_trip("123", "outbound")
        assert out[0]["minutes"] == 30

    async def test_hkkf_non_digit_route(self, mod, router, tdb_factory):
        out = await tdb_factory().fetch_hkkf_next_trip("KF1", "outbound")
        assert out == []
        assert router.calls("hkkfeta") == []

    async def test_error_yields_empty_list(self, mod, router, tdb_factory):
        router.add(r"etabus\.gov\.hk", status=500, json={})
        tdb = tdb_factory()
        assert await tdb.fetch_kmb_etas("S_A", "1", "O", 0, "1") == []


# ------------------------------------------------------------------
# leg_next_departures dispatcher
# ------------------------------------------------------------------
class TestLegNextDepartures:
    async def test_kmb_leg(self, mod, router, tdb_factory, freezer):
        from freezegun import freeze_time

        router.add(
            r"kmb/eta/S_A/1/1",
            json={"data": [{"eta": "2026-09-05T20:10:00+08:00", "dir": "O", "rmk_en": "on time", "rmk_tc": "準時"}]},
        )
        tdb = tdb_factory()
        with freeze_time(datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)):
            rows = await tdb.leg_next_departures("kmb", "1+kmb+south+north", "S_A", 0, limit_etas=2)
        assert len(rows) == 1
        row = rows[0]
        assert row["route"] == "1" and row["company"] == "kmb" and row["mode"] == "bus"
        assert row["eta"]["minutes"] == 10
        assert row["eta"]["text"] == "10 min"
        assert row["remark"] == {"en": "on time", "zh": "準時"}
        assert row["direction"] == "O"

    async def test_gmb_without_gtfs_id(self, mod, tdb_factory):
        db = mini_db()
        db["routeList"]["3+gmb+direct"].pop("gtfsId")
        tdb = tdb_factory(db)
        assert await tdb.leg_next_departures("gmb", "3+gmb+direct", "S_A", 0) == []

    async def test_mtr_leg(self, mod, router, tdb_factory):
        router.add(
            r"mtr/getSchedule",
            json={"status": 1, "data": {"ISL-S_B": {"UP": [{"valid": "Y", "ttnt": "3", "time": "2026-09-05 15:03:00", "dest": "CHW", "plat": "2"}]}}},
        )
        tdb = tdb_factory()
        rows = await tdb.leg_next_departures("mtr", "ISL+1+a+b", "S_B", 0, limit_etas=2)
        assert rows[0]["company"] == "mtr" and rows[0]["mode"] == "rail"
        assert rows[0]["platform"] == "2" and rows[0]["dest"] == "CHW"

    async def test_lightrail_leg_filters_route(self, mod, router, tdb_factory):
        router.add(
            r"mtr/lrt/getSchedule",
            json={"platform_list": [{"platform_id": "2", "route_list": [
                {"route_no": "507", "dest_en": "Tin Shui Wai", "time_en": "4 min"},
                {"route_no": "610", "dest_en": "Yuen Long", "time_en": "9 min"},
            ]}]},
        )
        tdb = tdb_factory()
        rows = await tdb.leg_next_departures("lightrail", "507+1+lrt", "1520", 0, limit_etas=5)
        assert [r["route"] for r in rows] == ["507"]
        assert rows[0]["eta"]["minutes"] == 4

    async def test_lightrail_non_numeric_stop(self, mod, tdb_factory):
        assert await tdb_factory().leg_next_departures("lightrail", "507+1+lrt", "S_A", 0) == []

    async def test_lrtfeeder_leg(self, mod, router, tdb_factory):
        db = mini_db()
        db["routeList"]["K14+1+feeder"] = mk_route("K14+1+feeder", ["lrtfeeder"], {"lrtfeeder": ["HP01"]}, route_no="K14")
        db["stopList"]["HP01"] = mk_stop("HP01", "Hospital Stop", 22.2850, 114.1510)
        router.add(
            r"mtr/bus/getSchedule",
            json={"busStop": [{"busStopId": "HP01", "bus": [{"departureTimeInSecond": "120", "departureTimeText": "2 min", "lineRef": "K14"}]}]},
        )
        tdb = tdb_factory(db)
        rows = await tdb.leg_next_departures("lrtfeeder", "K14+1+feeder", "HP01", 0, limit_etas=2)
        assert rows[0]["company"] == "lrtfeeder" and rows[0]["eta"]["minutes"] == 2

    async def test_ferry_legs(self, mod, router, tdb_factory):
        db = mini_db()
        db["routeList"]["CECC+1+c+c"] = mk_route("CECC+1+c+c", ["sunferry"], {"sunferry": ["P1", "P2"]}, route_no="CECC")
        db["routeList"]["7059+1+h+k"] = mk_route("7059+1+h+k", ["fortuneferry"], {"fortuneferry": ["P3"]}, route_no="7059")
        db["routeList"]["123+1+kf"] = mk_route("123+1+kf", ["hkkf"], {"hkkf": ["P4"]}, route_no="123", bound={"hkkf": "inbound"})
        db["stopList"].update({
            "P1": mk_stop("P1", "Central Pier", 22.2878, 114.1571),
            "P2": mk_stop("P2", "Cheung Chau Pier", 22.2017, 114.0289),
            "P3": mk_stop("P3", "Hung Hom Pier", 22.2937, 114.1730),
            "P4": mk_stop("P4", "Sok Kwu Wan", 22.2244, 114.2661),
        })
        router.add(r"sunferry\.com\.hk/eta/", json={"generated_timestamp": "2026-09-05T11:00:00+08:00", "data": [{"eta": "11:15"}]})
        router.add(r"hongkongwatertaxi\.com\.hk/eta/", json={"generated_timestamp": "2026-09-05T11:00:00+08:00", "data": [{"eta": "11:25"}]})
        router.add(r"hkkfeta\.com/opendata/eta/123/inbound", json={"data": [{"ETA": "2026-09-05T20:45:00+08:00"}]})
        tdb = tdb_factory(db)

        sf = await tdb.leg_next_departures("sunferry", "CECC+1+c+c", "P1", 0, limit_etas=2)
        assert sf[0]["company"] == "sunferry" and sf[0]["eta"]["minutes"] == 15
        ff = await tdb.leg_next_departures("fortuneferry", "7059+1+h+k", "P3", 0, limit_etas=2)
        assert ff[0]["company"] == "fortuneferry" and ff[0]["eta"]["minutes"] == 25

        from freezegun import freeze_time

        with freeze_time(datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)):
            kf = await tdb.leg_next_departures("hkkf", "123+1+kf", "P4", 0, limit_etas=2)
        assert kf[0]["company"] == "hkkf" and kf[0]["direction"] == "inbound" and kf[0]["eta"]["minutes"] == 45

    async def test_unknown_company(self, mod, tdb_factory):
        assert await tdb_factory().leg_next_departures("zeppelin", "1+kmb+south+north", "S_A", 0) == []
