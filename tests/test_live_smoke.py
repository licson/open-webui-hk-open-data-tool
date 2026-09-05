"""Opt-in live-network smoke tests (deselected by default; run with -m live).

These perform ONE real call per client family and assert only structural
validity. They skip (rather than fail) when the network is unavailable.
"""

from __future__ import annotations

import socket

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        socket.socket().connect_ex(("data.weather.gov.hk", 443)) != 0,
        reason="no network access",
    ),
]


@pytest.fixture()
def live_tools(mod, tmp_cache):
    t = mod.Tools()
    t.valves.__dict__.update(
        {"cache_dir": str(tmp_cache), "http_retries": 0, "http_timeout_s": 15}
    )
    t.http.cache_dir = t.valves.cache_dir
    yield t


async def test_live_hko_weather(live_tools):
    out = await live_tools.hko_weather_forecast()
    assert "error" not in (out.get("data") or {})
    assert out["meta"]["tool"] == "Hong Kong Open Data"


async def test_live_landsd_location_search(live_tools):
    out = await live_tools.landsd_location_search("Central Star Ferry Pier", limit=3)
    assert isinstance(out["items"], list)


async def test_live_epd_aqhi(live_tools):
    out = await live_tools.epd_aqhi_current()
    assert isinstance(out["stations"], list)


async def test_live_ha_aed(live_tools):
    out = await live_tools.ha_aed_waiting_time()
    assert isinstance(out["hospitals"], list)


async def test_live_dpo_address_lookup(live_tools):
    out = await live_tools.dpo_address_lookup("Central Plaza", limit=3)
    assert "suggestions" in out or "error" in out


async def test_live_td_catalog(live_tools):
    out = await live_tools.td_catalog_status()
    assert out["operators_seen"], "expected at least one operator in the live DB"


async def test_live_td_stop_search(live_tools):
    out = await live_tools.td_stop_search("Central", limit=5)
    assert isinstance(out["items"], list)
