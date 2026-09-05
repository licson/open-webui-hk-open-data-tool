"""HTTPClient contract tests: success paths, caching, retries, error dict."""

from __future__ import annotations

import json as jsonlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from conftest import Router, make_valves

URL = "https://example.test/api"


def make_client(mod, tmp_cache, **valve_kwargs):
    valves = make_valves(mod, tmp_cache, **valve_kwargs)
    hc = mod.HTTPClient(valves, valves.cache_dir)
    return hc, valves


@pytest.fixture()
async def hc(mod, tmp_cache):
    """HTTPClient with retries disabled and no transport installed yet."""
    client, _ = make_client(mod, tmp_cache)
    yield client
    if client._client is not None:
        await client._client.aclose()


def attach(hc, router: Router) -> None:
    hc._client = httpx.AsyncClient(transport=router.transport)


class TestSuccess:
    async def test_get_json(self, mod, hc, router):
        router.add(URL, json={"ok": True, "n": 1})
        attach(hc, router)
        assert await hc.request(URL) == {"ok": True, "n": 1}

    async def test_get_text(self, mod, hc, router):
        router.add(URL, text="plain-body")
        attach(hc, router)
        assert await hc.request(URL, expect="text") == "plain-body"

    async def test_post_json_body(self, mod, hc, router):
        r = router.add(URL, json={"echo": True})
        attach(hc, router)
        out = await hc.request(URL, method="POST", json_body={"lang": "zh", "route": "K14"})
        assert out == {"echo": True}
        sent = jsonlib.loads(r.calls[0].read())
        assert sent == {"lang": "zh", "route": "K14"}
        assert r.calls[0].method == "POST"

    async def test_params_forwarded(self, mod, hc, router):
        r = router.add(URL, json={})
        attach(hc, router)
        await hc.request(URL, params={"a": "1", "b": "two"})
        assert dict(r.calls[0].url.params) == {"a": "1", "b": "two"}


class TestMemCache:
    async def test_hit_within_ttl(self, mod, hc, router):
        r = router.add(URL, json={"v": 1})
        attach(hc, router)
        first = await hc.request(URL, cache_scope="mem", cache_ttl_s=60)
        second = await hc.request(URL, cache_scope="mem", cache_ttl_s=60)
        assert first == second == {"v": 1}
        assert len(r.calls) == 1

    async def test_expiry_refetches(self, mod, hc, router):
        from freezegun import freeze_time

        r = router.add(URL, json={"v": 1})
        attach(hc, router)
        with freeze_time(datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)):
            await hc.request(URL, cache_scope="mem", cache_ttl_s=60)
            with freeze_time(datetime(2026, 9, 5, 12, 1, 1, tzinfo=timezone.utc)):
                await hc.request(URL, cache_scope="mem", cache_ttl_s=60)
        assert len(r.calls) == 2

    async def test_different_params_dont_collide(self, mod, hc, router):
        r1 = router.add(rf"{re_esc(URL)}\?a=1", json={"a": 1})
        r2 = router.add(rf"{re_esc(URL)}\?a=2", json={"a": 2})
        attach(hc, router)
        assert await hc.request(URL, params={"a": "1"}, cache_scope="mem") == {"a": 1}
        assert await hc.request(URL, params={"a": "2"}, cache_scope="mem") == {"a": 2}
        assert len(r1.calls) == 1 and len(r2.calls) == 1


class TestDiskCache:
    async def test_roundtrip_and_hit(self, mod, tmp_cache, router):
        r = router.add(URL, json={"v": 9})
        c1, _ = make_client(mod, tmp_cache)
        attach(c1, router)
        assert await c1.request(URL, cache_scope="disk") == {"v": 9}
        # brand-new client, same cache dir -> served from disk
        c2, _ = make_client(mod, tmp_cache)
        attach(c2, router)
        assert await c2.request(URL, cache_scope="disk") == {"v": 9}
        assert len(r.calls) == 1

    async def test_mtime_expiry_refetches(self, mod, tmp_cache, router):
        r = router.add(URL, json={"v": 9})
        c1, _ = make_client(mod, tmp_cache)
        attach(c1, router)
        await c1.request(URL, cache_scope="disk", cache_ttl_s=3600)
        # age the written cache file beyond TTL
        for p in Path(tmp_cache).glob("*.json"):
            import os

            os.utime(p, (0, 0))
        assert await c1.request(URL, cache_scope="disk", cache_ttl_s=3600) == {"v": 9}
        assert len(r.calls) == 2

    async def test_unwritable_dir_still_returns_data(self, mod, tmp_path, router):
        router.add(URL, json={"v": 1})
        blocker = tmp_path / "blocker"  # a FILE, so cache writes fail
        blocker.write_text("not a dir")
        valves = make_valves(mod, tmp_path / "unused")
        valves.cache_dir = str(blocker)
        hc = mod.HTTPClient(valves, str(blocker))
        attach(hc, router)
        assert await hc.request(URL, cache_scope="disk") == {"v": 1}


class TestRetries:
    async def test_429_then_success(self, mod, tmp_cache, router):
        state = {"n": 0}

        def flaky(request):
            state["n"] += 1
            if state["n"] == 1:
                return httpx.Response(429, json={"e": "rate"})
            return httpx.Response(200, json={"ok": True})

        router.add(URL, callback=flaky)
        valves = make_valves(mod, tmp_cache, http_retries=1)
        hc = mod.HTTPClient(valves, valves.cache_dir)
        attach(hc, router)
        assert await hc.request(URL) == {"ok": True}
        assert state["n"] == 2

    async def test_5xx_exhausted_returns_error_dict(self, mod, tmp_cache, router):
        router.add(URL, status=503, json={"e": "down"})
        valves = make_valves(mod, tmp_cache, http_retries=1)
        hc = mod.HTTPClient(valves, valves.cache_dir)
        attach(hc, router)
        out = await hc.request(URL, params={"x": "1"}, method="POST", json_body={"a": 1})
        assert out["error"] == "request_failed"
        assert "503" in out["detail"]
        assert out["url"] == URL
        assert out["params"] == {"x": "1"}
        assert out["method"] == "POST"

    async def test_4xx_returns_error_dict(self, mod, tmp_cache, router):
        router.add(URL, status=404, text="missing")
        valves = make_valves(mod, tmp_cache, http_retries=0)
        hc = mod.HTTPClient(valves, valves.cache_dir)
        attach(hc, router)
        out = await hc.request(URL)
        assert out["error"] == "request_failed"
        assert "404" in out["detail"]

    async def test_no_retry_single_attempt(self, mod, tmp_cache, router):
        r = router.add(URL, status=500, json={})
        valves = make_valves(mod, tmp_cache, http_retries=0)
        hc = mod.HTTPClient(valves, valves.cache_dir)
        attach(hc, router)
        out = await hc.request(URL)
        assert out["error"] == "request_failed"
        assert len(r.calls) == 1


class TestGetHelpers:
    async def test_get_json_none_on_error(self, mod, hc, router):
        router.add(URL, status=500, json={})
        attach(hc, router)
        assert await hc.get_json(URL) is None

    async def test_get_json_none_on_non_dict(self, mod, hc, router):
        router.add(URL, json=[1, 2, 3])
        attach(hc, router)
        assert await hc.get_json(URL) is None  # list, not dict

    async def test_get_text_none_on_error(self, mod, hc, router):
        router.add(URL, status=502, text="bad")
        attach(hc, router)
        assert await hc.get_text(URL) is None

    async def test_get_json_ok(self, mod, hc, router):
        router.add(URL, json={"a": 1})
        attach(hc, router)
        assert await hc.get_json(URL) == {"a": 1}

    async def test_never_cached(self, mod, hc, router):
        r = router.add(URL, json={"a": 1})
        attach(hc, router)
        await hc.get_json(URL)
        await hc.get_json(URL)
        assert len(r.calls) == 2  # get_json forces cache_scope="none"


def re_esc(s: str) -> str:
    import re as _re

    return _re.escape(s)
