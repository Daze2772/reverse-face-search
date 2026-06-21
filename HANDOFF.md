# ════════════════════════════════════════════════════════════════════════
#  HANDOFF — Reverse Face Search v2.3 (Tier 1 sprint)
# ════════════════════════════════════════════════════════════════════════
#
# Copy everything below this line into the new agent's first message.

---

# Reverse Face Search v2.3 — Agent Handoff

## Project context

You're picking up an **existing, working codebase** — a Python-based reverse-face-search OSINT
tool that already runs in the Emergent preview. It is NOT a fresh project. Do not rebuild
from scratch.

**Location in Emergent:** `/app/`
**Owner's local copy:** `/Users/ryan/reverse-face-search`
**GitHub:** `github.com/Daze2772/reverse-face-search`
**Live preview:** `https://cad78729-539a-4a12-8452-f3e171f410c0.preview.emergentagent.com/`

**Tech stack:** Python 3.11 / FastAPI / Playwright / SQLite / vanilla-JS dashboard. Frontend
is served on port 3000 via `serve` (npm) from `/app/frontend/public/`. Backend on port 8001
via `uvicorn server:app` from `/app/backend/` (which is a thin shim importing the real app
at `/app/src/`).

## Read these BEFORE writing any code

In order:

1. `/app/IMPROVEMENTS.md` — Complete audit + v2.1 + v2.2 change log. The "what's already
   been done" master document.
2. `/app/README.md` — Architecture overview, env vars, run/test commands.
3. `/app/src/search_manager.py` — Pipeline orchestrator (the brain).
4. `/app/src/api/routes.py` — All HTTP/WS endpoints + lifespan + rate limits.
5. `/app/src/engines/base.py` — Engine interface contract.
6. `/app/src/intel/report.py` — Where the (currently templated) narrative lives.
7. `/app/tests/test_units.py` — Existing test suite (currently 11/11 pass).

## Already done — DO NOT redo these

- v2.1: Fixed PDF NameError, Einstein fallback hack, Maigret JSON parsing, broken
  requirements, --disable-web-security, in-memory state.
- v2.1: Added SQLite store, TTL disk cache, browser pool, slowapi rate limits, CORS,
  lifespan management, active DuckDuckGo name search.
- v2.2: **Signed-proxy file host** (privacy — image never leaves your infra), MinIO
  storage backend abstraction, **active InsightFace face verification** (top-10 per
  engine), HMAC-signed image URLs, og:image extractor for face filter.
- Emergent preview shim: `/app/backend/server.py` + `/app/frontend/` (don't move these).
- All 11 unit tests pass. Lint clean. Backend + frontend running in supervisor.

## What you're building (Tier 1 + 2 + 3 sprint)

User wants the following features, in this priority order. Owner is impatient — ship Tier 1
first, get a screenshot to them, then continue.

### TIER 1 — Ship first (≈4 days)

#### T1a — LLM-powered intelligence narratives (replaces `src/intel/report.py` narrative)

**Goal:** Replace the templated `_build_narrative()` function with an LLM call that produces
analyst-grade prose.

- **Integration:** Use the **Emergent LLM key** via `emergentintegrations` (call
  `integration_playbook_expert_v2` to get the playbook).
- **Recommended model:** `claude-sonnet-4.5` (best for structured analytical writing) with
  `gpt-5.2-mini` as fallback if balance is low.
- **Prompt design:** System prompt frames the LLM as an OSINT analyst. User prompt is the
  full dossier (Wikipedia data, social presence, affiliations, risk assessment) as JSON.
  Output target: 3 sections — Executive Summary, Identity & Footprint, Risk & Verification
  Notes. ~400-700 words.
- **Fallback:** If LLM fails or returns nothing, fall back to the existing template (already
  in `src/intel/report.py` — rename the function, keep it as `_build_template_narrative`).
- **Caching:** Cache LLM output by `(subject_name, hash(dossier_fingerprint))` in the
  existing `TTLDiskCache` so re-running the same search doesn't burn LLM credits.
- **Config:** Add `RFS_LLM_ENABLED=true` and `RFS_LLM_MODEL=claude-sonnet-4.5` to `.env`.
- **Cost protection:** Hard cap on tokens, log $estimate per search.

**Owner explicitly said:** "make it real LLM or have better more professional template" —
so deliver the LLM version, and ALSO upgrade the template fallback (current one is too
short and lifeless; rewrite to read like a real analyst's brief).

#### T1b — Add 4 new search engines

User wants **broader index coverage**. Add these alongside Yandex/Google/Bing:

| Engine | Why | Approach |
|---|---|---|
| **TinEye** | Largest reverse image index (~80B). | Free web scrape (Playwright). No API key required. URL: `https://tineye.com/search?url=<imgurl>`. Owner said do paid TinEye later if scrape fails. |
| **DuckDuckGo Images** | Bing-backed, uncensored, free. | URL endpoint: `https://duckduckgo.com/?iax=images&ia=images&q=<url>`. |
| **Baidu Images** | Chinese coverage Yandex/Google miss. | `https://image.baidu.com/n/pc_search?queryImageUrl=<urlencoded>`. Headless. |
| **Karma Decay** | Reddit reverse image search. | `https://karmadecay.com/<imgurl>` — simple HTML scrape. Owner explicitly requested this. |

All four follow the existing `BaseSearchEngine` pattern in `/app/src/engines/base.py`. Add
to enable list in config + `RFS_ENGINES` env var. Add `OWN_DOMAINS` per engine. Use the
shared `BrowserPool` so they share one Chromium with the existing engines.

**Owner has applied for PimEyes** — they're not approved yet. Stub a `PimEyesEngine` class
that reads `PIMEYES_API_KEY` from env and short-circuits (returns empty + clear log) when
no key is set, so it auto-activates when their access comes through.

#### T1c — Browser context reuse across searches (deferred from earlier)

Promote `BrowserPool` from per-search to per-process. One Chromium starts at lifespan boot,
each search gets a fresh context. Saves ~3s per search. Add `asyncio.Semaphore` capping
concurrent searches (default 4). Add restart-after-N-searches recycle policy to prevent
Chromium memory leaks (default N=100). Health-check pool every 60s; if dead, respawn
without dropping in-flight requests.

#### T1d — Parallel Maigret

`src/correlate/maigret.py` runs usernames **sequentially**. Parallelize with bounded
`asyncio.Semaphore` (default 3 concurrent). Total speedup: 3-5× for typical 2-4 username
dossiers.

### TIER 2 — Ship after Tier 1 (≈3 days each)

#### T2a — spaCy NER (replaces regex name/org/location extraction)

- Add `spacy>=3.7` to requirements.
- Download `en_core_web_lg` (580 MB) — do this at Docker build time, not at runtime.
- New module `src/extract/ner.py` exposing `extract_persons(text)`, `extract_orgs(text)`,
  `extract_locations(text)`.
- Use it in `src/extract/names.py` and `src/intel/affiliations.py`.
- Keep regex as fallback when spaCy not installed.
- Optional behind `RFS_NER_ENABLED=true` (default true if `spacy` is importable).

#### T2b — Face co-occurrence ("seen with" relationship mapping)

The killer feature. Logic:

1. For each result-page og:image already fetched in the face filter, run InsightFace on
   **all** faces (not just the largest).
2. Store the per-page list of face embeddings.
3. After all engines + face-filter done, find faces that appear on ≥2 different pages with
   our subject. Group them.
4. For each "seen with" face cluster, try reverse-search of that face's thumbnail against
   Wikipedia + Wikidata to identify them (best-effort).
5. Add a `relationships` section to the dossier:
   ```
   "seen_with": [
     {"name": "Jace Norman", "co_occurrence_pages": 12, "confidence": 0.91},
     {"name": "Unknown face #2", "co_occurrence_pages": 5}
   ]
   ```
6. Render as a small graph in the dashboard + PDF section.

#### T2c — Geo-intelligence (EXIF + location NER)

- Extract EXIF GPS from uploaded image (Pillow `_getexif`).
- Pull location entities from result page snippets via spaCy NER (`GPE` label).
- Geocode known places via Wikipedia coordinates API (free, no key).
- Add `geography` section to the dossier with primary location + confidence.

### TIER 3 — Backlog (defer; have ready proposals)

- **T3a Telegram channel search** via telegram-search engines (requires deeper crawler).
- **T3b Video face search** — keyframe extraction + per-frame search.
- **T3c Continuous monitoring** — daily re-runs, webhook alerts.
- **T3d Browser extension** — right-click any image → search.

Do NOT start Tier 3 in this session. Owner wants Tier 1 first, then Tier 2 if time.

## Integrations required — CALL THE PLAYBOOK SUBAGENT FIRST

Before writing any LLM code, **you must call `integration_playbook_expert_v2`** with:

```
INTEGRATION: Claude Sonnet 4.5 chat (text-only) via Emergent LLM key
CONSTRAINTS: Pure Python, async, used inside a FastAPI background task
```

Then implement EXACTLY per the playbook. The Emergent LLM key is in
`emergent_integrations_manager` tool — fetch and store in `.env` as `EMERGENT_LLM_KEY`.

For the OpenSanctions key (`97e0fd1172404c70c4a00c319f7d665b`): **already set in
`/app/.env` as `OPENSANCTIONS_API_KEY`**. Don't re-add it.

## Existing keys (preserved in `/app/.env`)

| Key | Status |
|-----|--------|
| `IMGBB_API_KEY` | ✅ set |
| `OPENSANCTIONS_API_KEY` | ✅ set (97e0fd11…) |
| `RFS_IMG_TOKEN_SECRET` | ✅ generated |
| `RFS_PUBLIC_URL` | ✅ set to preview URL |
| `EMERGENT_LLM_KEY` | ⚠️ you need to fetch via `emergent_integrations_manager` |
| `TWOCAPTCHA_API_KEY` | empty (not needed yet) |
| `PIMEYES_API_KEY` | empty (waiting on owner's account approval) |

## Architecture invariants — DO NOT BREAK

1. **Three deployment targets must all keep working:**
   - Emergent preview (`/app/backend/server.py` + `/app/frontend/`).
   - Local dev on macOS (`python -m src.main` from project root, port 8000).
   - Docker compose (with MinIO; reads `/app/.env`).
2. **Routes:** keep `/api/*` prefix for everything backend (Emergent ingress rule).
3. **WebSocket:** keep both `/ws/{id}` and `/api/ws/{id}` aliases (dashboard uses the
   `/api/ws/` one).
4. **Storage abstraction:** new code reads/writes images via `src/storage/get_storage()`,
   never directly touches `uploads/` or MinIO SDK.
5. **Cache layer:** new upstream calls go through `src/cache.py` TTL cache.
6. **No globals.** Use `app.state.*` set up in `lifespan()`.
7. **No hard-coded secrets.** Everything via `.env` / `os.environ`.
8. **Do NOT downgrade the InsightFace pipeline.** It's working — extend it, don't replace.

## Testing requirements

You MUST do this for each task you complete (no exceptions):

1. Run `python tests/test_units.py` — must be 11/11 (or 12+/12+ after you add new tests).
2. Run `python -c "from src.api.routes import create_app; create_app()"` to confirm boot.
3. Lint: `ruff check src/` — must be 0 errors.
4. Restart backend: `sudo supervisorctl restart backend` and confirm health endpoint:
   `curl https://cad78729-539a-4a12-8452-f3e171f410c0.preview.emergentagent.com/api/health`
   must return `{"status":"ok","version":"..."}`.
5. For each new engine: add a unit test that mocks Playwright and asserts URL extraction
   doesn't crash on empty/junk HTML.
6. For the LLM narrative: add a test that mocks the LLM call (return fake string) and
   confirms the dossier contains it.
7. **Before declaring done, call `testing_agent_v3` with the full feature list and have it
   exercise the live preview URL end-to-end.**

## File-creation guidelines

- Prefer **editing existing files** with `mcp_search_replace` over creating new ones.
- New engines → new files in `/app/src/engines/<name>.py` following the existing pattern.
- New LLM narrative code → new file `src/intel/llm_narrative.py`, wire into
  `src/intel/report.py` via dependency injection.
- Never touch `/app/.git`, `/app/.emergent`, supervisor configs, or `/app/backend/server.py`
  (the shim).

## Success criteria — when is Tier 1 done?

- [ ] LLM narrative is the default; dossier shows `narrative_source: "claude-sonnet-4.5"`.
- [ ] Template fallback still works (toggle `RFS_LLM_ENABLED=false` to verify).
- [ ] Template fallback rewritten to be analyst-quality, not the current short blurb.
- [ ] 4 new engines registered: TinEye, DuckDuckGo Images, Baidu, Karma Decay.
- [ ] `/api/config` reports all 7 engines + PimEyes stub.
- [ ] Browser pool: 1 Chromium per process, recycled after 100 searches.
- [ ] Maigret runs N usernames concurrently (default 3).
- [ ] All 11+ existing unit tests still pass.
- [ ] `testing_agent_v3` confirms full pipeline runs end-to-end via the preview URL on a
      public-figure image (try Elon Musk or Albert Einstein).
- [ ] `/app/IMPROVEMENTS.md` updated with v2.3 section.
- [ ] `/app/memory/PRD.md` updated.

## Owner preferences (from the conversation)

- Pragmatic, wants results fast. Hates fluff.
- Will run code on macOS locally + production Docker eventually.
- Already has imgbb key; applied for PimEyes; no TinEye paid subscription yet.
- Wants LLM narratives explicitly. Also wants a much better template fallback ("more
  professional template" — the current one is too brief).
- Wants Karma Decay specifically called out (Reddit coverage matters to them).
- Pushed back when feature gaps were oversold by the previous agent — be honest about
  limitations, no marketing copy.

## Start by

1. Greet the owner briefly. Say you've read the handoff doc.
2. Confirm you'll start with **T1a (LLM narrative) + T1b (4 engines)** in this session,
   defer T1c/T1d to follow-up.
3. Call `integration_playbook_expert_v2` for Claude Sonnet 4.5 + Emergent LLM key.
4. Fetch the key from `emergent_integrations_manager`.
5. Implement, test, restart, screenshot, summarise via `finish` tool.

Good luck. Don't over-engineer.
