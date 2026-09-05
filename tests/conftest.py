"""Shared fixtures for the hk-open-data-tool test suite.

Everything here is offline: the module's three HTTP paths (shared
HTTPClient, ALS's direct client use, and the GTFS ad-hoc client) are
intercepted via httpx.MockTransport.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Union

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "hk-open-data-tool.py"


# ------------------------------------------------------------------
# Module loading (hyphenated filename -> importlib)
# ------------------------------------------------------------------
@pytest.fixture(scope="session")
def mod():
    spec = importlib.util.spec_from_file_location("hkodt", MODULE_PATH)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["hkodt"] = m  # required for dataclass annotation resolution
    spec.loader.exec_module(m)
    return m


# ------------------------------------------------------------------
# Module-state hygiene
# ------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _restore_company_mode(mod):
    snapshot = dict(mod.COMPANY_MODE)
    yield
    mod.COMPANY_MODE.clear()
    mod.COMPANY_MODE.update(snapshot)


# ------------------------------------------------------------------
# HTTP mocking: Router + MockTransport
# ------------------------------------------------------------------
class Route:
    def __init__(
        self,
        pattern: str,
        *,
        json: Any = None,
        text: Optional[str] = None,
        content: Optional[bytes] = None,
        status: int = 200,
        headers: Optional[Dict[str, str]] = None,
        exc: Optional[Exception] = None,
        callback: Optional[Callable[[httpx.Request], httpx.Response]] = None,
    ):
        self.pattern = re.compile(pattern)
        self.json = json
        self.text = text
        self.content = content
        self.status = status
        self.headers = headers or {}
        self.exc = exc
        self.callback = callback
        self.calls: List[httpx.Request] = []

    def match(self, url: str) -> bool:
        return self.pattern.search(url) is not None

    def respond(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.exc is not None:
            raise self.exc
        if self.callback is not None:
            return self.callback(request)
        if self.content is not None:
            return httpx.Response(self.status, content=self.content, headers=self.headers)
        if self.text is not None:
            return httpx.Response(self.status, text=self.text, headers=self.headers)
        return httpx.Response(self.status, json=self.json, headers=self.headers)


class Router:
    """URL-pattern registry served through httpx.MockTransport."""

    def __init__(self):
        self.routes: List[Route] = []

    def add(self, pattern: str, **kwargs) -> Route:
        route = Route(pattern, **kwargs)
        self.routes.append(route)
        return route

    def route_for(self, url: str) -> Optional[Route]:
        for r in self.routes:
            if r.match(url):
                return r
        return None

    def calls(self, pattern: str) -> List[httpx.Request]:
        rx = re.compile(pattern)
        return [c for r in self.routes for c in r.calls if rx.search(str(c.url))]

    @property
    def transport(self) -> httpx.MockTransport:
        outer = self

        def handler(request: httpx.Request) -> httpx.Response:
            route = outer.route_for(str(request.url))
            if route is None:
                return httpx.Response(404, json={"error": "no_route_registered", "url": str(request.url)})
            return route.respond(request)

        return httpx.MockTransport(handler)


@pytest.fixture()
def router() -> Router:
    return Router()


def install_transport(tools, router: Router) -> httpx.AsyncClient:
    """Pre-set the shared HTTPClient._client with a MockTransport client.

    Covers HTTPClient.request egress and ALS's direct client.get() use.
    """
    client = httpx.AsyncClient(transport=router.transport)
    tools.http._client = client
    return client


def patch_async_client(monkeypatch, mod, router: Router) -> None:
    """Force every httpx.AsyncClient constructed by the module (e.g. the
    GTFS ferry-zip downloader) to use the router's MockTransport."""

    real_cls = mod.httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.setdefault("transport", router.transport)
        return real_cls(*args, **kwargs)

    monkeypatch.setattr(mod.httpx, "AsyncClient", factory)


# ------------------------------------------------------------------
# Tools / Valves
# ------------------------------------------------------------------
def make_valves(mod, cache_dir: Path, **overrides) -> "mod.Valves":
    kwargs = {"cache_dir": str(cache_dir), "http_retries": 0, "http_timeout_s": 2}
    kwargs.update(overrides)
    return mod.Valves(**kwargs)


@pytest.fixture()
def tmp_cache(tmp_path) -> Path:
    d = tmp_path / "cache"
    d.mkdir()
    return d


@pytest.fixture()
async def tools(mod, tmp_cache):
    """A fresh Tools instance with an isolated cache dir and no retries.

    The shared valves object is replaced before any request is made, so
    every sub-client (which holds the same reference) sees the test config.
    """
    t = mod.Tools()
    v = make_valves(mod, tmp_cache)
    t.valves.__dict__.update(v.__dict__)
    t.http.cache_dir = v.cache_dir
    yield t
    if t.http._client is not None:
        await t.http._client.aclose()
        t.http._client = None


@pytest.fixture()
async def mocked_tools(tools, router):
    """Tools with the shared client + any future ad-hoc client mocked."""
    install_transport(tools, router)
    yield tools


# ------------------------------------------------------------------
# Transit fixture builders
# ------------------------------------------------------------------
def stop(sid: str, name_en: str, lat: float, lng: float, name_zh: Optional[str] = None) -> dict:
    return {
        "name": {"en": name_en, "zh": name_zh or name_en},
        "location": {"lat": lat, "lng": lng},
    }


def route(
    rid: str,
    co: List[str],
    stops: Dict[str, List[str]],
    *,
    route_no: Optional[str] = None,
    orig_en: str = "Origin",
    dest_en: str = "Destination",
    orig_zh: Optional[str] = None,
    dest_zh: Optional[str] = None,
    bound: Optional[Dict[str, str]] = None,
    service_type: str = "1",
    gtfs_id: Optional[str] = None,
    freq: Optional[dict] = None,
) -> dict:
    r: Dict[str, Any] = {
        "route": route_no or rid.split("+")[0],
        "co": co,
        "stops": stops,
        "orig": {"en": orig_en, "zh": orig_zh or orig_en},
        "dest": {"en": dest_en, "zh": dest_zh or dest_en},
        "serviceType": service_type,
    }
    if bound:
        r["bound"] = bound
    if gtfs_id:
        r["gtfsId"] = gtfs_id
    if freq:
        r["freq"] = freq
    return r


def build_transit(mod, db: dict) -> "mod.TransitDB":
    """Directly seed a TransitDB from a hkbus-shaped dict (no network,
    no ensure_loaded) - indices are built and _db_loaded is set."""
    valves = mod.Valves(cache_dir="/tmp/opencode/hkodt-unused-cache")
    tdb = mod.TransitDB(mod.HTTPClient(valves, valves.cache_dir), valves)
    tdb._stop_list = db.get("stopList") or {}
    tdb._route_list = db.get("routeList") or {}
    tdb._build_indices(db)
    tdb._db_loaded = True
    tdb._db_source = "fixture"
    tdb._db_md5 = "fixture"
    return tdb


def seed_transit_files(cache_dir: Path, db: dict, md5: str = "deadbeef", *, fresh: bool = True) -> None:
    """Write hkbus DB cache files so ensure_loaded() resolves from disk."""
    (cache_dir / "routeFareList.min.json").write_text(json.dumps(db), encoding="utf-8")
    (cache_dir / "routeFareList.md5").write_text(md5, encoding="utf-8")
    if not fresh:
        import os

        old = 0
        os.utime(cache_dir / "routeFareList.min.json", (old, old))
        os.utime(cache_dir / "routeFareList.md5", (old, old))


def seed_ferry_cache(cache_dir: Path, ferry_data: dict, *, fresh: bool = True) -> None:
    """Write the GTFS ferry cache file so the merge skips the zip download."""
    p = cache_dir / "hk_gtfs_ferries_cache_v9.json"
    p.write_text(json.dumps(ferry_data), encoding="utf-8")
    if not fresh:
        import os

        os.utime(p, (0, 0))


def gtfs_zip_bytes(files: Dict[str, str]) -> bytes:
    """Build an in-memory GTFS zip from {filename: csv-text}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


# ------------------------------------------------------------------
# Mini transit graph used by planner / td_* tests
# ------------------------------------------------------------------
# Geography (approx, WGS84): a straight north-south corridor.
#   S_A (22.2800, 114.1500)  -- far south, near origin
#   S_B (22.2840, 114.1500)  -- ~440 m north of S_A
#   S_C (22.2880, 114.1500)  -- ~440 m north of S_B
#   S_D (22.2920, 114.1500)  -- near destination
#   S_E (22.2860, 114.1540)  -- ~440 m east of S_C (transfer stop pair)
# Route 1 (kmb "1"): S_A -> S_B -> S_C
# Route 2 (kmb "2"): S_E -> S_D
# MTR route "ISL": S_B -> S_E (rail transfer alternative)
# GMB route "3": S_A -> S_D direct minibus (no freq -> always operating)
def mini_db() -> dict:
    return {
        "stopList": {
            "S_A": stop("S_A", "South Terminus", 22.2800, 114.1500, "南端總站"),
            "S_B": stop("S_B", "Mid Street", 22.2840, 114.1500, "中街"),
            "S_C": stop("S_C", "North Gate", 22.2880, 114.1500, "北門"),
            "S_D": stop("S_D", "North Terminus", 22.2920, 114.1500, "北端總站"),
            "S_E": stop("S_E", "East Gate", 22.2860, 114.1540, "東門"),
        },
        "routeList": {
            "1+kmb+south+north": route(
                "1+kmb+south+north",
                ["kmb"],
                {"kmb": ["S_A", "S_B", "S_C"]},
                route_no="1",
                orig_en="South Terminus",
                dest_en="North Gate",
                bound={"kmb": "O"},
            ),
            "2+kmb+east+north": route(
                "2+kmb+east+north",
                ["kmb"],
                {"kmb": ["S_E", "S_D"]},
                route_no="2",
                orig_en="East Gate",
                dest_en="North Terminus",
                bound={"kmb": "O"},
            ),
            "ISL+1+a+b": route(
                "ISL+1+a+b",
                ["mtr"],
                {"mtr": ["S_B", "S_E"]},
                route_no="ISL",
                orig_en="Mid Street",
                dest_en="East Gate",
                bound={"mtr": "O"},
            ),
            "3+gmb+direct": route(
                "3+gmb+direct",
                ["gmb"],
                {"gmb": ["S_A", "S_D"]},
                route_no="3",
                orig_en="South Terminus",
                dest_en="North Terminus",
                bound={"gmb": "O"},
                gtfs_id="2006-1",
            ),
        },
        "holidays": [],
    }


@pytest.fixture()
def seeded_tools(mod, tools, monkeypatch):
    """Tools whose TransitDB is seeded directly from mini_db()."""
    tdb = build_transit(mod, mini_db())
    tools.transit = tdb
    tools.planner = mod.TripPlanner(tdb, tools.landsd, tools.valves)
    return tools


# ------------------------------------------------------------------
# Misc helpers
# ------------------------------------------------------------------
@pytest.fixture()
def emitter():
    """Async event-emitter recorder for status events."""
    events: List[dict] = []

    async def emit(event: dict) -> None:
        events.append(event)

    emit.events = events  # type: ignore[attr-defined]
    return emit


def hk_dt(mod, *args):
    return mod.datetime(*args, tzinfo=mod.HK_TZ)


# Convenience namespace so tests can import helpers without fixtures.
helpers = SimpleNamespace(
    stop=stop,
    route=route,
    build_transit=build_transit,
    seed_transit_files=seed_transit_files,
    seed_ferry_cache=seed_ferry_cache,
    gtfs_zip_bytes=gtfs_zip_bytes,
    mini_db=mini_db,
    install_transport=install_transport,
    patch_async_client=patch_async_client,
    make_valves=make_valves,
    hk_dt=hk_dt,
)
