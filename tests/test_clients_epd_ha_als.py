"""Client tests: EPD normalizers/fetches, HA aliases, ALS formatting + error mapping."""

from __future__ import annotations

import httpx
import pytest

ALS_SUGGESTION = {
    "Address": {
        "PremisesAddress": {
            "GeoAddress": "3508215732T20110704",
            "EngPremisesAddress": {
                "BuildingName": "Central Plaza",
                "EngStreet": {"StreetName": "Harbour Road", "BuildingNoFrom": "18"},
                "EngDistrict": {"DcDistrict": "Wan Chai"},
                "Region": "HONG KONG",
            },
            "ChiPremisesAddress": {
                "BuildingName": "中央廣場",
                "ChiStreet": {"StreetName": "港灣道", "BuildingNoFrom": "18"},
                "ChiDistrict": {"DcDistrict": "灣仔"},
                "Region": "香港",
            },
            "GeospatialInformation": {
                "Easting": "836000",
                "Northing": "816000",
                "Latitude": "22.279",
                "Longitude": "114.173",
            },
        }
    },
    "ValidationInformation": {"Score": 100, "Address_Type": "RESIDENTIAL", "Address_Status": "V"},
}


# ------------------------------------------------------------------
# EPD client
# ------------------------------------------------------------------
class TestEpdNormalizers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Central/Western", "centralwestern"),
            ("central western", "centralwestern"),
            ("中西區", "centralwestern"),
            ("Causeway Bay", "causewaybay"),
            ("銅鑼灣", "causewaybay"),
            ("Mong Kok", "mongkok"),
            ("", None),
            (None, None),
            ("unknown station", None),
        ],
    )
    def test_station_aliases(self, mocked_tools, raw, expected):
        assert mocked_tools.epd._normalize_station_name(raw) == expected

    @pytest.mark.parametrize(
        ("risk", "en", "zh"),
        [("Low", "Low", "低"), ("Very High", "Very High", "甚高"), ("Weird", "Weird", "Weird")],
    )
    def test_health_risk_translation(self, mocked_tools, risk, en, zh):
        assert mocked_tools.epd._translate_health_risk(risk) == {"en": en, "zh": zh}

    def test_station_info_bilingual(self, mocked_tools):
        info = mocked_tools.epd._get_station_info("causewaybay")
        assert info == {"en": "Causeway Bay", "zh": "銅鑼灣"}
        assert mocked_tools.epd._get_station_info("nope") == {"en": "nope", "zh": "nope"}

    def test_scale_explanation(self, mocked_tools):
        scale = mocked_tools.epd.get_scale_explanation()
        assert len(scale["levels"]) == 5
        assert scale["levels"][0]["risk"] == {"en": "Low", "zh": "低"}


class TestEpdFetchers:
    async def test_city_dashboard(self, mocked_tools, router):
        router.add(r"aqhi\.json", json=[{"type": "general", "aqhi_min": 3}])
        out = await mocked_tools.epd.fetch_city_dashboard()
        assert out == [{"type": "general", "aqhi_min": 3}]

    async def test_individual_params(self, mocked_tools, router):
        r = router.add(r"aqhi-individual", json=[])
        await mocked_tools.epd.fetch_individual_stations()
        assert dict(r.calls[0].url.params) == {"format": "json"}

    async def test_error_returns_empty(self, mocked_tools, router):
        router.add(r"datagovhk\.blob\.core\.windows\.net", status=500, json={})
        assert await mocked_tools.epd.fetch_city_dashboard() == []
        assert await mocked_tools.epd.fetch_individual_stations() == []
        assert await mocked_tools.epd.fetch_forecast() == []


# ------------------------------------------------------------------
# HA client
# ------------------------------------------------------------------
class TestHaClient:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("qeh", "Queen Elizabeth Hospital"),
            ("pym", "Pamela Youde Nethersole Eastern Hospital"),
            ("Queen Elizabeth Hospital", "Queen Elizabeth Hospital"),
            ("", None),
            ("not a hospital", None),
        ],
    )
    def test_hospital_aliases(self, mocked_tools, raw, expected):
        assert mocked_tools.ha._normalize_hospital_name(raw) == expected

    @pytest.mark.parametrize(
        ("lang", "url_part"),
        [("en", "aedwtdata2-en.json"), ("tc", "aedwtdata2-tc.json"), ("sc", "aedwtdata2-sc.json")],
    )
    async def test_lang_url_selection(self, mocked_tools, router, lang, url_part):
        r = router.add(r"aedwtdata2-", json={"waitTime": [], "updateTime": "t"})
        out = await mocked_tools.ha.fetch_waiting_times(lang=lang)
        assert url_part in str(r.calls[0].url)
        assert out["updateTime"] == "t"

    async def test_error_returns_empty_shape(self, mocked_tools, router):
        router.add(r"ha\.org\.hk", status=500, json={})
        out = await mocked_tools.ha.fetch_waiting_times()
        assert out == {"waitTime": [], "updateTime": None}

    def test_triage_info(self, mocked_tools):
        info = mocked_tools.ha.get_triage_info()
        assert set(info.keys()) >= {"t1", "t2", "t3", "t4", "t5"}


# ------------------------------------------------------------------
# ALS client (direct httpx path via shared mocked client)
# ------------------------------------------------------------------
class TestAlsFormatting:
    def test_english_order(self, mocked_tools):
        premises = ALS_SUGGESTION["Address"]["PremisesAddress"]["EngPremisesAddress"]
        assert mocked_tools.als._format_address(premises, "en") == (
            "Central Plaza, 18 Harbour Road, Wan Chai, HONG KONG"
        )

    def test_chinese_order(self, mocked_tools):
        premises = ALS_SUGGESTION["Address"]["PremisesAddress"]["ChiPremisesAddress"]
        assert mocked_tools.als._format_address(premises, "tc") == "香港灣仔港灣道 18 號中央廣場"

    def test_parse_premises(self, mocked_tools):
        addr = ALS_SUGGESTION["Address"]["PremisesAddress"]
        parsed = mocked_tools.als._parse_premises(addr)
        assert parsed["en"]["building_name"] == "Central Plaza"
        assert parsed["en"]["street"] == {"name": "Harbour Road", "number": "18"}
        assert parsed["en"]["district"] == "Wan Chai"
        assert parsed["zh"]["building_name"] == "中央廣場"
        assert parsed["zh"]["region"] == "香港"

    def test_transform_suggestion(self, mocked_tools):
        out = mocked_tools.als._transform_suggestion(ALS_SUGGESTION, "en")
        assert out["address"]["formatted"] == "Central Plaza, 18 Harbour Road, Wan Chai, HONG KONG"
        assert out["geoaddress"] == "3508215732T20110704"
        assert out["coordinates"]["hk1980"] == {"easting": 836000.0, "northing": 816000.0}
        assert out["coordinates"]["wgs84"] == {"lat": 22.279, "lon": 114.173}
        assert out["score"] == 100
        assert out["validation_info"] == {"address_type": "RESIDENTIAL", "address_status": "V"}

    def test_transform_suggestion_chinese(self, mocked_tools):
        out = mocked_tools.als._transform_suggestion(ALS_SUGGESTION, "tc")
        assert out["address"]["language"] == "tc"
        assert out["address"]["formatted"].endswith("中央廣場")


class TestAlsLookups:
    async def test_address_lookup_happy(self, mocked_tools, router):
        r = router.add(r"als\.gov\.hk/lookup", json={"SuggestedAddress": [ALS_SUGGESTION], "RequestAddress": {"AddressLine": ["central plaza"]}})
        out = await mocked_tools.als.address_lookup("central plaza", n=10)
        assert out["total_suggestions"] == 1
        assert out["suggestions"][0]["geoaddress"] == "3508215732T20110704"
        sent = dict(r.calls[0].url.params)
        assert sent["q"] == "central plaza" and sent["n"] == "10"

    @pytest.mark.parametrize(
        ("status", "error"),
        [
            (400, "bad_request"),
            (413, "payload_too_large"),
            (429, "rate_limited"),
            (406, "not_acceptable"),
        ],
    )
    async def test_address_lookup_error_mapping(self, mocked_tools, router, status, error):
        router.add(r"als\.gov\.hk/lookup", status=status, json={})
        out = await mocked_tools.als.address_lookup("x")
        assert out["error"] == error

    async def test_geoaddress_happy(self, mocked_tools, router):
        router.add(r"als\.gov\.hk/lookup", json={"SuggestedAddress": [ALS_SUGGESTION]})
        out = await mocked_tools.als.geoaddress_lookup("3508215732T20110704")
        assert out["request_geoaddress"] == "3508215732T20110704"
        assert out["suggestions"][0]["geoaddress"] == "3508215732T20110704"

    async def test_geoaddress_wrong_length(self, mocked_tools, router):
        out = await mocked_tools.als.geoaddress_lookup("too-short")
        assert out["error"] == "invalid_geoaddress"
        assert router.calls("als") == []

    @pytest.mark.parametrize(("status", "error"), [(400, "bad_request"), (429, "rate_limited")])
    async def test_geoaddress_error_mapping(self, mocked_tools, router, status, error):
        router.add(r"als\.gov\.hk/lookup", status=status, json={})
        out = await mocked_tools.als.geoaddress_lookup("3508215732T20110704")
        assert out["error"] == error
