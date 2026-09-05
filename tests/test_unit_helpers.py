"""Table-driven tests for the pure module-level helpers."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

HK_TZ = timezone(timedelta(hours=8))


# ------------------------------------------------------------------
# Text / operator normalization
# ------------------------------------------------------------------
class TestNormalizeText:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("  Central   Pier ", "central pier"),
            ("MONG KOK", "mong kok"),
            ("", ""),
            (None, ""),
            ("  多重   空格  ", "多重 空格"),
        ],
    )
    def test_cases(self, mod, raw, expected):
        assert mod.normalize_text(raw) == expected


class TestNormCo:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("kmb", "kmb"),
            ("KMB", "kmb"),
            (" minibus ", "gmb"),
            ("mtr-bus", "lrtfeeder"),
            ("mtr_bus", "lrtfeeder"),
            ("mtrbus", "lrtfeeder"),
            ("light_rail", "lightrail"),
            ("light-rail", "lightrail"),
            ("light rail", "lightrail"),
            ("lightRail", "lightrail"),
            ("MTR", "mtr"),
            (None, ""),
            ("", ""),
        ],
    )
    def test_cases(self, mod, raw, expected):
        assert mod.norm_co(raw) == expected


class TestModeOfCompany:
    @pytest.mark.parametrize(
        ("co", "mode"),
        [
            ("kmb", "bus"),
            ("ctb", "bus"),
            ("nlb", "bus"),
            ("gmb", "minibus"),
            ("lrtfeeder", "mtr_bus"),
            ("mtr", "rail"),
            ("lightrail", "rail"),
            ("sunferry", "ferry"),
            ("hkkf", "ferry"),
            ("starferry", "ferry"),
            ("unknown-op", "bus"),  # default
        ],
    )
    def test_cases(self, mod, co, mode):
        assert mod.mode_of_company(co) == mode


# ------------------------------------------------------------------
# Numbers / geo
# ------------------------------------------------------------------
class TestCoerceFloat:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, None),
            (5, 5.0),
            (5.5, 5.5),
            ("12.5", 12.5),
            ("  3 ", 3.0),
            ("", None),
            ("abc", None),
            ([1], None),
            ({}, None),
        ],
    )
    def test_cases(self, mod, raw, expected):
        assert mod.coerce_float(raw) == expected


class TestHaversine:
    def test_zero_distance(self, mod):
        assert mod.haversine_m(22.3, 114.1, 22.3, 114.1) == pytest.approx(0.0)

    def test_one_degree_lat(self, mod):
        # ~111 km per degree of latitude
        d = mod.haversine_m(22.0, 114.0, 23.0, 114.0)
        assert 110_000 < d < 112_000

    def test_symmetry(self, mod):
        assert mod.haversine_m(22.28, 114.15, 22.29, 114.16) == pytest.approx(
            mod.haversine_m(22.29, 114.16, 22.28, 114.15)
        )


# ------------------------------------------------------------------
# Datetimes / ETA math
# ------------------------------------------------------------------
class TestParseIso:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2026-09-05T12:00:00+08:00", datetime(2026, 9, 5, 12, 0, tzinfo=HK_TZ)),
            ("2026-09-05T04:00:00Z", datetime(2026, 9, 5, 4, 0, tzinfo=timezone.utc)),
            (None, None),
            ("", None),
            ("not-a-date", None),
            (123, None),
        ],
    )
    def test_cases(self, mod, raw, expected):
        got = mod.parse_iso(raw)
        if expected is None:
            assert got is None
        else:
            assert got == expected
            assert got.tzinfo is not None


class TestParseHkDt:
    def test_parses_as_hk_time(self, mod):
        dt = mod.parse_hk_dt("2026-09-05 12:34:56")
        assert dt == datetime(2026, 9, 5, 12, 34, 56, tzinfo=HK_TZ)

    @pytest.mark.parametrize("raw", [None, "", "2026/09/05", "garbage", 42])
    def test_invalid(self, mod, raw):
        assert mod.parse_hk_dt(raw) is None


class TestEtaMinutes:
    def test_future(self, mod, freezer):
        freezer.freeze_time(datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc))
        assert mod.eta_minutes("2026-09-05T20:10:00+08:00") == 10  # 12:10 UTC

    def test_slightly_past_is_clamped(self, mod, freezer):
        freezer.freeze_time(datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc))
        assert mod.eta_minutes("2026-09-05T19:59:30+08:00") == 0  # 30 s ago

    def test_far_past_is_none(self, mod, freezer):
        freezer.freeze_time(datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc))
        assert mod.eta_minutes("2026-09-05T19:00:00+08:00") is None  # 1 h ago

    def test_naive_treated_as_utc(self, mod, freezer):
        freezer.freeze_time(datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc))
        assert mod.eta_minutes("2026-09-05T12:30:00") == 30

    @pytest.mark.parametrize("raw", [None, "", "junk"])
    def test_invalid(self, mod, raw):
        assert mod.eta_minutes(raw) is None


class TestMinutesFromCompactText:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("5 min", 5),
            ("5 分鐘", 5),
            ("12 minutes", 12),
            ("", None),
            (None, None),
            ("arriving", None),
            ("0 min", 0),
        ],
    )
    def test_cases(self, mod, raw, expected):
        assert mod.minutes_from_compact_text(raw) == expected


class TestEtaMinutesFromHhmm:
    NOW = datetime(2026, 9, 5, 14, 30, tzinfo=HK_TZ)

    def test_later_today(self, mod):
        assert mod.eta_minutes_from_hhmm(self.NOW, "15:00") == 30

    def test_just_passed_still_counts(self, mod):
        assert mod.eta_minutes_from_hhmm(self.NOW, "14:29") == 0  # within 2-min grace

    def test_wrap_past_midnight(self, mod):
        assert mod.eta_minutes_from_hhmm(self.NOW, "01:30") == 11 * 60  # next day

    @pytest.mark.parametrize("raw", [None, "", "25:99", "abc", "9:5", 123])
    def test_invalid(self, mod, raw):
        assert mod.eta_minutes_from_hhmm(self.NOW, raw) is None


# ------------------------------------------------------------------
# HTML / cursors / limits
# ------------------------------------------------------------------
class TestStripHtml:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("<b>Central</b> Pier", "Central Pier"),
            ("no tags", "no tags"),
            ("", ""),
            (None, ""),
            ("<a href='x'>link</a> and <br/>more", "link and more"),
        ],
    )
    def test_cases(self, mod, raw, expected):
        assert mod.strip_html(raw) == expected


class TestCursor:
    def test_roundtrip(self, mod):
        c = mod.cursor_make("q", 40)
        assert c == "q:40"
        assert mod.cursor_parse(c) == ("q", 40)

    def test_parse_empty(self, mod):
        assert mod.cursor_parse(None) == ("", 0)
        assert mod.cursor_parse("") == ("", 0)

    def test_parse_garbage(self, mod):
        assert mod.cursor_parse("no-colon") == ("", 0)


class TestLimitItems:
    def test_slice_and_cursor(self, mod):
        items = list(range(10))
        sliced, nxt = mod.limit_items(items, 0, 3)
        assert sliced == [0, 1, 2]
        assert nxt == "q:3"

    def test_last_page_no_cursor(self, mod):
        items = list(range(10))
        sliced, nxt = mod.limit_items(items, 9, 3)
        assert sliced == [9]
        assert nxt is None

    def test_limit_clamped(self, mod):
        sliced, _ = mod.limit_items(list(range(10)), 0, 500)
        assert len(sliced) == 10  # capped at 50 but only 10 exist
        sliced2, _ = mod.limit_items(list(range(100)), 0, 500)
        assert len(sliced2) == 50

    def test_min_limit_one(self, mod):
        sliced, _ = mod.limit_items([1, 2, 3], 0, 0)
        assert sliced == [1]


class TestSha256:
    def test_known_digest(self, mod):
        assert mod.sha256("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


# ------------------------------------------------------------------
# freezegun plumbing
# ------------------------------------------------------------------
@pytest.fixture()
def freezer():
    from freezegun import freeze_time

    class _Freezer:
        def __init__(self):
            self._cm = None

        def freeze_time(self, dt):
            self._cm = freeze_time(dt)
            self._cm.start()

        def tick(self, seconds):
            self._cm.tick(delta=timedelta(seconds=seconds))

        def stop(self):
            if self._cm:
                self._cm.stop()

    f = _Freezer()
    yield f
    f.stop()
