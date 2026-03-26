"""
title: Hong Kong Open Data
author: Licson Lee
author_url: https://licson.net/
git_url: https://github.com/licson/open-webui-hk-open-data-tool
description: LLM-safe HK open-data tool (HKO, LandsD, TD). Transit supports bus/minibus + MTR (rail/LRT/MTR bus) + ferries; curated trip planning; no dump endpoints.
required_open_webui_version: 0.5.0
requirements: httpx,pydantic
version: 0.6.0
licence: MIT
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import math
import re
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import httpx
from pydantic import BaseModel, Field

# ============================================================
# Data Classes
# ============================================================
@dataclass(frozen=True)
class StopOcc:
    route_id: str
    company: str
    seq: int


@dataclass
class ETAResult:
    minutes: Optional[int] = None
    iso: Optional[str] = None
    text: Optional[str] = None
    platform: Optional[str] = None
    dest: Optional[str] = None
    remark_en: str = ""
    remark_zh: str = ""


@dataclass
class Point:
    lat: float
    lon: float


@dataclass
class PlanState:
    cur: str
    walk: float
    actual_time: float
    perceived_cost: float
    tx: int
    modes: int
    legs: list
    last_was_walk: bool = False


# ============================================================
# Constants & Endpoints
# ============================================================

# HKO Endpoints
HKO_BASE = "https://data.weather.gov.hk/weatherAPI/opendata"

# LandsD Endpoints
LANDSD_LOCATION_BASE = "https://www.map.gov.hk/gs/api"
LANDSD_LOCATION_VERSION = "v1.0.0"
LANDSD_TRANSFORM_BASE = "https://www.geodetic.gov.hk/transform/v2/"

# Transit DB Sources
HKBUS_PRIMARY_BASE = "https://data.hkbus.app"
HKBUS_FALLBACK_BASE = "https://hkbus.github.io/hk-bus-crawling"
HKBUS_DB_JSON = "routeFareList.min.json"
HKBUS_DB_MD5 = "routeFareList.md5"
HKBUS_VERSIONS_JSON = "0versions.json"

# Real-time ETA Endpoints
KMB_ETA_BASE = "https://data.etabus.gov.hk/v1/transport/kmb"
CTB_ETA_BASE = "https://rt.data.gov.hk/v2/transport/citybus"
GMB_ETA_BASE = "https://data.etagmb.gov.hk"
MTR_TRAIN_BASE = "https://rt.data.gov.hk/v1/transport/mtr/getSchedule.php"
MTR_LRT_BASE = "https://rt.data.gov.hk/v1/transport/mtr/lrt/getSchedule"
MTR_BUS_BASE = "https://rt.data.gov.hk/v1/transport/mtr/bus/getSchedule"
SUNFERRY_BASE = "https://www.sunferry.com.hk"
HKKF_BASE = "https://www.hkkfeta.com"
FORTUNEFERRY_BASE = "https://www.hongkongwatertaxi.com.hk"

# Timezone
HK_TZ = timezone(timedelta(hours=8))

# Station maps for HKO
HKO_TIDE_STATIONS: Dict[str, str] = {
    "CCH": "Cheung Chau",
    "CLK": "Chek Lap Kok",
    "CMW": "Chi Ma Wan",
    "KCT": "Kwai Chung",
    "KLW": "Ko Lau Wan",
    "LOP": "Lok On Pai",
    "MWC": "Ma Wan",
    "QUB": "Quarry Bay",
    "SPW": "Shek Pik",
    "TAO": "Tai O",
    "TBT": "Tsim Bei Tsui",
    "TMW": "Tai Miu Wan",
    "TPK": "Tai Po Kau",
    "WAG": "Waglan Island",
}

HKO_CLIMATE_STATIONS: Dict[str, str] = {
    "CCH": "Cheung Chau",
    "CWB": "Clear Water Bay",
    "HKA": "Hong Kong International Airport",
    "HKO": "Hong Kong Observatory",
    "HKP": "Hong Kong Park",
    "HKS": "Wong Chuk Hang",
    "HPV": "Happy Valley",
    "JKB": "Tseung Kwan O",
    "KLT": "Kowloon City",
    "KP": "King's Park",
    "KSC": "Kau Sai Chau",
    "KTG": "Kwun Tong",
    "LFS": "Lau Fau Shan",
    "NGP": "Ngong Ping",
    "PEN": "Peng Chau",
    "PLC": "Tai Mei Tuk",
    "SE1": "Kai Tak Runway Park",
    "SEK": "Shek Kong",
    "SHA": "Sha Tin",
    "SKG": "Sai Kung",
    "SKW": "Shau Kei Wan",
    "SSH": "Sheung Shui",
    "SSP": "Sham Shui Po",
    "STY": "Stanley",
    "TC": "Tate's Cairn",
    "TKL": "Ta Kwu Ling",
    "TMS": "Tai Mo Shan",
    "TPO": "Tai Po (Conservation Studies Centre)",
    "TU1": "Tuen Mun Children and Juvenile Home",
    "TW": "Tsuen Wan Shing Mun Valley",
    "TWN": "Tsuen Wan",
    "TY1": "New Tsing Yi Station",
    "TYW": "Pak Tam Chung (Tsak Yue Wu)",
    "VP1": "The Peak",
    "WGL": "Waglan Island",
    "WLP": "Wetland Park",
    "WTS": "Wong Tai Sin",
    "YCT": "Tai Po (Yuan Chau Tsai Park)",
    "YLP": "Yuen Long Park",
}

HKO_RYES_STATIONS: Dict[str, str] = {
    "CCH": "Cheung Chau",
    "CLK": "Chek Lap Kok",
    "EPC": "Ping Chau",
    "HKO": "Hong Kong Observatory",
    "HKP": "Hong Kong Park",
    "HKS": "Wong Chuk Hang",
    "HPV": "Happy Valley",
    "JKB": "Tseung Kwan O",
    "KAT": "Kat O",
    "KLT": "Kowloon City",
    "KP": "King's Park",
    "KTG": "Kwun Tong",
    "LFS": "Lau Fau Shan",
    "PLC": "Tai Mei Tuk",
    "SE1": "Kai Tak Runway Park",
    "SEK": "Shek Kong",
    "SHA": "Sha Tin",
    "SKG": "Sai Kung",
    "SKW": "Shau Kei Wan",
    "SSP": "Sham Shui Po",
    "STK": "Sha Tau Kok",
    "STY": "Stanley",
    "SWH": "Sai Wan Ho",
    "TAP": "Tap Mun",
    "TBT": "Tsim Bei Tsui",
    "TKL": "Ta Kwu Ling",
    "TUN": "Tuen Mun",
    "TW": "Tsuen Wan Shing Mun Valley",
    "TWN": "Tsuen Wan Ho Koon",
    "TY1": "Tsing Yi",
    "WTS": "Wong Tai Sin",
    "YCT": "Tai Po",
    "YLP": "Yuen Long Park",
    "YNF": "Yuen Ng Fan",
}

HKO_TIDE_STATION_MAP = HKO_TIDE_STATIONS
HKO_CLIMATE_STATION_MAP = HKO_CLIMATE_STATIONS
HKO_RYES_STATION_MAP = HKO_RYES_STATIONS


# ============================================================
# Small helpers (module-level; NOT exposed as tools)
# ============================================================
def now_s() -> float:
    return time.time()


def safe_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def normalize_text(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


# ============================================================
# Transit operator normalization
# ============================================================
def norm_co(co: Any) -> str:
    # Normalize hkbus co values for internal matching
    s = str(co or "").strip().lower()
    if s == "minibus":
        return "gmb"
    if s in {"mtr-bus", "mtr_bus", "mtrbus"}:
        return "lrtfeeder"
    if s in {"light_rail", "light-rail", "light rail"}:
        return "lightrail"
    return s


# hkbus `co` -> high-level mode (for scoring / labeling)
COMPANY_MODE: Dict[str, str] = {
    "kmb": "bus",
    "ctb": "bus",
    "nlb": "bus",
    "gmb": "minibus",
    # accept canonical name as well (will be normalized to gmb, but keep for safety)
    "minibus": "minibus",
    "lrtfeeder": "mtr_bus",
    "mtr": "rail",
    "lightrail": "rail",
    "sunferry": "ferry",
    "hkkf": "ferry",
    "fortuneferry": "ferry",
    "starferry": "ferry",
    "parkisland": "ferry",
    "dbferry": "ferry",
    "coralsea": "ferry",
    "tsuiwahferry": "ferry",
    "chuenkee": "ferry",
    "ferry": "ferry",
}


def mode_of_company(co_norm: str) -> str:
    return COMPANY_MODE.get(co_norm, "bus")


def coerce_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v.strip():
            return float(v)
    except Exception:
        return None
    return None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371008.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def parse_iso(iso_str: str) -> Optional[datetime]:
    if not iso_str or not isinstance(iso_str, str):
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return None


def eta_minutes(eta_iso: Optional[str]) -> Optional[int]:
    dt = parse_iso(eta_iso) if eta_iso else None
    if not dt:
        return None
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = (dt.astimezone(timezone.utc) - now).total_seconds()
    if diff < -120:
        return None
    return max(0, int(round(diff / 60.0)))


def parse_hk_dt(s: str) -> Optional[datetime]:
    # Parse MTR-style datetime as Hong Kong time
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=HK_TZ)
    except Exception:
        return None


def minutes_from_compact_text(s: str) -> Optional[int]:
    # Extract minutes from strings like '5 min', '5 分鐘'
    if not s or not isinstance(s, str):
        return None
    m = re.search(r"(\d+)", s)
    if not m:
        return None
    try:
        return max(0, int(m.group(1)))
    except Exception:
        return None


def eta_minutes_from_hhmm(now_hk: datetime, hhmm: str) -> Optional[int]:
    # For ferry APIs that return only HH:MM, compute minutes from now
    if not hhmm or not isinstance(hhmm, str):
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})$", hhmm.strip())
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    try:
        eta = now_hk.replace(hour=hh, minute=mm, second=0, microsecond=0)
    except Exception:
        return None
    if eta < now_hk - timedelta(minutes=2):
        eta = eta + timedelta(days=1)
    diff = (eta - now_hk).total_seconds()
    return max(0, int(round(diff / 60.0)))


def cursor_make(qkey: str, offset: int) -> str:
    return f"{qkey}:{offset}"


def cursor_parse(cursor: Optional[str]) -> Tuple[str, int]:
    if not cursor:
        return "", 0
    try:
        q, off = cursor.split(":", 1)
        return q, int(off)
    except Exception:
        return "", 0


def limit_items(items: list, offset: int, limit: int) -> Tuple[list, Optional[str]]:
    limit = max(1, min(limit, 50))
    sliced = items[offset : offset + limit]
    next_cursor = None
    if offset + limit < len(items):
        next_cursor = cursor_make("q", offset + limit)
    return sliced, next_cursor




# ============================================================
# HKO Client
# ============================================================
class HKOClient:
    BASE = "https://data.weather.gov.hk/weatherAPI/opendata"

    TIDE_STATIONS: Dict[str, str] = {
        "CCH": "Cheung Chau",
        "CLK": "Chek Lap Kok",
        "CMW": "Chi Ma Wan",
        "KCT": "Kwai Chung",
        "KLW": "Ko Lau Wan",
        "LOP": "Lok On Pai",
        "MWC": "Ma Wan",
        "QUB": "Quarry Bay",
        "SPW": "Shek Pik",
        "TAO": "Tai O",
        "TBT": "Tsim Bei Tsui",
        "TMW": "Tai Miu Wan",
        "TPK": "Tai Po Kau",
        "WAG": "Waglan Island",
    }

    CLIMATE_STATIONS: Dict[str, str] = {
        "CCH": "Cheung Chau",
        "CWB": "Clear Water Bay",
        "HKA": "Hong Kong International Airport",
        "HKO": "Hong Kong Observatory",
        "HKP": "Hong Kong Park",
        "HKS": "Wong Chuk Hang",
        "HPV": "Happy Valley",
        "JKB": "Tseung Kwan O",
        "KLT": "Kowloon City",
        "KP": "King's Park",
        "KSC": "Kau Sai Chau",
        "KTG": "Kwun Tong",
        "LFS": "Lau Fau Shan",
        "NGP": "Ngong Ping",
        "PEN": "Peng Chau",
        "PLC": "Tai Mei Tuk",
        "SE1": "Kai Tak Runway Park",
        "SEK": "Shek Kong",
        "SHA": "Sha Tin",
        "SKG": "Sai Kung",
        "SKW": "Shau Kei Wan",
        "SSH": "Sheung Shui",
        "SSP": "Sham Shui Po",
        "STY": "Stanley",
        "TC": "Tate's Cairn",
        "TKL": "Ta Kwu Ling",
        "TMS": "Tai Mo Shan",
        "TPO": "Tai Po (Conservation Studies Centre)",
        "TU1": "Tuen Mun Children and Juvenile Home",
        "TW": "Tsuen Wan Shing Mun Valley",
        "TWN": "Tsuen Wan",
        "TY1": "New Tsing Yi Station",
        "TYW": "Pak Tam Chung (Tsak Yue Wu)",
        "VP1": "The Peak",
        "WGL": "Waglan Island",
        "WLP": "Wetland Park",
        "WTS": "Wong Tai Sin",
        "YCT": "Tai Po (Yuan Chau Tsai Park)",
        "YLP": "Yuen Long Park",
    }

    RYES_STATIONS: Dict[str, str] = {
        "CCH": "Cheung Chau",
        "CLK": "Chek Lap Kok",
        "EPC": "Ping Chau",
        "HKO": "Hong Kong Observatory",
        "HKP": "Hong Kong Park",
        "HKS": "Wong Chuk Hang",
        "HPV": "Happy Valley",
        "JKB": "Tseung Kwan O",
        "KAT": "Kat O",
        "KLT": "Kowloon City",
        "KP": "King's Park",
        "KTG": "Kwun Tong",
        "LFS": "Lau Fau Shan",
        "PLC": "Tai Mei Tuk",
        "SE1": "Kai Tak Runway Park",
        "SEK": "Shek Kong",
        "SHA": "Sha Tin",
        "SKG": "Sai Kung",
        "SKW": "Shau Kei Wan",
        "SSP": "Sham Shui Po",
        "STK": "Sha Tau Kok",
        "STY": "Stanley",
        "SWH": "Sai Wan Ho",
        "TAP": "Tap Mun",
        "TBT": "Tsim Bei Tsui",
        "TKL": "Ta Kwu Ling",
        "TUN": "Tuen Mun",
        "TW": "Tsuen Wan Shing Mun Valley",
        "TWN": "Tsuen Wan Ho Koon",
        "TY1": "Tsing Yi",
        "WTS": "Wong Tai Sin",
        "YCT": "Tai Po",
        "YLP": "Yuen Long Park",
        "YNF": "Yuen Ng Fan",
    }

    def __init__(self, http: "HTTPClient"):
        self.http = http

    async def _get(self, endpoint: str, params: dict) -> Any:
        url = f"{self.BASE}/{endpoint}"
        return await self.http.request(url, params=params, expect="json", cache_scope="mem", cache_ttl_s=60)

    async def _get_text(self, endpoint: str, params: dict) -> Any:
        url = f"{self.BASE}/{endpoint}"
        return await self.http.request(url, params=params, expect="text", cache_scope="mem", cache_ttl_s=60)


# ============================================================
# LandsD Client
# ============================================================
class LandsDClient:
    LOCATION_BASE = "https://www.map.gov.hk/gs/api"
    LOCATION_VERSION = "v1.0.0"
    TRANSFORM_BASE = "https://www.geodetic.gov.hk/transform/v2/"

    def __init__(self, http: HTTPClient):
        self.http = http

    async def location_search(self, q: str, limit: int = 10) -> List[dict]:
        q = (q or "").strip()
        if not q:
            return []
        limit = max(1, min(int(limit), 25))
        url = f"{self.LOCATION_BASE}/{self.LOCATION_VERSION}/locationSearch"
        params = {"q": q}
        j = await self.http.request(url, params=params, expect="json", cache_scope="mem", cache_ttl_s=3600)
        if isinstance(j, dict) and j.get("error"):
            return []
        if not isinstance(j, list):
            return []
        rows = [x for x in j if isinstance(x, dict)][:limit]
        out = []
        for r in rows:
            x = coerce_float(r.get("x"))
            y = coerce_float(r.get("y"))
            wgs = None
            if x is not None and y is not None:
                wgs = await self.transform_hk1980_to_wgs84(float(x), float(y))
            out.append(
                {
                    "name": {"en": r.get("nameEN"), "zh": r.get("nameZH")},
                    "address": {"en": r.get("addressEN"), "zh": r.get("addressZH")},
                    "district": {"en": r.get("districtEN"), "zh": r.get("districtZH")},
                    "hk1980": {"x": x, "y": y},
                    "wgs84": wgs,
                }
            )
        return out

    async def transform_hk1980_to_wgs84(self, x: float, y: float) -> Optional[dict]:
        j = await self.http.request(
            self.TRANSFORM_BASE,
            params={"inSys": "hkgrid", "outSys": "wgsgeog", "e": float(x), "n": float(y)},
            method="GET",
            expect="json",
            cache_scope="mem",
            cache_ttl_s=30 * 24 * 3600,
        )
        if not isinstance(j, dict) or j.get("error"):
            return None

        lat = coerce_float(
            j.get("wgsLat") or j.get("wgslat") or j.get("lat") or j.get("latitude")
        )
        lon = coerce_float(
            j.get("wgsLong")
            or j.get("wgslong")
            or j.get("wgsLon")
            or j.get("wgslon")
            or j.get("lon")
            or j.get("long")
            or j.get("longitude")
        )
        if lat is None or lon is None:
            return None

        return {"lat": float(lat), "lon": float(lon)}


# ============================================================
# HTTP Client
# ============================================================
class HTTPClient:
    # HTTP operations with caching and retries

    def __init__(self, valves: "Valves", cache_dir: str):
        self.valves = valves
        self.cache_dir = cache_dir
        self._client: Optional[httpx.AsyncClient] = None
        self._mem: Dict[str, Tuple[float, Any]] = {}
        self._mem_lock = asyncio.Lock()

    def _cache_path(self, name: str) -> Path:
        return Path(self.cache_dir) / name

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"User-Agent": "HongKongOpenDataTool/0.6.0"}
            self._client = httpx.AsyncClient(
                timeout=self.valves.http_timeout_s, headers=headers
            )
        return self._client

    async def request(
        self,
        url: str,
        params: Optional[dict] = None,
        *,
        method: Literal["GET", "POST"] = "GET",
        json_body: Optional[dict] = None,
        expect: Literal["json", "text"] = "json",
        cache_ttl_s: Optional[int] = None,
        cache_scope: Literal["mem", "disk", "none"] = "none",
    ) -> Any:
        # Internal HTTP helper with retries + optional caching
        params = params or {}
        ttl = cache_ttl_s if cache_ttl_s is not None else self.valves.cache_ttl_s

        body_key = ""
        if json_body is not None:
            try:
                body_key = json.dumps(json_body, sort_keys=True, ensure_ascii=False)
            except Exception:
                body_key = str(json_body)

        key_material = (
            f"{method} {url}?"
            + "&".join([f"{k}={params[k]}" for k in sorted(params.keys())])
            + f" body={body_key}"
        )
        key = sha256(key_material)

        if cache_scope == "mem":
            async with self._mem_lock:
                item = self._mem.get(key)
                if item:
                    t0, val = item
                    if (now_s() - t0) <= ttl:
                        return val
                    self._mem.pop(key, None)

        if cache_scope == "disk":
            p = self._cache_path(f"{key}.json")
            if p.exists():
                try:
                    if (now_s() - p.stat().st_mtime) <= ttl:
                        return json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    pass

        client = await self._get_client()
        retries = max(0, int(self.valves.http_retries))
        last_err: Optional[str] = None

        for attempt in range(retries + 1):
            try:
                if method == "POST":
                    resp = await client.post(url, params=params or None, json=json_body)
                else:
                    resp = await client.get(url, params=params or None)

                if resp.status_code == 429 or (500 <= resp.status_code <= 599):
                    last_err = f"HTTP {resp.status_code}"
                    if attempt < retries:
                        await asyncio.sleep(min(0.75 * (2**attempt), 5.0))
                        continue

                resp.raise_for_status()
                data = resp.json() if expect == "json" else resp.text

                if cache_scope == "mem":
                    async with self._mem_lock:
                        self._mem[key] = (now_s(), data)
                elif cache_scope == "disk":
                    p = self._cache_path(f"{key}.json")
                    try:
                        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass

                return data
            except Exception as e:
                last_err = str(e)
                if attempt < retries:
                    await asyncio.sleep(min(0.5 * (2**attempt), 3.0))
                    continue

        return {
            "error": "request_failed",
            "detail": last_err,
            "url": url,
            "params": params,
            "method": method,
        }

    async def get_json(self, url: str, **kwargs) -> Optional[dict]:
        # Fetch JSON response
        r = await self.request(url, expect="json", cache_scope="none", **kwargs)
        if isinstance(r, dict) and r.get("error"):
            return None
        return r if isinstance(r, dict) else None

    async def get_text(self, url: str, **kwargs) -> Optional[str]:
        # Fetch text response
        r = await self.request(url, expect="text", cache_scope="none", **kwargs)
        if isinstance(r, dict) and r.get("error"):
            return None
        return r if isinstance(r, str) else None


# ============================================================
# Models / valves
# ============================================================
class Valves(BaseModel):
    cache_dir: str = Field(
        default_factory=lambda: str(Path(tempfile.gettempdir()) / "hk_open_data_cache")
    )
    cache_ttl_s: int = 24 * 3600
    eta_cache_ttl_s: int = 20
    max_concurrency: int = 8
    http_timeout_s: int = 15
    http_retries: int = 2

    # Trip planner knobs (HK-scale). Can also be overridden per-call via `preferences`.
    plan_origin_candidates_cap: int = 80
    plan_destination_candidates_cap: int = 80

    plan_transfer_walk_radius_m: int = 800
    plan_transfer_walk_max_stops: int = 80

    plan_max_board_per_stop: int = 80
    plan_max_alight_per_board: int = 120

    plan_max_down_route_scan: int = 260
    plan_hub_degree_threshold: int = 3
    plan_alight_near_dest_k: int = 30
    plan_alight_every_n: int = 6
    plan_alight_ferry_access_k: int = 24

    plan_max_expansions: int = 100000
    plan_max_pq: int = 240000
    plan_max_runtime_s: float = 20.0

    plan_eta_call_limit: int = 220

    # Transfer cap: HK can legitimately require 5+ transfers for remote NT points.
    # This caps the user-provided `max_transfers` (legs = transfers + 1).
    plan_max_transfers_cap: int = 10
    plan_default_max_transfers: int = 6
    # hkbus DB options (rarely change; keep minimal knobs)
    hkbus_primary_base: str = HKBUS_PRIMARY_BASE
    hkbus_fallback_base: str = HKBUS_FALLBACK_BASE


# ============================================================
# TransitDB: Transit database loading, indexing, and ETA fetching
# ============================================================
class TransitDB:
    GTFS_AGENCY_MAP = {
        "nwff": "sunferry",
        "hkkf": "hkkf",
        "craw": "fortuneferry",
        "star": "starferry",
        "pi": "parkisland",
        "pdbb": "dbferry",
        "coralsea": "coralsea",
        "tks": "tsuiwahferry",
        "chuenkee": "chuenkee",
    }

    def __init__(self, http: HTTPClient, valves: "Valves"):
        self.http = http
        self.valves = valves
        self._db_lock = asyncio.Lock()
        self._db_loaded = False
        self._db_source: Optional[str] = None
        self._db_md5: Optional[str] = None
        self._stop_list: Dict[str, dict] = {}
        self._route_list: Dict[str, dict] = {}
        self._stop_to_routes: Dict[str, List[StopOcc]] = {}
        self._route_company_stops: Dict[Tuple[str, str], List[str]] = {}
        self._route_company_stop_index: Dict[Tuple[str, str], Dict[str, int]] = {}
        self._stop_degree: Dict[str, int] = {}
        self._grid: Dict[Tuple[int, int], List[str]] = {}
        self._grid_cell: float = 0.004
        self._transfer_edges: Dict[str, List[Tuple[str, float]]] = {}

    def meta(self) -> dict:
        return {
            "cached_db": self._db_loaded,
            "db_source": self._db_source,
            "db_md5": self._db_md5,
        }

    async def lrt_next_trains(self, station_id: int) -> List[dict]:
        return await self.fetch_lrt_next_trains(station_id)

    async def ensure_loaded(self) -> None:
        if self._db_loaded:
            return
        async with self._db_lock:
            if self._db_loaded:
                return
            db, source, md5 = await self._load_hkbus_db()
            if not db:
                raise RuntimeError("Failed to load hkbus DB.")
            self._stop_list = db.get("stopList") or {}
            self._route_list = db.get("routeList") or {}
            await self.load_and_merge_gtfs_ferries()
            db["stopList"] = self._stop_list
            db["routeList"] = self._route_list
            self._build_indices(db)
            self._db_loaded = True
            self._db_source = source
            self._db_md5 = md5

    async def _load_hkbus_db(self) -> Tuple[Optional[dict], Optional[str], Optional[str]]:
        cache_dir = Path(self.valves.cache_dir)
        safe_mkdir(cache_dir)
        db_path = cache_dir / HKBUS_DB_JSON
        md5_path = cache_dir / HKBUS_DB_MD5

        if db_path.exists() and md5_path.exists():
            try:
                if (now_s() - db_path.stat().st_mtime) <= self.valves.cache_ttl_s:
                    j = json.loads(db_path.read_text(encoding="utf-8"))
                    md5 = md5_path.read_text(encoding="utf-8").strip()
                    return j, "disk", md5
            except Exception:
                pass

        async def try_source(base: str) -> Tuple[Optional[dict], Optional[str]]:
            md5 = await self.http.get_text(f"{base}/{HKBUS_DB_MD5}")
            if not md5:
                return None, None
            db = await self.http.get_json(f"{base}/{HKBUS_DB_JSON}")
            if not db:
                return None, None
            return db, md5.strip()

        db, md5 = await try_source(self.valves.hkbus_primary_base)
        source = self.valves.hkbus_primary_base
        if not db:
            db, md5 = await try_source(self.valves.hkbus_fallback_base)
            source = self.valves.hkbus_fallback_base

        if db and md5:
            try:
                db_path.write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")
                md5_path.write_text(md5, encoding="utf-8")
            except Exception:
                pass
            return db, source, md5

        if db_path.exists():
            try:
                j = json.loads(db_path.read_text(encoding="utf-8"))
                md5 = md5_path.read_text(encoding="utf-8").strip() if md5_path.exists() else None
                return j, "disk_stale", md5
            except Exception:
                pass

        return None, None, None

    def _build_indices(self, db: dict) -> None:
        self._stop_list = db.get("stopList") or {}
        self._route_list = db.get("routeList") or {}

        if not isinstance(self._stop_list, dict):
            self._stop_list = {}
        if not isinstance(self._route_list, dict):
            self._route_list = {}

        stop_to_routes: Dict[str, List[StopOcc]] = {}
        route_company_stops: Dict[Tuple[str, str], List[str]] = {}
        route_company_stop_index: Dict[Tuple[str, str], Dict[str, int]] = {}

        for rid, r in self._route_list.items():
            if not isinstance(r, dict):
                continue
            stops = r.get("stops")
            if not isinstance(stops, dict):
                continue
            for co_raw, seq in stops.items():
                if not isinstance(seq, list):
                    continue
                co = norm_co(co_raw)
                key = (rid, co)
                route_company_stops[key] = [str(x) for x in seq if isinstance(x, str)]
                idx = {}
                for i, sid in enumerate(route_company_stops[key]):
                    idx[sid] = i
                    stop_to_routes.setdefault(sid, []).append(StopOcc(route_id=rid, company=co, seq=i))
                route_company_stop_index[key] = idx

        stop_degree: Dict[str, int] = {}
        for sid, occs in stop_to_routes.items():
            stop_degree[sid] = len({(o.company, o.route_id) for o in occs})

        self._stop_to_routes = stop_to_routes
        self._route_company_stops = route_company_stops
        self._route_company_stop_index = route_company_stop_index
        self._stop_degree = stop_degree

        grid: Dict[Tuple[int, int], List[str]] = {}
        cell_size = 0.004
        for sid, s in self._stop_list.items():
            if not isinstance(s, dict):
                continue
            loc = s.get("location") or {}
            lat = coerce_float(loc.get("lat"))
            lon = coerce_float(loc.get("lng"))
            if lat is None or lon is None:
                continue
            gx = int(float(lat) / cell_size)
            gy = int(float(lon) / cell_size)
            grid.setdefault((gx, gy), []).append(str(sid))

        self._grid = grid
        self._grid_cell = cell_size

        transfer_edges: Dict[str, List[Tuple[str, float]]] = {}
        for sid, s in self._stop_list.items():
            loc = s.get("location") or {}
            lat = coerce_float(loc.get("lat"))
            lon = coerce_float(loc.get("lng"))
            if lat is None or lon is None:
                continue

            near = []
            gx = int(float(lat) / cell_size)
            gy = int(float(lon) / cell_size)
            steps = 2
            for dx in range(-steps, steps + 1):
                for dy in range(-steps, steps + 1):
                    for sid2 in grid.get((gx + dx, gy + dy), []):
                        if sid == sid2:
                            continue
                        s2 = self._stop_list.get(sid2, {})
                        loc2 = s2.get("location") or {}
                        lat2 = coerce_float(loc2.get("lat"))
                        lon2 = coerce_float(loc2.get("lng"))
                        if lat2 is None or lon2 is None:
                            continue
                        dist = haversine_m(float(lat), float(lon), float(lat2), float(lon2))
                        if dist <= 800.0:
                            near.append((sid2, dist))

            near.sort(key=lambda x: x[1])
            transfer_edges[sid] = near[:30]

        self._transfer_edges = transfer_edges

    async def load_and_merge_gtfs_ferries(self) -> None:
        cache_path = Path(self.valves.cache_dir) / "hk_gtfs_ferries_cache_v9.json"

        if cache_path.exists() and (now_s() - cache_path.stat().st_mtime) < 86400:
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    ferry_data = json.load(f)
                    self._inject_ferry_data_to_memory(ferry_data)
                    return
            except Exception:
                pass

        gtfs_urls = {
            "en": "https://static.data.gov.hk/td/pt-headway-en/gtfs.zip",
            "tc": "https://static.data.gov.hk/td/pt-headway-tc/gtfs.zip",
        }

        responses = {}
        async with httpx.AsyncClient(follow_redirects=True) as client:
            for lang, url in gtfs_urls.items():
                response = await client.get(url, timeout=30.0)
                response.raise_for_status()
                responses[lang] = response.content

        ferry_data = {"stops": {}, "routes": {}, "route_stops": {}}

        def normalize_route_name(name: str) -> str:
            n = str(name).lower()
            n = re.sub(r"[\s\-\–\—\(\)]", "", n)
            n = n.replace("to", "").replace("ordinaryferry", "").replace("fastferry", "")
            return n

        existing_ferry_fingerprints = set()
        for r_key, r_info in self._route_list.items():
            if not isinstance(r_info, dict):
                continue
            co_list = r_info.get("co", [])
            if not co_list:
                continue
            co = norm_co(co_list[0])
            if mode_of_company(co) == "ferry" or co in self.GTFS_AGENCY_MAP.values():
                route_name = str(r_info.get("route", ""))
                norm_name = normalize_route_name(route_name)
                existing_ferry_fingerprints.add((co, norm_name))

        def read_csv(z, filename):
            with z.open(filename) as f:
                content = f.read().decode("utf-8-sig").splitlines()
                return list(csv.DictReader(content))

        z_en = zipfile.ZipFile(io.BytesIO(responses["en"]))
        z_tc = zipfile.ZipFile(io.BytesIO(responses["tc"]))

        routes_en_raw = read_csv(z_en, "routes.txt")
        routes_tc_raw = read_csv(z_tc, "routes.txt")
        routes_tc = {r["route_id"]: r for r in routes_tc_raw}

        ferry_routes = {}

        for r in routes_en_raw:
            rt_type = str(r.get("route_type", "")).strip()
            if rt_type not in ("4", "1000", "1200"):
                continue
            raw_agency = r.get("agency_id", "").lower()
            mapped_co = self.GTFS_AGENCY_MAP.get(raw_agency, raw_agency)
            raw_name = r.get("route_short_name") or r.get("route_long_name") or "Ferry"
            norm_name = normalize_route_name(raw_name)

            is_duplicate = False
            for existing_co, existing_norm_name in existing_ferry_fingerprints:
                if mapped_co == existing_co and norm_name == existing_norm_name:
                    is_duplicate = True
                    break

            if is_duplicate:
                continue

            ferry_routes[r["route_id"]] = {
                "route_id": r["route_id"],
                "agency": mapped_co,
                "name": raw_name,
            }

        trips_en_raw = read_csv(z_en, "trips.txt")
        trips_meta = {}
        representative_trips = {}
        seen_route_dirs = set()

        for t in trips_en_raw:
            r_id = t["route_id"]
            if r_id in ferry_routes:
                trips_meta[t["trip_id"]] = {
                    "route_id": r_id,
                    "direction_id": t.get("direction_id", "0"),
                    "service_id": t.get("service_id", "1"),
                }
                dir_key = f"{r_id}_{t.get('direction_id', '0')}"
                if dir_key not in seen_route_dirs:
                    representative_trips[t["trip_id"]] = trips_meta[t["trip_id"]]
                    seen_route_dirs.add(dir_key)

        calendar_en_raw = read_csv(z_en, "calendar.txt")
        service_bitmasks = {}
        for c in calendar_en_raw:
            mask = 0
            if c.get("monday") == "1": mask |= 1
            if c.get("tuesday") == "1": mask |= 2
            if c.get("wednesday") == "1": mask |= 4
            if c.get("thursday") == "1": mask |= 8
            if c.get("friday") == "1": mask |= 16
            if c.get("saturday") == "1": mask |= 32
            if c.get("sunday") == "1": mask |= 64
            service_bitmasks[c["service_id"]] = str(mask)

        trip_frequencies = {}
        try:
            freq_en_raw = read_csv(z_en, "frequencies.txt")
            for f in freq_en_raw:
                t_id = f["trip_id"]
                start_hhmm = f["start_time"][:5].replace(":", "")
                end_hhmm = f["end_time"][:5].replace(":", "")
                h_mins = max(1, int(f["headway_secs"]) // 60)
                trip_frequencies.setdefault(t_id, []).append((start_hhmm, end_hhmm, h_mins))
        except KeyError:
            pass
        except Exception:
            pass

        stop_times_en_raw = read_csv(z_en, "stop_times.txt")
        trip_stops = {}
        trip_first_depart = {}

        for st in stop_times_en_raw:
            t_id = st["trip_id"]
            if t_id in trips_meta:
                seq = int(st["stop_sequence"])
                if t_id in representative_trips:
                    trip_stops.setdefault(t_id, []).append((seq, st["stop_id"]))
                if seq == 1 or t_id not in trip_first_depart:
                    trip_first_depart[t_id] = st["departure_time"]

        freq_data = {}
        for t_id, meta in trips_meta.items():
            r_id = meta["route_id"]
            d_id = meta["direction_id"]
            raw_s_id = meta["service_id"]
            s_id = service_bitmasks.get(raw_s_id, raw_s_id)
            dir_key = f"{r_id}_{d_id}"
            if dir_key not in freq_data:
                freq_data[dir_key] = {}
            if s_id not in freq_data[dir_key]:
                freq_data[dir_key][s_id] = {}

            if t_id in trip_frequencies:
                for start_hm, end_hm, h_mins in trip_frequencies[t_id]:
                    freq_data[dir_key][s_id][start_hm] = [end_hm, h_mins]
            else:
                depart = trip_first_depart.get(t_id)
                if depart:
                    hhmm = depart[:5].replace(":", "")
                    freq_data[dir_key][s_id][hhmm] = None

        stops_en_raw = read_csv(z_en, "stops.txt")
        stops_tc_raw = read_csv(z_tc, "stops.txt")
        stops_en = {s["stop_id"]: s for s in stops_en_raw}
        stops_tc = {s["stop_id"]: s for s in stops_tc_raw}

        def resolve_route_code(agency: str, r_id: str, orig_en: str, dest_en: str, orig_tc: str, dest_tc: str) -> str:
            if agency == "sunferry":
                sunferry_pairs = [
                    ("CECC", "Central", "Cheung Chau"),
                    ("CEMW", "Central", "Mui Wo"),
                    ("NPHH", "North Point", "Hung Hom"),
                    ("NPKC", "North Point", "Kowloon City"),
                    ("IIPECMUW", "Peng Chau", "Mui Wo"),
                    ("IIMUWCMW", "Mui Wo", "Chi Ma Wan"),
                    ("IICMWCHC", "Chi Ma Wan", "Cheung Chau"),
                    ("IICHCMUW", "Cheung Chau", "Mui Wo"),
                    ("IIMUWCHC", "Mui Wo", "Cheung Chau"),
                ]
                o_en_low, d_en_low = orig_en.lower(), dest_en.lower()
                for code, mo, md in sunferry_pairs:
                    if (mo.lower() in o_en_low and md.lower() in d_en_low) or (md.lower() in o_en_low and mo.lower() in d_en_low):
                        return code
            elif agency == "fortuneferry":
                fortune_pairs = [
                    ("7059", "中環", "紅磡"),
                    ("7021", "北角", "啟德"),
                    ("7056", "北角", "觀塘"),
                    ("7025", "屯門", "大澳"),
                    ("7000004", "東涌", "大澳"),
                ]
                for code, mo, md in fortune_pairs:
                    if (mo in orig_tc and md in dest_tc) or (md in orig_tc and mo in dest_tc):
                        return code
            elif agency == "hkkf":
                hkkf_pairs = [
                    ("KF1", "Central", "Sok Kwu Wan"),
                    ("KF2", "Central", "Yung Shue Wan"),
                    ("KF3", "Central", "Peng Chau"),
                    ("KF4", "Peng Chau", "Hei Ling Chau"),
                ]
                o_en_low, d_en_low = orig_en.lower(), dest_en.lower()
                for code, mo, md in hkkf_pairs:
                    if (mo.lower() in o_en_low and md.lower() in d_en_low) or (md.lower() in o_en_low and mo.lower() in d_en_low):
                        return code
            return r_id

        ferry_pier_ids = set()
        for t_id, stops in trip_stops.items():
            trip_meta = representative_trips[t_id]
            r_id = trip_meta["route_id"]
            direction_id = trip_meta["direction_id"]
            bound_letter = "I" if direction_id == "1" else "O"

            stops.sort(key=lambda x: x[0])
            stop_ids = [s[1] for s in stops]
            ferry_pier_ids.update([s[1] for s in stops])

            rt_info = ferry_routes[r_id]
            orig_stop_id = stops[0][1]
            dest_stop_id = stops[-1][1]

            orig_en = stops_en.get(orig_stop_id, {}).get("stop_name", "Pier").strip()
            dest_en = stops_en.get(dest_stop_id, {}).get("stop_name", "Pier").strip()
            orig_tc = stops_tc.get(orig_stop_id, {}).get("stop_name", orig_en).strip()
            dest_tc = stops_tc.get(dest_stop_id, {}).get("stop_name", dest_en).strip()

            route_code = resolve_route_code(rt_info["agency"], r_id, orig_en, dest_en, orig_tc, dest_tc)
            unified_route_id = f"{route_code}+1+{orig_en}+{dest_en}"
            route_freq = freq_data.get(f"{r_id}_{direction_id}", {})

            ferry_data["route_stops"][unified_route_id] = stop_ids
            ferry_data["routes"][unified_route_id] = {
                "gtfsId": r_id,
                "route_id": unified_route_id,
                "route": route_code,
                "company": rt_info["agency"],
                "co": [rt_info["agency"]],
                "orig_tc": orig_tc,
                "orig_en": orig_en,
                "dest_tc": dest_tc,
                "dest_en": dest_en,
                "orig": {"en": orig_en, "zh": orig_tc},
                "dest": {"en": dest_en, "zh": dest_tc},
                "service_type": 1,
                "serviceType": "1",
                "bound": {rt_info["agency"]: bound_letter},
                "stops": {rt_info["agency"]: stop_ids, bound_letter: stop_ids},
                "freq": route_freq,
            }

        for sid in ferry_pier_ids:
            s_en = stops_en.get(sid, {})
            s_tc = stops_tc.get(sid, {})
            ferry_data["stops"][sid] = {
                "stop_id": sid,
                "name": {"en": s_en.get("stop_name", ""), "zh": s_tc.get("stop_name", s_en.get("stop_name", ""))},
                "lat": float(s_en.get("stop_lat", 0)),
                "lng": float(s_en.get("stop_lon", 0)),
            }

        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(ferry_data, f, ensure_ascii=False)
        except Exception:
            pass

        self._inject_ferry_data_to_memory(ferry_data)

    def _inject_ferry_data_to_memory(self, ferry_data: dict) -> None:
        for stop_id, stop_info in ferry_data["stops"].items():
            self._stop_list[stop_id] = {
                "stop": str(stop_id),
                "name": stop_info["name"],
                "location": {"lat": stop_info["lat"], "lng": stop_info["lng"]},
            }
            lat = float(stop_info["lat"])
            lon = float(stop_info["lng"])
            gx = int(lat / self._grid_cell)
            gy = int(lon / self._grid_cell)
            self._grid.setdefault((gx, gy), []).append(str(stop_id))

        for unified_route_id, stop_ids in ferry_data["route_stops"].items():
            route_meta = ferry_data["routes"][unified_route_id]
            company = route_meta["company"]
            COMPANY_MODE[company] = "ferry"

            self._route_list[unified_route_id] = {
                "gtfsId": route_meta.get("gtfsId"),
                "route": route_meta["route"],
                "co": [str(company)],
                "orig_tc": route_meta["orig_tc"],
                "orig_en": route_meta["orig_en"],
                "dest_tc": route_meta["dest_tc"],
                "dest_en": route_meta["dest_en"],
                "orig": route_meta["orig"],
                "dest": route_meta["dest"],
                "service_type": route_meta["service_type"],
                "serviceType": route_meta["serviceType"],
                "bound": route_meta["bound"],
                "stops": route_meta["stops"],
                "freq": route_meta["freq"],
            }

            self._route_company_stops[(unified_route_id, company)] = stop_ids
            self._route_company_stop_index[(unified_route_id, company)] = {sid: idx for idx, sid in enumerate(stop_ids)}

            for seq, sid in enumerate(stop_ids):
                occ = StopOcc(route_id=unified_route_id, company=company, seq=seq)
                if sid not in self._stop_to_routes:
                    self._stop_to_routes[sid] = []
                    self._stop_degree[sid] = 0
                self._stop_to_routes[sid].append(occ)
                self._stop_degree[sid] += 1

    def stop_lite(self, stop_id: str) -> Optional[dict]:
        s = self._stop_list.get(stop_id)
        if not isinstance(s, dict):
            return None
        loc = s.get("location") or {}
        lat = coerce_float(loc.get("lat"))
        lon = coerce_float(loc.get("lng"))
        name = s.get("name") or {}
        name_en = str(name.get("en", "") or "")
        name_zh = str(name.get("zh", "") or "")
        return {
            "stop_id": stop_id,
            "name": {"en": name_en, "zh": name_zh},
            "location": {"lat": lat, "lng": lon},
            "display": name_en if name_en else (name_zh if name_zh else stop_id),
        }

    def route_lite(self, route_id: str) -> Optional[dict]:
        r = self._route_list.get(route_id)
        if not isinstance(r, dict):
            return None
        return {
            "route_id": route_id,
            "route": str(r.get("route", "") or ""),
            "serviceType": r.get("serviceType"),
            "co": [str(x) for x in (r.get("co") or []) if isinstance(x, str)],
            "bound": r.get("bound") if isinstance(r.get("bound"), dict) else {},
            "orig": r.get("orig") if isinstance(r.get("orig"), dict) else {},
            "dest": r.get("dest") if isinstance(r.get("dest"), dict) else {},
        }

    def stop_distance_to_point(self, stop_id: str, lat2: float, lon2: float) -> Optional[float]:
        s = self._stop_list.get(stop_id)
        if not isinstance(s, dict):
            return None
        loc = s.get("location") or {}
        lat1 = coerce_float(loc.get("lat"))
        lon1 = coerce_float(loc.get("lng"))
        if lat1 is None or lon1 is None:
            return None
        return haversine_m(float(lat1), float(lon1), float(lat2), float(lon2))

    def nearby_stop_ids(self, lat: float, lon: float, radius_m: float, limit: int = 30) -> List[Tuple[str, float]]:
        cell = self._grid_cell
        gx = int(lat / cell)
        gy = int(lon / cell)
        steps = max(1, int((radius_m / 111000.0) / cell) + 1)
        cand = []
        for dx in range(-steps, steps + 1):
            for dy in range(-steps, steps + 1):
                for sid in self._grid.get((gx + dx, gy + dy), []):
                    d = self.stop_distance_to_point(sid, lat, lon)
                    if d is None:
                        continue
                    if d <= radius_m:
                        cand.append((sid, d))
        cand.sort(key=lambda x: x[1])
        return cand[:limit]

    async def fetch_kmb_etas(self, stop_id: str, route: str, bound: str, seq: int, service_type: str) -> List[dict]:
        async def _fetch(st: str) -> List[dict]:
            url = f"{KMB_ETA_BASE}/eta/{stop_id}/{route}/{st}"
            j = await self.http.request(url, expect="json", cache_scope="mem", cache_ttl_s=self.valves.eta_cache_ttl_s)
            if not isinstance(j, dict) or j.get("error"):
                return []
            data = j.get("data") or []
            return data if isinstance(data, list) else []

        data = await _fetch("1")
        st_obs = None
        if isinstance(service_type, str) and service_type.strip().isdigit():
            st_obs = service_type.strip()
        if (not data) and st_obs and st_obs != "1":
            data = await _fetch(st_obs)

        if not data:
            return []
        out = []
        for e in data:
            if not isinstance(e, dict):
                continue
            if bound and str(e.get("dir", "")).strip() != bound:
                continue
            out.append(e)
        out.sort(key=lambda x: x.get("eta") or "")
        return out

    async def fetch_ctb_etas(self, stop_id: str, route: str, bound: str, seq: int) -> List[dict]:
        url = f"{CTB_ETA_BASE}/eta/CTB/{stop_id}/{route}"
        j = await self.http.request(url, expect="json", cache_scope="mem", cache_ttl_s=self.valves.eta_cache_ttl_s)
        if not isinstance(j, dict) or j.get("error"):
            return []
        data = j.get("data") or []
        if not isinstance(data, list):
            return []
        out = []
        for e in data:
            if not isinstance(e, dict):
                continue
            if bound and str(e.get("dir", "")).strip() != bound:
                continue
            out.append(e)
        out.sort(key=lambda x: x.get("eta") or "")
        return out

    async def fetch_gmb_etas(self, stop_id: str, gtfs_id: str, bound: str, seq: int) -> List[dict]:
        url = f"{GMB_ETA_BASE}/eta/stop/{stop_id}/{gtfs_id}"
        j = await self.http.request(url, expect="json", cache_scope="mem", cache_ttl_s=self.valves.eta_cache_ttl_s)
        if not isinstance(j, dict) or j.get("error"):
            return []
        data = j.get("data") or []
        if not isinstance(data, list):
            return []
        out = []
        for e in data:
            if not isinstance(e, dict):
                continue
            out.append(e)
        out.sort(key=lambda x: x.get("eta") or "")
        return out

    async def fetch_mtr_next_trains(self, line: str, sta: str, lang: str = "en") -> List[dict]:
        if not line or not sta:
            return []
        lang0 = (lang or "en").lower()
        lang_param = "tc" if lang0 in ("tc", "zh", "sc") else "en"
        params = {"line": line, "sta": sta, "lang": lang_param}
        j = await self.http.request(MTR_TRAIN_BASE, params=params, expect="json", cache_ttl_s=self.valves.eta_cache_ttl_s, cache_scope="mem")
        if not isinstance(j, dict):
            return []

        status = j.get("status")
        if status == 0:
            return [{"direction": None, "dest": None, "platform": None, "minutes": None, "iso": None, "message": j.get("message") or "", "url": j.get("url"), "raw": j}]

        data = j.get("data")
        if not isinstance(data, dict):
            return []

        key = f"{line}-{sta}"
        payload = data.get(key)
        if not isinstance(payload, dict):
            return []

        out: List[dict] = []
        for d in ("UP", "DOWN"):
            arr = payload.get(d)
            if not isinstance(arr, list):
                continue
            for t in arr:
                if not isinstance(t, dict):
                    continue
                if str(t.get("valid", "Y")).upper() != "Y":
                    continue
                mins = None
                try:
                    if str(t.get("ttnt", "")).strip().isdigit():
                        mins = int(str(t.get("ttnt")).strip())
                except Exception:
                    mins = None
                dt = parse_hk_dt(str(t.get("time", "") or ""))
                iso = dt.isoformat() if dt else None
                out.append({"direction": d, "dest": t.get("dest"), "platform": t.get("plat"), "minutes": mins, "iso": iso, "seq": t.get("seq"), "source": t.get("source")})
        out.sort(key=lambda x: (10**9 if x.get("minutes") is None else int(x["minutes"]), str(x.get("direction") or "")))
        return out

    async def fetch_lrt_next_trains(self, station_id: int) -> List[dict]:
        if station_id <= 0:
            return []
        j = await self.http.request(MTR_LRT_BASE, params={"station_id": station_id}, expect="json", cache_ttl_s=self.valves.eta_cache_ttl_s, cache_scope="mem")
        if not isinstance(j, dict):
            return []
        out: List[dict] = []
        pls = j.get("platform_list")
        if not isinstance(pls, list):
            return out
        for p in pls:
            if not isinstance(p, dict):
                continue
            pid = p.get("platform_id")
            routes = p.get("route_list")
            if not isinstance(routes, list):
                continue
            for r in routes:
                if not isinstance(r, dict):
                    continue
                time_en = str(r.get("time_en", "") or "")
                mins = minutes_from_compact_text(time_en)
                out.append({"platform": pid, "route_no": r.get("route_no"), "dest_en": r.get("dest_en"), "dest_zh": r.get("dest_ch"), "minutes": mins, "text": time_en or None, "train_length": r.get("train_length"), "arrival_departure": r.get("arrival_departure")})
        out.sort(key=lambda x: (10**9 if x.get("minutes") is None else int(x["minutes"]), str(x.get("route_no") or "")))
        return out

    async def fetch_mtr_bus_next_buses(self, route_name: str, stop_id: str, lang: str = "en") -> List[dict]:
        if not route_name or not stop_id:
            return []
        lang0 = (lang or "en").lower()
        api_lang = "zh" if lang0 in ("tc", "zh", "sc") else "en"
        body = {"language": api_lang, "routeName": route_name}
        j = await self.http.request(MTR_BUS_BASE, method="POST", json_body=body, expect="json", cache_ttl_s=self.valves.eta_cache_ttl_s, cache_scope="mem")
        if not isinstance(j, dict):
            return []
        stops = j.get("busStop")
        if not isinstance(stops, list):
            return []
        target = None
        for s in stops:
            if isinstance(s, dict) and str(s.get("busStopId", "")).strip() == stop_id:
                target = s
                break
        if not isinstance(target, dict):
            return []

        out: List[dict] = []
        buses = target.get("bus")
        if not isinstance(buses, list):
            return out
        for b in buses:
            if not isinstance(b, dict):
                continue
            sec = None
            try:
                if str(b.get("departureTimeInSecond", "")).strip().isdigit():
                    sec = int(str(b.get("departureTimeInSecond")).strip())
            except Exception:
                sec = None
            mins = None
            if sec is not None:
                mins = max(0, int(round(sec / 60.0)))
            out.append({"minutes": mins, "text": b.get("departureTimeText") or b.get("arrivalTimeText") or None, "is_delayed": b.get("isDelayed"), "is_scheduled": b.get("isScheduled"), "remark": b.get("busRemark"), "lineRef": b.get("lineRef"), "busId": b.get("busId")})
        out.sort(key=lambda x: (10**9 if x.get("minutes") is None else int(x["minutes"])))
        return out

    async def fetch_sunferry_next_trip(self, route_code: str, lang: str = "en") -> List[dict]:
        if not route_code:
            return []
        params = {"route": route_code}
        j = await self.http.request(f"{SUNFERRY_BASE}/eta/", params=params, expect="json", cache_ttl_s=30, cache_scope="mem")
        if not isinstance(j, dict):
            return []
        data = j.get("data")
        if not isinstance(data, list):
            return []
        ts = j.get("generated_timestamp") or (data[0].get("date_timestamp") if data and isinstance(data[0], dict) else None)
        now_dt = parse_iso(str(ts or "")) or datetime.now(HK_TZ)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=HK_TZ)
        now_hk = now_dt.astimezone(HK_TZ)

        lang0 = (lang or "en").lower()
        out = []
        for r in data:
            if not isinstance(r, dict):
                continue
            eta_hhmm = str(r.get("eta", "") or "")
            mins = eta_minutes_from_hhmm(now_hk, eta_hhmm)
            rmk = r.get("rmk_en") if lang0 == "en" else r.get("rmk_tc") if lang0 in ("tc", "zh") else r.get("rmk_sc")
            out.append({"minutes": mins, "iso": None, "eta_hhmm": eta_hhmm or None, "depart_hhmm": r.get("depart_time"), "route_en": r.get("route_en"), "route_tc": r.get("route_tc"), "remark": rmk, "vesselcode": r.get("vesselcode")})
        out.sort(key=lambda x: (10**9 if x.get("minutes") is None else int(x["minutes"])))
        return out

    async def fetch_fortuneferry_next_trip(self, route_code: str, lang: str = "en") -> List[dict]:
        if not route_code:
            return []
        params = {"route": route_code}
        j = await self.http.request(f"{FORTUNEFERRY_BASE}/eta/", params=params, expect="json", cache_ttl_s=30, cache_scope="mem")
        if not isinstance(j, dict):
            return []
        data = j.get("data")
        if not isinstance(data, list):
            return []
        ts = j.get("generated_timestamp") or (data[0].get("date_timestamp") if data and isinstance(data[0], dict) else None)
        now_dt = parse_iso(str(ts or "")) or datetime.now(HK_TZ)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=HK_TZ)
        now_hk = now_dt.astimezone(HK_TZ)

        lang0 = (lang or "en").lower()
        out = []
        for r in data:
            if not isinstance(r, dict):
                continue
            eta_hhmm = str(r.get("eta", "") or "")
            mins = eta_minutes_from_hhmm(now_hk, eta_hhmm)
            rmk = r.get("rmk_en") if lang0 == "en" else r.get("rmk_tc") if lang0 in ("tc", "zh") else r.get("rmk_sc")
            out.append({"minutes": mins, "iso": None, "eta_hhmm": eta_hhmm or None, "depart_hhmm": r.get("depart_time"), "route_en": r.get("route_en"), "route_tc": r.get("route_tc"), "remark": rmk, "vesselcode": r.get("vesselcode")})
        out.sort(key=lambda x: (10**9 if x.get("minutes") is None else int(x["minutes"])))
        return out

    async def fetch_hkkf_next_trip(self, route_id: str, direction: str) -> List[dict]:
        rid = None
        try:
            if str(route_id).strip().isdigit():
                rid = int(str(route_id).strip())
        except Exception:
            rid = None
        if rid is None:
            return []
        dir0 = (direction or "outbound").strip().lower()
        if dir0 not in ("inbound", "outbound"):
            dir0 = "outbound"

        url = f"{HKKF_BASE}/opendata/eta/{rid}/{dir0}"
        j = await self.http.request(url, expect="json", cache_ttl_s=30, cache_scope="mem")
        if not isinstance(j, dict):
            return []
        data = j.get("data")
        if not isinstance(data, list):
            return []
        out = []
        for r in data:
            if not isinstance(r, dict):
                continue
            iso = r.get("ETA")
            mins = eta_minutes(str(iso)) if iso else None
            out.append({"minutes": mins, "iso": iso, "route_id": r.get("route_id"), "direction": r.get("direction"), "session_time": r.get("session_time"), "date": r.get("date")})
        out.sort(key=lambda x: (10**9 if x.get("minutes") is None else int(x["minutes"])))
        return out

    async def leg_next_departures(self, company: str, route_id: str, board_stop_id: str, board_seq: int, limit_etas: int = 2, lang: str = "en") -> List[dict]:
        r = self._route_list.get(route_id, {})
        if not isinstance(r, dict):
            return []

        co = norm_co(company)
        route_no = str(r.get("route", "") or "")
        bounds = r.get("bound", {}) if isinstance(r.get("bound"), dict) else {}
        bound = str(bounds.get(co, bounds.get(co.lower(), "")) or "")

        out: List[dict] = []

        if co == "kmb":
            observed_st = str(r.get("serviceType", "") or "").strip()
            arr = await self.fetch_kmb_etas(board_stop_id, route_no, bound, board_seq, observed_st)
            for e in arr[:limit_etas]:
                eta_iso = e.get("eta")
                mins = eta_minutes(eta_iso)
                out.append({"stop_id": board_stop_id, "route_id": route_id, "route": route_no, "company": "kmb", "mode": mode_of_company("kmb"), "direction": bound or None, "service_type_used": 1, "eta": {"iso": eta_iso, "minutes": mins, "text": (f"{mins} min" if mins is not None else None)}, "remark": {"en": e.get("rmk_en") or "", "zh": e.get("rmk_tc") or ""}})
            return out

        if co == "ctb":
            arr = await self.fetch_ctb_etas(board_stop_id, route_no, bound, board_seq)
            for e in arr[:limit_etas]:
                eta_iso = e.get("eta")
                mins = eta_minutes(eta_iso)
                out.append({"stop_id": board_stop_id, "route_id": route_id, "route": route_no, "company": "ctb", "mode": mode_of_company("ctb"), "direction": e.get("dir") or bound or None, "service_type_used": 1, "eta": {"iso": eta_iso, "minutes": mins, "text": (f"{mins} min" if mins is not None else None)}, "remark": {"en": e.get("rmk_en") or "", "zh": e.get("rmk_tc") or ""}})
            return out

        if co == "gmb":
            gtfs_id = str(r.get("gtfsId", "") or "").strip()
            if not gtfs_id:
                return []
            arr = await self.fetch_gmb_etas(board_stop_id, gtfs_id, bound, board_seq)
            for e in arr[:limit_etas]:
                eta_iso = e.get("eta") or None
                mins = eta_minutes(eta_iso) if eta_iso else None
                out.append({"stop_id": board_stop_id, "route_id": route_id, "route": route_no, "company": "gmb", "mode": mode_of_company("gmb"), "direction": bound or None, "service_type_used": 1, "eta": {"iso": eta_iso, "minutes": mins, "text": (f"{mins} min" if mins is not None else None)}, "remark": {"en": e.get("rmk_en") or "", "zh": e.get("rmk_tc") or ""}})
            return out

        if co == "mtr":
            trains = await self.fetch_mtr_next_trains(route_no, board_stop_id, lang=lang)
            for t in trains[:limit_etas]:
                mins = t.get("minutes")
                iso = t.get("iso")
                dest = t.get("dest")
                plat = t.get("platform")
                msg = t.get("message") or ""
                out.append({"stop_id": board_stop_id, "route_id": route_id, "route": route_no, "company": "mtr", "mode": mode_of_company("mtr"), "direction": t.get("direction"), "service_type_used": 1, "eta": {"iso": iso, "minutes": mins, "text": (f"{mins} min" if isinstance(mins, int) else None)}, "platform": plat, "dest": dest, "remark": {"en": msg, "zh": msg}, "url": t.get("url")})
            return out

        if co == "lightrail":
            station_id = None
            try:
                if str(board_stop_id).strip().isdigit():
                    station_id = int(str(board_stop_id).strip())
            except Exception:
                station_id = None
            if station_id is None:
                return []
            trains = await self.fetch_lrt_next_trains(station_id)
            filtered = [x for x in trains if str(x.get("route_no") or "") == route_no] or trains
            for t in filtered[:limit_etas]:
                mins = t.get("minutes")
                text = t.get("text")
                out.append({"stop_id": board_stop_id, "route_id": route_id, "route": route_no, "company": "lightrail", "mode": mode_of_company("lightrail"), "direction": None, "service_type_used": 1, "eta": {"iso": None, "minutes": mins, "text": text}, "platform": t.get("platform"), "dest": t.get("dest_en"), "remark": {"en": "", "zh": ""}})
            return out

        if co == "lrtfeeder":
            buses = await self.fetch_mtr_bus_next_buses(route_no, board_stop_id, lang=lang)
            for b in buses[:limit_etas]:
                mins = b.get("minutes")
                txt = b.get("text")
                out.append({"stop_id": board_stop_id, "route_id": route_id, "route": route_no, "company": "lrtfeeder", "mode": mode_of_company("lrtfeeder"), "direction": None, "service_type_used": 1, "eta": {"iso": None, "minutes": mins, "text": txt}, "remark": {"en": str(b.get("remark") or ""), "zh": str(b.get("remark") or "")}})
            return out

        if co == "sunferry":
            trips = await self.fetch_sunferry_next_trip(route_no, lang=lang)
            for t in trips[:limit_etas]:
                mins = t.get("minutes")
                out.append({"stop_id": board_stop_id, "route_id": route_id, "route": route_no, "company": "sunferry", "mode": mode_of_company("sunferry"), "direction": None, "service_type_used": 1, "eta": {"iso": None, "minutes": mins, "text": (t.get("eta_hhmm") or None)}, "remark": {"en": str(t.get("remark") or ""), "zh": str(t.get("remark") or "")}})
            return out

        if co == "fortuneferry":
            trips = await self.fetch_fortuneferry_next_trip(route_no, lang=lang)
            for t in trips[:limit_etas]:
                mins = t.get("minutes")
                out.append({"stop_id": board_stop_id, "route_id": route_id, "route": route_no, "company": "fortuneferry", "mode": mode_of_company("fortuneferry"), "direction": None, "service_type_used": 1, "eta": {"iso": None, "minutes": mins, "text": (t.get("eta_hhmm") or None)}, "remark": {"en": str(t.get("remark") or ""), "zh": str(t.get("remark") or "")}})
            return out

        if co == "hkkf":
            direction = bound.strip().lower() if bound else "outbound"
            trips = await self.fetch_hkkf_next_trip(route_no, direction=direction)
            for t in trips[:limit_etas]:
                mins = t.get("minutes")
                iso = t.get("iso")
                out.append({"stop_id": board_stop_id, "route_id": route_id, "route": route_no, "company": "hkkf", "mode": mode_of_company("hkkf"), "direction": t.get("direction") or direction, "service_type_used": 1, "eta": {"iso": iso, "minutes": mins, "text": (f"{mins} min" if isinstance(mins, int) else None)}, "remark": {"en": "", "zh": ""}})
            return out

        return out


# ============================================================
# Trip Planner
# ============================================================
class TripPlanner:
    WALK_SPEED_M_PER_MIN = 80.0
    WALK_WEIGHT = 1.5
    WAIT_WEIGHT = 1.5
    RIDE_WEIGHT = 1.0
    MAX_EXPANSIONS = 150000

    def __init__(self, transit: TransitDB, landsd: LandsDClient, valves: "Valves"):
        self.transit = transit
        self.landsd = landsd
        self.valves = valves

    def transfer_penalty(self, from_mode: Optional[str], to_mode: str) -> float:
        if not from_mode:
            return 0.0
        if from_mode == "rail" and to_mode == "rail":
            return 3.0
        if "bus" in from_mode and "bus" in to_mode:
            return 10.0
        if "ferry" in from_mode or "ferry" in to_mode:
            return 6.0
        return 8.0

    def mode_times(self, company: str, ride_stops: int) -> Tuple[float, float]:
        mode = mode_of_company(company)
        if mode == "rail":
            return 3.0, ride_stops * 1.8
        elif mode == "minibus":
            return 6.0, ride_stops * 1.5
        elif mode == "ferry":
            if company in ("starferry", "sunferry"):
                return 30.0, ride_stops * 12.0
            return 60.0, ride_stops * 15.0
        elif mode == "lightrail":
            return 5.0, ride_stops * 1.5
        else:
            return 8.0, ride_stops * 2.5

    def is_rail_station(self, stop_id: str) -> bool:
        for occ in self.transit._stop_to_routes.get(stop_id, []):
            if occ.company == "mtr":
                return True
        return False

    def walk_cost(self, distance_m: float, target_stop_id: str) -> float:
        effective_dist = distance_m
        if self.is_rail_station(target_stop_id) and distance_m > 150.0:
            effective_dist = max(50.0, distance_m - 250.0)
        walk_time = effective_dist / self.WALK_SPEED_M_PER_MIN
        return walk_time * self.WALK_WEIGHT

    def mode_bit(self, co: str) -> int:
        m = mode_of_company(co)
        return 1 if m == "rail" else 2 if m == "bus" else 4 if m == "ferry" else 8

    def is_operating_now(self, freq_data: dict, expected_bound: str = "", projected_dt: Optional[datetime] = None) -> bool:
        if not freq_data or not isinstance(freq_data, dict):
            return True
        now_hk = projected_dt or datetime.now(HK_TZ)
        hour = now_hk.hour
        day_of_week = now_hk.weekday()
        if hour < 4:
            hour += 24
            day_of_week = (day_of_week - 1) % 7
        current_time_str = f"{hour:02d}{now_hk.minute:02d}"
        today_bit = 1 << day_of_week
        bounds_to_check = [expected_bound] if expected_bound and expected_bound in freq_data else list(freq_data.keys())
        for b in bounds_to_check:
            bound_schedules = freq_data.get(b, {})
            if not isinstance(bound_schedules, dict):
                continue
            matching_schedules = []
            for day_mask_str, schedule in bound_schedules.items():
                try:
                    day_mask = int(day_mask_str)
                    if (day_mask & today_bit) > 0 or (day_mask & 128) > 0 or (day_mask & 256) > 0:
                        matching_schedules.append(schedule)
                except ValueError:
                    return True
            for schedule in matching_schedules:
                if not isinstance(schedule, dict):
                    continue
                fixed_times = []
                for start_str, value in schedule.items():
                    if value is None:
                        fixed_times.append(start_str)
                    elif isinstance(value, list) and len(value) >= 1:
                        end_str = str(value[0])
                        if start_str <= current_time_str <= end_str:
                            return True
                if fixed_times:
                    if min(fixed_times) <= current_time_str <= max(fixed_times):
                        return True
        return False

    async def plan(
        self,
        origin_place: str,
        destination_place: str,
        limit: int = 3,
        max_transfers: Optional[int] = None,
        preferences: Optional[dict] = None,
        lang: Literal["en", "tc", "sc"] = "en",
        __event_emitter__: Optional[Any] = None,
    ) -> dict:
        import heapq
        preferences = preferences or {}
        limit = max(1, min(int(limit), 5))
        max_transfers = int(max_transfers) if max_transfers is not None else 6

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Resolving locations…", "done": False}})

        o_loc = await self.landsd.location_search(origin_place, limit=1)
        d_loc = await self.landsd.location_search(destination_place, limit=1)

        def get_pt(loc_resp) -> Optional[Tuple[float, float]]:
            items = loc_resp.get("items", []) if isinstance(loc_resp, dict) else []
            if not items:
                return None
            w = items[0].get("wgs84") or {}
            lat, lon = coerce_float(w.get("lat")), coerce_float(w.get("lon"))
            return (lat, lon) if lat and lon else None

        o_pt = get_pt(o_loc)
        d_pt = get_pt(d_loc)

        if not o_pt or not d_pt:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "Could not resolve locations.", "done": True}})
            return {"error": "location_not_found", "detail": "Could not resolve WGS84 coordinates for origin/destination."}

        def get_knn_stops(pt, k=25, max_radius=800):
            near = self.transit.nearby_stop_ids(pt[0], pt[1], radius_m=max_radius, limit=k)
            if not near:
                near = self.transit.nearby_stop_ids(pt[0], pt[1], radius_m=4000, limit=3)
            return {sid: dist for sid, dist in near}

        o_candidates = get_knn_stops(o_pt, k=25)
        d_candidates = get_knn_stops(d_pt, k=25)
        d_set = set(d_candidates.keys())

        approach_goal_tails = {}
        for dsid in d_set:
            for occ in self.transit._stop_to_routes.get(dsid, []):
                co, rid = occ.company, occ.route_id
                seq_list = self.transit._route_company_stops.get((rid, co), [])
                idxmap = self.transit._route_company_stop_index.get((rid, co), {})
                di = idxmap.get(dsid)
                if di is not None:
                    for back in range(1, 80):
                        bi = int(di) - back
                        if bi < 0:
                            break
                        bsid = seq_list[bi]
                        if bsid == dsid:
                            continue
                        approach_goal_tails.setdefault(bsid, []).append({
                            "company": co, "route_id": rid, "board_stop_id": bsid,
                            "alight_stop_id": dsid, "board_seq": bi, "alight_seq": int(di),
                        })

        def h_time(stop_id: str) -> float:
            s = self.transit._stop_list.get(stop_id)
            if not isinstance(s, dict):
                return 0.0
            loc = s.get("location") or {}
            lat, lon = coerce_float(loc.get("lat")), coerce_float(loc.get("lng"))
            if not lat or not lon:
                return 0.0
            return haversine_m(lat, lon, d_pt[0], d_pt[1]) / 800.0

        pq = []
        push_id = 0
        pareto_visited = {}

        for sid, ow in o_candidates.items():
            actual_t0 = ow / self.WALK_SPEED_M_PER_MIN
            cost0 = self.walk_cost(float(ow), sid)
            st = {"cur": sid, "walk": float(ow), "actual_time": float(actual_t0), "perceived_cost": cost0, "tx": 0, "modes": 0, "legs": [], "last_was_walk": True}
            f_score = cost0 + (h_time(sid) * 1.5)
            heapq.heappush(pq, (f_score, cost0, st["actual_time"], st["walk"], push_id, st))
            pareto_visited[sid] = [(st["walk"], cost0, 0, 0)]
            push_id += 1

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Running Multi-Criteria A* Search…", "done": False}})

        best_goals = []
        expansions = 0
        global_best_cost = float("inf")
        eta_validity_cache = {}

        async def is_leg_active(L: dict) -> bool:
            co = norm_co(L["company"])
            if co not in ("kmb", "ctb", "nlb", "gmb"):
                return True
            rid = L["route_id"]
            bid = L["board_stop_id"]
            proj_mins = L.get("board_time_minutes", 0.0)
            cache_key = (co, rid, bid, int(proj_mins // 30))
            if cache_key in eta_validity_cache:
                return eta_validity_cache[cache_key]
            r = self.transit._route_list.get(rid, {})
            route_no = str(r.get("route", "")).strip().upper()
            if not route_no or route_no.endswith("R"):
                eta_validity_cache[cache_key] = True
                return True
            freq_data = r.get("freq")
            is_scheduled_now = True
            projected_dt = datetime.now(HK_TZ) + timedelta(minutes=proj_mins)
            if freq_data:
                bounds = r.get("bound", {}) if isinstance(r.get("bound"), dict) else {}
                bound = str(bounds.get(co, bounds.get(co.lower(), "")) or "")
                is_scheduled_now = self.is_operating_now(freq_data, bound, projected_dt)
            if not is_scheduled_now:
                eta_validity_cache[cache_key] = False
                return False
            board_seq = L.get("board_seq")
            if board_seq is None:
                idxmap = self.transit._route_company_stop_index.get((rid, co), {})
                board_seq = idxmap.get(bid, 0)
            etas = await self.transit.leg_next_departures(co, rid, bid, board_seq, limit_etas=1, lang=lang)
            has_live_eta = any(e.get("eta", {}).get("minutes") is not None for e in (etas or []))
            is_valid = has_live_eta or is_scheduled_now
            eta_validity_cache[cache_key] = is_valid
            return is_valid

        async def is_candidate_valid(legs: list) -> bool:
            for L in legs:
                if not await is_leg_active(L):
                    return False
            return True

        while pq and expansions < self.MAX_EXPANSIONS:
            f_score, perceived_cost, actual_time, walk_m, _, st = heapq.heappop(pq)
            if best_goals and f_score > global_best_cost * 1.25 and len(best_goals) >= 10:
                break
            cur = st["cur"]
            tx = st["tx"]
            modes = st["modes"]
            expansions += 1
            if expansions % 10 == 0:
                await asyncio.sleep(0)
                if __event_emitter__ and expansions % 100 == 0:
                    msg = f"Running A* Search... (Explored {expansions:,} transit combinations)"
                    await __event_emitter__({"type": "status", "data": {"description": msg, "done": False}})

            if cur in d_set and st["legs"]:
                final_walk = float(d_candidates[cur])
                effective_final_walk = final_walk
                if self.is_rail_station(cur) and final_walk > 150.0:
                    effective_final_walk = max(50.0, final_walk - 250.0)
                walk_penalty_multiplier = 1.0 if effective_final_walk <= 800.0 else (effective_final_walk / 800.0)
                final_walk_time = effective_final_walk / self.WALK_SPEED_M_PER_MIN
                total_walk = walk_m + final_walk
                total_actual_time = actual_time + final_walk_time
                total_perceived = perceived_cost + (final_walk_time * self.WALK_WEIGHT * walk_penalty_multiplier)
                if total_perceived < global_best_cost:
                    global_best_cost = total_perceived
                if not await is_candidate_valid(st["legs"]):
                    continue
                if total_perceived < global_best_cost:
                    global_best_cost = total_perceived
                best_goals.append({"perceived_cost": total_perceived, "actual_time": total_actual_time, "walk_m": total_walk, "transfers": tx, "legs": list(st["legs"]), "modes": modes, "final_stop": cur})
                if final_walk < 300.0:
                    continue

            if cur in approach_goal_tails and st["legs"]:
                for tail in approach_goal_tails[cur]:
                    from_mode = mode_of_company(st["legs"][-1]["company"])
                    to_mode = mode_of_company(tail["company"])
                    ntx = tx
                    if not (from_mode == "rail" and to_mode == "rail"):
                        ntx = tx + 1
                    if ntx > max_transfers:
                        continue
                    final_stop = tail["alight_stop_id"]
                    ride_stops = tail["alight_seq"] - tail["board_seq"]
                    wait_time, ride_time = self.mode_times(tail["company"], ride_stops)
                    tx_penalty = self.transfer_penalty(from_mode, to_mode)
                    final_walk = float(d_candidates.get(final_stop, 0.0))
                    effective_final_walk = final_walk
                    if self.is_rail_station(final_stop) and final_walk > 150.0:
                        effective_final_walk = max(50.0, final_walk - 250.0)
                    final_walk_time = effective_final_walk / self.WALK_SPEED_M_PER_MIN
                    total_walk = walk_m + final_walk
                    total_actual_time = actual_time + wait_time + ride_time + final_walk_time
                    tail_perceived = (wait_time * self.WAIT_WEIGHT) + (ride_time * self.RIDE_WEIGHT) + tx_penalty + (final_walk_time * self.WALK_WEIGHT)
                    total_perceived = perceived_cost + tail_perceived
                    if total_perceived < global_best_cost:
                        global_best_cost = total_perceived
                    nlegs = list(st["legs"])
                    tail_copy = tail.copy()
                    tail_copy["board_time_minutes"] = actual_time
                    nlegs.append(tail_copy)
                    if not await is_candidate_valid(nlegs):
                        continue
                    if total_perceived < global_best_cost:
                        global_best_cost = total_perceived
                    best_goals.append({"perceived_cost": total_perceived, "actual_time": total_actual_time, "walk_m": total_walk, "transfers": ntx, "legs": nlegs, "modes": modes | self.mode_bit(tail["company"]), "final_stop": final_stop})

            if tx >= max_transfers:
                continue

            if not st.get("last_was_walk"):
                for neighbor, walk_dist in self.transit._transfer_edges.get(cur, []):
                    nw = walk_m + walk_dist
                    walk_time = walk_dist / self.WALK_SPEED_M_PER_MIN
                    nt_actual = actual_time + walk_time
                    leg_cost = self.walk_cost(walk_dist, neighbor)
                    ncost = perceived_cost + leg_cost
                    dominated = False
                    for pw, pcost, ptx, pm in pareto_visited.get(neighbor, []):
                        if pw <= nw and pcost <= ncost and ptx <= tx and pm == modes:
                            dominated = True
                            break
                    if not dominated:
                        pareto_visited.setdefault(neighbor, []).append((nw, ncost, tx, modes))
                        nst = {"cur": neighbor, "walk": nw, "actual_time": nt_actual, "perceived_cost": ncost, "tx": tx, "modes": modes, "legs": list(st["legs"])}
                        nf = ncost + (h_time(neighbor) * 1.5)
                        heapq.heappush(pq, (nf, ncost, nt_actual, nw, push_id, nst))
                        push_id += 1

            for occ in self.transit._stop_to_routes.get(cur, []):
                rid, co = occ.route_id, occ.company
                if st["legs"] and st["legs"][-1]["route_id"] == rid:
                    continue
                to_mode = mode_of_company(co)
                mode_bit = self.mode_bit(co)
                nmodes = modes | mode_bit
                from_mode = mode_of_company(st["legs"][-1]["company"]) if st["legs"] else None
                tx_penalty = self.transfer_penalty(from_mode, to_mode)
                ntx = tx
                if not (from_mode == "rail" and to_mode == "rail"):
                    ntx = tx + 1
                seq_list = self.transit._route_company_stops.get((rid, co), [])
                if occ.seq >= len(seq_list):
                    continue
                for i in range(occ.seq + 1, min(len(seq_list), occ.seq + 120)):
                    alight_sid = seq_list[i]
                    ride_stops = i - occ.seq
                    wait_time, ride_time = self.mode_times(co, ride_stops)
                    nt_actual = actual_time + wait_time + ride_time
                    leg_perceived_cost = (wait_time * self.WAIT_WEIGHT) + (ride_time * self.RIDE_WEIGHT) + tx_penalty
                    ncost = perceived_cost + leg_perceived_cost
                    dominated = False
                    for pw, pcost, ptx, pm in pareto_visited.get(alight_sid, []):
                        if pw <= walk_m and pcost <= ncost and ptx <= ntx and pm == nmodes:
                            dominated = True
                            break
                    if not dominated:
                        pareto_visited.setdefault(alight_sid, []).append((walk_m, ncost, ntx, nmodes))
                        nlegs = list(st["legs"])
                        nlegs.append({"company": co, "route_id": rid, "board_stop_id": cur, "alight_stop_id": alight_sid, "board_time_minutes": actual_time})
                        nst = {"cur": alight_sid, "walk": walk_m, "actual_time": nt_actual, "perceived_cost": ncost, "tx": ntx, "modes": nmodes, "legs": nlegs, "last_was_walk": False}
                        nf = ncost + (h_time(alight_sid) * 1.5)
                        heapq.heappush(pq, (nf, ncost, nt_actual, walk_m, push_id, nst))
                        push_id += 1

        if not best_goals:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "Could not find a feasible route.", "done": True}})
            return {"error": "no_route_found", "detail": "Could not find a feasible route."}

        champion_fastest = min(best_goals, key=lambda x: x["actual_time"])
        champion_direct = min(best_goals, key=lambda x: (x["transfers"], x["actual_time"]))
        champion_lazy = min(best_goals, key=lambda x: (x["walk_m"], x["actual_time"]))
        balanced_goals = sorted(best_goals, key=lambda x: x["perceived_cost"])

        unique_plans = []
        seen_sigs = set()

        def add_plan(g, semantic_tag):
            sig = ">".join([f"{L['company']}:{L['route_id']}:{L['alight_stop_id']}" for L in g["legs"]])
            if sig in seen_sigs:
                for plan in unique_plans:
                    if plan["_sig"] == sig and semantic_tag not in plan["tags"]:
                        plan["tags"].append(semantic_tag)
                return
            g_copy = g.copy()
            g_copy["tags"] = [semantic_tag]
            g_copy["_sig"] = sig
            unique_plans.append(g_copy)
            seen_sigs.add(sig)

        add_plan(champion_fastest, "fastest")
        add_plan(champion_direct, "fewest_transfers")
        add_plan(champion_lazy, "least_walking")
        for g in balanced_goals:
            if len(unique_plans) >= limit:
                break
            add_plan(g, "balanced")

        itineraries = []
        for g in unique_plans:
            formatted_legs = []
            g.pop("_sig", None)
            first_leg = g["legs"][0]
            live_etas = await self.transit.leg_next_departures(first_leg["company"], first_leg["route_id"], first_leg["board_stop_id"], 0, limit_etas=1, lang=lang)
            live_wait = live_etas[0].get("eta", {}).get("minutes") if live_etas else None
            if live_wait is not None:
                g["actual_time"] = (g["actual_time"] - 5.0) + float(live_wait)
            for L in g["legs"]:
                rlt = self.transit.route_lite(L["route_id"])
                b = self.transit.stop_lite(L["board_stop_id"])
                a = self.transit.stop_lite(L["alight_stop_id"])
                formatted_legs.append({"mode": mode_of_company(L["company"]), "operator": L["company"], "route": rlt, "board_stop": b, "alight_stop": a, "next_departures": live_etas if L == first_leg else []})
            itineraries.append({"tags": g["tags"], "score": round(g["perceived_cost"], 2), "summary": {"transfers": g["transfers"], "walk_m": round(g["walk_m"], 1), "time_min_est": round(g["actual_time"], 1)}, "legs": formatted_legs})

        itineraries.sort(key=lambda x: x["summary"]["time_min_est"])

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Done.", "done": True}})

        return {"meta": {}, "origin": {"label": origin_place}, "destination": {"label": destination_place}, "itineraries": itineraries[:limit]}


# ============================================================
# Tools class (ONLY public tool methods here)
# ============================================================
class Tools:
    """
    Hong Kong Open Data tool for Open WebUI.

    IMPORTANT for LLMs:
      - Call ONLY methods that start with:
          * hko_   (Hong Kong Observatory)
          * landsd_ (Lands Department)
          * td_    (Transport Department / hkbus aggregated)
      - Do NOT call internal helpers (functions starting with underscore). They are not tools.
    """

    # Expose valve model for Open WebUI UI
    class Valves(Valves):
        """User-configurable valves exposed in Open WebUI."""

        pass

    def __init__(self):
        self.valves = self.Valves()
        safe_mkdir(Path(self.valves.cache_dir))
        self.http = HTTPClient(self.valves, self.valves.cache_dir)
        self.hko = HKOClient(self.http)
        self.landsd = LandsDClient(self.http)
        self.transit = TransitDB(self.http, self.valves)
        self.planner = TripPlanner(self.transit, self.landsd, self.valves)

    def meta(self, source: Optional[str] = None) -> dict:
        base = {"tool": "Hong Kong Open Data", "version": "0.6.0", "ts": int(now_s())}
        if source == "td":
            return {**base, "data_source": "hkbus DB + Transport Department APIs", **self.transit.meta()}
        return base

    # =========================
    # HKO: Weather / Open Data API
    # =========================
    async def hko_weather_forecast(
        self,
        data_type: Literal[
            "flw", "fnd", "rhrread", "warnsum", "warningInfo", "swt"
        ] = "rhrread",
        lang: Literal["en", "tc", "sc"] = "en",
    ) -> dict:
        """
        Hong Kong Observatory (HKO) - Weather Information API.

        Official endpoint:
          - GET https://data.weather.gov.hk/weatherAPI/opendata/weather.php

        Parameters
        ----------
        data_type:
            - "rhrread"     Real-time weather report (current conditions)
            - "fnd"         9-day forecast
            - "flw"         Local weather forecast
            - "warnsum"     Summary of warnings
            - "warningInfo" Detailed warning info
            - "swt"         Special weather tips

            Notes:
              - Some older callers may send "rhr" (alias). This tool treats it as "rhrread".

        lang:
            - "en" English
            - "tc" Traditional Chinese
            - "sc" Simplified Chinese

        Examples
        --------
        Real-time weather (English):
            {"data_type":"rhrread","lang":"en"}

        9-day forecast (Traditional Chinese):
            {"data_type":"fnd","lang":"tc"}
        """
        # Backward compatibility alias: older callers may use "rhr"
        if data_type == "rhr":  # type: ignore[comparison-overlap]
            data_type = "rhrread"
        endpoint = "weather.php"
        params = {"dataType": data_type, "lang": lang}
        j = await self.hko._get(endpoint, params)
        return {"meta": self.meta(source="hko"), "data": j}

    async def hko_earthquake(
        self,
        data_type: Literal["qem", "feltearthquake"] = "qem",
        lang: Literal["en", "tc", "sc"] = "en",
    ) -> dict:
        """
        Hong Kong Observatory (HKO) - Earthquake Information API.

        Official endpoint:
          - GET https://data.weather.gov.hk/weatherAPI/opendata/earthquake.php

        Parameters
        ----------
        data_type:
            - "qem"            Quick Earthquake Messages
            - "feltearthquake" Locally-felt tremor report

        lang:
            - "en" | "tc" | "sc"

        Examples
        --------
        Latest quick earthquake messages:
            {"data_type":"qem","lang":"en"}

        Locally felt tremor report:
            {"data_type":"feltearthquake","lang":"en"}
        """
        endpoint = "earthquake.php"
        params = {"dataType": data_type, "lang": lang}
        j = await self.hko._get(endpoint, params)
        return {"meta": self.meta(source="hko"), "data": j}

    # --- Narrow, descriptive wrappers around `hko_opendata` (recommended for agents) ---

    async def hko_tide_hourly_heights(
        self,
        station: str,
        year: int,
        month: Optional[int] = None,
        day: Optional[int] = None,
        hour: Optional[int] = None,
        rformat: Literal["json", "csv"] = "json",
    ) -> dict:
        """
        HKO Open Data - Hourly heights of astronomical tides (HHOT).

        Recommended over `hko_opendata` for tidal-height queries.

        Parameters
        ----------
        station:
            Tide station code. Allowed values (code - name):
              - "CCH" - Cheung Chau
              - "CLK" - Chek Lap Kok
              - "CMW" - Chi Ma Wan
              - "KCT" - Kwai Chung
              - "KLW" - Ko Lau Wan
              - "LOP" - Lok On Pai
              - "MWC" - Ma Wan
              - "QUB" - Quarry Bay
              - "SPW" - Shek Pik
              - "TAO" - Tai O
              - "TBT" - Tsim Bei Tsui
              - "TMW" - Tai Miu Wan
              - "TPK" - Tai Po Kau
              - "WAG" - Waglan Island

        year:
            Required.

        month/day/hour:
            Optional filters; dependency rules apply:
              - month requires year
              - day requires year+month
              - hour requires year+month+day

        rformat:
            "json" (LLM-friendly) or "csv" (raw table).

        Example
        -------
        {"station":"CCH","year":2024,"month":3,"rformat":"json"}
        """
        return await self.hko_opendata(
            data_type="HHOT",
            rformat=rformat,
            station=station,
            year=year,
            month=month,
            day=day,
            hour=hour,
        )

    async def hko_tide_high_low(
        self,
        station: str,
        year: int,
        month: Optional[int] = None,
        day: Optional[int] = None,
        hour: Optional[int] = None,
        rformat: Literal["json", "csv"] = "json",
    ) -> dict:
        """
        HKO Open Data - Times and heights of astronomical high and low tides (HLT).

        Parameters
        ----------
        station:
            Tide station code. Allowed values (code - name):
              - "CCH" - Cheung Chau
              - "CLK" - Chek Lap Kok
              - "CMW" - Chi Ma Wan
              - "KCT" - Kwai Chung
              - "KLW" - Ko Lau Wan
              - "LOP" - Lok On Pai
              - "MWC" - Ma Wan
              - "QUB" - Quarry Bay
              - "SPW" - Shek Pik
              - "TAO" - Tai O
              - "TBT" - Tsim Bei Tsui
              - "TMW" - Tai Miu Wan
              - "TPK" - Tai Po Kau
              - "WAG" - Waglan Island

        year:
            Required.

        month/day/hour:
            Optional filters; dependency rules apply:
              - month requires year
              - day requires year+month
              - hour requires year+month+day

        rformat:
            "json" (LLM-friendly) or "csv" (raw table).

        Example
        -------
        {"station":"QUB","year":2024,"month":3,"rformat":"json"}
        """
        return await self.hko_opendata(
            data_type="HLT",
            rformat=rformat,
            station=station,
            year=year,
            month=month,
            day=day,
            hour=hour,
        )

    async def hko_sunrise_sunset(
        self,
        year: int,
        month: Optional[int] = None,
        day: Optional[int] = None,
        rformat: Literal["json", "csv"] = "json",
    ) -> dict:
        """
        HKO Open Data - Times of sunrise, sun transit and sunset (SRS).

        Parameters
        ----------
        year:
            Required.

        month/day:
            Optional filters; day requires year+month.

        Example
        -------
        {"year":2024,"month":6,"rformat":"json"}
        """
        return await self.hko_opendata(
            data_type="SRS",
            rformat=rformat,
            year=year,
            month=month,
            day=day,
        )

    async def hko_moonrise_moonset(
        self,
        year: int,
        month: Optional[int] = None,
        day: Optional[int] = None,
        rformat: Literal["json", "csv"] = "json",
    ) -> dict:
        """
        HKO Open Data - Times of moonrise, moon transit and moonset (MRS).

        Example
        -------
        {"year":2024,"month":6,"rformat":"json"}
        """
        return await self.hko_opendata(
            data_type="MRS",
            rformat=rformat,
            year=year,
            month=month,
            day=day,
        )

    async def hko_lightning_count(
        self,
        lang: Literal["en", "tc", "sc"] = "en",
        rformat: Literal["json", "csv"] = "json",
    ) -> dict:
        """
        HKO Open Data - Cloud-to-ground and cloud-to-cloud lightning count (LHL).

        Example
        -------
        {"lang":"en","rformat":"json"}
        """
        return await self.hko_opendata(
            data_type="LHL",
            rformat=rformat,
            lang=lang,
        )

    async def hko_visibility_10min_mean(
        self,
        lang: Literal["en", "tc", "sc"] = "en",
        rformat: Literal["json", "csv"] = "json",
    ) -> dict:
        """
        HKO Open Data - Latest 10-minute mean visibility (LTMV).

        Example
        -------
        {"lang":"en","rformat":"json"}
        """
        return await self.hko_opendata(
            data_type="LTMV",
            rformat=rformat,
            lang=lang,
        )

    async def hko_climate_daily_mean_temperature(
        self,
        station: str,
        year: Optional[int] = None,
        month: Optional[int] = None,
        rformat: Literal["json", "csv"] = "json",
    ) -> dict:
        """
        HKO Open Data - Daily mean temperature (CLMTEMP).

        Parameters
        ----------
        station:
            Climate station code. Allowed values (code - name):
              - "CCH" - Cheung Chau
              - "CWB" - Clear Water Bay
              - "HKA" - Hong Kong International Airport
              - "HKO" - Hong Kong Observatory
              - "HKP" - Hong Kong Park
              - "HKS" - Wong Chuk Hang
              - "HPV" - Happy Valley
              - "JKB" - Tseung Kwan O
              - "KLT" - Kowloon City
              - "KP" - King's Park
              - "KSC" - Kau Sai Chau
              - "KTG" - Kwun Tong
              - "LFS" - Lau Fau Shan
              - "NGP" - Ngong Ping
              - "PEN" - Peng Chau
              - "PLC" - Tai Mei Tuk
              - "SE1" - Kai Tak Runway Park
              - "SEK" - Shek Kong
              - "SHA" - Sha Tin
              - "SKG" - Sai Kung
              - "SKW" - Shau Kei Wan
              - "SSH" - Sheung Shui
              - "SSP" - Sham Shui Po
              - "STY" - Stanley
              - "TC" - Tate's Cairn
              - "TKL" - Ta Kwu Ling
              - "TMS" - Tai Mo Shan
              - "TPO" - Tai Po (Conservation Studies Centre)
              - "TU1" - Tuen Mun Children and Juvenile Home
              - "TW" - Tsuen Wan Shing Mun Valley
              - "TWN" - Tsuen Wan
              - "TY1" - New Tsing Yi Station
              - "TYW" - Pak Tam Chung (Tsak Yue Wu)
              - "VP1" - The Peak
              - "WGL" - Waglan Island
              - "WLP" - Wetland Park
              - "WTS" - Wong Tai Sin
              - "YCT" - Tai Po (Yuan Chau Tsai Park)
              - "YLP" - Yuen Long Park

        year/month:
            Optional but strongly recommended.
            If `year` is omitted, HKO may return a very large multi-year table.

        rformat:
            "json" (LLM-friendly) or "csv" (raw table).

        Example
        -------
        {"station":"HKO","year":2023,"rformat":"json"}
        """
        return await self.hko_opendata(
            data_type="CLMTEMP",
            rformat=rformat,
            station=station,
            year=year,
            month=month,
        )

    async def hko_climate_daily_max_temperature(
        self,
        station: str,
        year: Optional[int] = None,
        month: Optional[int] = None,
        rformat: Literal["json", "csv"] = "json",
    ) -> dict:
        """
        HKO Open Data - Daily maximum temperature (CLMMAXT).

        Parameters
        ----------
        station:
            Climate station code. Allowed values (code - name):
              - "CCH" - Cheung Chau
              - "CWB" - Clear Water Bay
              - "HKA" - Hong Kong International Airport
              - "HKO" - Hong Kong Observatory
              - "HKP" - Hong Kong Park
              - "HKS" - Wong Chuk Hang
              - "HPV" - Happy Valley
              - "JKB" - Tseung Kwan O
              - "KLT" - Kowloon City
              - "KP" - King's Park
              - "KSC" - Kau Sai Chau
              - "KTG" - Kwun Tong
              - "LFS" - Lau Fau Shan
              - "NGP" - Ngong Ping
              - "PEN" - Peng Chau
              - "PLC" - Tai Mei Tuk
              - "SE1" - Kai Tak Runway Park
              - "SEK" - Shek Kong
              - "SHA" - Sha Tin
              - "SKG" - Sai Kung
              - "SKW" - Shau Kei Wan
              - "SSH" - Sheung Shui
              - "SSP" - Sham Shui Po
              - "STY" - Stanley
              - "TC" - Tate's Cairn
              - "TKL" - Ta Kwu Ling
              - "TMS" - Tai Mo Shan
              - "TPO" - Tai Po (Conservation Studies Centre)
              - "TU1" - Tuen Mun Children and Juvenile Home
              - "TW" - Tsuen Wan Shing Mun Valley
              - "TWN" - Tsuen Wan
              - "TY1" - New Tsing Yi Station
              - "TYW" - Pak Tam Chung (Tsak Yue Wu)
              - "VP1" - The Peak
              - "WGL" - Waglan Island
              - "WLP" - Wetland Park
              - "WTS" - Wong Tai Sin
              - "YCT" - Tai Po (Yuan Chau Tsai Park)
              - "YLP" - Yuen Long Park

        year/month:
            Optional but strongly recommended.
            If `year` is omitted, HKO may return a very large multi-year table.

        rformat:
            "json" (LLM-friendly) or "csv" (raw table).

        Example
        -------
        {"station":"HKO","year":2023,"rformat":"json"}
        """
        return await self.hko_opendata(
            data_type="CLMMAXT",
            rformat=rformat,
            station=station,
            year=year,
            month=month,
        )

    async def hko_climate_daily_min_temperature(
        self,
        station: str,
        year: Optional[int] = None,
        month: Optional[int] = None,
        rformat: Literal["json", "csv"] = "json",
    ) -> dict:
        """
        HKO Open Data - Daily minimum temperature (CLMMINT).

        Parameters
        ----------
        station:
            Climate station code. Allowed values (code - name):
              - "CCH" - Cheung Chau
              - "CWB" - Clear Water Bay
              - "HKA" - Hong Kong International Airport
              - "HKO" - Hong Kong Observatory
              - "HKP" - Hong Kong Park
              - "HKS" - Wong Chuk Hang
              - "HPV" - Happy Valley
              - "JKB" - Tseung Kwan O
              - "KLT" - Kowloon City
              - "KP" - King's Park
              - "KSC" - Kau Sai Chau
              - "KTG" - Kwun Tong
              - "LFS" - Lau Fau Shan
              - "NGP" - Ngong Ping
              - "PEN" - Peng Chau
              - "PLC" - Tai Mei Tuk
              - "SE1" - Kai Tak Runway Park
              - "SEK" - Shek Kong
              - "SHA" - Sha Tin
              - "SKG" - Sai Kung
              - "SKW" - Shau Kei Wan
              - "SSH" - Sheung Shui
              - "SSP" - Sham Shui Po
              - "STY" - Stanley
              - "TC" - Tate's Cairn
              - "TKL" - Ta Kwu Ling
              - "TMS" - Tai Mo Shan
              - "TPO" - Tai Po (Conservation Studies Centre)
              - "TU1" - Tuen Mun Children and Juvenile Home
              - "TW" - Tsuen Wan Shing Mun Valley
              - "TWN" - Tsuen Wan
              - "TY1" - New Tsing Yi Station
              - "TYW" - Pak Tam Chung (Tsak Yue Wu)
              - "VP1" - The Peak
              - "WGL" - Waglan Island
              - "WLP" - Wetland Park
              - "WTS" - Wong Tai Sin
              - "YCT" - Tai Po (Yuan Chau Tsai Park)
              - "YLP" - Yuen Long Park

        year/month:
            Optional but strongly recommended.
            If `year` is omitted, HKO may return a very large multi-year table.

        rformat:
            "json" (LLM-friendly) or "csv" (raw table).

        Example
        -------
        {"station":"HKO","year":2023,"rformat":"json"}
        """
        return await self.hko_opendata(
            data_type="CLMMINT",
            rformat=rformat,
            station=station,
            year=year,
            month=month,
        )

    async def hko_weather_radiation_report(
        self,
        station: str,
        date: str = "yesterday",
        lang: Literal["en", "tc", "sc"] = "en",
        rformat: Literal["json", "csv"] = "json",
    ) -> dict:
        """
        HKO Open Data - Weather and Radiation Level Report (RYES).

        Parameters
        ----------
        station:
            Station code (Weather & Radiation Level Report). Allowed values (code - name):
              - "CCH" - Cheung Chau
              - "CLK" - Chek Lap Kok
              - "EPC" - Ping Chau
              - "HKO" - Hong Kong Observatory
              - "HKP" - Hong Kong Park
              - "HKS" - Wong Chuk Hang
              - "HPV" - Happy Valley
              - "JKB" - Tseung Kwan O
              - "KAT" - Kat O
              - "KLT" - Kowloon City
              - "KP" - King's Park
              - "KTG" - Kwun Tong
              - "LFS" - Lau Fau Shan
              - "PLC" - Tai Mei Tuk
              - "SE1" - Kai Tak Runway Park
              - "SEK" - Shek Kong
              - "SHA" - Sha Tin
              - "SKG" - Sai Kung
              - "SKW" - Shau Kei Wan
              - "SSP" - Sham Shui Po
              - "STK" - Sha Tau Kok
              - "STY" - Stanley
              - "SWH" - Sai Wan Ho
              - "TAP" - Tap Mun
              - "TBT" - Tsim Bei Tsui
              - "TKL" - Ta Kwu Ling
              - "TUN" - Tuen Mun
              - "TW" - Tsuen Wan Shing Mun Valley
              - "TWN" - Tsuen Wan Ho Koon
              - "TY1" - Tsing Yi
              - "WTS" - Wong Tai Sin
              - "YCT" - Tai Po
              - "YLP" - Yuen Long Park
              - "YNF" - Yuen Ng Fan

        date:
            - "yesterday" (recommended default; resolved to the most recent available bulletin)
            - "YYYYMMDD" (8 digits), e.g. "20240116"
            - "YYYY-MM-DD", e.g. "2024-01-16" (converted to YYYYMMDD)

        lang:
            "en" | "tc" | "sc"

        rformat:
            "json" (LLM-friendly) or "csv" (raw table).

        Example
        -------
        {"station":"KP","date":"yesterday","lang":"en","rformat":"json"}
        """
        return await self.hko_opendata(
            data_type="RYES",
            rformat=rformat,
            lang=lang,
            station=station,
            date=date,
        )

    async def hko_opendata(
        self,
        data_type: Literal[
            "HHOT",
            "HLT",
            "SRS",
            "MRS",
            "LHL",
            "LTMV",
            "CLMTEMP",
            "CLMMAXT",
            "CLMMINT",
            "RYES",
        ],
        rformat: Literal["json", "csv"] = "csv",
        *,
        lang: Literal["en", "tc", "sc"] = "en",
        station: Optional[str] = None,
        year: Optional[int] = None,
        month: Optional[int] = None,
        day: Optional[int] = None,
        hour: Optional[int] = None,
        date: Optional[str] = None,
    ) -> dict:
        """
        Hong Kong Observatory (HKO) - Open Data (Climate and Weather Information) API.

        Official endpoint:
          - GET https://data.weather.gov.hk/weatherAPI/opendata/opendata.php

        This endpoint multiplexes several datasets via `data_type` (HKO query parameter: `dataType`).
        If you are an agent, prefer the narrower wrappers (e.g. `hko_tide_high_low`,
        `hko_visibility_10min_mean`, `hko_climate_daily_max_temperature`, etc.).

        Output format is controlled by `rformat`:
          - "csv" (HKO default): raw CSV text
          - "json": JSON object (usually {"fields":[...], "data":[...]}; some datasets include "type"/"legend")

        Dataset selectors (`data_type`)
        ------------------------------
        Astronomical tides (requires tide station + year):
          - "HHOT": Hourly heights of astronomical tides
          - "HLT" : Times and heights of astronomical high and low tides

        Sun / Moon (requires year):
          - "SRS": Times of sunrise, sun transit and sunset
          - "MRS": Times of moonrise, moon transit and moonset

        Real-time environment (no station/year/month/day/hour/date):
          - "LHL" : Cloud-to-ground and cloud-to-cloud lightning count
          - "LTMV": Latest 10-minute mean visibility

        Climate temperatures (requires climate station; year/month optional but strongly recommended):
          - "CLMTEMP": Daily mean temperature
          - "CLMMAXT": Daily maximum temperature
          - "CLMMINT": Daily minimum temperature

        Weather & radiation (requires station; date optional default "yesterday"):
          - "RYES": Weather and Radiation Level Report

        Parameters and validation rules (enforced)
        ------------------------------------------
        - `month` requires `year`
        - `day` requires `year` + `month`
        - `hour` requires `year` + `month` + `day`
        - `date` is only valid for "RYES"
        - `station` requirements depend on dataset (see above)
        - Parameters not applicable to a dataset are rejected (prevents silent API errors)

        Station code mapping (code=name) is defined in-module as:
          - HKO_TIDE_STATION_MAP
          - HKO_CLIMATE_STATION_MAP
          - HKO_RYES_STATION_MAP

        LLM usage hints
        --------------
        - **HLT/HHOT**: always supply BOTH `station` and `year`. Add `month`/`day`/`hour` to reduce output.
        - **CLM***: always supply `station`. If you omit `year`, HKO defaults to **all years** (can be huge).
        - **RYES**: supply `station` and normally keep `date="yesterday"` unless a specific date is needed.
        - Prefer `rformat="json"` for structured downstream parsing.

        Examples
        --------
        Latest 10-minute mean visibility (JSON):
            {"data_type":"LTMV","rformat":"json","lang":"en"}

        High/low tide times & heights for Cheung Chau in March 2024 (CSV):
            {"data_type":"HLT","rformat":"csv","station":"CCH","year":2024,"month":3}

        Daily maximum temperature for HKO station in 2023 (JSON):
            {"data_type":"CLMMAXT","rformat":"json","station":"HKO","year":2023}

        Yesterday's Weather & Radiation Level report for King's Park (JSON):
            {"data_type":"RYES","rformat":"json","lang":"en","station":"KP","date":"yesterday"}
        """

        def _bad(detail: str, llm_hint: Optional[str] = None) -> dict:
            # Keep signature for internal call-sites but do not emit llm_hint in tool output.
            return {"error": "bad_request", "detail": detail}

        use_date: Optional[str] = None

        def _norm_station(s: Optional[str]) -> Optional[str]:
            if s is None:
                return None
            s2 = str(s).strip().upper()
            return s2 or None

        def _station_map_hint(m: Dict[str, str], max_items: int = 999) -> str:
            items = sorted(m.items())
            if max_items and len(items) > max_items:
                items = items[:max_items]
            return ", ".join([f"{k}={v}" for k, v in items])

        # --- Simple type/range validation for scalar params ---
        # We intentionally do NOT hardcode year ranges from the PDF because those shift over time.
        for name, val, lo, hi in (
            ("year", year, 1800, 2100),
            ("month", month, 1, 12),
            ("day", day, 1, 31),
            ("hour", hour, 1, 24),
        ):
            if val is None:
                continue
            try:
                ival = int(val)
            except Exception:
                return _bad(f"{name} must be an integer.")
            if not (lo <= ival <= hi):
                return _bad(f"{name} must be between {lo} and {hi}.")
            if name == "year":
                year = ival
            elif name == "month":
                month = ival
            elif name == "day":
                day = ival
            elif name == "hour":
                hour = ival

        # --- Hierarchical dependencies (per HKO spec) ---
        if month is not None and year is None:
            return _bad(
                "month requires year.",
                "Provide both year and month, e.g. year=2024, month=3.",
            )
        if day is not None and (year is None or month is None):
            return _bad(
                "day requires year and month.", "Provide year+month before adding day."
            )
        if hour is not None and (year is None or month is None or day is None):
            return _bad(
                "hour requires year, month and day.",
                "Provide year+month+day before adding hour.",
            )

        st = _norm_station(station)

        tide_station_map = HKO_TIDE_STATION_MAP
        climate_station_map = HKO_CLIMATE_STATION_MAP
        ryes_station_map = HKO_RYES_STATION_MAP

        tide_stations = set(tide_station_map.keys())
        climate_stations = set(climate_station_map.keys())
        ryes_stations = set(ryes_station_map.keys())

        # Reject parameters that are not applicable to the chosen dataset (prevents silent API errors).
        if data_type in ("HHOT", "HLT"):
            if st is None:
                return _bad(
                    f"{data_type} requires station.",
                    "Pick a tide station code (e.g., CCH, CLK, QUB) and include station=... in the call.",
                )
            if st not in tide_stations:
                return _bad(
                    f"Invalid tide station '{st}'.",
                    "Allowed tide stations (code=name): "
                    + _station_map_hint(tide_station_map),
                )
            if year is None:
                return _bad(
                    f"{data_type} requires year.",
                    "Include year=YYYY (and optionally month/day/hour).",
                )
            if date is not None:
                return _bad(
                    "date is only valid for RYES.",
                    "For tide datasets, use year/month/day/hour instead.",
                )

        elif data_type in ("SRS", "MRS"):
            if year is None:
                return _bad(
                    f"{data_type} requires year.",
                    "Include year=YYYY (and optionally month/day).",
                )
            if st is not None:
                return _bad(
                    "station is not applicable to SRS/MRS.",
                    "Remove station; only year/month/day are used.",
                )
            if hour is not None:
                return _bad(
                    "hour is not applicable to SRS/MRS.",
                    "Remove hour; only year/month/day are used.",
                )
            if date is not None:
                return _bad("date is only valid for RYES.", "Remove date for SRS/MRS.")

        elif data_type in ("LHL", "LTMV"):
            if any(v is not None for v in (st, year, month, day, hour, date)):
                return _bad(
                    f"{data_type} does not accept station/year/month/day/hour/date.",
                    "Use only lang and rformat for LHL/LTMV.",
                )

        elif data_type in ("CLMTEMP", "CLMMAXT", "CLMMINT"):
            if st is None:
                return _bad(
                    f"{data_type} requires station.",
                    "Pick a climate station code (e.g., HKO, HKA, KP, CWB) and include station=... in the call.",
                )
            if st not in climate_stations:
                return _bad(
                    f"Invalid climate station '{st}'.",
                    "Allowed climate stations (code=name): "
                    + _station_map_hint(climate_station_map),
                )
            if day is not None or hour is not None:
                return _bad(
                    "day/hour are not applicable to CLM* datasets.",
                    "Use only station, year, month.",
                )
            if date is not None:
                return _bad(
                    "date is only valid for RYES.", "Remove date for CLM* datasets."
                )

        elif data_type == "RYES":
            if st is None:
                return _bad(
                    "RYES requires station.",
                    "Pick a station code (e.g., KP, HKO, CCH, CLK) and include station=... in the call.",
                )
            if st not in ryes_stations:
                return _bad(
                    f"Invalid RYES station '{st}'.",
                    "Allowed RYES stations (code=name): "
                    + _station_map_hint(ryes_station_map),
                )
            if any(v is not None for v in (year, month, day, hour)):
                return _bad(
                    "RYES does not accept year/month/day/hour.",
                    "Use station + date (+lang/rformat).",
                )

            # Normalize date. HKO expects YYYYMMDD; "yesterday" is not a literal accepted by the API.
            def _hk_now() -> datetime:
                return datetime.now(timezone(timedelta(hours=8)))

            def _normalize_ryes_date(ds: Optional[str]) -> Optional[str]:
                now_hk = _hk_now()
                s = (ds or "").strip()
                if s == "" or s.lower() in ("yesterday", "latest"):
                    # Data is published after 01:30 HKT on the next day; before that time, the most recent
                    # available bulletin is usually the day before yesterday.
                    d = (
                        now_hk.date() - timedelta(days=2)
                        if (now_hk.hour, now_hk.minute) < (1, 30)
                        else now_hk.date() - timedelta(days=1)
                    )
                    return d.strftime("%Y%m%d")

                if s.lower() == "today":
                    # "today" bulletin is not provided; fall back to the most recent available (yesterday).
                    d = (
                        now_hk.date() - timedelta(days=2)
                        if (now_hk.hour, now_hk.minute) < (1, 30)
                        else now_hk.date() - timedelta(days=1)
                    )
                    return d.strftime("%Y%m%d")

                if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
                    try:
                        d = datetime.strptime(s, "%Y-%m-%d").date()
                    except Exception:
                        return None
                    return d.strftime("%Y%m%d")

                if re.match(r"^\d{8}$", s):
                    return s

                return None

            use_date = _normalize_ryes_date(date)
            if not use_date:
                return _bad(
                    "date must be YYYYMMDD (8 digits), YYYY-MM-DD, or 'yesterday'."
                )
            if use_date < "20190910":
                return _bad("date must be on/after 20190910 for RYES.")

            now_hk = _hk_now()
            latest = (
                now_hk.date() - timedelta(days=2)
                if (now_hk.hour, now_hk.minute) < (1, 30)
                else now_hk.date() - timedelta(days=1)
            )
            if use_date > latest.strftime("%Y%m%d"):
                return _bad(
                    f"date cannot be later than {latest.strftime('%Y%m%d')} for RYES."
                )

        else:
            return _bad("Unsupported data_type.")

        # --- Build request params (only include parameters relevant to the chosen dataType) ---
        params: Dict[str, Any] = {"dataType": data_type, "rformat": rformat}

        if data_type in ("HHOT", "HLT"):
            params["station"] = st
            params["year"] = int(year)  # required by validation
            if month is not None:
                params["month"] = int(month)
            if day is not None:
                params["day"] = int(day)
            if hour is not None:
                params["hour"] = int(hour)

        elif data_type in ("SRS", "MRS"):
            params["year"] = int(year)  # required
            if month is not None:
                params["month"] = int(month)
            if day is not None:
                params["day"] = int(day)

        elif data_type in ("LHL", "LTMV"):
            params["lang"] = lang

        elif data_type in ("CLMTEMP", "CLMMAXT", "CLMMINT"):
            params["station"] = st
            if year is not None:
                params["year"] = int(year)
            if month is not None:
                params["month"] = int(month)

        elif data_type == "RYES":
            params["lang"] = lang
            params["station"] = st
            params["date"] = use_date

        endpoint = "opendata.php"

        if rformat == "csv":
            csv_text = await self.hko._get_text(endpoint, params)
            out = {
                "meta": self.meta(source="hko"),
                "format": "csv",
                "data": csv_text,
                "params": params,
            }
            return out

        j = await self.hko._get(endpoint, params)
        out = {"meta": self.meta(source="hko"), "format": "json", "data": j, "params": params}
        return out

    async def hko_lunardate(self, date: str) -> dict:
        """
        Hong Kong Observatory (HKO) - Gregorian-Lunar Calendar Conversion API.

        Official endpoint:
          - GET https://data.weather.gov.hk/weatherAPI/opendata/lunardate.php

        Parameters
        ----------
        date:
            Gregorian date in "YYYY-MM-DD" format.

        Example
        -------
        {"date":"2026-03-04"}
        """
        if not isinstance(date, str) or not re.match(
            r"^\d{4}-\d{2}-\d{2}$", date.strip()
        ):
            return {
                "error": "bad_request",
                "detail": "date must be in YYYY-MM-DD format.",
                "llm_hint": "Example: date='2026-03-04'",
            }

        endpoint = "lunardate.php"
        params = {"date": date.strip()}
        j = await self.hko._get(endpoint, params)
        return {"meta": self.meta(source="hko"), "data": j}

    async def hko_hourly_rainfall(self, lang: Literal["en", "tc", "sc"] = "en") -> dict:
        """
        Hong Kong Observatory (HKO) - Rainfall in the Past Hour from Automatic Weather Station API.

        Official endpoint:
          - GET https://data.weather.gov.hk/weatherAPI/opendata/hourlyRainfall.php

        Parameters
        ----------
        lang:
            - "en" English
            - "tc" Traditional Chinese
            - "sc" Simplified Chinese

        Example
        -------
        {"lang":"en"}
        """
        endpoint = "hourlyRainfall.php"
        params = {"lang": lang}
        j = await self.hko._get(endpoint, params)
        return {"meta": self.meta(source="hko"), "data": j}

    # =========================
    # LandsD: Location Search + Transform
    # =========================
    async def landsd_location_search(self, query: str, limit: int = 10) -> dict:
        """
        Lands Department - Location Search API.
        Returns matched places with HK1980 x/y plus WGS84 lat/lon.

        Required:
          - query: place name (EN/ZH)

        Optional:
          - limit: max results (default 10; capped to 25)

        Example:
          {"query":"Ap Lei Chau","limit":5}
        """
        items = await self.landsd.location_search(query, limit=limit)
        return {"meta": self.meta(source="hko"), "query": query, "items": items}

    # =========================
    # TD: hkbus catalog + ETAs + planning
    # =========================
    async def td_catalog_status(self) -> dict:
        """
        Show hkbus DB status (loaded source + md5), and supported operators/modes.

        Example:
          {}
        """
        await self.transit.ensure_loaded()
        return {
            "meta": self.meta(source="hko"),
            "operators_seen": sorted(
                {o.company for occs in self.transit._stop_to_routes.values() for o in occs}
            ),
            "modes": sorted(set(COMPANY_MODE.values())),
        }

    async def td_stop_search(
        self, query: str, limit: int = 20, cursor: Optional[str] = None
    ) -> dict:
        """
        Search stops/stations/piers by name (EN/ZH), LLM-safe.

        Required:
          - query

        Optional:
          - limit (default 20; capped 50)
          - cursor: pagination cursor from previous call

        Example:
          {"query":"Central","limit":10}
        """
        await self.transit.ensure_loaded()
        q = normalize_text(query)
        if not q:
            return {"meta": self.meta(source="hko"), "items": [], "next_cursor": None}

        qkey, offset = cursor_parse(cursor)
        if qkey and qkey != "q":
            offset = 0

        hits = []
        for sid, s in self.transit._stop_list.items():
            if not isinstance(s, dict):
                continue
            name = s.get("name") or {}
            en = normalize_text(str(name.get("en", "") or ""))
            zh = normalize_text(str(name.get("zh", "") or ""))
            if q in en or q in zh:
                hits.append(self.transit.stop_lite(str(sid)))
        hits = [x for x in hits if x]
        hits.sort(key=lambda x: x["display"])
        sliced, next_cursor = limit_items(hits, offset, limit)
        if next_cursor:
            next_cursor = cursor_make("q", offset + len(sliced))
        return {
            "meta": self.meta(source="hko"),
            "query": query,
            "items": sliced,
            "next_cursor": next_cursor,
        }

    async def td_stop_nearby(
        self,
        place_name: Optional[str] = None,
        wgs84: Optional[dict] = None,
        radius_m: int = 300,
        limit: int = 20,
    ) -> dict:
        """
        Find nearby stops/stations/piers by coordinate or place name.

        Required: provide ONE of
          - place_name: will be resolved by landsd_location_search + coordinate transform
          - wgs84: {"lat":..,"lon":..}

        Optional:
          - radius_m (default 300)
          - limit (default 20; capped 50)

        Example:
          {"place_name":"Ap Lei Chau","radius_m":500,"limit":20}
        """
        await self.transit.ensure_loaded()
        limit = max(1, min(int(limit), 50))
        radius_m = max(50, int(radius_m))

        resolved = None
        lat = None
        lon = None

        if wgs84 and isinstance(wgs84, dict):
            lat = coerce_float(wgs84.get("lat"))
            lon = coerce_float(wgs84.get("lon"))
            resolved = {"input": {"wgs84": {"lat": lat, "lon": lon}}}
        elif place_name:
            loc = await self.landsd_location_search(place_name, limit=1)
            items = loc.get("items", []) if isinstance(loc, dict) else []
            if items and isinstance(items[0], dict):
                w = items[0].get("wgs84") or {}
                lat = coerce_float(w.get("lat"))
                lon = coerce_float(w.get("lon"))
                resolved = {"input": {"place_name": place_name}, "best_match": items[0]}
        else:
            return {"error": "bad_request", "detail": "Provide place_name or wgs84."}

        if lat is None or lon is None:
            return {
                "error": "resolve_failed",
                "detail": "Failed to resolve WGS84 coordinate.",
            }

        nearby = self.transit.nearby_stop_ids(
            float(lat), float(lon), radius_m=radius_m, limit=limit
        )
        out = []
        for sid, dist in nearby:
            s = self.transit.stop_lite(sid)
            if not s:
                continue
            s["distance_m"] = round(float(dist), 1)
            out.append(s)
        return {
            "meta": self.meta(source="hko"),
            "resolved_location": {
                "wgs84": {"lat": float(lat), "lon": float(lon)},
                "details": resolved,
            },
            "radius_m": radius_m,
            "items": out,
        }

    async def td_route_get(self, route_id: str) -> dict:
        """
        Get a route/line/ferry service by hkbus route_id (small, LLM-safe).

        Required:
          - route_id (from td_route_search or from itineraries)

        Example:
          {"route_id":"TCL+1+Hong Kong+Tung Chung"}
        """
        await self.transit.ensure_loaded()
        r = self.transit.route_lite(route_id)
        if not r:
            return {"error": "route_not_found", "detail": "Unknown route_id."}
        return {"meta": self.meta(source="hko"), "route": r}

    async def td_route_search(
        self, query: str, limit: int = 20, cursor: Optional[str] = None
    ) -> dict:
        """
        Search routes/lines/ferries by route number/name (LLM-safe).

        Required:
          - query: route number, line code, or partial (e.g., "TCL", "6", "CECC")

        Optional:
          - limit (default 20; capped 50)
          - cursor (pagination)

        Example:
          {"query":"TCL","limit":10}
        """
        await self.transit.ensure_loaded()
        q = normalize_text(query)
        if not q:
            return {"meta": self.meta(source="hko"), "items": [], "next_cursor": None}

        qkey, offset = cursor_parse(cursor)
        if qkey and qkey != "q":
            offset = 0

        hits = []
        for rid, r in self.transit._route_list.items():
            if not isinstance(r, dict):
                continue
            route_no = normalize_text(str(r.get("route", "") or ""))
            orig_en = normalize_text(str((r.get("orig") or {}).get("en", "") or ""))
            dest_en = normalize_text(str((r.get("dest") or {}).get("en", "") or ""))
            if q in route_no or q in orig_en or q in dest_en:
                hits.append(self.transit.route_lite(str(rid)))
        hits = [x for x in hits if x]
        hits.sort(key=lambda x: (x.get("route") or "", x.get("route_id") or ""))
        sliced, next_cursor = limit_items(hits, offset, limit)
        if next_cursor:
            next_cursor = cursor_make("q", offset + len(sliced))
        return {
            "meta": self.meta(source="hko"),
            "query": query,
            "items": sliced,
            "next_cursor": next_cursor,
        }

    async def td_departures_by_stop(
        self,
        stop_id: str,
        limit_routes: int = 8,
        limit_etas_per_route: int = 2,
        modes: Optional[List[str]] = None,
        operators: Optional[List[str]] = None,
        lang: Literal["en", "tc", "sc"] = "en",
    ) -> dict:
        """
        Next departures at a stop (LLM-safe, multi-modal, small).

        Required:
          - stop_id: hkbus stopId/stationId/pierId (from td_stop_search/td_stop_nearby/td_route_get)

        Optional:
          - limit_routes:
              * number of distinct services to include at this stop
              * default 8, hard-capped to 20
          - limit_etas_per_route:
              * number of ETA entries per service
              * default 2, hard-capped to 4
          - modes:
              * optional filter by high-level mode(s): ["bus","minibus","mtr_bus","rail","ferry"]
          - operators:
              * optional filter by hkbus `co` values (case-insensitive):
                ["kmb","ctb","nlb","gmb","lrtfeeder","mtr","lightRail","sunferry","hkkf","fortuneferry"]
                Note: internally, "lightRail" is normalized as "lightrail".
          - lang:
              * "en" English
              * "tc" Traditional Chinese (used by MTR APIs as zh/tc)
              * "sc" Simplified Chinese (best-effort; some MTR APIs only support en/tc)

        Example call:
          {"stop_id":"ADM","limit_routes":6,"limit_etas_per_route":2,"lang":"en"}

        Notes for LLMs:
          - This returns a compact, normalized list suitable for conversational answers.
          - KMB service_type is treated as optional/opaque; regular service (1) is preferred automatically.
        """
        await self.transit.ensure_loaded()
        limit_routes = max(1, min(int(limit_routes), 20))
        limit_etas_per_route = max(1, min(int(limit_etas_per_route), 4))

        stop = self.transit.stop_lite(stop_id)
        if not stop:
            return {"error": "stop_not_found", "detail": "Unknown stop_id."}

        # normalize filters
        op_filter = None
        if operators:
            op_filter = {
                norm_co(x) for x in operators if isinstance(x, str) and x.strip()
            }
        mode_filter = None
        if modes:
            mode_filter = {
                str(x).strip().lower()
                for x in modes
                if isinstance(x, str) and x.strip()
            }

        def allowed_company(co_norm: str) -> bool:
            if op_filter is not None and co_norm not in op_filter:
                return False
            if mode_filter is not None and mode_of_company(co_norm) not in mode_filter:
                return False
            return True

        occs = self.transit._stop_to_routes.get(stop_id, [])

        # Companies we can provide real-time-ish ETAs for (others may still appear in planning)
        eta_capable = {
            "kmb",
            "ctb",
            "gmb",
            "mtr",
            "lightrail",
            "lrtfeeder",
            "sunferry",
            "hkkf",
            "fortuneferry",
        }

        # Build service keys (dedupe aggressively; avoid redundant API calls)
        # - MTR (mtr): call per line code
        # - Light Rail (lightrail): call once per station, returns all routes
        # - Others: call per (route_id, company)
        mtr_lines = {}
        generic_services = []
        has_lrt = False

        for occ in occs:
            co = occ.company
            if co not in eta_capable:
                continue
            if not allowed_company(co):
                continue
            if co == "mtr":
                r = self.transit._route_list.get(occ.route_id, {})
                if isinstance(r, dict):
                    line = str(r.get("route", "") or "").strip()
                    if line:
                        mtr_lines.setdefault(line, occ.route_id)
            elif co == "lightrail":
                has_lrt = True
            else:
                generic_services.append((occ.route_id, co, occ.seq))

        # deterministic ranking for generic services
        def rk_service(x):
            rid, co, _ = x
            r = self.transit._route_list.get(rid, {})
            route_no = str(r.get("route", "") or "") if isinstance(r, dict) else ""
            return (co, route_no, rid)

        generic_services.sort(key=rk_service)

        # Dedupe generic by (route_id, company)
        uniq_generic = []
        seen = set()
        for rid, co, seq in generic_services:
            k = (rid, co)
            if k in seen:
                continue
            seen.add(k)
            uniq_generic.append((rid, co, seq))
            if len(uniq_generic) >= limit_routes:
                break

        departures: List[dict] = []

        # MTR lines (call per line; each call yields up/down next trains)
        for line, rid in sorted(mtr_lines.items()):
            if len(departures) >= limit_routes:
                break
            rows = await self.transit.leg_next_departures("mtr", rid, stop_id, 0, limit_etas=limit_etas_per_route, lang=lang
            )
            departures.extend(rows[:limit_etas_per_route])

        # Light Rail (single call; then take top results)
        if has_lrt and len(departures) < limit_routes and allowed_company("lightrail"):
            try:
                station_id = int(str(stop_id).strip())
            except Exception:
                station_id = None
            if station_id is not None:
                lrt_rows = await self.transit.lrt_next_trains(station_id)
                # Convert to same schema
                for r in lrt_rows[: max(0, limit_routes - len(departures))]:
                    departures.append(
                        {
                            "stop_id": stop_id,
                            "route_id": None,
                            "route": r.get("route_no"),
                            "company": "lightrail",
                            "mode": mode_of_company("lightrail"),
                            "direction": None,
                            "service_type_used": 1,
                            "eta": {
                                "iso": None,
                                "minutes": r.get("minutes"),
                                "text": r.get("text"),
                            },
                            "platform": r.get("platform"),
                            "dest": r.get("dest_en"),
                            "remark": {"en": "", "zh": ""},
                        }
                    )
                    if len(departures) >= limit_routes:
                        break

        # Remaining generic services (kmb/ctb/gmb/lrtfeeder/ferries)
        sem = asyncio.Semaphore(self.valves.max_concurrency)

        async def one(rid: str, co: str, seq: int) -> List[dict]:
            async with sem:
                return await self.transit.leg_next_departures(
                    co,
                    rid,
                    stop_id,
                    seq,
                    limit_etas=limit_etas_per_route,
                    lang=lang,
                )

        remaining_slots = max(0, limit_routes - len(departures))
        nested = await asyncio.gather(
            *[one(rid, co, seq) for rid, co, seq in uniq_generic[:remaining_slots]]
        )
        for sub in nested:
            for row in sub[:limit_etas_per_route]:
                departures.append(row)
            if len(departures) >= limit_routes:
                break

        return {"meta": self.meta(source="hko"), "stop": stop, "departures": departures}

    async def td_departures_nearby(
        self,
        place_name: Optional[str] = None,
        wgs84: Optional[dict] = None,
        radius_m: int = 250,
        limit_stops: int = 6,
        limit_routes_per_stop: int = 5,
        limit_etas_per_route: int = 2,
        modes: Optional[List[str]] = None,
        operators: Optional[List[str]] = None,
        lang: Literal["en", "tc", "sc"] = "en",
        __event_emitter__: Optional[Any] = None,
    ) -> dict:
        """
        Next departures near a place/point (LLM-safe, multi-modal, small).

        Required:
          - Provide ONE of:
              * place_name (string)
              * wgs84 {"lat":..,"lon":..}

        Optional:
          - radius_m: nearby stop search radius (default 250)
          - limit_stops: number of nearby stops to return (default 6; capped to 10)
          - limit_routes_per_stop: services per stop (default 5; capped to 10)
          - limit_etas_per_route: ETAs per service (default 2; capped to 4)
          - modes/operators/lang: passed through to td_departures_by_stop

        Example call:
          {"place_name":"Ap Lei Chau","radius_m":300,"limit_stops":5,"modes":["rail","bus"],"lang":"en"}
        """
        await self.transit.ensure_loaded()
        limit_stops = max(1, min(int(limit_stops), 10))
        limit_routes_per_stop = max(1, min(int(limit_routes_per_stop), 10))
        limit_etas_per_route = max(1, min(int(limit_etas_per_route), 4))

        near = await self.td_stop_nearby(
            place_name=place_name, wgs84=wgs84, radius_m=radius_m, limit=limit_stops
        )
        if isinstance(near, dict) and near.get("error"):
            return near

        stops = near.get("items", []) if isinstance(near, dict) else []
        if not isinstance(stops, list):
            stops = []

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"Fetching departures for {len(stops)} nearby stops…",
                        "done": False,
                    },
                }
            )

        sem = asyncio.Semaphore(self.valves.max_concurrency)

        async def one_stop(s: dict) -> dict:
            sid = s.get("stop_id")
            if not isinstance(sid, str):
                return {"stop": s, "departures": []}
            async with sem:
                dep = await self.td_departures_by_stop(
                    sid,
                    limit_routes=limit_routes_per_stop,
                    limit_etas_per_route=limit_etas_per_route,
                    modes=modes,
                    operators=operators,
                    lang=lang,
                )
            return {
                "stop": s,
                "departures": (
                    dep.get("departures", []) if isinstance(dep, dict) else []
                ),
            }

        try:
            items = await asyncio.gather(*[one_stop(s) for s in stops])
        finally:
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": "Done.", "done": True}}
                )

        return {
            "meta": self.meta(source="hko"),
            "resolved_location": near.get("resolved_location"),
            "radius_m": radius_m,
            "stops": items,
        }

    async def td_plan_trip(
        self,
        origin_place: str,
        destination_place: str,
        limit: int = 3,
        max_transfers: Optional[int] = None,
        preferences: Optional[dict] = None,
        lang: Literal["en", "tc", "sc"] = "en",
        __event_emitter__: Optional[Any] = None,
    ) -> dict:
        """
        Plan an optimized multimodal public-transport trip in Hong Kong.

        This planner uses a Multi-Criteria Pareto A* Search to efficiently find the best
        combinations of walk, bus, minibus, rail, and ferry legs. It naturally curates a
        diverse set of options (e.g., fast rail routes vs. direct bus routes) in a single pass.
        It also uses K-Nearest Neighbors (KNN) to resolve transit stops, allowing it to
        gracefully handle rural destinations (like Hoi Ha or Pak Tam Chung) that require
        longer initial/final walks.

        Parameters
        ----------
        origin_place : str
            Human-friendly origin place name, address, or POI.
            Examples: "Times Square, Causeway Bay", "Shek Pai Wan Estate".
        destination_place : str
            Human-friendly destination place name, address, or POI.
            Examples: "APM Mall, Kwun Tong", "Cheung Chau", "Hoi Ha".
        limit : int, optional
            Maximum number of curated itineraries to return. Default is 3 (capped at 5).
        max_transfers : int, optional
            Maximum number of ride changes allowed. Default is 6. Rural trips may
            require higher values.
        preferences : dict, optional
            Advanced knobs for routing. (e.g., avoiding certain modes, though the
            A* algorithm automatically balances mode selection).
        lang : {"en", "tc", "sc"}, optional
            Response language for labels and stop names. Default is "en".

        Returns
        -------
        dict
            A structured dictionary containing:
            - meta: Tool metadata.
            - origin / destination: Resolved labels.
            - itineraries: A ranked list of trip options. Each itinerary includes a
              summary (score, time, distance, transfers) and a sequence of legs
              (walk, bus, rail, ferry) with live ETAs fetched for the first departure.

        Examples
        --------
        1) Typical urban multimodal trip:
            {
                "origin_place": "Causeway Bay",
                "destination_place": "Kwun Tong",
                "limit": 3,
                "lang": "en"
            }

        2) Rural or island trip requiring transfers and ferries:
            {
                "origin_place": "Mong Kok",
                "destination_place": "Cheung Chau",
                "max_transfers": 4,
                "lang": "tc"
            }
        """

        await self.transit.ensure_loaded()
        result = await self.planner.plan(origin_place, destination_place, limit, max_transfers, preferences, lang, __event_emitter__)
        result["meta"] = self.meta(source="td")
        return result
