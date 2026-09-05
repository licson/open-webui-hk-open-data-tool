# LandsD Tools Specification

## Purpose

Two public `landsd_*` tools plus the coordinate transforms that back them: place search with HK1980→WGS84 conversion, and nearby-place search around a WGS84 point.

## Requirements

### Requirement: Location search
`landsd_location_search` SHALL query the map.gov.hk location search API, cap `limit` at 25, return bilingual name/address/district with `hk1980` coordinates, and attach `wgs84` coordinates by transforming each result's grid coordinates (30-day mem cache). Failed transforms yield `wgs84: null`.

#### Scenario: Bilingual result with transform
- **WHEN** a result has `x`/`y` grid coordinates and the transform succeeds
- **THEN** the item carries both `hk1980` and `wgs84` dictionaries

### Requirement: Nearby search
`landsd_search_nearby` SHALL transform the input WGS84 point to HK1980 (returning `{"meta", "error": "Coordinate transformation failed", "query", "items": []}` when the transform fails), query the nearby API, and strip HTML from `additional_info` values.

#### Scenario: Transform failure
- **WHEN** the forward transform returns no coordinates
- **THEN** the tool returns the transformation-failed error shape

#### Scenario: HTML stripping
- **WHEN** a nearby result has `additionalInfoValue` containing markup
- **THEN** the returned `additional_info` values have tags removed

### Requirement: Coordinate transforms
`transform_hk1980_to_wgs84` and `transform_wgs84_to_hk1980` SHALL call the geodetic.gov.hk transform service, accept its varied response key spellings (`wgsLat`/`wgslat`/`lat`/`latitude` etc.), and return `None` on error or missing coordinates.

#### Scenario: Alternate key spellings accepted
- **WHEN** the transform response uses `wgsLong` instead of `wgsLon`
- **THEN** the longitude is still parsed
