# Live Smoke Specification

## Purpose

Opt-in, real-network smoke tests (marked `live`, deselected by default) that sanity-check each client family end-to-end while tolerating real-world data variance and skipping gracefully without network access.

## Requirements

### Requirement: Opt-in live network smoke tests
The suite SHALL provide one real-network smoke test per client family — `hko_weather_forecast`, `landsd_location_search`, `epd_aqhi_current`, `ha_aed_waiting_time`, `dpo_address_lookup`, and `td_catalog_status`/`td_stop_search` (plus a short `td_plan_trip`) — all marked `pytest.mark.live` and deselected by default via pytest configuration (`-m "not live"`). Live tests SHALL assert only structural validity (no `error` key / expected top-level keys), tolerating real-world data variance, and SHALL skip (not fail) when the network is unavailable.

#### Scenario: Live run selects only smoke tests
- **WHEN** `python3 -m pytest -m live` is run with network access
- **THEN** only the live-marked tests run and each returns a structurally valid response

#### Scenario: Offline default run skips live tests
- **WHEN** `python3 -m pytest` is run
- **THEN** the live smoke tests are deselected and the offline suite is unaffected
