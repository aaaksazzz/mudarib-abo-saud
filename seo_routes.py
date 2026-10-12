"""SEO endpoints for public pages and educational articles."""
import os
from pathlib import Path
from urllib.parse import quote
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response
from multilingual_articles import (
    router as multilingual_router,
    DATA as MULTILINGUAL_DATA,
    LANGS as MULTILINGUAL_LANGS,
)

router = APIRouter()
BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
DEFAULT_SITE_URL = "https://web--mudarib-abo-saud--bn5qcyddt9b4.code.run"
EXCLUDED = {"admin.html", "login.html", "signup.html", "register.html", "index.html"}


def _site_url(request: Request) -> str:
    # Set SEO_SITE_URL in Northflank when a permanent custom domain is configured.
    return os.getenv("SEO_SITE_URL", DEFAULT_SITE_URL).rstrip("/")


@router.get("/robots.txt", include_in_schema=False)
def robots(request: Request):
    base = _site_url(request)
    return PlainTextResponse(
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "Disallow: /admin\n"
        "Disallow: /static/admin.html\n"
        "Disallow: /static/login.html\n"
        "Disallow: /static/signup.html\n"
        f"Sitemap: {base}/sitemap.xml\n",
        media_type="text/plain",
    )


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(request: Request):
    base = _site_url(request)
    urls = {"/"}

    # Include existing public pages and static articles only.
    if STATIC.exists():
        for path in STATIC.rglob("*.html"):
            if path.name.lower() in EXCLUDED:
                continue
            rel = path.relative_to(STATIC).as_posix()
            if rel.startswith("articles/") or "/" not in rel:
                urls.add("/static/" + rel)

    # Some blog articles are generated dynamically at /blog/{slug}; list them
    # too, but skip slugs with a static article because /blog/{slug} redirects.
    try:
        from content import BLOG

        for item in BLOG:
            slug = str(item.get("slug", "")).strip()
            if not slug or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in slug):
                continue
            if (STATIC / "articles" / (slug + ".html")).is_file():
                continue
            urls.add("/blog/" + quote(slug, safe="-._~"))
    except Exception as exc:
        # Keep sitemap generation alive if optional blog content cannot load.
        print(f"[SEO] dynamic blog sitemap skipped: {type(exc).__name__}", flush=True)

    urls.add("/learn")
    for slug, _titles, _tips in MULTILINGUAL_DATA:
        for lang in MULTILINGUAL_LANGS:
            urls.add(f"/learn/{lang}/{slug}")

    root = Element("urlset", {"xmlns": "http://www.sitemaps.org/schemas/sitemap/0.9"})
    for path in sorted(urls):
        node = SubElement(root, "url")
        SubElement(node, "loc").text = base + path
        if path.startswith("/static/articles/") or path.startswith("/blog/"):
            SubElement(node, "changefreq").text = "monthly"
            SubElement(node, "priority").text = "0.7"
        elif path == "/":
            SubElement(node, "changefreq").text = "daily"
            SubElement(node, "priority").text = "1.0"
        else:
            SubElement(node, "changefreq").text = "weekly"
            SubElement(node, "priority").text = "0.6"

    xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="utf-8")
    return Response(content=xml, media_type="application/xml")


# Multilingual educational content: 25 topics × 5 localized URLs.
router.include_router(multilingual_router)
