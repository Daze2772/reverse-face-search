# Reverse Face Search v2.1

Cross-platform digital footprint correlation via reverse image search. Upload a
facial image → reverse search across Google, Yandex, and Bing → cluster results
by domain → extract usernames → correlate across 300+ platforms via Maigret →
generate intelligence report + PDF.

```
image → file host → [Yandex | Google Lens | Bing] (shared browser)
                      ↓
                 URL clustering
                      ↓
      candidate name extraction ──── Wikipedia (cached)
                      ↓                    │
       active name-based social search     │
                      ↓                    ↓
       username extraction & scoring  OpenSanctions (cached)
                      ↓
              Maigret (--json simple)
                      ↓
            Intelligence report + PDF
```

## What's new in v2.1

* **imgbb integration** as the primary file host — fixes Google Lens reliability.
* **Browser pool** — three engines share one Chromium process per search instead of three.
* **SQLite persistence** — search state and dossiers survive a restart.
* **TTL disk cache** for Wikipedia & OpenSanctions (24h default).
* **Active name-based social search** via DuckDuckGo `site:` queries.
* **Optional face-embedding verification** with InsightFace (opt-in).
* **slowapi rate-limits**, CORS, structured `lifespan` startup.
* **Docker / docker-compose** for production deployment.
* All secrets moved to `.env`; **`config.yaml` is now behaviour-only**.
* Fixed: PDF `NameError`, Einstein fallback hack, Maigret JSON parsing,
  WebSocket silent-failure handler, and a handful of smaller bugs (see
  [`IMPROVEMENTS.md`](IMPROVEMENTS.md) for the full audit).

## Quick start (local)

```bash
# 1. Prerequisites: Python 3.11+
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m playwright install --with-deps chromium

# 2. Configure secrets
cp .env.example .env
# → set IMGBB_API_KEY, optionally TWOCAPTCHA_API_KEY, OPENSANCTIONS_API_KEY

# 3. Launch
./launch.sh
# Dashboard: http://127.0.0.1:8000
```

## Docker (production)

```bash
cp .env.example .env
# → fill in IMGBB_API_KEY etc.

docker compose up -d --build
# Dashboard: http://localhost:8000
# Healthcheck: docker compose ps
# Logs:       docker compose logs -f
```

Persistent volumes are declared in `docker-compose.yml`:

| Volume         | Purpose                            |
| -------------- | ---------------------------------- |
| `rfs_data`     | SQLite database (`rfs.sqlite`)     |
| `rfs_dossiers` | JSON + PDF dossiers                |
| `rfs_uploads`  | Temporary image uploads            |
| `rfs_logs`     | App logs                           |
| `rfs_cache`    | Wikipedia / OpenSanctions cache    |
| `rfs_reports`  | Maigret scratch space              |

## Configuration

| Env var                          | Description                                        | Default          |
| -------------------------------- | -------------------------------------------------- | ---------------- |
| `IMGBB_API_KEY`                  | Primary file host (highly recommended)             | —                |
| `TWOCAPTCHA_API_KEY`             | 2Captcha for CAPTCHA solving                       | —                |
| `OPENSANCTIONS_API_KEY`          | Enables PEP / sanctions check                      | —                |
| `RFS_FACE_EMBEDDING_ENABLED`     | InsightFace verification (heavy)                   | `false`          |
| `RFS_FACE_SIMILARITY_THRESHOLD`  | Cosine similarity cutoff                           | `0.55`           |
| `RFS_ENGINES`                    | Comma-separated: `yandex,google,bing`              | all three        |
| `RFS_UPLOAD_RATE`                | slowapi rule for `/api/upload`                     | `10/minute`      |
| `RFS_SEARCH_RATE`                | slowapi rule for `/api/search/{id}`                | `5/minute`       |
| `RFS_DB_PATH`                    | SQLite location                                    | `data/rfs.sqlite`|
| `RFS_CORS_ORIGINS`               | Comma-separated CORS origins                       | `*`              |

Full list: [`.env.example`](.env.example).

## Face-embedding verification (optional)

When enabled, every external result URL from the reverse search is passed
through **InsightFace `buffalo_l`** (CPU ONNX) to filter out matches that
look similar but aren't the same person. Cosine similarity is compared to
the reference face from the uploaded image.

To enable:

```bash
pip install insightface onnxruntime opencv-python-headless numpy
export RFS_FACE_EMBEDDING_ENABLED=true
```

Adds ~700 MB of model files and ~2–5 s per result image on CPU.

## API

| Method | Path                            | Description                                       |
| ------ | ------------------------------- | ------------------------------------------------- |
| GET    | `/`                             | Dashboard                                         |
| GET    | `/api/health`                   | Liveness probe                                    |
| GET    | `/api/config`                   | Sanitised config + feature flags                  |
| POST   | `/api/upload`                   | Upload image (rate-limited)                       |
| POST   | `/api/search/{search_id}`       | Start pipeline (rate-limited)                     |
| GET    | `/api/status/{search_id}`       | Live status                                       |
| GET    | `/api/dossier/{search_id}`      | JSON dossier                                      |
| GET    | `/api/report/{search_id}`       | Download PDF report                               |
| GET    | `/api/recent?limit=25`          | Recent searches                                   |
| WS     | `/ws/{search_id}`               | Live progress stream                              |

## Testing

```bash
# Fast unit tests (no network, no browser)
python tests/test_units.py

# Non-browser pipeline coverage (uploads, clustering, extraction, dossier)
python tests/test_quick.py

# Single-engine browser test (Yandex)
python tests/test_browser.py

# Full E2E — requires live internet
python tests/test_pipeline.py
```

## Project layout

```
reverse-face-search/
├── src/
│   ├── main.py                 # Entry point — uvicorn server
│   ├── config.py               # YAML + env loader → typed dataclasses
│   ├── store.py                # SQLite persistence (new)
│   ├── cache.py                # TTL disk cache (new)
│   ├── search_manager.py       # Pipeline orchestrator
│   ├── api/
│   │   ├── routes.py           # FastAPI endpoints + lifespan + rate limits
│   │   └── websocket_broadcast.py
│   ├── engines/
│   │   ├── base.py             # Playwright + stealth + shared extraction
│   │   ├── pool.py             # BrowserPool (one Chromium per search)  (new)
│   │   ├── filehost.py         # imgbb → tmpfiles → 0x0.st waterfall
│   │   ├── yandex.py / google.py / bing.py
│   ├── extract/
│   │   ├── usernames.py        # Regex + name-scoring
│   │   ├── names.py            # Candidate person-name extraction
│   │   └── name_search.py      # DuckDuckGo active social search       (new)
│   ├── cluster/parser.py
│   ├── correlate/maigret.py    # Now uses `--json simple`
│   ├── dossier/builder.py
│   ├── intel/                  # Wikipedia, OpenSanctions, affiliations, PDF
│   └── face/                   # InsightFace verification              (new, opt-in)
├── templates/dashboard.html
├── static/
├── tests/
│   ├── test_units.py           # New, fast, no-network suite
│   └── ...
├── config.yaml                 # Behaviour-only (no secrets)
├── .env.example                # Secrets template
├── Dockerfile                  # Multi-stage prod image
├── docker-compose.yml
├── requirements.txt
├── launch.sh
├── IMPROVEMENTS.md             # Full audit + change log
└── README.md
```

## License

Private tool. Built for research and digital footprint analysis.
