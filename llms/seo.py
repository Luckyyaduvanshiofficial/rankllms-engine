"""
RankLLMs Engine — SEO surfaces.

Target keywords: rankllms, rankllm, ai models ranking, llms leaderboard.

Everything here is served from the same merged ``rankindex`` table the rest of
the site reads, so crawlable pages and the live API never disagree.
"""

from datetime import datetime, timezone

from django.http import HttpResponse, JsonResponse

from llms.models import RankIndex

SITE_URL = "https://api.rankllms.com"

# Pages that describe the product to search engines. Keep in sync with the
# nav (_wa_nav.html) and the footer links on each page.
INDEXABLE_PAGES = [
    # (path, changefreq, priority, why it ranks)
    ("/", "daily", "1.0"),
    ("/llm-leaderboard", "daily", "0.9"),
    ("/rankllms", "daily", "0.9"),
    ("/rankllms/models", "daily", "0.8"),
    ("/benchmarks", "daily", "0.8"),
    ("/compare", "weekly", "0.7"),
    ("/cards", "weekly", "0.7"),
    ("/leaderboard", "weekly", "0.6"),
    ("/agent-guide", "monthly", "0.5"),
    ("/ormodels", "weekly", "0.5"),
    ("/orbench", "weekly", "0.5"),
    ("/aamodels", "weekly", "0.5"),
    ("/aabanch", "weekly", "0.5"),
    ("/modelsdev", "weekly", "0.5"),
]


def _esc(text):
    """Minimal XML/HTML escaper — enough for slugs, names and prose."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def robots_txt(request):
    """
    Crawl instructions. Points at sitemap.xml and keeps admin/sync routes out
    of the index.
    """
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /api/",
        "Disallow: /ping",
        "Disallow: /health",
        "Disallow: /healthz",
        "",
        f"Sitemap: {SITE_URL}/sitemap.xml",
        "",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def sitemap_xml(request):
    """
    Sitemap of the indexable HTML pages (lastmod = latest rankindex sync).
    Individual model pages, if any exist later, can be added here.
    """
    lastmod = datetime.now(timezone.utc)
    try:
        latest = RankIndex.objects.order_by("-updated_at").values_list(
            "updated_at", flat=True
        ).first()
        if latest:
            lastmod = latest
    except Exception:
        # Never let the sitemap 500 — a missing table is a sync problem,
        # not a crawl problem.
        pass

    urls = []
    for route, changefreq, priority in INDEXABLE_PAGES:
        urls.append(
            f"""  <url>
    <loc>{_esc(SITE_URL)}{_esc(route)}</loc>
    <lastmod>{lastmod.strftime('%Y-%m-%d')}</lastmod>
    <changefreq>{changefreq}</changefreq>
    <priority>{priority}</priority>
  </url>"""
        )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>
"""
    return HttpResponse(xml, content_type="application/xml")


def keyword_report(request):
    """
    Internal QA view: what the target keywords look like on every page.
    ``?verbose=1`` prints the per-page keyword hits so a deploy can be
    checked with curl before relying on it.
    """
    targets = {
        "rankllms": 0,
        "rankllm": 0,
        "ai models ranking": 0,
        "ai model rankings": 0,
        "llms leaderboard": 0,
        "llm leaderboard": 0,
    }
    pages = []
    for route, _cf, _pr in INDEXABLE_PAGES:
        # Only pages rendered from templates can be checked this way; the
        # root page is docs_portal.html.
        view_name = {
            "/": "root_home",
            "/llm-leaderboard": "llm_leaderboard_page",
            "/rankllms": "rankllms_page",
            "/rankllms/models": "rankllms_models_page",
            "/benchmarks": "benchmarks_page",
            "/compare": "compare_page",
            "/cards": "cards_page",
            "/leaderboard": "leaderboard_page",
            "/agent-guide": "agent_guide_page",
            "/ormodels": "ormodels_page",
            "/orbench": "orbench_page",
            "/aamodels": "aamodels_page",
            "/aabanch": "aabanch_page",
            "/modelsdev": "modelsdev_page",
        }[route]
        pages.append({"path": route, "view": view_name})

    report = {
        "site_url": SITE_URL,
        "sitemap": f"{SITE_URL}/sitemap.xml",
        "robots": f"{SITE_URL}/robots.txt",
        "target_keywords": list(targets.keys()),
        "pages": pages,
        "indexable_count": len(pages),
    }
    return JsonResponse(report)


app_name = "seo"
