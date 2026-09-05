# EPD Tools Specification

## Purpose

Two public `epd_*` tools exposing the Air Quality Health Index: current readings (city summary + individual stations) and health-risk forecasts.

## Requirements

### Requirement: Current AQHI combines dashboard and stations
`epd_aqhi_current` SHALL merge the city dashboard (general/roadside summaries with `aqhi_range` formatting like `"3-4"`) and individual station readings, translate health risks to bilingual form (unknown risks echo verbatim), embed the AQHI scale explanation, and sort stations by AQHI descending.

#### Scenario: Range formatting
- **WHEN** a dashboard row has `aqhi_min=3` and `aqhi_max=4`
- **THEN** `city_summary[type]["aqhi_range"]` is `"3-4"`

#### Scenario: Highest-risk station first
- **WHEN** stations report AQHI 7, 5, 4, 2
- **THEN** they are returned in descending AQHI order

### Requirement: Station fuzzy filter
`station` SHALL be fuzzy-matched through bilingual aliases (English and Chinese) to a canonical station key; unmatched stations are filtered out.

#### Scenario: Chinese alias
- **WHEN** `station="沙田"`
- **THEN** only the Sha Tin station is returned

### Requirement: Roadside inference
For `type_filter`, individual stations SHALL be classified as roadside only for the hardcoded set `{causewaybay, central, mongkok}`; all others are general.

#### Scenario: Roadside filter
- **WHEN** `type_filter="roadside"`
- **THEN** only the three roadside stations appear

### Requirement: AQHI forecast
`epd_aqhi_forecast` SHALL group forecasts by type (`general`/`roadside`), honor `type_filter`, translate risk ranges bilingually, and sort each group A.M.-before-P.M.

#### Scenario: A.M. first
- **WHEN** a P.M. row precedes an A.M. row in the payload
- **THEN** the A.M. entry is sorted first
