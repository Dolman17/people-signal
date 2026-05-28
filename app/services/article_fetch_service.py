import re
from html import unescape

import requests


def clean_text(value):
    if not value:
        return ""

    value = unescape(value)
    value = re.sub(r"<script[\s\S]*?</script>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("&nbsp;", " ")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def extract_meta_content(html, property_name=None, name=None):
    if not html:
        return ""

    if property_name:
        pattern = (
            r'<meta[^>]+property=["\']'
            + re.escape(property_name)
            + r'["\'][^>]+content=["\']([^"\']+)["\']'
        )

        match = re.search(pattern, html, flags=re.IGNORECASE)

        if match:
            return clean_text(match.group(1))

        pattern_reverse = (
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']'
            + re.escape(property_name)
            + r'["\']'
        )

        match = re.search(pattern_reverse, html, flags=re.IGNORECASE)

        if match:
            return clean_text(match.group(1))

    if name:
        pattern = (
            r'<meta[^>]+name=["\']'
            + re.escape(name)
            + r'["\'][^>]+content=["\']([^"\']+)["\']'
        )

        match = re.search(pattern, html, flags=re.IGNORECASE)

        if match:
            return clean_text(match.group(1))

        pattern_reverse = (
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']'
            + re.escape(name)
            + r'["\']'
        )

        match = re.search(pattern_reverse, html, flags=re.IGNORECASE)

        if match:
            return clean_text(match.group(1))

    return ""


def extract_between_tags(html, tag_name):
    if not html:
        return ""

    pattern = rf"<{tag_name}[^>]*>([\s\S]*?)</{tag_name}>"
    match = re.search(pattern, html, flags=re.IGNORECASE)

    if not match:
        return ""

    return clean_text(match.group(1))


def extract_article_context(url):
    """
    Fetches a news article and extracts a compact context bundle.

    Kept dependency-light: requests + regex only.
    """

    if not url:
        return {
            "final_url": "",
            "page_title": "",
            "meta_title": "",
            "meta_description": "",
            "h1": "",
            "body_preview": "",
        }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122 Safari/537.36"
        )
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=8,
            allow_redirects=True
        )

        if response.status_code >= 400:
            return {
                "final_url": url,
                "page_title": "",
                "meta_title": "",
                "meta_description": "",
                "h1": "",
                "body_preview": "",
            }

        html = response.text or ""

        page_title = extract_between_tags(html, "title")
        h1 = extract_between_tags(html, "h1")

        meta_title = (
            extract_meta_content(html, property_name="og:title")
            or extract_meta_content(html, name="twitter:title")
        )

        meta_description = (
            extract_meta_content(html, property_name="og:description")
            or extract_meta_content(html, name="description")
            or extract_meta_content(html, name="twitter:description")
        )

        body_text = clean_text(html)
        body_preview = body_text[:3500]

        return {
            "final_url": response.url,
            "page_title": page_title,
            "meta_title": meta_title,
            "meta_description": meta_description,
            "h1": h1,
            "body_preview": body_preview,
        }

    except Exception:
        return {
            "final_url": url,
            "page_title": "",
            "meta_title": "",
            "meta_description": "",
            "h1": "",
            "body_preview": "",
        }