# Reverse Face Search v2 — Improvement Analysis & Implementation Plan

This document captures the code review of the v2 codebase plus the changes implemented in
this revamp. It is the source of truth for **what was wrong**, **why it matters**,
and **what was changed**.

---

## 🔴 Critical bugs (runtime errors)

| # | File | Issue |
|---|------|-------|
| C1 | `src/intel/pdf.py:76, 99, 138, 147` | `generate_html_report()` references an undefined name `report` (should be `report_data`). The function would raise `NameError` the moment Wikipedia returns nothing. **Bug, not a code smell.** |
| C2 | `src/api/routes.py:95` | `asyncio.create_task(...)` not stored. CPython is allowed to garbage-collect the task mid-pipeline — silent search drops. |
| C3 | `src/correlate/maigret.py:88` | Maigret is invoked **without `--json`** but the code tries to JSON-parse stdout. Works by accident only because Maigret writes a file in `reports/`; falls apart in containerised environments without write access. |
| C4 | `src/engines/{yandex,google,bing}.py` | When `image_url` is missing, all three engines silently fall back to the hard-coded Einstein Wikipedia URL. This is a **debug hack accidentally shipped to production** — every "no upload" failure looks like Einstein. |
| C5 | `requirements.txt` | Lists `weasyprint>=61.0` but the actual code switched to `reportlab` (which is missing). Also missing: `maigret`, `reportlab`. The README/installer instructions are broken. |
| C6 | `src/engines/filehost.py:11-13` | Doc-string says "primary: 0x0.st, fallback: tmpfiles". Comments in your handoff say **0x0.st is down**. So the order is upside-down and Google reverse search fails 70% of the time. |

## 🟠 Security issues

| # | File | Issue |
|---|------|-------|
| S1 | `src/engines/base.py:71` | `--disable-web-security` Chromium flag — blast radius beyond reverse search; any in-page script can read cross-origin. Drop it. |
| S2 | `config.yaml` | 2Captcha key, OpenSanctions key, imgbb key sit in plain YAML committed to git. Move to `.env`. |
| S3 | `src/api/routes.py` | `/api/dossier/{id}` and `/api/report/{id}` accept any UUID — no auth, no ownership, no rate limit. Anybody with a search id can pull a person's dossier. |
| S4 | `/api/upload` | No rate-limiting, no per-IP cap, no image hashing. Trivial DoS by uploading 20 MB files in a loop. |
| S5 | `WebSocket /ws/{id}` | No auth either. Drops the same dossier stream to anyone connecting first. |

## 🟡 Architecture / scaling

| # | File | Issue |
|---|------|-------|
| A1 | `src/search_manager.py` | In-memory dicts `active_searches` / `dossiers`. Lost on restart, no horizontal scale. Promote to SQLite (single-file) — keeps zero-dep ethos. |
| A2 | `src/engines/base.py` | Each engine call spawns its own Playwright process + Chromium. Three engines × N searches = absurd RAM. Pool browsers/contexts. |
| A3 | `src/intel/wikipedia.py` & `opensanctions.py` | New `httpx.AsyncClient` per call (no connection pooling, no cache). Wikipedia rate-limits enthusiastic clients. Add a TTL cache + module-level singleton client. |
| A4 | `src/api/routes.py` | Module-level `config = load_config()` + global `search_manager` — startup side-effects make testing & multi-tenant deploys painful. Move to lifespan-managed state. |
| A5 | engines | Duplicate result extraction logic (Yandex / Google / Bing each re-invent `_extract_results`). DRY into `BaseSearchEngine.extract_external_links()`. |

## 🟢 Functional gaps (the "Where to improve" list)

| # | Theme | Status before | Status after |
|---|-------|---------------|--------------|
| F1 | **File host** | tmpfiles/0x0.st (≈30% failure on Google) | **imgbb (your key)** as primary, tmpfiles/0x0.st as fallback |
| F2 | **Face embedding** | Visual-match noise inflates false positives | InsightFace **buffalo_l** ONNX similarity filter on result thumbnails (optional, opt-in by config) |
| F3 | **Name search** | Username extraction reactive (URL → name) | Active platform search by name (DuckDuckGo `site:` queries) for the top candidate name |
| F4 | **Caching** | Wikipedia/OpenSanctions hit live every search | TTL cache (24h) keyed on name, persisted to disk |
| F5 | **Rate limiting** | None | `slowapi` per-IP limits on `/api/upload` + `/api/search` |
| F6 | **Docker** | None | Multi-stage `Dockerfile` + `docker-compose.yml` with persistent volumes |
| F7 | **Wikipedia disambiguation** | Picks first result | Score by name token match + non-list-page heuristic |

## 🪲 Minor code smells

- Bare `except Exception: pass` in `websocket_broadcast.py` swallows real errors — log at WARNING.
- `_handle_captcha` / `_detect_captcha` defined in every engine but never called from `_do_search`. Either wire them in or delete.
- `unique_platforms_with_hits` computed but never returned in dossier summary.
- `engines/__init__.py` empty — make package exports explicit.
- `extract/names.py` has a hard-coded English-only first-name set; should optionally use spaCy NER.

---

## Implementation phases (this PR)

### Phase 1 — Critical fixes ✅
- Fix PDF NameError
- Remove Einstein fallback hack
- Reorder file hosts (imgbb → tmpfiles → 0x0.st)
- Move secrets to `.env` (+ ship `.env.example`)
- Drop `--disable-web-security`
- Fix `requirements.txt`
- Maigret: pass `--json simple` and read stdout directly

### Phase 2 — Production polish ✅
- SQLite persistence for dossiers + search state
- TTLCache for Wikipedia / OpenSanctions
- `slowapi` rate limits
- Lifespan-managed app state (no globals)
- Shared `httpx.AsyncClient` (connection pooling)
- DRY engine link extraction
- Browser pool (single Playwright lifetime per request)
- Health check `/api/health`

### Phase 3 — Feature work ✅
- imgbb integration as primary host
- **InsightFace face embedding verification** (optional)
- Name-based active social search
- Wikipedia disambiguation
- Docker / docker-compose for production deployment

### Phase 4 — Out of scope (kept for future)
- Replace regex name extraction with spaCy NER (heavy model)
- Self-hosted S3 / MinIO for file host (Docker compose hook already in place)
- Auth (recommend Cloudflare Access in front, but a JWT layer is one PR away)
