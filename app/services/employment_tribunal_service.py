import re
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests

from app.extensions import db
from app.models import Company, LeadSignal
from app.services.company_match_service import (
    find_company_by_name_or_alias,
    add_company_alias,
)
from app.services.pdf_extract_service import extract_first_pdf_context_from_page


GOVUK_SEARCH_API_URL = "https://www.gov.uk/api/search.json"
GOVUK_BASE_URL = "https://www.gov.uk"


EMPLOYMENT_TRIBUNAL_SEARCHES = [
    {
        "query": '"care home" "unfair dismissal"',
        "confidence_score": 8,
    },
    {
        "query": '"care provider" "employment tribunal"',
        "confidence_score": 8,
    },
    {
        "query": '"supported living" "employment tribunal"',
        "confidence_score": 8,
    },
    {
        "query": '"domiciliary care" "unfair dismissal"',
        "confidence_score": 8,
    },
    {
        "query": '"nursing home" "employment tribunal"',
        "confidence_score": 8,
    },
    {
        "query": '"care home" "discrimination"',
        "confidence_score": 8,
    },
    {
        "query": '"care provider" "constructive dismissal"',
        "confidence_score": 8,
    },
    {
        "query": '"care home" "wages"',
        "confidence_score": 7,
    },
    {
        "query": '"care home" "whistleblowing"',
        "confidence_score": 8,
    },
    {
        "query": '"care assistant" "unfair dismissal"',
        "confidence_score": 7,
    },
]


HIGH_VALUE_TRIBUNAL_TERMS = [
    "unfair dismissal",
    "constructive dismissal",
    "discrimination",
    "whistleblowing",
    "victimisation",
    "harassment",
    "breach of contract",
    "unauthorised deduction",
    "unauthorised deductions",
    "deduction from wages",
    "wages",
    "holiday pay",
    "tupe",
    "redundancy",
    "wrongful dismissal",
    "race discrimination",
    "sex discrimination",
    "age discrimination",
    "disability discrimination",
    "religion or belief discrimination",
    "sexual orientation discrimination",
]


LOW_VALUE_TERMS = [
    "appeal dismissed",
    "case management",
    "withdrawn",
]


GENERIC_RESPONDENT_TERMS = {
    "employment tribunal",
    "et",
    "hmcts",
    "gov.uk",
    "unknown",
    "care home",
    "care provider",
    "supported living",
    "nursing home",
}


def clean_text(value):
    if not value:
        return ""

    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def text_contains_any(value, terms):
    if not value:
        return False

    lowered = value.lower()

    return any(term.lower() in lowered for term in terms)


def normalise_title(value):
    value = clean_text(value)
    value = value.replace(" - GOV.UK", "")
    return value.strip()


def parse_public_timestamp(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def is_recent_public_timestamp(value, days=730):
    parsed = parse_public_timestamp(value)

    if not parsed:
        return True

    cutoff = datetime.utcnow() - timedelta(days=days)

    try:
        parsed_naive = parsed.replace(tzinfo=None)
    except Exception:
        parsed_naive = parsed

    return parsed_naive >= cutoff


def extract_respondent_from_title(title):
    """
    GOV.UK tribunal titles are often formatted like:
    Person v Company Ltd: 1234567/2024
    Person v Company Ltd
    A Smith v Example Care Home Ltd: 1800000/2024
    """

    title = normalise_title(title)

    patterns = [
        r"\bv\s+(.+?)(?:\:|\(|$)",
        r"\bvs\s+(.+?)(?:\:|\(|$)",
        r"\bversus\s+(.+?)(?:\:|\(|$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, title, flags=re.IGNORECASE)

        if match:
            respondent = match.group(1).strip()

            respondent = re.sub(r"\s+\d{4,}.*$", "", respondent)
            respondent = respondent.strip(" -:|,.;()[]{}")

            if respondent and respondent.lower() not in GENERIC_RESPONDENT_TERMS:
                return respondent[:255]

    return "Unknown Care Organisation"


def extract_respondent_from_pdf_text(pdf_text):
    """
    Attempts to extract respondent from tribunal PDF text.
    This is deliberately conservative and only used as a fallback.
    """

    if not pdf_text:
        return "Unknown Care Organisation"

    patterns = [
        r"Claimant\s+(.+?)\s+Respondent\s+(.+?)(?:\s+Heard|\s+Before|\s+JUDGMENT|\s+RESERVED|\s+Employment Judge)",
        r"Between\s+(.+?)\s+and\s+(.+?)(?:\s+Respondent|\s+Heard|\s+Before|\s+JUDGMENT)",
        r"v\s+([A-Z][A-Za-z0-9&'\-,\. ]{3,120})(?:\s+Respondent|\s+Heard|\s+Before|\s+JUDGMENT|\s+\d{4})",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            pdf_text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if not match:
            continue

        if len(match.groups()) >= 2:
            respondent = match.group(2)
        else:
            respondent = match.group(1)

        respondent = clean_text(respondent)
        respondent = respondent.strip(" -:|,.;()[]{}")

        # Remove common headings/noise.
        respondent = re.sub(
            r"\b(respondent|heard at|before|judgment|employment judge)\b.*$",
            "",
            respondent,
            flags=re.IGNORECASE,
        ).strip()

        if (
            respondent
            and len(respondent) >= 4
            and respondent.lower() not in GENERIC_RESPONDENT_TERMS
        ):
            return respondent[:255]

    return "Unknown Care Organisation"


def build_govuk_search_params(query, count=5, start=0):
    return {
        "q": query,
        "count": count,
        "start": start,
        "order": "-public_timestamp",
        "fields": [
            "title",
            "description",
            "link",
            "public_timestamp",
            "content_store_document_type",
        ],
        "filter_content_store_document_type": "employment_tribunal_decision",
    }


def govuk_search(query, count=5, start=0):
    response = requests.get(
        GOVUK_SEARCH_API_URL,
        params=build_govuk_search_params(query, count=count, start=start),
        timeout=20,
    )

    if response.status_code == 422:
        params = build_govuk_search_params(query, count=count, start=start)
        params.pop("filter_content_store_document_type", None)

        response = requests.get(
            GOVUK_SEARCH_API_URL,
            params=params,
            timeout=20,
        )

    response.raise_for_status()

    data = response.json()

    return data.get("results", []) or []


def get_result_link(result):
    link = result.get("link") or ""

    if not link:
        return ""

    return urljoin(GOVUK_BASE_URL, link)


def find_or_create_company(company_name):
    company_name = company_name or "Unknown Care Organisation"

    existing_company = find_company_by_name_or_alias(company_name)

    if existing_company:
        add_company_alias(
            existing_company,
            company_name,
            source="employment_tribunal_match",
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


def signal_exists(company_id, title, source):
    return LeadSignal.query.filter_by(
        company_id=company_id,
        title=title,
        source=source,
    ).first() is not None


def should_create_tribunal_signal(title, description, pdf_text=""):
    combined = f"{title or ''} {description or ''} {pdf_text or ''}"

    if text_contains_any(combined, HIGH_VALUE_TRIBUNAL_TERMS):
        return True

    if text_contains_any(combined, LOW_VALUE_TERMS):
        return False

    return "tribunal" in combined.lower()


def build_signal_raw_text(result, company_name, source_link, pdf_url="", pdf_text=""):
    title = normalise_title(result.get("title") or "Employment tribunal decision")
    description = clean_text(result.get("description") or "")
    public_timestamp = result.get("public_timestamp") or "Unknown"

    lines = [
        description or title,
        "",
        f"Decision date / public timestamp: {public_timestamp}",
        f"Likely respondent: {company_name}",
        "",
        "Why this matters: Employment tribunal decisions can indicate employee relations risk, management capability issues, policy/process weakness, discrimination exposure or dismissal-risk concerns. For HR consultants, this may create an opportunity for preventative ER support, policy review, manager training or employment law advice.",
        "",
        "Quality reason: Employment Tribunal decision found via GOV.UK search for care-sector employment dispute terms.",
    ]

    if source_link:
        lines.append("")
        lines.append(f"Source link: {source_link}")

    if pdf_url:
        lines.append("")
        lines.append(f"PDF link: {pdf_url}")

    if pdf_text:
        lines.append("")
        lines.append("Judgment excerpt:")
        lines.append(pdf_text)

    return "\n".join(lines)


def ingest_employment_tribunal_signals(
    source_run_id=None,
    results_per_query=3,
    recent_days=730,
    extract_pdf_text=True,
    max_pdf_chars=3000,
):
    records_found = 0
    signals_created = 0
    companies_created = 0
    skipped = 0

    seen_links = set()

    for search in EMPLOYMENT_TRIBUNAL_SEARCHES:
        query = search["query"]

        try:
            results = govuk_search(
                query=query,
                count=results_per_query,
                start=0,
            )
        except Exception:
            skipped += 1
            continue

        for result in results:
            records_found += 1

            title = normalise_title(result.get("title") or "Employment tribunal decision")
            description = clean_text(result.get("description") or "")
            source_link = get_result_link(result)

            if source_link and source_link in seen_links:
                skipped += 1
                continue

            if source_link:
                seen_links.add(source_link)

            if not is_recent_public_timestamp(
                result.get("public_timestamp"),
                days=recent_days,
            ):
                skipped += 1
                continue

            pdf_url = ""
            pdf_text = ""

            if extract_pdf_text and source_link:
                pdf_context = extract_first_pdf_context_from_page(
                    page_url=source_link,
                    max_chars=max_pdf_chars,
                )

                pdf_url = pdf_context.get("pdf_url") or ""
                pdf_text = pdf_context.get("pdf_text") or ""

            if not should_create_tribunal_signal(title, description, pdf_text):
                skipped += 1
                continue

            company_name = extract_respondent_from_title(title)

            if company_name == "Unknown Care Organisation" and pdf_text:
                company_name = extract_respondent_from_pdf_text(pdf_text)

            if company_name == "Unknown Care Organisation":
                skipped += 1
                continue

            company, created = find_or_create_company(company_name)

            if created:
                companies_created += 1

            clean_title = f"Employment Tribunal decision involving {company.name}"

            if signal_exists(company.id, clean_title, "Employment Tribunal Decisions"):
                skipped += 1
                continue

            confidence_score = search.get("confidence_score") or 7

            if pdf_text:
                confidence_score = min(10, confidence_score + 1)

            signal = LeadSignal(
                company_id=company.id,
                source_run_id=source_run_id,
                signal_type="negative_publicity",
                source="Employment Tribunal Decisions",
                title=clean_title,
                raw_text=build_signal_raw_text(
                    result=result,
                    company_name=company.name,
                    source_link=source_link,
                    pdf_url=pdf_url,
                    pdf_text=pdf_text,
                ),
                confidence_score=confidence_score,
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