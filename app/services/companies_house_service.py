import os
import time
from datetime import datetime, timedelta

import requests

from app.extensions import db
from app.models import Company, LeadSignal
from app.services.company_match_service import (
    find_company_by_name_or_alias,
    add_company_alias,
)


COMPANIES_HOUSE_BASE_URL = "https://api.company-information.service.gov.uk"


CARE_COMPANY_SEARCH_TERMS = [
    "care home",
    "care homes",
    "residential care",
    "nursing home",
    "supported living",
    "homecare",
    "domiciliary care",
    "care services",
    "healthcare services",
]


HIGH_VALUE_FILING_KEYWORDS = [
    "administration",
    "administrator",
    "liquidation",
    "liquidator",
    "insolvency",
    "winding up",
    "strike off",
    "striking off",
    "dissolution",
    "dissolved",
    "voluntary arrangement",
    "receiver",
    "receivership",
    "petition",
    "moratorium",
    "change of name",
    "registered office",
    "termination of appointment",
    "appointment terminated",
    "resignation",
    "cessation",
]


def get_companies_house_api_key():
    key = os.getenv("COMPANIES_HOUSE_API_KEY")
    return key.strip() if key else None


def companies_house_get(path, params=None, max_retries=3):
    api_key = get_companies_house_api_key()

    if not api_key or api_key == "your_companies_house_api_key":
        raise ValueError("COMPANIES_HOUSE_API_KEY is missing or still set to placeholder.")

    url = f"{COMPANIES_HOUSE_BASE_URL}{path}"

    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(
                url,
                params=params or {},
                auth=(api_key, ""),
                timeout=15,
            )

            if response.status_code == 404:
                return None

            if response.status_code in [429, 500, 502, 503, 504]:
                last_error = requests.HTTPError(
                    f"{response.status_code} temporary error for {url}"
                )

                if attempt < max_retries:
                    time.sleep(2 * attempt)
                    continue

            response.raise_for_status()
            return response.json()

        except requests.RequestException as e:
            last_error = e

            if attempt < max_retries:
                time.sleep(2 * attempt)
                continue

    raise last_error


def parse_date(value):
    if not value:
        return None

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


def is_recent_date(value, days=365):
    parsed = parse_date(value)

    if not parsed:
        return False

    cutoff = datetime.utcnow().date() - timedelta(days=days)

    return parsed >= cutoff


def text_contains_any(value, keywords):
    if not value:
        return False

    lowered = value.lower()

    return any(keyword.lower() in lowered for keyword in keywords)


def format_address(address):
    if not address:
        return ""

    parts = [
        address.get("address_line_1"),
        address.get("address_line_2"),
        address.get("locality"),
        address.get("region"),
        address.get("postal_code"),
        address.get("country"),
    ]

    return ", ".join([part for part in parts if part])


def find_or_create_company_from_ch_profile(profile):
    company_number = profile.get("company_number")
    company_name = profile.get("company_name") or "Unknown Company"
    companies_house_ref = f"companies-house:{company_number}"

    existing_by_ch_ref = Company.query.filter_by(website=companies_house_ref).first()

    if existing_by_ch_ref:
        add_company_alias(
            existing_by_ch_ref,
            company_name,
            source="companies_house_profile",
        )
        return existing_by_ch_ref, False

    existing_by_name_or_alias = find_company_by_name_or_alias(company_name)

    if existing_by_name_or_alias:
        if not existing_by_name_or_alias.website:
            existing_by_name_or_alias.website = companies_house_ref

        add_company_alias(
            existing_by_name_or_alias,
            company_name,
            source="companies_house_match",
        )

        return existing_by_name_or_alias, False

    address = profile.get("registered_office_address") or {}

    company = Company(
        name=company_name[:255],
        sector="Care",
        website=companies_house_ref,
        city=address.get("locality"),
        region=address.get("region") or address.get("country") or "Unknown",
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


def create_signal(
    company,
    source_run_id,
    signal_type,
    title,
    raw_text,
    confidence_score,
):
    source = "Companies House"

    if signal_exists(company.id, title, source):
        return False

    signal = LeadSignal(
        company_id=company.id,
        source_run_id=source_run_id,
        signal_type=signal_type,
        source=source,
        title=title,
        raw_text=raw_text,
        confidence_score=confidence_score,
        review_status="new",
    )

    db.session.add(signal)

    return True


def search_companies(term, items_per_page=5):
    data = companies_house_get(
        "/search/companies",
        params={
            "q": term,
            "items_per_page": items_per_page,
        },
    )

    if not data:
        return []

    return data.get("items", []) or []


def get_company_profile(company_number):
    return companies_house_get(f"/company/{company_number}")


def get_company_officers(company_number, items_per_page=10):
    data = companies_house_get(
        f"/company/{company_number}/officers",
        params={
            "items_per_page": items_per_page,
        },
    )

    if not data:
        return []

    return data.get("items", []) or []


def get_company_filing_history(company_number, items_per_page=25):
    data = companies_house_get(
        f"/company/{company_number}/filing-history",
        params={
            "items_per_page": items_per_page,
        },
    )

    if not data:
        return []

    return data.get("items", []) or []


def build_officer_signal_text(profile, officer, event_type):
    company_name = profile.get("company_name") or "Unknown company"
    company_number = profile.get("company_number") or "Unknown"
    company_status = profile.get("company_status") or "Unknown"
    address = format_address(profile.get("registered_office_address"))

    officer_name = officer.get("name") or "Unknown officer"
    officer_role = officer.get("officer_role") or "Unknown role"
    appointed_on = officer.get("appointed_on") or "Unknown"
    resigned_on = officer.get("resigned_on") or ""

    lines = [
        f"{company_name} has a Companies House officer change.",
        "",
        f"Officer: {officer_name}",
        f"Role: {officer_role}",
        f"Appointed on: {appointed_on}",
        f"Company number: {company_number}",
        f"Company status: {company_status}",
    ]

    if resigned_on:
        lines.append(f"Resigned on: {resigned_on}")

    if address:
        lines.append(f"Registered office: {address}")

    lines.append("")
    lines.append(
        "Why this matters: Leadership or officer changes can indicate ownership, governance, "
        "strategic or operational change. For HR consultants, this may create an opportunity "
        "around management alignment, restructuring support, policy/process review or ER risk prevention."
    )

    lines.append("")
    lines.append(f"Quality reason: Companies House {event_type} detected for a care-sector search result.")

    return "\n".join(lines)


def build_status_signal_text(profile):
    company_name = profile.get("company_name") or "Unknown company"
    company_number = profile.get("company_number") or "Unknown"
    company_status = profile.get("company_status") or "Unknown"
    address = format_address(profile.get("registered_office_address"))

    lines = [
        f"{company_name} has a Companies House company status signal.",
        "",
        f"Company number: {company_number}",
        f"Company status: {company_status}",
    ]

    if address:
        lines.append(f"Registered office: {address}")

    lines.append("")
    lines.append(
        "Why this matters: A non-active or distressed company status can indicate restructuring, "
        "closure, insolvency or operational uncertainty. This may create HR needs around consultation, "
        "redundancy, transfer, communications or employee relations."
    )

    lines.append("")
    lines.append("Quality reason: Companies House company status was not active.")

    return "\n".join(lines)


def filing_category_to_signal_type(category, description):
    combined = f"{category or ''} {description or ''}".lower()

    if any(term in combined for term in [
        "administration",
        "liquidation",
        "insolvency",
        "winding up",
        "strike off",
        "dissolution",
        "voluntary arrangement",
        "receiver",
        "petition",
        "moratorium",
    ]):
        return "restructuring_signal", 9

    if any(term in combined for term in [
        "termination of appointment",
        "appointment terminated",
        "resignation",
        "cessation",
    ]):
        return "leadership_change", 7

    if any(term in combined for term in [
        "change of name",
        "registered office",
    ]):
        return "restructuring_signal", 5

    return "restructuring_signal", 5


def build_filing_signal_text(profile, filing):
    company_name = profile.get("company_name") or "Unknown company"
    company_number = profile.get("company_number") or "Unknown"
    company_status = profile.get("company_status") or "Unknown"

    filing_date = filing.get("date") or "Unknown"
    filing_type = filing.get("type") or "Unknown"
    category = filing.get("category") or "Unknown"
    description = filing.get("description") or ""
    description_values = filing.get("description_values") or {}

    address = format_address(profile.get("registered_office_address"))

    lines = [
        f"{company_name} has a Companies House filing history signal.",
        "",
        f"Filing date: {filing_date}",
        f"Filing type: {filing_type}",
        f"Category: {category}",
        f"Description: {description}",
        f"Company number: {company_number}",
        f"Company status: {company_status}",
    ]

    if description_values:
        lines.append("")
        lines.append("Description values:")
        for key, value in description_values.items():
            lines.append(f"- {key}: {value}")

    if address:
        lines.append("")
        lines.append(f"Registered office: {address}")

    lines.append("")
    lines.append(
        "Why this matters: Filing history can reveal structural, leadership, distress or governance changes. "
        "For HR consultants, this may indicate a need for restructuring support, consultation planning, "
        "leadership alignment, communications support or ER risk management."
    )

    lines.append("")
    lines.append("Quality reason: High-value Companies House filing history event detected.")

    return "\n".join(lines)


def filing_is_high_value(filing):
    category = filing.get("category") or ""
    description = filing.get("description") or ""
    filing_type = filing.get("type") or ""

    combined = f"{category} {description} {filing_type}"

    return text_contains_any(combined, HIGH_VALUE_FILING_KEYWORDS)


def ingest_companies_house_signals(
    source_run_id=None,
    search_limit_per_term=5,
    officers_per_company=10,
    filings_per_company=25,
    recent_days=365,
):
    records_found = 0
    signals_created = 0
    companies_created = 0
    skipped = 0

    seen_company_numbers = set()

    for term in CARE_COMPANY_SEARCH_TERMS:
        try:
            search_results = search_companies(
                term,
                items_per_page=search_limit_per_term,
            )
        except Exception:
            skipped += 1
            continue

        for result in search_results:
            company_number = result.get("company_number")

            if not company_number:
                skipped += 1
                continue

            if company_number in seen_company_numbers:
                skipped += 1
                continue

            seen_company_numbers.add(company_number)
            records_found += 1

            try:
                profile = get_company_profile(company_number)
            except Exception:
                skipped += 1
                continue

            if not profile:
                skipped += 1
                continue

            company, created = find_or_create_company_from_ch_profile(profile)

            if created:
                companies_created += 1

            company_name = profile.get("company_name") or company.name
            company_status = profile.get("company_status") or ""

            if company_status and company_status.lower() != "active":
                title = f"{company_name} company status is {company_status}"

                if create_signal(
                    company=company,
                    source_run_id=source_run_id,
                    signal_type="restructuring_signal",
                    title=title,
                    raw_text=build_status_signal_text(profile),
                    confidence_score=8,
                ):
                    signals_created += 1
                else:
                    skipped += 1

            try:
                filings = get_company_filing_history(
                    company_number,
                    items_per_page=filings_per_company,
                )
            except Exception:
                skipped += 1
                filings = []

            for filing in filings:
                filing_date = filing.get("date")

                if not is_recent_date(filing_date, days=recent_days):
                    skipped += 1
                    continue

                if not filing_is_high_value(filing):
                    skipped += 1
                    continue

                category = filing.get("category") or ""
                description = filing.get("description") or ""
                filing_type = filing.get("type") or "filing"

                signal_type, confidence_score = filing_category_to_signal_type(
                    category,
                    description,
                )

                title = f"Companies House filing at {company_name}: {filing_type}"

                if create_signal(
                    company=company,
                    source_run_id=source_run_id,
                    signal_type=signal_type,
                    title=title,
                    raw_text=build_filing_signal_text(profile, filing),
                    confidence_score=confidence_score,
                ):
                    signals_created += 1
                else:
                    skipped += 1

            try:
                officers = get_company_officers(
                    company_number,
                    items_per_page=officers_per_company,
                )
            except Exception:
                skipped += 1
                continue

            for officer in officers:
                officer_name = officer.get("name") or "Unknown officer"
                officer_role = (officer.get("officer_role") or "").lower()

                relevant_roles = [
                    "director",
                    "corporate-director",
                    "llp-designated-member",
                    "member",
                ]

                if officer_role not in relevant_roles:
                    skipped += 1
                    continue

                appointed_on = officer.get("appointed_on")
                resigned_on = officer.get("resigned_on")

                if appointed_on and is_recent_date(appointed_on, days=recent_days):
                    title = f"Recent officer appointment at {company_name}: {officer_name}"

                    if create_signal(
                        company=company,
                        source_run_id=source_run_id,
                        signal_type="leadership_change",
                        title=title,
                        raw_text=build_officer_signal_text(profile, officer, "appointment"),
                        confidence_score=5,
                    ):
                        signals_created += 1
                    else:
                        skipped += 1

                if resigned_on and is_recent_date(resigned_on, days=recent_days):
                    title = f"Recent officer resignation at {company_name}: {officer_name}"

                    if create_signal(
                        company=company,
                        source_run_id=source_run_id,
                        signal_type="leadership_change",
                        title=title,
                        raw_text=build_officer_signal_text(profile, officer, "resignation"),
                        confidence_score=7,
                    ):
                        signals_created += 1
                    else:
                        skipped += 1

    db.session.commit()

    return {
        "records_found": records_found,
        "signals_created": signals_created,
        "companies_created": companies_created,
        "skipped": skipped,
    }