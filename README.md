# EVE Sentinel

**Alliance Intel & Recruitment Analysis Tool for EVE Online**

Analyze ESI data from alliance auth systems to produce risk assessments for recruitment. Identifies playstyle, detects alts, and flags potential security risks.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)

## Features

### Recruitment Analysis
- **Risk Scoring**: Green/Yellow/Red flag system for applicants
- **Corp History Analysis**: Detect spy corps, rapid corp hopping, suspicious patterns
- **Alt Detection**: Identify likely alts through activity patterns and correlations
- **Playstyle Profiling**: Classify pilots (PvPer, industrialist, capital pilot, etc.)

### Data Integration
- **Alliance Auth Bridge**: Connect to SeAT, Alliance Auth, or custom auth systems
- **ESI Direct Access**: Authenticated ESI queries for detailed character data
- **zKillboard Analysis**: PvP history, AWOX detection, activity patterns
- **Wallet Analysis**: ISK flow patterns, RMT detection (requires auth data)

### Reporting
- **Detailed Reports**: Comprehensive applicant analysis with confidence scores
- **Webhook Notifications**: Discord/Slack alerts for high-risk applicants
- **Batch Processing**: Analyze multiple applicants efficiently
- **Historical Tracking**: Track applicants over time

## Quick Start

### Installation

```bash
git clone https://github.com/AreteDriver/EVE_Sentinel.git
cd EVE_Sentinel

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .
```

### Configuration

```bash
cp .env.example .env
# Edit .env with your ESI credentials and auth bridge settings
```

### Run the Server

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: http://localhost:8000/docs

## API Endpoints

### Analysis
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/analyze/{character_id}` | POST | Full recruitment analysis |
| `/api/v1/analyze/batch` | POST | Analyze multiple characters |
| `/api/v1/quick-check/{character_id}` | GET | Fast risk assessment |

### Reports
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/reports` | GET | List all reports |
| `/api/v1/reports/{report_id}` | GET | Get specific report |
| `/api/v1/reports/{report_id}/pdf` | GET | Download PDF report |

### Webhooks
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/webhooks` | POST | Configure notifications |
| `/api/v1/webhooks/test` | POST | Test webhook delivery |

## Risk Flags

### Red Flags (High Risk)
| Flag | Description |
|------|-------------|
| `KNOWN_SPY_CORP` | Member of known spy/hostile corporation |
| `AWOX_HISTORY` | History of killing corp/alliance mates |
| `RAPID_CORP_HOP` | 5+ corps in 6 months |
| `RMT_PATTERN` | Suspicious ISK transfer patterns |
| `HIDDEN_ALTS` | Undisclosed alts detected |
| `ENEMY_STANDINGS` | Negative standings with your alliance |

### Yellow Flags (Caution)
| Flag | Description |
|------|-------------|
| `LOW_ACTIVITY` | <20 kills in 90 days |
| `SHORT_TENURE` | <30 days in current corp |
| `NO_ASSETS` | No significant assets declared |
| `TIMEZONE_MISMATCH` | Activity outside corp's primary TZ |
| `CYNO_ALT_PATTERN` | Likely cyno/scout alt |
| `NEW_CHARACTER` | Character <6 months old |

### Green Flags (Positive)
| Flag | Description |
|------|-------------|
| `ACTIVE_PVPER` | Regular PvP activity |
| `ESTABLISHED` | 2+ years, stable corp history |
| `CAPITAL_PILOT` | Owns/flies capitals |
| `VOUCHED` | Known by existing members |
| `CLEAN_HISTORY` | No negative indicators |

## Project Structure

```
EVE_Sentinel/
├── backend/
│   ├── analyzers/          # Analysis modules
│   │   ├── killboard.py    # zKillboard analysis
│   │   ├── corp_history.py # Corp history analysis
│   │   ├── activity.py     # Activity patterns
│   │   ├── assets.py       # Asset analysis
│   │   ├── wallet.py       # Wallet/ISK analysis
│   │   ├── social.py       # Alt detection
│   │   └── risk_scorer.py  # Aggregate scoring
│   ├── connectors/         # External data sources
│   │   ├── esi.py          # ESI client
│   │   ├── zkill.py        # zKillboard API
│   │   └── auth_bridge.py  # Alliance Auth/SeAT
│   ├── models/             # Data models
│   │   ├── applicant.py    # Applicant profile
│   │   ├── report.py       # Analysis report
│   │   └── flags.py        # Risk flags
│   ├── api/                # FastAPI routes
│   │   ├── analyze.py
│   │   ├── reports.py
│   │   └── webhooks.py
│   └── main.py             # FastAPI app
├── frontend/               # Web dashboard (optional)
├── tests/
└── docs/
```

## Example Output

```json
{
  "character_id": 12345678,
  "character_name": "Suspicious Pilot",
  "analysis_date": "2024-01-15T10:30:00Z",
  "overall_risk": "YELLOW",
  "confidence": 0.82,
  "flags": [
    {
      "type": "RED",
      "category": "corp_history",
      "reason": "Member of 'Goonwaffe' (known hostile) for 3 months in 2022",
      "evidence": {"corp_id": 667531913, "start": "2022-03-01", "end": "2022-06-01"}
    },
    {
      "type": "YELLOW",
      "category": "activity",
      "reason": "Only 12 kills in past 90 days",
      "evidence": {"kills_90d": 12, "avg_alliance": 45}
    },
    {
      "type": "GREEN",
      "category": "assets",
      "reason": "Owns capitals, established in region",
      "evidence": {"capitals": ["Revelation", "Apostle"], "region": "Delve"}
    }
  ],
  "playstyle": {
    "primary": "Capital Pilot",
    "secondary": "Small Gang PvP",
    "ship_preferences": ["Dreadnought", "HAC", "Logi"],
    "timezone": "EU-TZ",
    "peak_hours": "18:00-23:00 EVE",
    "activity_level": "Moderate"
  },
  "alt_analysis": {
    "likely_main": false,
    "suspected_alts": [
      {"name": "Cyno Alt III", "confidence": 0.87, "reason": "Login correlation"}
    ],
    "declared_alts": ["Industry Alt"],
    "alt_count_estimate": 2
  },
  "recommendations": [
    "Request full API access for deeper analysis",
    "Verify reason for leaving Goonswarm",
    "Confirm capital ship locations"
  ]
}
```

## Configuration

### Environment Variables

```bash
# ESI Configuration
ESI_CLIENT_ID=your_client_id
ESI_SECRET_KEY=your_secret_key
ESI_CALLBACK_URL=http://localhost:8000/callback

# Alliance Auth Bridge (optional)
AUTH_BRIDGE_URL=https://auth.youalliance.com/api
AUTH_BRIDGE_TOKEN=your_token

# Database
DATABASE_URL=sqlite:///./sentinel.db

# Webhooks
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# Known Hostile Corps/Alliances (comma-separated IDs)
HOSTILE_CORPS=667531913,98000001
HOSTILE_ALLIANCES=1354830081,99000001
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy backend/

# Linting
ruff check .
```

## Roadmap

- [x] Core analysis framework
- [x] ESI integration
- [x] zKillboard analysis
- [ ] Alliance Auth bridge
- [ ] SeAT integration
- [ ] Web dashboard
- [ ] Discord bot integration
- [ ] PDF report generation
- [ ] Machine learning risk scoring

## License

MIT License - see [LICENSE](LICENSE)

## Disclaimer

This tool is designed for legitimate alliance security purposes. Always respect EVE Online's EULA and ESI terms of service. Do not use for harassment or malicious purposes.

---

**Built for EVE Online alliance security** | [Report Issues](https://github.com/AreteDriver/EVE_Sentinel/issues)
