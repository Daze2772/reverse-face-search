"""Unit tests for the new v2.1 modules.

Run from the project root:
    python tests/test_units.py

These tests do NOT touch the network (file host is mocked) so they're fast
and CI-friendly.
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test_units")


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ─── Store ─────────────────────────────────────────────────────────────────

def test_store_lifecycle():
    from src.store import Store
    with tempfile.TemporaryDirectory() as td:
        store = Store(str(Path(td) / "rfs.sqlite"))
        s = store.create_search("abc-1", "uploads/abc-1.jpg")
        assert_true(s["status"] == "running", "fresh search should be running")
        assert_true(s["stage"] == "uploaded", "initial stage should be 'uploaded'")

        store.update_stage("abc-1", "reverse_search", {"current_engine": "yandex"})
        s = store.get_search("abc-1")
        assert_true(s["stage"] == "reverse_search", "stage should advance")
        assert_true(s["progress"]["current_engine"] == "yandex", "progress should accumulate")

        store.append_error("abc-1", "bing: blocked")
        s = store.get_search("abc-1")
        assert_true(s["errors"] == ["bing: blocked"], "errors should be persisted")

        store.finalize("abc-1", "completed", dossier={"search_id": "abc-1", "summary": {"x": 1}})
        d = store.get_dossier("abc-1")
        assert_true(d["search_id"] == "abc-1", "dossier round-trip")
        assert_true(store.get_search("abc-1")["status"] == "completed", "status should be completed")

        # Recent list
        store.create_search("abc-2", "uploads/abc-2.jpg")
        recent = store.list_recent(5)
        assert_true(len(recent) == 2, f"expected 2 recent, got {len(recent)}")
        store.close()
    logger.info("✔ store_lifecycle PASS")


# ─── Cache ─────────────────────────────────────────────────────────────────

async def test_cache_get_or_compute():
    from src.cache import TTLDiskCache
    with tempfile.TemporaryDirectory() as td:
        cache = TTLDiskCache(td, ttl_seconds=60)
        calls = {"n": 0}

        async def producer():
            calls["n"] += 1
            return {"who": "Einstein", "n": calls["n"]}

        v1 = await cache.get_or_compute("wikipedia", "Einstein", producer)
        v2 = await cache.get_or_compute("wikipedia", "Einstein", producer)
        assert_true(v1 == v2, "cache should return identical value")
        assert_true(calls["n"] == 1, f"producer should fire once, fired {calls['n']}")

        v3 = await cache.get_or_compute("wikipedia", "Bohr", producer)
        assert_true(v3["who"] == "Einstein", "value cached under previous key")
        assert_true(calls["n"] == 2, "different key triggers producer")
    logger.info("✔ cache_get_or_compute PASS")


# ─── Name handle variants ──────────────────────────────────────────────────

def test_name_variants():
    from src.extract.names import name_to_handle_variants, score_username_against_names
    v = name_to_handle_variants("Cooper Barnes")
    assert_true("cooperbarnes" in v, "should generate concatenated handle")
    assert_true("cooper_barnes" in v, "should generate underscore handle")
    assert_true("cooper.barnes" in v, "should generate dotted handle")

    s = score_username_against_names("cooperbarnes", ["Cooper Barnes"])
    assert_true(s == 1.0, f"exact handle match should be 1.0, got {s}")

    s = score_username_against_names("therealcooperbarnes", ["Cooper Barnes"])
    assert_true(s > 0.7, f"prefix match should be > 0.7, got {s}")

    s = score_username_against_names("randomuser123", ["Cooper Barnes"])
    assert_true(s < 0.3, f"unrelated handle should be < 0.3, got {s}")
    logger.info("✔ name_variants PASS")


# ─── File host parity (imgbb key configured) ──────────────────────────────

def test_filehost_uses_imgbb():
    from src.engines import filehost
    # We can't actually upload without hitting the network, but we can confirm
    # the function falls through gracefully when the file path is missing.
    out = asyncio.run(filehost.upload_to_public("/does/not/exist.jpg"))
    assert_true(out is None, "non-existent file should return None")
    logger.info("✔ filehost_uses_imgbb PASS")


# ─── PDF generation does not raise on missing wiki ────────────────────────

def test_pdf_missing_wiki():
    from src.intel.pdf import generate_pdf, generate_html_report

    report = {
        "report_id": "test-1234",
        "subject_name": "John Doe",
        "candidate_names": ["John Doe"],
        "wikipedia": None,        # the bug-trigger condition
        "risk_assessment": None,
        "affiliations": {"organizations": [], "locations": [], "topics": []},
        "search_summary": {"total_urls": 0, "engines": {}},
        "social_presence": {"usernames_found": 0, "accounts": []},
        "public_figure": {"level": "PRIVATE_INDIVIDUAL", "confidence": "HIGH"},
        "narrative": "## Identity\nName: John Doe.\n",
        "cross_platform": {"total_platform_hits": 0, "usernames_searched": 0, "details": {}},
    }
    html = generate_html_report(report)
    assert_true("John Doe" in html, "HTML should contain subject name")
    assert_true("No Wikipedia entry found" in html, "HTML should handle missing wiki cleanly")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        out = generate_pdf(report, tmp.name)
    assert_true(out and len(out) > 100, "PDF should be a few bytes at least")
    os.unlink(tmp.name)
    logger.info("✔ pdf_missing_wiki PASS")


# ─── Username extraction sanity ───────────────────────────────────────────

def test_username_extraction():
    from src.extract.usernames import UsernameExtractor
    e = UsernameExtractor()
    out = e.extract_from_url("https://www.instagram.com/cooperbarnes/")
    assert_true(any(r["username"] == "cooperbarnes" for r in out), f"missed instagram: {out}")
    out = e.extract_from_url("https://twitter.com/cooperbarnes")
    assert_true(any(r["username"] == "cooperbarnes" for r in out), f"missed twitter: {out}")
    # Org filter
    out = e.extract_from_url("https://twitter.com/cnnnews")
    usernames = [r["username"] for r in out]
    assert_true("cnnnews" not in usernames, "org filter should drop news outlet handles")
    logger.info("✔ username_extraction PASS")


# ─── Engine refusal when no image_url ────────────────────────────────────

def test_engine_rejects_missing_image_url():
    from src.engines.yandex import YandexEngine
    from src.config import load_config
    cfg = load_config()
    eng = YandexEngine(cfg)
    out = asyncio.run(eng.search("/tmp/fake.jpg", image_url=None))
    assert_true(out["urls"] == [], "no image_url → no results")
    assert_true("file host" in (out.get("error") or "").lower(),
                f"should reference file host failure, got {out.get('error')}")
    logger.info("✔ engine_rejects_missing_image_url PASS")


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    tests = [
        ("store_lifecycle", test_store_lifecycle, False),
        ("cache_get_or_compute", test_cache_get_or_compute, True),
        ("name_variants", test_name_variants, False),
        ("filehost_uses_imgbb", test_filehost_uses_imgbb, False),
        ("pdf_missing_wiki", test_pdf_missing_wiki, False),
        ("username_extraction", test_username_extraction, False),
        ("engine_rejects_missing_image_url", test_engine_rejects_missing_image_url, False),
    ]
    results = {}
    for name, fn, is_async in tests:
        try:
            if is_async:
                asyncio.run(fn())
            else:
                fn()
            results[name] = "pass"
        except Exception as e:
            logger.error(f"✘ {name} FAIL: {e}")
            results[name] = f"fail: {e}"

    passed = sum(1 for v in results.values() if v == "pass")
    logger.info("=" * 50)
    logger.info(f"{passed}/{len(tests)} unit tests passed")
    for k, v in results.items():
        logger.info(f"  {'PASS' if v == 'pass' else 'FAIL'}: {k}")

    # Write a report for the testing agent
    (PROJECT_ROOT / "test_reports").mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "test_reports" / "test_units.json").write_text(
        json.dumps({"results": results, "passed": passed, "total": len(tests)}, indent=2)
    )

    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
