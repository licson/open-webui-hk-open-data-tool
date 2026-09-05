"""hko_* tool tests: validation matrix, wrapper delegation, passthrough shapes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

HK = timezone(timedelta(hours=8))

OPENDATA_RX = r"data\.weather\.gov\.hk/weatherAPI/opendata/opendata\.php"


def register_hko(router):
    router.add(OPENDATA_RX, text="STATION,YEAR,VALUE\nCCH,2025,2.1\n")
    router.add(r"weather\.php", json={"payload": "weather"})
    router.add(r"earthquake\.php", json={"payload": "quake"})
    router.add(r"lunardate\.php", json={"LunarDate": "2026-07-19", "Year": "丙午"})
    router.add(r"hourlyRainfall\.php", json={"payload": "rain"})


# ------------------------------------------------------------------
# hko_opendata: pure validation (no HTTP expected)
# ------------------------------------------------------------------
class TestHkoOpendataValidation:
    async def test_year_range(self, mocked_tools):
        out = await mocked_tools.hko_opendata(data_type="SRS", year=1799)
        assert out == {"error": "bad_request", "detail": "year must be between 1800 and 2100."}
        out = await mocked_tools.hko_opendata(data_type="SRS", year=2101)
        assert out["error"] == "bad_request"

    @pytest.mark.parametrize(
        ("kwargs", "detail_part"),
        [
            ({"month": 13}, "month must be between"),
            ({"day": 0}, "day must be between"),
            ({"hour": 25}, "hour must be between"),
        ],
    )
    async def test_scalar_ranges(self, mocked_tools, kwargs, detail_part):
        out = await mocked_tools.hko_opendata(data_type="SRS", year=2025, **kwargs)
        assert out["error"] == "bad_request"
        assert detail_part in out["detail"]

    async def test_non_integer_year(self, mocked_tools):
        out = await mocked_tools.hko_opendata(data_type="SRS", year="twenty")
        assert out["error"] == "bad_request"

    async def test_month_requires_year(self, mocked_tools):
        out = await mocked_tools.hko_opendata(data_type="SRS", month=3)
        assert out["error"] == "bad_request"
        assert "month requires year" in out["detail"]

    async def test_day_requires_year_month(self, mocked_tools):
        out = await mocked_tools.hko_opendata(data_type="SRS", year=2025, day=3)
        assert "day requires year and month" in out["detail"]

    async def test_hour_requires_full_date(self, mocked_tools):
        out = await mocked_tools.hko_opendata(data_type="HHOT", station="CCH", year=2025, month=1, hour=12)
        assert "hour requires year, month and day" in out["detail"]

    async def test_tide_requires_station(self, mocked_tools):
        out = await mocked_tools.hko_opendata(data_type="HLT", year=2025)
        assert "requires station" in out["detail"]

    async def test_tide_invalid_station(self, mocked_tools):
        out = await mocked_tools.hko_opendata(data_type="HLT", station="XXX", year=2025)
        assert "Invalid tide station" in out["detail"]

    async def test_tide_requires_year(self, mocked_tools):
        out = await mocked_tools.hko_opendata(data_type="HHOT", station="CCH")
        assert "requires year" in out["detail"]

    async def test_tide_rejects_date(self, mocked_tools):
        out = await mocked_tools.hko_opendata(data_type="HLT", station="CCH", year=2025, date="20250101")
        assert "date is only valid for RYES" in out["detail"]

    async def test_srs_rejects_station_hour_date(self, mocked_tools):
        assert "station is not applicable" in (await mocked_tools.hko_opendata(data_type="SRS", year=2025, station="CCH"))["detail"]
        assert "hour is not applicable" in (
            await mocked_tools.hko_opendata(data_type="SRS", year=2025, month=1, day=2, hour=12)
        )["detail"]
        assert "date is only valid for RYES" in (await mocked_tools.hko_opendata(data_type="SRS", year=2025, date="20250101"))["detail"]

    async def test_lhl_rejects_filters(self, mocked_tools):
        out = await mocked_tools.hko_opendata(data_type="LHL", year=2025)
        assert "does not accept" in out["detail"]

    async def test_climate_rejects_day_hour_date(self, mocked_tools):
        assert "day/hour are not applicable" in (
            await mocked_tools.hko_opendata(data_type="CLMTEMP", station="HKO", year=2025, month=1, day=2)
        )["detail"]
        assert "date is only valid for RYES" in (
            await mocked_tools.hko_opendata(data_type="CLMMAXT", station="HKO", year=2025, date="20250101")
        )["detail"]

    async def test_climate_invalid_station(self, mocked_tools):
        out = await mocked_tools.hko_opendata(data_type="CLMTEMP", station="ZZZ", year=2025)
        assert "Invalid climate station" in out["detail"]

    async def test_unsupported_dataset(self, mocked_tools):
        out = await mocked_tools.hko_opendata(data_type="NOPE")
        assert out["error"] == "bad_request"

    async def test_ryes_requires_station(self, mocked_tools):
        out = await mocked_tools.hko_opendata(data_type="RYES", date="20260904")
        assert "RYES requires station" in out["detail"]

    async def test_ryes_rejects_year_etc(self, mocked_tools):
        out = await mocked_tools.hko_opendata(data_type="RYES", station="KP", date="20260904", year=2025)
        assert "does not accept year/month/day/hour" in out["detail"]


class TestRyesDateNormalization:
    async def test_yesterday_after_cutoff(self, mocked_tools, freezer):
        freezer.freeze(datetime(2026, 9, 5, 2, 0, tzinfo=HK))  # after 01:30 HKT
        out = await mocked_tools.hko_opendata(data_type="RYES", station="KP", date="yesterday", rformat="csv")
        assert out["params"]["date"] == "20260904"

    async def test_yesterday_before_cutoff(self, mocked_tools, freezer, router):
        router.add(OPENDATA_RX, text="x")
        freezer.freeze(datetime(2026, 9, 5, 1, 0, tzinfo=HK))  # before 01:30 HKT
        out = await mocked_tools.hko_opendata(data_type="RYES", station="KP", date="latest", rformat="csv")
        assert out["params"]["date"] == "20260903"

    async def test_floor_20190910(self, mocked_tools):
        out = await mocked_tools.hko_opendata(data_type="RYES", station="KP", date="20190909")
        assert "on/after 20190910" in out["detail"]

    async def test_rejects_future_date(self, mocked_tools, freezer):
        freezer.freeze(datetime(2026, 9, 5, 2, 0, tzinfo=HK))
        out = await mocked_tools.hko_opendata(data_type="RYES", station="KP", date="20260905")
        assert "cannot be later than" in out["detail"]

    async def test_iso_date_normalized(self, mocked_tools, freezer):
        freezer.freeze(datetime(2026, 9, 5, 2, 0, tzinfo=HK))
        out = await mocked_tools.hko_opendata(data_type="RYES", station="KP", date="2026-09-01", rformat="csv")
        assert out["params"]["date"] == "20260901"

    async def test_bad_date_format(self, mocked_tools):
        out = await mocked_tools.hko_opendata(data_type="RYES", station="KP", date="Sept 1")
        assert out["error"] == "bad_request"


# ------------------------------------------------------------------
# hko_opendata: happy paths
# ------------------------------------------------------------------
class TestHkoOpendataHappy:
    async def test_csv_format(self, mocked_tools, router):
        r = router.add(OPENDATA_RX, text="STATION,YEAR\nCCH,2025")
        out = await mocked_tools.hko_opendata(data_type="HHOT", station="cch", year=2025, month=1, day=2, hour=3)
        assert out["format"] == "csv"
        assert out["data"].startswith("STATION")
        assert out["params"] == {
            "dataType": "HHOT", "rformat": "csv", "station": "CCH", "year": 2025, "month": 1, "day": 2, "hour": 3,
        }
        assert dict(r.calls[0].url.params)["station"] == "CCH"  # upper-cased

    async def test_json_format(self, mocked_tools, router):
        router.add(OPENDATA_RX, json=[{"v": 1}])
        out = await mocked_tools.hko_opendata(data_type="CLMTEMP", station="HKO", year=2025, rformat="json")
        assert out["format"] == "json"
        assert out["data"] == [{"v": 1}]
        assert out["params"]["dataType"] == "CLMTEMP"

    async def test_request_failure_passthrough(self, mocked_tools, router):
        router.add(OPENDATA_RX, status=500, json={})
        out = await mocked_tools.hko_opendata(data_type="SRS", year=2025)
        assert out["data"].get("error") == "request_failed"


# ------------------------------------------------------------------
# Wrapper tools delegate with the right dataset + params
# ------------------------------------------------------------------
@pytest.mark.parametrize(
    ("call", "dataset"),
    [
        (lambda t: t.hko_tide_hourly_heights(station="CCH", year=2025), "HHOT"),
        (lambda t: t.hko_tide_high_low(station="CCH", year=2025), "HLT"),
        (lambda t: t.hko_sunrise_sunset(year=2025), "SRS"),
        (lambda t: t.hko_moonrise_moonset(year=2025), "MRS"),
        (lambda t: t.hko_lightning_count(), "LHL"),
        (lambda t: t.hko_visibility_10min_mean(), "LTMV"),
        (lambda t: t.hko_climate_daily_mean_temperature(station="HKO", year=2025), "CLMTEMP"),
        (lambda t: t.hko_climate_daily_max_temperature(station="HKO", year=2025), "CLMMAXT"),
        (lambda t: t.hko_climate_daily_min_temperature(station="HKO", year=2025), "CLMMINT"),
        (lambda t: t.hko_weather_radiation_report(station="KP", date="20260901"), "RYES"),
    ],
)
async def test_wrapper_delegates(mocked_tools, router, call, dataset):
    # wrappers default to rformat="json"
    r = router.add(OPENDATA_RX, json=[{"ok": 1}])
    out = await call(mocked_tools)
    assert out["format"] == "json"
    assert out["data"] == [{"ok": 1}]
    assert dict(r.calls[0].url.params)["dataType"] == dataset


async def test_wrapper_explicit_csv(mocked_tools, router):
    router.add(OPENDATA_RX, text="ok")
    out = await mocked_tools.hko_tide_high_low(station="CCH", year=2025, rformat="csv")
    assert out["format"] == "csv" and out["data"] == "ok"


# ------------------------------------------------------------------
# Other HKO tools
# ------------------------------------------------------------------
class TestHkoWeatherForecast:
    @pytest.mark.parametrize("data_type", ["flw", "fnd", "rhrread", "warnsum", "warningInfo", "swt"])
    async def test_data_types(self, mocked_tools, router, data_type):
        r = router.add(r"weather\.php", json={"t": 1})
        out = await mocked_tools.hko_weather_forecast(data_type=data_type)
        assert out["data"] == {"t": 1}
        assert dict(r.calls[0].url.params)["dataType"] == data_type

    async def test_rhr_alias(self, mocked_tools, router):
        r = router.add(r"weather\.php", json={})
        out = await mocked_tools.hko_weather_forecast(data_type="rhr")
        assert "error" not in out["data"]
        assert dict(r.calls[0].url.params)["dataType"] == "rhrread"

    async def test_lang_param(self, mocked_tools, router):
        r = router.add(r"weather\.php", json={})
        await mocked_tools.hko_weather_forecast(lang="tc")
        assert dict(r.calls[0].url.params)["lang"] == "tc"

    async def test_request_failure_passthrough(self, mocked_tools, router):
        router.add(r"weather\.php", status=500, json={})
        out = await mocked_tools.hko_weather_forecast()
        assert out["data"].get("error") == "request_failed"


class TestHkoEarthquake:
    @pytest.mark.parametrize("data_type", ["qem", "feltearthquake"])
    async def test_data_types(self, mocked_tools, router, data_type):
        r = router.add(r"earthquake\.php", json={"e": 1})
        out = await mocked_tools.hko_earthquake(data_type=data_type)
        assert out["data"] == {"e": 1}
        assert dict(r.calls[0].url.params)["dataType"] == data_type


class TestHkoLunardate:
    async def test_happy(self, mocked_tools, router):
        register_hko(router)
        out = await mocked_tools.hko_lunardate("2026-09-05")
        assert out["data"]["LunarDate"] == "2026-07-19"

    async def test_bad_format(self, mocked_tools, router):
        out = await mocked_tools.hko_lunardate("05/09/2026")
        assert out["error"] == "bad_request"
        assert router.calls("lunardate") == []


class TestHkoHourlyRainfall:
    @pytest.mark.parametrize("lang", ["en", "tc", "sc"])
    async def test_langs(self, mocked_tools, router, lang):
        r = router.add(r"hourlyRainfall\.php", json={"r": 1})
        out = await mocked_tools.hko_hourly_rainfall(lang=lang)
        assert out["data"] == {"r": 1}
        assert dict(r.calls[0].url.params)["lang"] == lang
