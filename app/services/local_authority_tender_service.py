import re
from datetime import datetime, timedelta
from urllib.parse import quote_plus

import requests

from app.extensions import db
from app.models import Company, LeadSignal
from app.services.company_match_service import (
    find_company_by_name_or_alias,
    add_company_alias,
)


CONTRACTS_FINDER_SEARCH_URL = "https://www.contractsfinder.service.gov.uk/api/rest/2/search_notices/json"
CONTRACTS_FINDER_NOTICE_URL = "https://www.contractsfinder.service.gov.uk/Notice/{notice_id}"


LOCAL_AUTHORITY_TENDER_SEARCHES = [
    {
        "keyword": "HR consultancy",
        "confidence_score": 8,
    },
    {
        "keyword": "employment law",
        "confidence_score": 8,
    },
    {
        "keyword": "employee relations",
        "confidence_score": 8,
    },
    {
        "keyword": "workforce planning",
        "confidence_score": 7,
    },
    {
        "keyword": "organisational development",
        "confidence_score": 7,
    },
    {
        "keyword": "management training",
        "confidence_score": 7,
    },
    {
        "keyword": "leadership training",
        "confidence_score": 7,
    },
    {
        "keyword": "adult social care workforce",
        "confidence_score": 8,
    },
    {
        "keyword": "social care recruitment",
        "confidence_score": 8,
    },
    {
        "keyword": "HR support",
        "confidence_score": 7,
    },
]


LOCAL_AUTHORITY_TERMS = [
    "council",
    "borough council",
    "city council",
    "county council",
    "district council",
    "metropolitan borough",
    "local authority",
    "combined authority",
    "unitary authority",
    "london borough",
    "municipal",
]


HR_TENDER_TERMS = [
    "hr",
    "human resources",
    "employment law",
    "employee relations",
    "workforce",
    "workforce planning",
    "organisational development",
    "organization development",
    "management training",
    "leadership training",
    "coaching",
    "recruitment",
    "retention",
    "absence management",
    "change management",
    "people strategy",
    "pay and reward",
    "job evaluation",
    "consultancy",
    "training",
]


SOCIAL_CARE_TERMS = [
    "adult social care",
    "children's social care",
    "childrens social care",
    "social care",
    "care provider",
    "care home",
    "supported living",
    "domiciliary care",
    "home care",
    "safeguarding",
]


GENERIC_BUYER_NAMES = {
    "unknown",
    "local authority",
    "council",
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


def parse_contracts_finder_date(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def is_recent_notice(item, recent_days=120):
    published_at = parse_contracts_finder_date(item.get("publishedDate"))

    if not published_at:
        return True

    return published_at >= datetime.utcnow() - timedelta(days=recent_days)


def is_live_or_useful_notice(item):
    status = (item.get("noticeStatus") or "").lower()
    notice_type = (item.get("noticeType") or "").lower()

    if status in ["open", "planning", "published"]:
        return True

    if notice_type in ["contract", "future opportunity", "early engagement"]:
        return True

    return False


def get_notice_link(item):
    notice_id = item.get("id") or item.get("noticeIdentifier")

    if not notice_id:
        keyword = quote_plus(item.get("title") or "")
        return f"https://www.contractsfinder.service.gov.uk/Search/Results?Keyword={keyword}"

    return CONTRACTS_FINDER_NOTICE_URL.format(notice_id=notice_id)


def get_buyer_name(item):
    buyer = clean_text(item.get("organisationName") or "")

    if buyer and buyer.lower() not in GENERIC_BUYER_NAMES:
        return buyer[:255]

    return "Unknown Local Authority"


def find_or_create_company(company_name, region=None):
    company_name = company_name or "Unknown Local Authority"

    existing_company = find_company_by_name_or_alias(company_name)

    if existing_company:
        add_company_alias(
            existing_company,
            company_name,
            source="local_authority_tender_match",
        )
        return existing_company, False

    company = Company(
        name=company_name[:255],
        sector="Local Authority",
        region=region or "Unknown",
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


def should_create_tender_signal(item):
    title = clean_text(item.get("title") or "")
    description = clean_text(item.get("description") or "")
    buyer = clean_text(item.get("organisationName") or "")
    cpv_description = clean_text(item.get("cpvDescription") or "")
    cpv_expanded = clean_text(item.get("cpvDescriptionExpanded") or "")

    combined = f"{title} {description} {buyer} {cpv_description} {cpv_expanded}"

    has_hr_relevance = text_contains_any(combined, HR_TENDER_TERMS)
    has_local_authority_buyer = text_contains_any(buyer, LOCAL_AUTHORITY_TERMS)
    has_social_care_relevance = text_contains_any(combined, SOCIAL_CARE_TERMS)

    # We accept:
    # 1. HR-related notices from local authority buyers
    # 2. Social-care workforce / recruitment / training notices even if the buyer is not explicitly council-named
    return has_hr_relevance and (has_local_authority_buyer or has_social_care_relevance)


def score_tender_signal(search, item):
    score = search.get("confidence_score", 7)

    title = clean_text(item.get("title") or "")
    description = clean_text(item.get("description") or "")
    buyer = clean_text(item.get("organisationName") or "")
    combined = f"{title} {description} {buyer}"

    if text_contains_any(buyer, LOCAL_AUTHORITY_TERMS):
        score += 1

    if text_contains_any(combined, ["employment law", "employee relations", "hr consultancy"]):
        score += 1

    if text_contains_any(combined, SOCIAL_CARE_TERMS):
        score += 1

    if (item.get("noticeStatus") or "").lower() == "open":
        score += 1

    return min(10, score)


def format_money(value):
    if value is None or value == "":
        return "Unknown"

    try:
        return f"£{float(value):,.0f}"
    except Exception:
        return str(value)


def build_contracts_finder_payload(keyword, size=10, recent_days=120):
    published_from = (datetime.utcnow() - timedelta(days=recent_days)).strftime("%Y-%m-%dT00:00:00Z")

    return {
        "searchCriteria": {
            "types": [
                "Contract",
                "FutureOpportunity",
                "EarlyEngagement",
            ],
            "statuses": [
                "Open",
                "Planning",
                "Published",
            ],
            "keyword": keyword,
            "queryString": None,
            "regions": None,
            "postcode": None,
            "radius": 0.0,
            "valueFrom": None,
            "valueTo": None,
            "publishedFrom": published_from,
            "publishedTo": None,
            "deadlineFrom": None,
            "deadlineTo": None,
            "approachMarketFrom": None,
            "approachMarketTo": None,
            "awardedFrom": None,
            "awardedTo": None,
            "isSubcontract": None,
            "suitableForSme": None,
            "suitableForVco": None,
            "awardedToSme": None,
            "awardedToVcse": None,
            "cpvCodes": None,
        },
        "size": size,
    }


def contracts_finder_search(keyword, size=10, recent_days=120):
    payload = build_contracts_finder_payload(
        keyword=keyword,
        size=size,
        recent_days=recent_days,
    )

    response = requests.post(
        CONTRACTS_FINDER_SEARCH_URL,
        json=payload,
        timeout=30,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "PeopleSignal/1.0",
        },
    )

    response.raise_for_status()

    data = response.json()

    notices = []

    for row in data.get("noticeList", []) or []:
        item = row.get("item") or {}

        if item:
            notices.append(item)

    return notices


def build_signal_raw_text(item, source_link):
    title = clean_text(item.get("title") or "Local authority tender opportunity")
    description = clean_text(item.get("description") or "")
    buyer = clean_text(item.get("organisationName") or "Unknown buyer")
    region = clean_text(item.get("regionText") or item.get("region") or "Unknown")
    status = clean_text(item.get("noticeStatus") or "Unknown")
    notice_type = clean_text(item.get("noticeType") or "Unknown")
    published_date = item.get("publishedDate") or "Unknown"
    deadline_date = item.get("deadlineDate") or "Unknown"
    approach_market_date = item.get("approachMarketDate") or "Unknown"
    value_low = format_money(item.get("valueLow"))
    value_high = format_money(item.get("valueHigh"))
    cpv_description = clean_text(item.get("cpvDescription") or "")
    cpv_expanded = clean_text(item.get("cpvDescriptionExpanded") or "")

    lines = [
        description or title,
        "",
        f"Buyer: {buyer}",
        f"Region: {region}",
        f"Notice type: {notice_type}",
        f"Status: {status}",
        f"Published: {published_date}",
        f"Deadline: {deadline_date}",
        f"Approach market date: {approach_market_date}",
        f"Estimated value low: {value_low}",
        f"Estimated value high: {value_high}",
    ]

    if cpv_description:
        lines.append(f"CPV: {cpv_description}")

    if cpv_expanded and cpv_expanded != cpv_description:
        lines.append(f"CPV expanded: {cpv_expanded}")

    lines.extend(
        [
            "",
            "Why this matters: Local authority tender notices can indicate active demand for HR consultancy, employment law, workforce planning, recruitment support, management training or organisational development. These are direct procurement opportunities rather than indirect signals.",
            "",
            "Quality reason: Contracts Finder notice matched HR, employment law, workforce, training or social-care procurement search terms.",
        ]
    )

    if source_link:
        lines.append("")
        lines.append(f"Source link: {source_link}")

    return "\n".join(lines)


def ingest_local_authority_tender_signals(
    source_run_id=None,
    results_per_query=10,
    recent_days=120,
):
    records_found = 0
    signals_created = 0
    companies_created = 0
    skipped = 0

    seen_links = set()

    for search in LOCAL_AUTHORITY_TENDER_SEARCHES:
        keyword = search["keyword"]

        try:
            notices = contracts_finder_search(
                keyword=keyword,
                size=results_per_query,
                recent_days=recent_days,
            )
        except Exception:
            skipped += 1
            continue

        for item in notices:
            records_found += 1

            if not is_recent_notice(item, recent_days=recent_days):
                skipped += 1
                continue

            if not is_live_or_useful_notice(item):
                skipped += 1
                continue

            if not should_create_tender_signal(item):
                skipped += 1
                continue

            source_link = get_notice_link(item)

            if source_link and source_link in seen_links:
                skipped += 1
                continue

            if source_link:
                seen_links.add(source_link)

            buyer_name = get_buyer_name(item)

            if buyer_name == "Unknown Local Authority":
                skipped += 1
                continue

            region = clean_text(item.get("regionText") or item.get("region") or "Unknown")

            company, created = find_or_create_company(
                company_name=buyer_name,
                region=region,
            )

            if created:
                companies_created += 1

            title = clean_text(item.get("title") or "Local authority tender opportunity")
            clean_title = f"Local Authority Tender: {title}"[:500]

            if signal_exists(
                company_id=company.id,
                title=clean_title,
                source="Local Authority Tenders",
                source_link=source_link,
            ):
                skipped += 1
                continue

            signal = LeadSignal(
                company_id=company.id,
                source_run_id=source_run_id,
                signal_type="tender_opportunity",
                source="Local Authority Tenders",
                title=clean_title,
                raw_text=build_signal_raw_text(
                    item=item,
                    source_link=source_link,
                ),
                confidence_score=score_tender_signal(search, item),
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