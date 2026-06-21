"""
Quick non-browser pipeline test — verifies Phases 0-1, 4-5, 7 (no headless browser).
Tests upload, clustering, username extraction, dossier assembly.
"""

import sys
import asyncio
import json
import logging
from pathlib import Path
import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("quick_test")

TEST_IMAGE_URL = "https://upload.wikimedia.org/wikipedia/commons/d/d3/Albert_Einstein_Head.jpg"
TEST_IMAGE_NAME = "einstein_test.jpg"


async def test_phases():
    results = {}
    
    # ── Phase 0: Download ──
    logger.info("=== Phase 0: Download test image ===")
    dest = PROJECT_ROOT / "uploads" / TEST_IMAGE_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    
    if not dest.exists() or dest.stat().st_size < 1000:
        req = urllib.request.Request(TEST_IMAGE_URL, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            dest.write_bytes(resp.read())
    logger.info(f"Image ready: {dest.stat().st_size / 1024:.0f}KB")
    results["phase_0_download"] = True

    # ── Phase 1: Upload ──
    logger.info("=== Phase 1: Upload test ===")
    import aiohttp
    from src.config import load_config
    config = load_config()

    async with aiohttp.ClientSession() as session:
        url = f"http://{config.server.host}:{config.server.port}/api/upload"
        with open(dest, "rb") as f:
            form = aiohttp.FormData()
            form.add_field("file", f, filename=TEST_IMAGE_NAME, content_type="image/jpeg")
            async with session.post(url, data=form) as resp:
                data = await resp.json()
                assert resp.status == 200, f"Upload failed: {data}"
                search_id = data["search_id"]
                assert data["status"] == "uploaded"
                logger.info(f"Phase 1 PASSED — search_id: {search_id}")
                results["phase_1_upload"] = True
                results["search_id"] = search_id

    # ── Phase 4: Clustering ──
    logger.info("=== Phase 4: Clustering test ===")
    from src.cluster.parser import ClusterParser
    
    test_urls = [
        {"url": "https://www.instagram.com/alberteinstein/", "title": "Instagram"},
        {"url": "https://www.linkedin.com/in/albert-einstein/", "title": "LinkedIn"},
        {"url": "https://twitter.com/AlbertEinstein", "title": "Twitter"},
        {"url": "https://x.com/EinsteinQuotes", "title": "X"},
        {"url": "https://www.facebook.com/AlbertEinstein", "title": "Facebook"},
        {"url": "https://en.wikipedia.org/wiki/Albert_Einstein", "title": "Wikipedia"},
        {"url": "https://www.nobelprize.org/prizes/physics/1921/einstein/", "title": "Nobel"},
        {"url": "https://www.bbc.com/news/science-environment-123", "title": "BBC News"},
        {"url": "https://www.reddit.com/r/physics/comments/abc/", "title": "Reddit"},
        {"url": "https://medium.com/@einstein_quotes/relativity", "title": "Medium"},
        {"url": "https://www.instagram.com/einstein_legacy/", "title": "Instagram 2"},
    ]

    parser = ClusterParser(config)
    clusters = parser.cluster(test_urls)
    categories = clusters.get("categories", {})
    social = categories.get("social_media", {}).get("count", 0)
    news = categories.get("news_media", {}).get("count", 0)
    blogs = categories.get("personal_blogs", {}).get("count", 0)
    forums = categories.get("forums_communities", {}).get("count", 0)

    logger.info(f"Clusters: social={social}, news={news}, blogs={blogs}, forums={forums}")
    assert social >= 3, f"Expected >=3 social URLs, got {social}"
    results["phase_4_clustering"] = True
    logger.info("Phase 4 PASSED")

    # ── Phase 5: Username extraction ──
    logger.info("=== Phase 5: Username extraction test ===")
    from src.extract.usernames import UsernameExtractor

    extractor = UsernameExtractor()
    test_social_urls = [
        "https://www.instagram.com/alberteinstein/",
        "https://www.linkedin.com/in/albert-einstein-12345/",
        "https://twitter.com/AlbertEinstein",
        "https://x.com/EinsteinQuotes",
        "https://www.facebook.com/AlbertEinstein",
        "https://www.tiktok.com/@einstein_fan",
        "https://www.reddit.com/user/einstein_legacy",
        "https://github.com/einstein-relativity",
    ]

    all_extracted = []
    for url in test_social_urls:
        extracted = extractor.extract_from_url(url)
        all_extracted.extend(extracted)

    usernames = set(r["username"] for r in all_extracted)
    logger.info(f"Extracted usernames: {usernames}")
    assert len(usernames) >= 3, f"Expected >=3 usernames, got {len(usernames)}"
    results["phase_5_usernames"] = True
    logger.info(f"Phase 5 PASSED — {len(usernames)} usernames")

    # ── Phase 6: Maigret (quick test) ──
    logger.info("=== Phase 6: Maigret quick test ===")
    from src.correlate.maigret import MaigretRunner
    from src.config import load_config as lc
    config2 = lc()

    runner = MaigretRunner(config2)
    maigret_results = await runner.run([{"username": "einstein", "platforms": [], "urls": []}])
    einstein_data = maigret_results.get("einstein", {})
    sites = einstein_data.get("sites", [])
    hits = [s for s in sites if s.get("found")]
    
    logger.info(f"Maigret: {len(sites)} sites checked, {len(hits)} hits")
    if len(hits) >= 2:
        results["phase_6_maigret"] = True
        logger.info(f"Phase 6 PASSED — {len(hits)} hits")
    elif len(sites) >= 10:
        results["phase_6_maigret"] = True
        logger.info(f"Phase 6 PASSED (sites only) — {len(sites)} sites checked")
    else:
        results["phase_6_maigret"] = False
        logger.warning(f"Phase 6 PARTIAL — {len(hits)} hits, {len(sites)} sites")

    # ── Phase 7: Dossier ──
    logger.info("=== Phase 7: Dossier test ===")
    from src.dossier.builder import DossierBuilder

    builder = DossierBuilder()
    pipeline_data = {
        "search_id": search_id,
        "image_path": str(dest),
        "engine_results": {
            "yandex": {"urls": [
                {"url": "https://en.wikipedia.org/wiki/Albert_Einstein", "title": "Albert Einstein - Wikipedia"},
                {"url": "https://www.instagram.com/einstein_quotes/", "title": "Einstein Quotes"},
            ]},
            "google": {"urls": [
                {"url": "https://www.linkedin.com/in/alberteinstein/", "title": "Albert Einstein"},
            ]},
        },
        "clusters": {},
        "usernames": [
            {"username": "alberteinstein", "platforms": ["instagram", "linkedin"], "urls": ["https://www.instagram.com/alberteinstein/"]},
        ],
        "maigret_results": {},
        "errors": [],
    }

    # Generate clusters from synthetic URLs
    all_urls = []
    for eng_data in pipeline_data["engine_results"].values():
        all_urls.extend(eng_data.get("urls", []))
    pipeline_data["clusters"] = parser.cluster(all_urls)

    dossier = builder.build(pipeline_data)
    required = ["search_id", "summary", "engines", "clusters", "usernames", "cross_platform_correlation"]
    missing = [s for s in required if s not in dossier]
    assert not missing, f"Dossier missing: {missing}"

    # Save JSON
    dossiers_dir = PROJECT_ROOT / "dossiers"
    dossiers_dir.mkdir(parents=True, exist_ok=True)
    dossier_path = dossiers_dir / f"{search_id}.json"
    with open(dossier_path, "w") as f:
        json.dump(dossier, f, indent=2, default=str)

    logger.info(f"Dossier saved: {dossier_path}")
    logger.info(f"Summary: {dossier['summary']}")
    results["phase_7_dossier"] = True
    logger.info("Phase 7 PASSED")

    # ── Summary ──
    logger.info("\n" + "=" * 50)
    passed = sum(1 for v in results.values() if v and isinstance(v, bool))
    total = sum(1 for v in results.values() if isinstance(v, bool))
    for k, v in results.items():
        if isinstance(v, bool):
            logger.info(f"  {k}: {'PASS' if v else 'FAIL'}")
    logger.info(f"  Total: {passed}/{total}")

    return results


if __name__ == "__main__":
    results = asyncio.run(test_phases())
    with open(PROJECT_ROOT / "test_results.json", "w") as f:
        json.dump(results, f, indent=2)
