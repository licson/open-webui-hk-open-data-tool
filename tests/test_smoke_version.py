"""Smoke + version-sync tests: module loads, Tools constructs, versions agree."""

from __future__ import annotations

import re
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "hk-open-data-tool.py"


def module_source() -> str:
    return MODULE_PATH.read_text(encoding="utf-8")


class TestSmoke:
    def test_module_imports(self, mod):
        assert hasattr(mod, "Tools")
        assert hasattr(mod, "HTTPClient")
        assert hasattr(mod, "TransitDB")
        assert hasattr(mod, "TripPlanner")

    def test_tools_constructs(self, mod, tmp_path):
        t = mod.Tools()
        t.valves.cache_dir = str(tmp_path)
        for attr in ("valves", "http", "hko", "landsd", "epd", "transit", "planner", "ha", "als"):
            assert hasattr(t, attr), attr

    def test_public_tool_surface(self, mod):
        prefixes = ("hko_", "landsd_", "epd_", "ha_", "dpo_", "td_")
        public = [n for n in dir(mod.Tools) if n.startswith(prefixes)]
        assert len(public) == 30, f"expected 30 public tools, found {len(public)}"

    def test_meta_shape(self, mod, tmp_cache):
        t = mod.Tools()
        t.valves.cache_dir = str(tmp_cache)
        m = t.meta()
        assert m["tool"] == "Hong Kong Open Data"
        assert isinstance(m["version"], str)
        assert isinstance(m["ts"], int)
        assert "data_source" not in m
        m_td = t.meta(source="td")
        assert m_td["data_source"] == "hkbus DB + Transport Department APIs"
        assert "cached_db" in m_td and "db_source" in m_td


class TestVersionSync:
    def test_versions_agree(self, mod, tmp_cache):
        src = module_source()
        manifest = re.search(r"^version:\s*(\S+)$", src, re.MULTILINE).group(1)
        ua = re.search(r"HongKongOpenDataTool/([\d.]+)", src).group(1)
        t = mod.Tools()
        t.valves.cache_dir = str(tmp_cache)
        meta_version = t.meta()["version"]
        assert manifest == ua == meta_version, (
            f"version drift: manifest={manifest} user-agent={ua} meta={meta_version}; "
            "bump all three together (header manifest, HTTPClient User-Agent, Tools.meta)"
        )
