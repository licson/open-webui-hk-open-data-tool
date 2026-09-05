# HA Tools Specification

## Purpose

One public `ha_*` tool exposing Hospital Authority Accident & Emergency waiting times across hospitals, with hospital and triage filtering.

## Requirements

### Requirement: Language-specific endpoints
`ha_aed_waiting_time` SHALL fetch the `aedwtdata2-{en,tc,sc}.json` endpoint matching `lang` and surface `updateTime`.

#### Scenario: Traditional Chinese
- **WHEN** `lang="tc"`
- **THEN** the `aedwtdata2-tc.json` endpoint is called

### Requirement: Hospital alias filter
`hospital` SHALL be fuzzy-matched through bilingual aliases and abbreviations (e.g. `qeh`, `pym`, `uch`) to canonical hospital names; unmatched hospitals are filtered out.

#### Scenario: Abbreviation
- **WHEN** `hospital="qeh"`
- **THEN** only Queen Elizabeth Hospital is returned

### Requirement: Triage category mapping
`triage_category` (`t1`–`t5`, default `all`) SHALL control the returned fields: t1/t2 expose `waiting_time` plus `managing_cases`; t3 exposes `median_wait`/`percentile_95` from `t3p50`/`t3p95`; t4 and t5 share the combined `t45p50`/`t45p95` fields.

#### Scenario: T3-only view
- **WHEN** `triage_category="t3"`
- **THEN** each hospital carries only the `t3` waiting-time block

### Requirement: Urgency ordering
When t3 data is present, hospitals SHALL be sorted by T3 median wait descending, parsing hour-based strings (e.g. `"2.5 hours"` → 150 minutes).

#### Scenario: Hour strings parsed for sorting
- **WHEN** one hospital reports `"2.5 hours"` and another `"33 minutes"` for T3 median
- **THEN** the 150-minute hospital is listed first

### Requirement: Triage guide
The response meta SHALL embed the bilingual triage category guide.

#### Scenario: Guide present
- **WHEN** the tool returns successfully
- **THEN** `meta.triage_guide` covers categories t1 through t5
