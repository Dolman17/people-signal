from urllib.parse import urlparse

try:
    from googlenewsdecoder import gnewsdecoder
except Exception:
    gnewsdecoder = None


def is_google_news_url(url):
    if not url:
        return False

    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return "news.google.com" in host
    except Exception:
        return False


def decode_google_news_url(url):
    """
    Attempts to decode Google News RSS URLs into the original publisher URL.

    Falls back to the original URL if decoding fails.
    """

    if not url:
        return ""

    if not is_google_news_url(url):
        return url

    if gnewsdecoder is None:
        return url

    try:
        result = gnewsdecoder(url)

        if isinstance(result, dict):
            decoded_url = (
                result.get("decoded_url")
                or result.get("url")
                or result.get("source_url")
            )

            if decoded_url:
                return decoded_url

        if isinstance(result, str) and result.startswith("http"):
            return result

    except Exception:
        return url

    return url