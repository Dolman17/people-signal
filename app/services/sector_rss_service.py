import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

import feedparser

from app.extensions import db
from app.models import Company, LeadSignal
from app.services.company_match_service import (
    find_company_by_name_or_alias,
    add_company_alias,
)


SECTOR_RSS_FEEDS = [
    {
        "name": "Care England News",
        "url": "https://www.careengland.org.uk/category/news/feed/",
        "default_confidence": 6,
    },
    {
        "name": "Care Home Professional",
        "url": "https://www.carehomeprofessional.com/feed/",
        "default_confidence": 6,
    },
    {
        "name": "Home Care Insight",
        "url": "https://www.homecareinsight.co.uk/feed/",
        "default_confidence": 6,
    },
    {
        "name": "NHS England Digital RSS",
        "url": "https://digital.nhs.uk/feed/news",
        "default_confidence": 5,
    },
]


HIGH_VALUE_TERMS = [
    "cqc",
    "inadequate",
    "requires improvement",
    "special measures",
    "safeguarding",
    "closure",
    "closed",
    "administration",
    "administrator",
    "insolvency",
    "liquidation",
    "tribunal",
    "unfair dismissal",
    "constructive dismissal",
    "whistleblowing",
    "discrimination",
    "wages",
    "holiday pay",
    "tupe",
    "redundancy",
    "workforce",
    "recruitment",
    "retention",
    "staffing",
    "agency staff",
    "funding",
    "adult social care",
    "care home",
    "care homes",
    "supported living",
    "domiciliary care",
    "homecare",
    "nursing home",
    "care provider",
]


CARE_CONTEXT_TERMS = [
    "care home",
    "care homes",
    "adult social care",
    "social care",
    "supported living",
    "domiciliary care",
    "homecare",
    "nursing home",
    "care provider",
    "care providers",
    "residential care",
    "cqc",
]


NEGATIVE_TERMS = [
    "inadequate",
    "requires improvement",
    "special measures",
    "safeguarding",
    "closure",
    "closed",
    "administration",
    "insolvency",
    "liquidation",
    "tribunal",
    "unfair dismissal",
    "discrimination",
    "whistleblowing",
]


WORKFORCE_TERMS = [
    "workforce",
    "recruitment",
    "retention",
    "staffing",
    "vacancies",
    "agency staff",
    "pay",
    "wages",
    "training",
]


GENERIC_COMPANY_NAMES = {
    "care home",
    "care homes",
    "care provider",
    "care providers",
    "adult social care",
    "social care",
    "supported living",
    "domiciliary care",
    "homecare",
    "nursing home",
    "unknown",
}


def clean_text(value):
    if not value:
        return ""

    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"&nbsp;", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def text_contains_any(value, terms):
    if not value:
        return False

    lowered = value.lower()

    return any(term.lower() in lowered for term in terms)


def parse_entry_date(entry):
    if getattr(entry, "published_parsed", None):
        try:
            return datetime(*entry.published_parsed[:6])
        except Exception:
            return None

    if getattr(entry, "updated_parsed", None):
        try:
            return datetime(*entry.updated_parsed[:6])
        except Exception:
            return None

    return None


def is_recent_entry(entry, recent_days=90):
    parsed = parse_entry_date(entry)

    if not parsed:
        return True

    cutoff = datetime.utcnow() - timedelta(days=recent_days)

    return parsed >= cutoff


def get_entry_link(entry):
    return getattr(entry, "link", "") or ""


def get_domain_from_link(link):
    if not link:
        return ""

    try:
        parsed = urlparse(link)
        return parsed.netloc.replace("www.", "")
    except Exception:
        return ""


def classify_signal_type(title, summary):
    combined = f"{title or ''} {summary or ''}".lower()

    if text_contains_any(combined, NEGATIVE_TERMS):
        return "negative_publicity"

    if text_contains_any(combined, WORKFORCE_TERMS):
        return "workforce_signal"

    if "cqc" in combined or "regulator" in combined or "inspection" in combined:
        return "regulatory_signal"

    return "sector_news"


def score_signal(feed, title, summary):
    score = feed.get("default_confidence", 5)
    combined = f"{title or ''} {summary or ''}".lower()

    if text_contains_any(combined, NEGATIVE_TERMS):
        score += 2

    if text_contains_any(combined, ["cqc", "inadequate", "special measures", "safeguarding"]):
        score += 1

    if text_contains_any(combined, ["administration", "insolvency", "liquidation"]):
        score += 1

    return min(10, score)


def extract_likely_company_name(title, summary):
    """
    Conservative extraction from RSS titles.
    Uses quoted names or title prefixes where possible.
    """

    combined = clean_text(f"{title or ''} {summary or ''}")

    quoted_match = re.search(r"[\"“](.+?)[\"”]", combined)

    if quoted_match:
        candidate = quoted_match.group(1).strip(" -:|,.;()[]{}")

        if candidate and candidate.lower() not in GENERIC_COMPANY_NAMES:
            return candidate[:255]

    patterns = [
        r"^([A-Z][A-Za-z0-9&'\-,\. ]{3,120})\s+(?:secures|appoints|opens|closes|enters|wins|faces|announces|launches|acquires|sold|backs|expands)",
        r"^([A-Z][A-Za-z0-9&'\-,\. ]{3,120})\s*:",
        r"(?:at|by|from|for)\s+([A-Z][A-Za-z0-9&'\-,\. ]{3,120})(?:\s+care home|\s+care group|\s+limited|\s+ltd|\s+group|\s+home|\s+service|\.|,|$)",
        r"([A-Z][A-Za-z0-9&'\-,\. ]{3,120})\s+(?:Care Home|Care Group|Healthcare|Health Care|Homecare|Home Care|Supported Living|Ltd|Limited)",
    ]

    for pattern in patterns:
        match = re.search(pattern, combined)

        if not match:
            continue

        candidate = clean_text(match.group(1))
        candidate = candidate.strip(" -:|,.;()[]{}")

        if (
            candidate
            and len(candidate) >= 4
            and candidate.lower() not in GENERIC_COMPANY_NAMES
        ):
            return candidate[:255]

    return "Unknown Care Organisation"


def find_or_create_company(company_name):
    company_name = company_name or "Unknown Care Organisation"

    existing_company = find_company_by_name_or_alias(company_name)

    if existing_company:
        add_company_alias(
            existing_company,
            company_name,
            source="sector_rss_match",
        )
        return existing_company, False

    company = Company(
        name=company_name[:255],
        sector="Care",
        region="Unknown",
        company_size="Unknown",
    )

    db.session.add(company)
    db.session.flush()

    return company, True


def signal_exists(company_id, title, source, source_link):
    existing = (
        LeadSignal.query
        .filter_by(
            company_id=company_id,
            title=title,
            source=source,
        )
        .first()
    )

    if existing:
        return True

    if source_link:
        linked = (
            LeadSignal.query
            .filter(
                LeadSignal.source == source,
                LeadSignal.raw_text.contains(source_link),
            )
            .first()
        )

        if linked:
            return True

    return False


def should_create_sector_rss_signal(title, summary):
    combined = f"{title or ''} {summary or ''}"

    has_high_value_term = text_contains_any(combined, HIGH_VALUE_TERMS)
    has_care_context = text_contains_any(combined, CARE_CONTEXT_TERMS)

    return has_high_value_term and has_care_context


def build_signal_raw_text(feed_name, title, summary, source_link, published_at):
    lines = [
        summary or title,
        "",
        f"Feed: {feed_name}",
        f"Published: {published_at or 'Unknown'}",
        "",
        "Why this matters: Sector RSS items can reveal care-sector operating pressure, regulatory risk, workforce issues, funding changes, reputational triggers or leadership activity. For HR consultants, this may create an opportunity for ER advice, workforce planning, manager training, policy review or compliance support.",
        "",
        "Quality reason: Sector-specific RSS item matched care-sector and HR/regulatory trigger keywords.",
    ]

    if source_link:
        lines.append("")
        lines.append(f"Source link: {source_link}")

    return "\n".join(lines)


def ingest_sector_rss_signals(
    source_run_id=None,
    entries_per_feed=10,
    recent_days=90,
):
    records_found = 0
    signals_created = 0
    companies_created = 0
    skipped = 0

    seen_links = set()

    for feed in SECTOR_RSS_FEEDS:
        feed_name = feed["name"]
        feed_url = feed["url"]

        try:
            parsed = feedparser.parse(feed_url)
        except Exception:
            skipped += 1
            continue

        if getattr(parsed, "bozo", False) and not getattr(parsed, "entries", []):
            skipped += 1
            continue

        entries = getattr(parsed, "entries", []) or []

        for entry in entries[:entries_per_feed]:
            records_found += 1

            title = clean_text(getattr(entry, "title", "") or "Sector RSS item")
            summary = clean_text(
                getattr(entry, "summary", "")
                or getattr(entry, "description", "")
                or ""
            )
            source_link = get_entry_link(entry)

            if source_link and source_link in seen_links:
                skipped += 1
                continue

            if source_link:
                seen_links.add(source_link)

            if not is_recent_entry(entry, recent_days=recent_days):
                skipped += 1
                continue

            if not should_create_sector_rss_signal(title, summary):
                skipped += 1
                continue

            company_name = extract_likely_company_name(title, summary)
            company, created = find_or_create_company(company_name)

            if created:
                companies_created += 1

            signal_type = classify_signal_type(title, summary)
            clean_title = f"{feed_name}: {title}"

            if signal_exists(
                company_id=company.id,
                title=clean_title,
                source="Sector RSS",
                source_link=source_link,
            ):
                skipped += 1
                continue

            published_at = parse_entry_date(entry)
            published_display = published_at.isoformat() if published_at else ""

            signal = LeadSignal(
                company_id=company.id,
                source_run_id=source_run_id,
                signal_type=signal_type,
                source="Sector RSS",
                title=clean_title[:500],
                raw_text=build_signal_raw_text(
                    feed_name=feed_name,
                    title=title,
                    summary=summary,
                    source_link=source_link,
                    published_at=published_display,
                ),
                confidence_score=score_signal(feed, title, summary),
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
    }