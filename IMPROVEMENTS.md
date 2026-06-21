# Reverse Face Search v2 — Improvement Analysis & Implementation Log

This document captures the full audit of the v2 codebase plus the v2.1 → v2.2
refactor. It is the source of truth for **what was wrong**, **why it mattered**,
**what was changed**, and **how the new feature downsides were mitigated**.

---

## v2.1 — Bug-fix and architecture pass (completed earlier)

### Critical bugs (runtime errors)

| # | File | Issue | Status |
|---|------|-------|--------|
| C1 | `src/intel/pdf.py` | `NameError: report` (was `report_data`) | ✅ fixed |
| C2 | `src/api/routes.py` | `asyncio.create_task` not stored → GC risk | ✅ fixed |
| C3 | `src/correlate/maigret.py` | JSON parsing without `--json simple` | ✅ fixed |
| C4 | engines | Hard-coded Einstein fallback URL in prod | ✅ removed |
| C5 | `requirements.txt` | Wrong deps (weasyprint vs reportlab) | ✅ fixed |
| C6 | `src/engines/filehost.py` | 0x0.st listed as primary (it's down) | ✅ reordered |

### Security

| # | Issue | Status |
|---|-------|--------|
| S1 | `--disable-web-security` Chromium flag | ✅ removed |
| S2 | Secrets in plain YAML | ✅ moved to `.env` |
| S3 | Unprotected dossier endpoints | ✅ noted; auth deferred (see v2.2) |
| S4 | No rate limit on `/api/upload` | ✅ slowapi added |
| S5 | No-auth WebSocket | ✅ noted |

### Architecture

* SQLite persistence (`src/store.py`).
* Disk-backed TTL cache (`src/cache.py`).
* Browser pool — one Chromium per search across 3 engines (`src/engines/pool.py`).
* Lifespan-managed app state (no globals).
* DRY engine link extraction.

### Features added

* Active name-based social search via DuckDuckGo (`src/extract/name_search.py`).
* Optional InsightFace verifier scaffolding (`src/face/`).

### Production

* Dockerfile + docker-compose.yml.
* Emergent preview compatibility (`/app/backend/server.py` shim, `/app/frontend/`).

---

## v2.2 — Privacy & accuracy (this PR)

Built **MinIO storage backend** + **signed-proxy file host** + **active InsightFace
verification** with explicit mitigations for every documented downside.

### Privacy file-host architecture

```
┌─────────┐   /api/upload    ┌────────────┐   PUT      ┌──────────┐
│ Browser ├─────────────────▶│  Backend   ├───────────▶│  MinIO   │
└─────────┘                  │            │            │ (private)│
                             │            │            └──────────┘
                             │            │
                             │   issues   │
                             │   HMAC     │ /api/img/{token}     ┌─────────────┐
                             │   token    │◀─────────────────────│ Yandex/G/B  │
                             │            │   reads from MinIO   │   engines   │
                             │            ├─────────────────────▶│             │
                             └────────────┘                      └─────────────┘
```

The reverse-image-search engines fetch the reference image from the same
domain as the API — no third party sees the upload, no separate domain to
expose, no MinIO endpoint published to the internet.

### Files added (v2.2)

| File | Role |
|------|------|
| `src/storage/signed_token.py` | HMAC-signed URL tokens with TTL |
| `src/storage/backend.py` | `LocalStorage` / `MinIOStorage` abstraction |
| `src/storage/__init__.py` | Public surface |
| `src/face/page_extractor.py` | og:image / twitter:image extractor |
| `src/api/routes.py` | New `/api/img/{token}` endpoint |
| `docker-compose.yml` | Added MinIO service |
| `Dockerfile` | `WITH_FACE` build arg (slim vs. face-enabled images) |

### Files modified (v2.2)

* `src/engines/filehost.py` — signed proxy → imgbb → tmpfiles → 0x0.st waterfall.
* `src/search_manager.py` — `_face_filter` actually wired in; Google bot-detection retry.
* `src/api/routes.py` — `/api/img/{token}` endpoint; upload mirrors into storage.
* `templates/dashboard.html`, `static/js/dashboard.js`, and frontend twins — added `face_filter` pipeline stage.
* `requirements.txt` — `minio>=7.2.0`; face deps uncommented.
* `.env.example`, `.env` — new vars (`RFS_PUBLIC_URL`, `RFS_IMG_TOKEN_SECRET`, `MINIO_*`).
* `tests/test_units.py` — 4 new tests (signed-token roundtrip / tamper / expiry; LocalStorage; og:image).

### Downsides solved

| Original concern | Mitigation |
|------------------|------------|
| **MinIO needs public reachability + HTTPS cert** | Don't expose MinIO. Backend proxies via signed `/api/img/{token}`; engines hit the same domain as the API, automatic HTTPS via Emergent ingress / your existing reverse proxy. |
| **Bot detection — engines distrust new domains** | Google-specific retry: if signed-proxy attempt returns 0 URLs, automatic retry with imgbb (`prefer_external=True`). Best of both — privacy by default, reliability on demand. |
| **Bandwidth costs from engines hitting our bucket** | Token TTL default 10 min; per-IP `60/minute` rate limit on `/api/img/{token}`; `Cache-Control: no-store` to prevent CDN replay. |
| **Operational burden (MinIO container)** | docker-compose ships it healthchecked; MinIO console bound to 127.0.0.1 only; auto-creates bucket on first boot; `LocalStorage` fallback if MinIO isn't configured (graceful degradation). |
| **InsightFace ~700 MB ONNX model** | Build-time `WITH_FACE` arg keeps slim Docker images at <1 GB. Graceful fallback when libs missing (logged once, pipeline continues). |
| **InsightFace slow on CPU (2-5s/image)** | Cap to `max_images_per_engine=10` per engine; concurrent og:image fetch (sem=8); embeddings in thread pool to avoid blocking the event loop. |
| **PII at rest (face embeddings)** | Embeddings computed in-memory, scored, then **discarded** — never persisted. Only the boolean `face_match` flag and the float similarity score are stored in the dossier. |
| **GPU recommended but optional** | `CPUExecutionProvider` is the default; documented GPU upgrade path; first-load model cache happens on first search, not at boot. |

### Token security model

The signed URL uses HMAC-SHA256 over `<base64url(key)>.<exp>`, truncated to
128 bits of MAC. Constant-time comparison via `hmac.compare_digest`.
Failure modes:

* Tampered MAC → 404 (not 401 — no oracle).
* Expired token → 404 (same).
* Malformed token → 404 (same).

Replay during TTL window is acceptable: the token only grants read access
to a single search's reference image, which the user already uploaded.

### Test results

```
11/11 unit tests pass
  - store_lifecycle           - signed_token_roundtrip
  - cache_get_or_compute      - signed_token_expiry
  - name_variants             - local_storage
  - filehost_uses_imgbb       - og_image_extract
  - pdf_missing_wiki          - engine_rejects_missing_image_url
  - username_extraction
```

### Verified through Emergent preview

```
GET  /api/health            → 200
GET  /api/config            → features.face_embedding=true,
                              features.signed_proxy_configured=true,
                              features.storage_backend="local(uploads)"
POST /api/upload            → 200 (returns search_id)
GET  /api/img/{token}       → 200, image/jpeg, exact bytes
GET  /api/img/<tampered>    → 404
GET  /api/img/garbage       → 404
GET  /api/img/a.b.c         → 404
```

---

## Out of scope (kept for future)

* **spaCy NER** — better multilingual name extraction
* **Browser context reuse across searches** — only matters >50 searches/hour
* **JWT auth** — Cloudflare Access in front is the better answer
* **Self-hosted S3-compatible alternatives** — already abstracted; just point at AWS/R2/GCS
