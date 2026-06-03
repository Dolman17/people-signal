from html import unescape
from urllib.parse import quote_plus
import re

import feedparser

from app.extensions import db
from app.models import Company, LeadSignal
from app.services.article_fetch_service import extract_article_context
from app.services.company_match_service import (
    find_company_by_name_or_alias,
    add_company_alias,
)
from app.services.google_news_decode_service import decode_google_news_url
from app.services.news_ai_service import extract_news_signal_with_ai
from app.services.ingestion_profile_service import (
    get_profile_or_default,
    get_profile_queries,
)


GOOGLE_NEWS_SEARCHES = [
    {
        "query": '"care home" "CQC" "inadequate" UK',
        "signal_type": "regulatory_concern",
        "confidence_score": 9,
    },
    {
        "query": '"care home" "special measures" "CQC" UK',
        "signal_type": "regulatory_concern",
        "confidence_score": 9,
    },
    {
        "query": '"care home" "requires improvement" "CQC" UK',
        "signal_type": "regulatory_concern",
        "confidence_score": 8,
    },
    {
        "query": '"care provider" "warning notice" "CQC" UK',
        "signal_type": "regulatory_concern",
        "confidence_score": 9,
    },
    {
        "query": '"care home" safeguarding UK',
        "signal_type": "regulatory_concern",
        "confidence_score": 8,
    },
    {
        "query": '"care home" neglect UK',
        "signal_type": "negative_publicity",
        "confidence_score": 8,
    },
    {
        "query": '"care home" "unacceptable conditions" UK',
        "signal_type": "regulatory_concern",
        "confidence_score": 8,
    },
    {
        "query": '"care home" closure UK',
        "signal_type": "restructuring_signal",
        "confidence_score": 7,
    },
    {
        "query": '"care home operator" administration UK',
        "signal_type": "restructuring_signal",
        "confidence_score": 9,
    },
    {
        "query": '"care provider" insolvency UK',
        "signal_type": "restructuring_signal",
        "confidence_score": 9,
    },
    {
        "query": '"nursing home" closure UK',
        "signal_type": "restructuring_signal",
        "confidence_score": 7,
    },
    {
        "query": '"care home" "staff shortage" UK',
        "signal_type": "rapid_hiring",
        "confidence_score": 7,
    },
    {
        "query": '"care provider" "recruitment drive" UK',
        "signal_type": "rapid_hiring",
        "confidence_score": 7,
    },
    {
        "query": '"care home" "up to" "staff" UK',
        "signal_type": "rapid_hiring",
        "confidence_score": 6,
    },
    {
        "query": '"supported living" "staff" UK',
        "signal_type": "rapid_hiring",
        "confidence_score": 6,
    },
    {
        "query": '"new care home" opening UK',
        "signal_type": "rapid_hiring",
        "confidence_score": 7,
    },
    {
        "query": '"care provider" expansion UK',
        "signal_type": "rapid_hiring",
        "confidence_score": 6,
    },
    {
        "query": '"supported living" "planning permission" UK',
        "signal_type": "rapid_hiring",
        "confidence_score": 6,
    },
    {
        "query": '"supported living" "new development" UK',
        "signal_type": "rapid_hiring",
        "confidence_score": 6,
    },
    {
        "query": '"care provider" acquisition UK',
        "signal_type": "restructuring_signal",
        "confidence_score": 7,
    },
    {
        "query": '"care home group" acquisition UK',
        "signal_type": "restructuring_signal",
        "confidence_score": 7,
    },
    {
        "query": '"registered manager" "care home" "resigned" UK',
        "signal_type": "leadership_change",
        "confidence_score": 7,
    },
    {
        "query": '"care provider" "employment tribunal" UK',
        "signal_type": "negative_publicity",
        "confidence_score": 8,
    },
    {
        "query": '"care home" "employment tribunal" UK',
        "signal_type": "negative_publicity",
        "confidence_score": 8,
    },
    {
        "query": '"care provider" whistleblowing UK',
        "signal_type": "negative_publicity",
        "confidence_score": 8,
    },
]


def clean_html_text(value):
    if not value:
        return ""

    value = unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("&nbsp;", " ")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def extract_first_href(value):
    if not value:
        return ""

    value = unescape(value)

    match = re.search(
        r'<a[^>]+href=["\']([^"\']+)["\']',
        value,
        flags=re.IGNORECASE
    )

    if match:
        return match.group(1).strip()

    return ""


def build_google_news_url(query):
    encoded_query = quote_plus(query)

    return (
        "https://news.google.com/rss/search"
        f"?q={encoded_query}"
        "&hl=en-GB"
        "&gl=GB"
        "&ceid=GB:en"
    )


def choose_best_article_url(entry, raw_summary_html):
    summary_href = extract_first_href(raw_summary_html)

    if summary_href:
        return decode_google_news_url(summary_href)

    fallback_link = getattr(entry, "link", "") or ""

    return decode_google_news_url(fallback_link)


def find_or_create_company(company_name, sector_label="Unknown"):
    company_name = company_name or f"Unknown {sector_label} Organisation"

    existing_company = find_company_by_name_or_alias(company_name)

    if existing_company:
        add_company_alias(
            existing_company,
            company_name,
            source="google_news_match",
        )
        return existing_company, False

    company = Company(
        name=company_name[:255],
        sector=sector_label or "Unknown",
        region="Unknown",
        company_size="Unknown"
    )

    db.session.add(company)
    db.session.flush()

    return company, True


def signal_exists(company_id, title, source):
    return LeadSignal.query.filter_by(
        company_id=company_id,
        title=title,
        source=source
    ).first() is not None


def get_google_news_searches_for_profile(profile):
    profile_queries = get_profile_queries(profile, source_type="google_news")

    if profile_queries:
        return [
            {
                "query": profile_query.query,
                "signal_type": profile_query.signal_type,
                "confidence_score": profile_query.confidence_score,
            }
            for profile_query in profile_queries
            if profile_query.query
        ]

    return GOOGLE_NEWS_SEARCHES


def ingest_google_news_signals(limit_per_query=1, source_run_id=None, profile_id=None):
    records_found = 0
    signals_created = 0
    companies_created = 0
    skipped = 0

    profile = get_profile_or_default(profile_id)
    sector_label = profile.sector_label if profile else "Unknown"
    searches = get_google_news_searches_for_profile(profile)

    for search in searches:
        url = build_google_news_url(search["query"])
        feed = feedparser.parse(url)

        entries = feed.entries[:limit_per_query]

        for entry in entries:
            records_found += 1

            raw_title = getattr(entry, "title", "") or "Untitled news item"
            raw_summary_html = getattr(entry, "summary", "") or ""

            title = clean_html_text(raw_title)
            summary = clean_html_text(raw_summary_html)

            article_url = choose_best_article_url(entry, raw_summary_html)
            article_context = extract_article_context(article_url)

            extracted = extract_news_signal_with_ai(
                title=title,
                summary=summary,
                link=article_url,
                default_signal_type=search["signal_type"],
                default_confidence=search["confidence_score"],
                article_context=article_context,
                profile=profile,
            )

            if not extracted.get("should_create_signal"):
                skipped += 1
                continue

            company_name = extracted.get("company_name") or f"Unknown {sector_label} Organisation"

            company, created = find_or_create_company(company_name, sector_label=sector_label)

            if created:
                companies_created += 1

            source = f"Google News RSS - {profile.name}" if profile else "Google News RSS"

            clean_title = clean_html_text(extracted.get("clean_title") or title)

            if signal_exists(company.id, clean_title, source):
                skipped += 1
                continue

            signal_summary = clean_html_text(extracted.get("summary") or summary)
            reason = clean_html_text(extracted.get("reason") or "")
            quality_reason = clean_html_text(extracted.get("quality_reason") or "")

            raw_text = signal_summary

            if reason:
                raw_text = f"{raw_text}\n\nWhy this matters: {reason}"

            if quality_reason:
                raw_text = f"{raw_text}\n\nQuality reason: {quality_reason}"

            if profile:
                raw_text = f"{raw_text}\n\nIngestion profile: {profile.name}"

            if article_url:
                raw_text = f"{raw_text}\n\nSource link: {article_url}"

            signal = LeadSignal(
                company_id=company.id,
                source_run_id=source_run_id,
                signal_type=extracted.get("signal_type") or search["signal_type"],
                source=source,
                title=clean_title,
                raw_text=raw_text,
                confidence_score=extracted.get("confidence_score") or search["confidence_score"],
                review_status="new",
            )

            db.session.add(signal)
            signals_created += 1

    db.session.commit()

    return {
        "records_found": records_found,
        "signals_created": signals_created,
        "companies_created": companies_created,
        "skipped": skipped,
        "profile": profile.name if profile else None,
    }
