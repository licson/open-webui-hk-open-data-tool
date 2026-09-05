"""Tool-layer tests: landsd_*, epd_*, ha_*, dpo_* wrappers with mocked payloads."""

from __future__ import annotations

import pytest

from test_clients_epd_ha_als import ALS_SUGGESTION

LOCATION_ROW = {
    "nameEN": "Star Ferry Pier",
    "nameZH": "天星碼頭",
    "addressEN": "Man Kwong Street",
    "addressZH": "民光街",
    "districtEN": "Central",
    "districtZH": "中環",
    "x": 834000,
    "y": 817000,
}

CITY_DASHBOARD = [
    {"type": "general", "aqhi_min": 3, "aqhi_max": 4, "health_risk_min": "Low", "health_risk_max": "Moderate", "publish_date": "2026-09-05"},
    {"type": "roadside", "aqhi_min": 5, "aqhi_max": 5, "health_risk_max": "Moderate", "publish_date": "2026-09-05"},
]

INDIVIDUAL_STATIONS = [
    {"station": "Central/Western", "aqhi": 4, "health_risk": "Moderate", "publish_date": "2026-09-05"},
    {"station": "Causeway Bay", "aqhi": 7, "health_risk": "High", "publish_date": "2026-09-05"},
    {"station": "Mong Kok", "aqhi": 5, "health_risk": "Moderate", "publish_date": "2026-09-05"},
    {"station": "Sha Tin", "aqhi": 2, "health_risk": "Low", "publish_date": "2026-09-05"},
]

FORECAST = [
    {"type": "general", "date": "2026-09-06", "time": "P.M.", "health_risk_min": "Moderate", "health_risk_max": "High", "publish_date": "2026-09-05"},
    {"type": "general", "date": "2026-09-06", "time": "A.M.", "health_risk_min": "Low", "health_risk_max": "Low", "publish_date": "2026-09-05"},
    {"type": "roadside", "date": "2026-09-06", "time": "A.M.", "health_risk_min": "Moderate", "health_risk_max": "Moderate", "publish_date": "2026-09-05"},
]

AED_PAYLOAD = {
    "updateTime": "2026-09-05T12:00:00",
    "waitTime": [
        {
            "hospName": "Queen Elizabeth Hospital",
            "t1wt": "immediate", "manageT1case": "Y",
            "t2wt": "< 15 minutes", "manageT2case": "Y",
            "t3p50": "2.5 hours", "t3p95": "4 hours",
            "t45p50": "33 minutes", "t45p95": "1 hours",
        },
        {
            "hospName": "Princess Margaret Hospital",
            "t1wt": "immediate", "manageT1case": "N",
            "t2wt": "< 15 minutes", "manageT2case": "Y",
            "t3p50": "33 minutes", "t3p95": "1 hours",
            "t45p50": "10 minutes", "t45p95": "30 minutes",
        },
    ],
}


@pytest.fixture()
def landsd_router(router):
    router.add(r"map\.gov\.hk/gs/api/v1\.0\.0/locationSearch", json=[LOCATION_ROW, LOCATION_ROW, LOCATION_ROW])
    router.add(r"map\.gov\.hk/gs/api/v1\.0\.0/searchNearby",
               json=[{"name": "Cafe", "address": "1 Main Street", "x": 834001, "y": 817001,
                      "additionalInfoKey": ["opening"], "additionalInfoValue": ["<b>09:00</b> - 18:00"]}])
    router.add(r"geodetic\.gov\.hk/transform/v2/",
               json={"wgsLat": 22.2805, "wgsLong": 114.1502, "hkE": 834000, "hkN": 817000})
    return router


@pytest.fixture()
def epd_router(router):
    router.add(r"dataset/aqhi/aqhi\.json", json=CITY_DASHBOARD)
    router.add(r"aqhi-individual", json=INDIVIDUAL_STATIONS)
    router.add(r"aqhi-forecast\.json", json=FORECAST)
    return router


@pytest.fixture()
def ha_router(router):
    router.add(r"aedwtdata2-en\.json", json=AED_PAYLOAD)
    router.add(r"aedwtdata2-tc\.json", json=AED_PAYLOAD)
    return router


# ------------------------------------------------------------------
# landsd_*
# ------------------------------------------------------------------
class TestLandsdLocationSearch:
    async def test_shape_and_transform(self, mocked_tools, landsd_router):
        out = await mocked_tools.landsd_location_search("Star Ferry Pier")
        assert out["query"] == "Star Ferry Pier"
        item = out["items"][0]
        assert item["name"] == {"en": "Star Ferry Pier", "zh": "天星碼頭"}
        assert item["hk1980"] == {"x": 834000.0, "y": 817000.0}
        assert item["wgs84"] == {"lat": 22.2805, "lon": 114.1502}

    async def test_limit_applied(self, mocked_tools, landsd_router):
        out = await mocked_tools.landsd_location_search("Star Ferry Pier", limit=2)
        assert len(out["items"]) == 2

    async def test_empty_result(self, mocked_tools, router):
        router.add(r"locationSearch", json=[])
        out = await mocked_tools.landsd_location_search("nothing")
        assert out["items"] == []


class TestLandsdSearchNearby:
    async def test_success_with_html_stripping(self, mocked_tools, landsd_router):
        out = await mocked_tools.landsd_search_nearby(lat=22.2805, lon=114.1502)
        assert "error" not in out
        assert out["transformed_hk1980"] == {"x": 834000.0, "y": 817000.0}
        item = out["items"][0]
        assert item["additional_info"]["opening"] == "09:00 - 18:00"
        assert item["wgs84"] == {"lat": 22.2805, "lon": 114.1502}

    async def test_transform_failure(self, mocked_tools, router):
        router.add(r"geodetic\.gov\.hk/transform/v2/", json={})  # no coords -> None
        out = await mocked_tools.landsd_search_nearby(lat=22.28, lon=114.15)
        assert out["error"] == "Coordinate transformation failed"
        assert out["items"] == []


# ------------------------------------------------------------------
# epd_*
# ------------------------------------------------------------------
class TestEpdAqhiCurrent:
    async def test_city_summary_ranges(self, mocked_tools, epd_router):
        out = await mocked_tools.epd_aqhi_current()
        assert out["city_summary"]["general"]["aqhi_range"] == "3-4"
        assert out["city_summary"]["roadside"]["aqhi_range"] == "5"
        assert out["city_summary"]["general"]["health_risk"] == {"en": "Moderate", "zh": "中"}
        assert out["total_stations"] == 4
        assert out["scale_explanation"]["levels"]

    async def test_stations_sorted_desc(self, mocked_tools, epd_router):
        out = await mocked_tools.epd_aqhi_current()
        aqhis = [s["aqhi"] for s in out["stations"]]
        assert aqhis == sorted(aqhis, reverse=True)
        assert out["stations"][0]["name"] == {"en": "Causeway Bay", "zh": "銅鑼灣"}

    async def test_fuzzy_station_filter_chinese(self, mocked_tools, epd_router):
        out = await mocked_tools.epd_aqhi_current(station="沙田")
        assert out["total_stations"] == 1
        assert out["stations"][0]["name"]["en"] == "Sha Tin"

    async def test_type_filter_roadside_inference(self, mocked_tools, epd_router):
        out = await mocked_tools.epd_aqhi_current(type_filter="roadside")
        names = {s["name"]["en"] for s in out["stations"]}
        # only the hardcoded roadside trio is inferred as roadside
        assert names == {"Causeway Bay", "Mong Kok"}

    async def test_type_filter_general(self, mocked_tools, epd_router):
        out = await mocked_tools.epd_aqhi_current(type_filter="general")
        names = {s["name"]["en"] for s in out["stations"]}
        # NB: slash-named stations echo their raw key (EPD_AQHI_STATIONS has no
        # "central/western" entry) -- documented behavior, not a test artifact.
        assert names == {"central/western", "Sha Tin"}

    async def test_fetch_error_empty(self, mocked_tools, router):
        router.add(r"datagovhk", status=500, json={})
        router.add(r"aqhi-individual", status=500, json={})
        out = await mocked_tools.epd_aqhi_current()
        assert out["stations"] == [] and out["city_summary"] == {}


class TestEpdAqhiForecast:
    async def test_am_sorted_first(self, mocked_tools, epd_router):
        out = await mocked_tools.epd_aqhi_forecast()
        general = out["forecasts"]["general"]
        assert general[0]["time_period"] == "A.M."
        assert general[1]["time_period"] == "P.M."
        assert general[0]["health_risk_range"] == {
            "min": {"en": "Low", "zh": "低"},
            "max": {"en": "Low", "zh": "低"},
        }

    async def test_type_filter(self, mocked_tools, epd_router):
        out = await mocked_tools.epd_aqhi_forecast(type_filter="roadside")
        assert set(out["forecasts"].keys()) == {"roadside"}


# ------------------------------------------------------------------
# ha_*
# ------------------------------------------------------------------
class TestHaAedWaitingTime:
    async def test_all_categories(self, mocked_tools, ha_router):
        out = await mocked_tools.ha_aed_waiting_time()
        assert out["total_hospitals"] == 2
        assert out["update_time"] == "2026-09-05T12:00:00"
        qeh = out["hospitals"][0]  # sorted by T3 median: 150 min first
        assert qeh["name"] == "Queen Elizabeth Hospital"
        wt = qeh["waiting_times"]
        assert wt["t1"]["waiting_time"] == "immediate" and wt["t1"]["managing_cases"] is True
        assert wt["t3"]["median_wait"] == "2.5 hours"
        assert wt["t4"]["median_wait"] == "33 minutes"
        assert out["hospitals"][1]["name"] == "Princess Margaret Hospital"

    async def test_hospital_alias_filter(self, mocked_tools, ha_router):
        out = await mocked_tools.ha_aed_waiting_time(hospital="qeh")
        assert out["total_hospitals"] == 1
        assert out["hospitals"][0]["name"] == "Queen Elizabeth Hospital"
        assert out["filters_applied"]["hospital"] == "qeh"

    async def test_triage_t3_only(self, mocked_tools, ha_router):
        out = await mocked_tools.ha_aed_waiting_time(triage_category="t3")
        for h in out["hospitals"]:
            assert set(h["waiting_times"].keys()) == {"t3"}

    async def test_triage_t5_uses_t45_fields(self, mocked_tools, ha_router):
        out = await mocked_tools.ha_aed_waiting_time(triage_category="t5")
        assert set(out["hospitals"][0]["waiting_times"].keys()) == {"t5"}
        assert out["hospitals"][0]["waiting_times"]["t5"]["median_wait"] == "33 minutes"

    async def test_lang_tc(self, mocked_tools, ha_router):
        out = await mocked_tools.ha_aed_waiting_time(lang="tc")
        assert out["total_hospitals"] == 2
        assert ha_router.calls("aedwtdata2-tc")


# ------------------------------------------------------------------
# dpo_*
# ------------------------------------------------------------------
class TestDpoAddressLookup:
    async def test_happy(self, mocked_tools, router):
        router.add(r"als\.gov\.hk/lookup",
                   json={"SuggestedAddress": [ALS_SUGGESTION], "RequestAddress": {"AddressLine": ["central plaza"]}})
        out = await mocked_tools.dpo_address_lookup("central plaza", limit=5)
        assert out["total_suggestions"] == 1
        s = out["suggestions"][0]
        assert s["geoaddress"] == "3508215732T20110704"
        assert s["address"]["formatted"] == "Central Plaza, 18 Harbour Road, Wan Chai, HONG KONG"
        assert out["query"] == "central plaza"

    async def test_params_forwarded(self, mocked_tools, router):
        r = router.add(r"als\.gov\.hk/lookup", json={"SuggestedAddress": []})
        await mocked_tools.dpo_address_lookup("queen's road", limit=7, tolerance=40, basic_mode=True)
        sent = dict(r.calls[0].url.params)
        assert sent["n"] == "7" and sent["t"] == "40" and sent["b"] == "1"

    async def test_error_passthrough(self, mocked_tools, router):
        router.add(r"als\.gov\.hk/lookup", status=413, json={})
        out = await mocked_tools.dpo_address_lookup("x" * 300)
        assert out["error"] == "payload_too_large"
        assert out["meta"]["tool"] == "Hong Kong Open Data"


class TestDpoGeoaddressLookup:
    async def test_happy(self, mocked_tools, router):
        router.add(r"als\.gov\.hk/lookup", json={"SuggestedAddress": [ALS_SUGGESTION]})
        out = await mocked_tools.dpo_geoaddress_lookup("3508215732T20110704")
        assert out["suggestions"][0]["geoaddress"] == "3508215732T20110704"

    async def test_length_validation(self, mocked_tools, router):
        out = await mocked_tools.dpo_geoaddress_lookup("short")
        assert out["error"] == "invalid_geoaddress"
        assert router.calls("als") == []
