# DPO Tools Specification

## Purpose

Two public `dpo_*` tools over the Address Lookup Service (ALS): free-text address lookup and 19-character GeoAddress lookup, both returning LLM-friendly bilingual suggestions.

## Requirements

### Requirement: Address lookup
`dpo_address_lookup` SHALL query ALS with `q` plus plumbing for `n` (≤200), `t` tolerance (0–80), `b` basic mode, 3D mode with floor/unit filters, and `lang` (`en`/`tc`), always requesting bilingual responses via `Accept-Language: *`.

#### Scenario: Parameters forwarded
- **WHEN** called with `limit=7, tolerance=40, basic_mode=True`
- **THEN** ALS receives `n=7, t=40, b=1`

### Requirement: GeoAddress validation
`dpo_geoaddress_lookup` SHALL reject inputs whose length differs from exactly 19 characters with `invalid_geoaddress` before any request.

#### Scenario: Short input
- **WHEN** a 10-character geoaddress is supplied
- **THEN** the validation error is returned and ALS is not called

### Requirement: Bilingual suggestion schema
Each suggestion SHALL carry a formatted address (English order `Building, No Street, District, Region`; Chinese order `Region+District+Street+ No號+Building`), a structured bilingual breakdown, the GeoAddress, HK1980 and WGS84 coordinates as floats, the match score, and validation info (type/status).

#### Scenario: Chinese ordering
- **WHEN** `lang="tc"` and the premises has region/district/street/building
- **THEN** the formatted address places region first and appends the building name last

### Requirement: ALS error mapping
Address lookup SHALL map HTTP 400/413/429/406 to `bad_request`/`payload_too_large`/`rate_limited`/`not_acceptable`; geoaddress lookup maps 400/429. Transport-level failures map to `http_error`. The `dpo_*` tools surface these errors flat with a `meta` attached.

#### Scenario: Payload too large
- **WHEN** ALS responds 413 to an over-long query
- **THEN** the tool returns `{"error": "payload_too_large", ..., "meta"}`
