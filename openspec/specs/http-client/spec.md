# HTTP Client Specification

## Purpose

A shared async HTTP layer (`HTTPClient`) used by every department client. Provides opt-in caching, bounded retries, and a never-raises error contract so tool methods can stay simple.

## Requirements

### Requirement: Requests support GET and POST with json or text expectations
`HTTPClient.request` SHALL forward query params and optional JSON bodies for GET/POST, and SHALL parse the response as JSON or plain text per the `expect` argument.

#### Scenario: POST with JSON body
- **WHEN** a request is made with `method="POST"` and a `json_body`
- **THEN** the body is sent as JSON and the response is parsed per `expect`

### Requirement: Caching is opt-in per request
Caching SHALL be disabled unless `cache_scope` is set to `"mem"` or `"disk"`; `get_json`/`get_text` SHALL always bypass cache. The cache key SHALL include method, URL, sorted params, and a canonicalized body. Mem entries expire by TTL against the stored timestamp; disk entries are `<sha256>.json` files whose freshness is the file mtime. Disk write failures SHALL be swallowed.

#### Scenario: Mem cache hit within TTL
- **WHEN** the same URL+params is requested twice within the TTL with `cache_scope="mem"`
- **THEN** only one HTTP call is made and both calls return identical data

#### Scenario: Disk cache survives client restarts
- **WHEN** a new HTTPClient instance uses the same `cache_dir` and the cached file is newer than the TTL
- **THEN** the value is served from disk without an HTTP call

### Requirement: Retries and the error contract
`request` SHALL retry up to `valves.http_retries` times on 429, 5xx, and transport errors, and SHALL return `{"error": "request_failed", "detail", "url", "params", "method"}` after exhaustion instead of raising.

#### Scenario: Exhausted retries return an error dict
- **WHEN** the endpoint returns 5xx on every attempt
- **THEN** the caller receives the error dict and no exception propagates

### Requirement: ETA fetches use short cache TTLs
Real-time ETA requests SHALL be cached with `valves.eta_cache_ttl_s` (default 20 s), never the general 24 h TTL; Sunferry/Fortune Ferry/HKKF trip fetches use a hardcoded 30 s TTL.

#### Scenario: Stale ETAs are not served
- **WHEN** an ETA cached 20+ seconds ago is requested again
- **THEN** a fresh HTTP call is made

### Requirement: Versioned User-Agent
The shared client SHALL identify itself as `HongKongOpenDataTool/<version>`, where the version matches the module manifest and `Tools.meta()`.

#### Scenario: Version bump keeps User-Agent in sync
- **WHEN** the module version is changed in the manifest only
- **THEN** the version-sync regression test fails until the User-Agent matches
