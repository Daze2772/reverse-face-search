# Reverse Face Search Tool

Cross-platform digital footprint correlation via reverse image search. Upload a facial image → reverse search across Google, Yandex, and Bing → extract usernames from social profiles → correlate across 300+ platforms via Maigret → structured dossier + live dashboard.

## Architecture

```
image upload → [Google Lens | Yandex Images | Bing Visual Search] → URL clustering → username extraction → Maigret → dossier
```

**Pipeline stages:**
1. **Image Ingestion** — FastAPI upload endpoint, validates JPEG/PNG/WebP, generates search ID
2. **Multi-engine Reverse Search** — Playwright + stealth browser pool, parallel search across 3 engines
3. **Result Clustering** — Domain-based URL grouping (social media, news, forums, blogs, etc.)
4. **Username Extraction** — Platform-specific regex patterns for Instagram, LinkedIn, Twitter/X, Facebook, TikTok, Reddit, GitHub, and more
5. **Cross-Platform Correlation** — Maigret integration across 300+ sites
6. **Dossier Aggregation** — Structured JSON export with all pipeline data
7. **Live Dashboard** — WebSocket-powered progress, result panels, export

## Install

```bash
# Prerequisites: Python 3.11+

# Clone / navigate to project
cd reverse-face-search

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium

# (Optional) Install Maigret if not already in venv
pip install maigret
```

## Configure

Edit `config.yaml`:

```yaml
captcha:
  api_key: "your-2captcha-key"    # Required for CAPTCHA solving

proxy:
  enabled: false                   # Set true if using proxies
  residential_url: ""              # Proxy URL if enabled

engines:
  yandex:
    enabled: true
  google:
    enabled: true
  bing:
    enabled: true
```

All settings documented in `config.yaml` comments.

## Launch

```bash
# Quick launch
./launch.sh

# Or manually
source venv/bin/activate
python -m src.main
```

Dashboard opens at **http://127.0.0.1:8000**

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/upload` | Upload image (multipart/form-data) |
| POST | `/api/search/{search_id}` | Start reverse search pipeline |
| GET | `/api/status/{search_id}` | Get live search status |
| GET | `/api/dossier/{search_id}` | Retrieve completed dossier (JSON) |
| GET | `/api/config` | Get sanitized config |
| WS | `/ws/{search_id}` | WebSocket for live progress |
| GET | `/` | Dashboard HTML |

## Testing

```bash
# Run the automated test suite (requires live internet)
source venv/bin/activate
python tests/test_pipeline.py
```

Tests download a public figure portrait from Wikipedia and run the full pipeline against live search engines.

## Project Structure

```
reverse-face-search/
├── config.yaml              # All configuration
├── requirements.txt         # Python dependencies
├── launch.sh                # Quick launch script
├── src/
│   ├── main.py              # Entry point
│   ├── config.py            # Config loader
│   ├── search_manager.py    # Pipeline orchestrator
│   ├── api/
│   │   └── routes.py        # FastAPI routes + WebSocket
│   ├── engines/
│   │   ├── base.py          # Base engine (Playwright + stealth)
│   │   ├── yandex.py        # Yandex Images handler
│   │   ├── google.py        # Google Lens handler
│   │   └── bing.py          # Bing Visual Search handler
│   ├── cluster/
│   │   └── parser.py        # Domain clustering
│   ├── extract/
│   │   └── usernames.py     # Username extraction
│   ├── correlate/
│   │   └── maigret.py       # Maigret integration
│   ├── dossier/
│   │   └── builder.py       # Dossier assembly
│   └── dashboard/
│       └── (reserved)
├── templates/
│   └── dashboard.html       # Web dashboard
├── static/
│   ├── css/style.css
│   └── js/dashboard.js
├── tests/
│   └── test_pipeline.py     # Automated E2E tests
├── uploads/                 # Temp image storage (auto-purge)
├── dossiers/                # JSON dossier exports
└── logs/                    # Structured logs
```

## License

Private tool. Built for research and digital footprint analysis.
