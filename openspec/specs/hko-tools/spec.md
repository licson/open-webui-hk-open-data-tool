# HKO Tools Specification

## Purpose

Fifteen public `hko_*` tools exposing Hong Kong Observatory open data: current weather, forecasts, warnings, earthquakes, tides, sunrise/sunset, moonrise/moonset, lightning, visibility, daily climate series, weather-radiation reports, lunar dates, and hourly rainfall — with strict client-side validation before any request.

## Requirements

### Requirement: Weather forecast datasets
`hko_weather_forecast` SHALL fetch `weather.php` for `data_type` in `flw`, `fnd`, `rhrread`, `warnsum`, `warningInfo`, `swt` (with `"rhr"` accepted as an alias for `"rhrread"`), honoring `lang` (`en`/`tc`/`sc`), and SHALL pass request-failure dicts through under `data`.

#### Scenario: Alias resolution
- **WHEN** called with `data_type="rhr"`
- **THEN** the API receives `dataType=rhrread`

### Requirement: Earthquake datasets
`hko_earthquake` SHALL fetch `earthquake.php` for `qem` and `feltearthquake` with lang support.

#### Scenario: Quick earth movement
- **WHEN** called with `data_type="qem"`
- **THEN** the response meta/data shape matches the weather tools' contract

### Requirement: hko_opendata validates scalars and hierarchy
`hko_opendata` SHALL reject, with `{"error": "bad_request", "detail"}` and no HTTP call: non-integer or out-of-range `year` (1800–2100), `month` (1–12), `day` (1–31), `hour` (1–24); `month` without `year`; `day` without `year`+`month`; `hour` without full date.

#### Scenario: Hour without a full date
- **WHEN** called with `hour=12` but no year/month/day
- **THEN** a `bad_request` error names the missing hierarchy

### Requirement: Per-dataset parameter rules
`hko_opendata` SHALL enforce dataset-specific rules: HHOT/HLT require a whitelisted tide station and `year` and reject `date`; SRS/MRS require `year` and reject station/hour/date; LHL/LTMV reject all filters; CLMTEMP/CLMMAXT/CLMMINT require a whitelisted climate station and reject day/hour/date; RYES requires a whitelisted RYES station, rejects year/month/day/hour, and requires `date`. Station codes SHALL be matched case-insensitively.

#### Scenario: Invalid tide station
- **WHEN** `hko_opendata` is called with `station="XXX"` for HLT
- **THEN** the error lists the allowed station codes

### Requirement: RYES date normalization
For RYES, `date` SHALL accept `"yesterday"`/`"latest"`/`"today"`, `YYYY-MM-DD`, and `YYYYMMDD`; the relative forms resolve against the 01:30 HKT publication cutoff (before it, the latest bulletin is two days back); dates before 20190910 or later than the latest available bulletin SHALL be rejected.

#### Scenario: Before the 01:30 cutoff
- **WHEN** the HK time is 01:00 and `date="yesterday"`
- **THEN** the requested date is two calendar days back

### Requirement: Response shape
Successful `hko_opendata` calls SHALL return `{"meta", "format": "csv"|"json", "data", "params"}` where `params` mirrors exactly what was sent to the API; wrapper tools SHALL default to `rformat="json"`.

#### Scenario: CSV passthrough
- **WHEN** `rformat="csv"` and the API returns CSV text
- **THEN** the tool returns the raw text under `data` with `format="csv"`

### Requirement: Wrapper delegation
`hko_tide_hourly_heights`/`hko_tide_high_low`/`hko_sunrise_sunset`/`hko_moonrise_moonset`/`hko_lightning_count`/`hko_visibility_10min_mean`/`hko_climate_daily_{mean,max,min}_temperature`/`hko_weather_radiation_report` SHALL delegate to `hko_opendata` with their fixed dataset codes (HHOT, HLT, SRS, MRS, LHL, LTMV, CLMTEMP, CLMMAXT, CLMMINT, RYES) and the caller's parameters.

#### Scenario: Tide high/low maps to HLT
- **WHEN** `hko_tide_high_low(station="CCH", year=2025)` is called
- **THEN** the API receives `dataType=HLT` with the station and year

### Requirement: Lunar date and hourly rainfall
`hko_lunardate` SHALL validate a `YYYY-MM-DD` string (rejecting other formats before any request) and return the API's lunar-date payload; `hko_hourly_rainfall` SHALL forward `lang`.

#### Scenario: Bad lunar date format
- **WHEN** `hko_lunardate("05/09/2026")` is called
- **THEN** a `bad_request` error is returned without an HTTP call
