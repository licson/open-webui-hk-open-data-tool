# Hong Kong Open Data Tool

An [Open WebUI](https://github.com/open-webui/open-webui) tool providing LLM-safe access to Hong Kong open data sources.

## Features

### Hong Kong Observatory (HKO)
- Real-time weather reports and forecasts
- 9-day weather forecast
- Weather warnings and special weather tips
- Earthquake information
- Tide predictions (hourly heights, high/low tides)
- Climate data (daily temperatures)
- Sunrise/sunset and moonrise/moonset times
- Lunar calendar conversion
- Lightning and visibility reports

### Lands Department (LandsD)
- Location search (place names, addresses, landmarks)
- Coordinate transformation (HK1980 grid to WGS84)
- Search nearby places from WGS84 coordinates (finds features within 1km radius, sorted by distance)

### Environment Protection Department (EPD)
- Air Quality Health Index (AQHI) current readings:
  - City-wide summary (general and roadside)
  - Individual monitoring stations (18 stations across Hong Kong)
  - Bilingual station names (English/Chinese)
  - Health risk level translations
  - Station-specific filtering support
- AQHI forecast for today (AM/PM predictions)
- AQHI scale explanation (1-10+ with health advice)

### Hospital Authority (HA)
- A&E Waiting Time real-time queue statistics:
  - All 18 public hospital A&E departments
  - Triage category breakdown (T1-T5):
    - T1 (Critical): Life-threatening conditions
    - T2 (Emergency): Potential threat to life
    - T3 (Urgent): Stable but distressing conditions
    - T4 (Semi-urgent): Stable with less distress
    - T5 (Non-urgent): Stable with minimal discomfort
  - Median and 95th percentile wait times
  - Hospital name fuzzy matching (supports English/Chinese aliases)
  - Data sorted by urgency (longest waits first)
- Bilingual support (English/Traditional Chinese/Simplified Chinese)

### Digital Policy Office (DPO)
- Address Lookup Service (ALS):
  - Standardized Hong Kong address search with fuzzy matching
  - Returns structured address components (English/Chinese)
  - GeoAddress - 19-character standardized unique identifier for each address
  - Coordinates - Both HK1980 grid and WGS84 latitude/longitude
  - Address validation and similar spelling matching
  - 3D address support (floor/unit) for Housing Authority properties
- GeoAddress Lookup:
  - Retrieve address details from GeoAddress identifier
  - Cross-reference addresses between systems

### Transport / Transit (TD)
- Comprehensive transit database: buses, minibuses, MTR, Light Rail, ferries
- Real-time ETA for all major operators (KMB, CTB, GMB, MTR, LRT, ferries)
- Multi-criteria trip planner with:
  - Fastest, fewest transfers, and least walking options
  - Real-time departure integration
  - Support for complex multi-leg journeys across Hong Kong

## Requirements

- Python 3.10+
- httpx
- pydantic

## Installation

1. Download or clone this repository
2. Copy `hk-open-data-tool.py` to your Open WebUI tools directory
3. The tool will be automatically loaded and available for use

Or just copy and paste the whole source code to your Open WebUI tools menu.

## Usage

This tool is designed for natural conversation. Simply ask questions about Hong Kong weather, transit, or locations in your preferred language (English, Traditional Chinese, or Simplified Chinese).

**Example conversations:**

- "What's the weather like right now in Hong Kong?"
- "When's the next bus from Central to Causeway Bay?"
- "Plan a route from Tsim Sha Tsui to Mong Kok"
- "What time is sunset today?"
- "Find the coordinates for Victoria Peak"
- "What facilities are near Wong Shek Pier?"
- "Show me places near these coordinates: 22.37, 114.31"
- "What's the air quality like today?"
- "Is the air quality good in Causeway Bay?"
- "Show me the air quality forecast for today"
- "How long is the A&E wait at Queen Elizabeth Hospital?"
- "Which hospital has the shortest A&E waiting time?"
- "Show me A&E waiting times for urgent cases"
- "What's the standardized address for Central Government Office?"
- "Look up address: 漢口中心 in Tsim Sha Tsui"
- "Find address by GeoAddress: 3508215732T20110704"

## Development & Testing

The module is tested with an offline pytest suite (~350 tests) that mocks all
HTTP egress via `httpx.MockTransport` — no network needed.

```bash
# one-time setup (pytest/pytest-asyncio/httpx/pydantic are usually present already)
pip install --break-system-packages pytest pytest-asyncio freezegun

python3 -m py_compile hk-open-data-tool.py   # compile check
python3 -m pytest                            # offline suite (live tests deselected)
python3 -m pytest -m live                    # opt-in real-network smoke tests
```

Test conventions live in `tests/conftest.py` (importlib loader for the
hyphenated module, URL-pattern mock router, seeded transit fixtures); a
version-sync test enforces keeping the manifest/User-Agent/`meta()` versions
in agreement.

## Credits

This tool aggregates data from official Hong Kong government open data sources:

- **[Hong Kong Observatory](https://www.hko.gov.hk)** - Weather, climate, and astronomical data
- **[Lands Department](https://www.landsd.gov.hk)** - Geospatial and location services
- **[Environment Protection Department](https://www.epd.gov.hk)** - Air Quality Health Index (AQHI) data
- **[Hospital Authority](https://www.ha.org.hk)** - Accident and Emergency waiting time statistics
- **[Digital Policy Office](https://www.dpo.gov.hk)** - Address Lookup Service (ALS) for standardized Hong Kong addresses
- **[Transport Department](https://www.td.gov.hk)** - Public transport information

Transit database powered by **[HKBus (HK Bus Crawling)](https://github.com/hkbus/hk-bus-crawling)** © 2021 - Comprehensive Hong Kong bus route and stop data.

## Contributing

Contributions are welcome! When adding or modifying public tool methods:

1. **Conversation-First Design**: Design methods to match natural conversation patterns, not raw API calls. Users interact through chat, so method signatures and documentation should feel intuitive in a conversational context.

2. **Detailed Docstrings**: Every public method (those sit in the `Tool` class that expose calls to LLMs) must include:
   - Each method should be prefixed with the related government deparment's initials
   - Clear description of what the tool does
   - All parameters with explanations
   - Allowed values/enums where applicable
   - Practical examples in the docstring

3. **Examples Should Be Conversation-Ready**: Include example calls that an LLM would naturally make during a user interaction, not just raw parameter dumps.

4. **No Data Dumps**: Avoid exposing endpoints that return large unstructured datasets. Curate and filter data to be LLM-friendly.

## License

MIT License
