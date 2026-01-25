# EVE Sentinel

**Alliance Intel & Recruitment Analysis Tool for EVE Online**

Analyze ESI data from alliance auth systems to produce risk assessments for recruitment. Identifies playstyle, detects alts, and flags potential security risks.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://hub.docker.com)
[![PWA](https://img.shields.io/badge/PWA-Installable-purple.svg)](https://web.dev/progressive-web-apps/)

## Platforms

| Platform | Status | Download |
|----------|--------|----------|
| Web (PWA) | Available | [Install from browser](#pwa-installation) |
| Docker | Available | [Docker Hub](#docker-deployment) |
| macOS (Apple Silicon) | Available | [Releases](../../releases) |
| macOS (Intel) | Available | [Releases](../../releases) |
| Windows | Available | [Releases](../../releases) |
| Linux | Available | [Releases](../../releases) |
| iOS | Coming Soon | App Store |
| Android | Coming Soon | Google Play |

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

## Multi-Platform Deployment

### PWA Installation

EVE Sentinel is a Progressive Web App (PWA) that can be installed directly from your browser:

1. Open EVE Sentinel in Chrome, Edge, or Safari
2. Look for the "Install" button in the address bar (or menu)
3. Click "Install" to add it to your home screen/applications

The PWA works offline for cached data and syncs when online.

### Docker Deployment

```bash
# Quick start with Docker
docker run -d \
  --name eve-sentinel \
  -p 8000:8000 \
  -v sentinel-data:/app/data \
  -e ESI_CLIENT_ID=your_client_id \
  -e ESI_SECRET_KEY=your_secret_key \
  ghcr.io/aretedriver/eve_sentinel:latest

# Or using Docker Compose
docker compose up -d
```

### Cloud Deployment

**Railway** (recommended for beginners):
```bash
# One-click deploy
railway init
railway up
```

**Fly.io**:
```bash
fly launch --no-deploy
fly secrets set ESI_CLIENT_ID=xxx ESI_SECRET_KEY=xxx
fly deploy
```

**Render**: Connect your GitHub repo and deploy automatically.

**Heroku/Dokku**: Uses the included `Procfile`.

### Desktop Applications

Native desktop apps are available for Windows, macOS, and Linux:

1. Go to [Releases](../../releases)
2. Download the installer for your platform:
   - **macOS**: `.dmg` (Intel or Apple Silicon)
   - **Windows**: `.msi` or `.exe`
   - **Linux**: `.AppImage` or `.deb`

#### Building Desktop Apps Locally

Requires [Rust](https://rustup.rs/) and [Tauri CLI](https://tauri.app/):

```bash
# Install Tauri CLI
cargo install tauri-cli

# Build for your current platform
cd src-tauri
cargo tauri build

# Build for specific target
cargo tauri build --target aarch64-apple-darwin  # macOS ARM
cargo tauri build --target x86_64-pc-windows-msvc  # Windows
```

### Mobile Applications

#### iOS (App Store)

To build for iOS (requires macOS and Xcode):

```bash
cd src-tauri
cargo tauri ios init
cargo tauri ios build
```

Then open the generated Xcode project to sign and submit to App Store.

#### Android (Google Play)

To build for Android (requires Android Studio and NDK):

```bash
cd src-tauri
cargo tauri android init
cargo tauri android build --apk
```

The APK will be generated in `src-tauri/gen/android/app/build/outputs/`.

### Mac App Store Submission Checklist

1. Set up Apple Developer account ($99/year)
2. Configure signing identity in `src-tauri/tauri.conf.json`
3. Generate app icons (use `tauri icon` command)
4. Build with `cargo tauri build --target aarch64-apple-darwin`
5. Submit via Xcode or Transporter

### Google Play Store Submission Checklist

1. Set up Google Play Developer account ($25 one-time)
2. Configure signing keystore
3. Build release AAB: `cargo tauri android build --aab`
4. Upload to Play Console

## Roadmap

- [x] Core analysis framework
- [x] ESI integration
- [x] zKillboard analysis
- [x] Web dashboard
- [x] PWA support
- [x] Docker containerization
- [x] Desktop apps (Tauri)
- [x] Discord webhook notifications
- [ ] iOS App Store release
- [ ] Android Play Store release
- [ ] Alliance Auth bridge
- [ ] SeAT integration
- [ ] Discord bot integration
- [ ] PDF report generation
- [ ] Machine learning risk scoring

## License

MIT License - see [LICENSE](LICENSE)

## Disclaimer

This tool is designed for legitimate alliance security purposes. Always respect EVE Online's EULA and ESI terms of service. Do not use for harassment or malicious purposes.

---

**Built for EVE Online alliance security** | [Report Issues](https://github.com/AreteDriver/EVE_Sentinel/issues)
