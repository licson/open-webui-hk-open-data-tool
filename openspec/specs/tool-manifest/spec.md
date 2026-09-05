# Tool Manifest Specification

## Purpose

The `Tools` class is the single surface Open WebUI exposes. This spec pins the naming/exposure conventions, the Valves configuration model, the `meta()` contract, and the version-sync rule.

## Requirements

### Requirement: Public tool surface
Only methods prefixed `hko_`, `landsd_`, `epd_`, `ha_`, `dpo_`, or `td_` SHALL be public tools (currently 30); internal helpers SHALL start with `_`. Every public tool SHALL carry a conversation-style docstring documenting parameters, allowed enums, and an LLM-natural example call.

#### Scenario: Prefix enforcement by convention
- **WHEN** a new tool is added with one of the six prefixes
- **THEN** it is counted by the public-surface regression test

### Requirement: No raw data dumps
Tools SHALL curate and filter responses for LLM consumption rather than forwarding raw datasets; pagination SHALL be enforced (cursors and hard caps) on list-producing tools.

#### Scenario: Bounded results
- **WHEN** a list tool is asked for an oversized limit
- **THEN** the effective limit is clamped to its documented cap

### Requirement: Valves configuration
`Valves` SHALL be a pydantic v2 model carrying cache (dir, general TTL, ETA TTL), HTTP (timeout, retries, concurrency), hkbus source overrides, and planner knobs (`plan_*`, including `plan_max_transfers_cap` and `plan_default_max_transfers`). `Tools.Valves` SHALL subclass it without changes so Open WebUI surfaces the knobs.

#### Scenario: Overrides honored
- **WHEN** `hkbus_primary_base`/`hkbus_fallback_base` are redirected
- **THEN** DB downloads use the redirected sources

### Requirement: meta contract
`meta()` SHALL return `{"tool": "Hong Kong Open Data", "version", "ts"}`; with `source="td"` it SHALL add the transit data source descriptor and DB state (cached_db, db_source, db_md5).

#### Scenario: td meta extras
- **WHEN** `meta(source="td")` after a DB load
- **THEN** the response includes `data_source` and DB cache fields

### Requirement: Version sync
The version string SHALL agree across the module header manifest, the HTTPClient User-Agent, and `Tools.meta()`; all three SHALL be bumped together.

#### Scenario: Single-spot bump caught
- **WHEN** only one of the three version occurrences changes
- **THEN** the version-sync regression test fails
