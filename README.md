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
- **Search nearby places** from WGS84 coordinates (finds features within 1km radius, sorted by distance)

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

## Credits

This tool aggregates data from official Hong Kong government open data sources:

- **[Hong Kong Observatory](https://www.hkgov.hk)** - Weather, climate, and astronomical data
- **[Lands Department](https://www.landsd.gov.hk)** - Geospatial and location services
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
