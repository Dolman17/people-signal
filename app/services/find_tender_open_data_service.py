import io
import re
import zipfile
from datetime import datetime, timedelta
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import requests

from app.extensions import db
from app.models import Company, LeadSignal
from app.services.company_match_service import (
    find_company_by_name_or_alias,
    add_company_alias,
)


CKAN_PACKAGE_SEARCH_URL = "https://ckan.publishing.service.gov.uk/api/action/package_search"
FIND_TENDER_NOTICE_URL = "https://www.find-tender.service.gov.uk/Notice/{notice_id}"
FIND_TENDER_SEARCH_URL = "https://www.find-tender.service.gov.uk/Search/Results?Keyword={keyword}"


FIND_TENDER_SEARCH_TERMS = [
    "HR consultancy",
    "employment law",
    "employee relations",
    "workforce planning",
    "organisational development",
    "leadership training",
    "management training",
    "recruitment support",
    "social care workforce",
    "adult social care workforce",
    "occupational health",
    "mediation",
    "change management",
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
    "leadership training",
    "management training",
    "coaching",
    "training",
    "recruitment",
    "retention",
    "occupational health",
    "absence management",
    "mediation",
    "change management",
    "people strategy",
    "pay and reward",
    "job evaluation",
    "consultancy",
]


PUBLIC_SECTOR_TERMS = [
    "council",
    "local authority",
    "nhs",
    "integrated care board",
    "icb",
    "government",
    "police",
    "fire and rescue",
    "borough",
    "county",
    "city council",
    "district council",
    "combined authority",
    "university",
    "college",
    "public sector",
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
    "buyer",
    "contracting authority",
    "authority",
}


def clean_text(value):
    if not value:
        return ""

    value = re.sub(r"<[^>]+>", " ", str(value))
    value = re.sub(r"&nbsp;", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def text_contains_any(value, terms):
    if not value:
        return False

    lowered = value.lower()

    return any(term.lower() in lowered for term in terms)


def local_name(tag):
    if not tag:
        return ""

    return tag.split("}")[-1].lower()


def all_element_text(root):
    parts = []

    for element in root.iter():
        if element.text and element.text.strip():
            parts.append(element.text.strip())

    return clean_text(" ".join(parts))


def find_first_by_tag_contains(root, tag_terms):
    for element in root.iter():
        tag = local_name(element.tag)

        if any(term.lower() in tag for term in tag_terms):
            text = clean_text(element.text)

            if text:
                return text

    return ""


def find_all_by_tag_contains(root, tag_terms, max_items=8):
    values = []

    for element in root.iter():
        tag = local_name(element.tag)

        if any(term.lower() in tag for term in tag_terms):
            text = clean_text(element.text)

            if text and text not in values:
                values.append(text)

            if len(values) >= max_items:
                break

    return values


def extract_notice_id(root, fallback_text=""):
    candidates = find_all_by_tag_contains(
        root,
        [
            "notice_number",
            "no_doc",
            "noticeidentifier",
            "noticeid",
            "publicationnumber",
            "id",
        ],
        max_items=12,
    )

    combined = " ".join(candidates + [fallback_text or ""])

    patterns = [
        r"\b\d{4}/S\s+\d{3}-\d{6}\b",
        r"\b\d{4}-\d{6}\b",
        r"\bocds-[A-Za-z0-9\-]+\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, combined, flags=re.IGNORECASE)

        if match:
            return match.group(0).strip()

    return ""


def extract_buyer_name(root, fallback_text=""):
    buyer_candidates = find_all_by_tag_contains(
        root,
        [
            "officialname",
            "buyer",
            "contractingbody",
            "organisation",
            "organization",
            "authority",
            "legalname",
            "name",
        ],
        max_items=20,
    )

    for candidate in buyer_candidates:
        candidate = clean_text(candidate)

        if (
            candidate
            and len(candidate) >= 4
            and candidate.lower() not in GENERIC_BUYER_NAMES
            and not candidate.lower().startswith("http")
        ):
            return candidate[:255]

    council_match = re.search(
        r"([A-Z][A-Za-z&'\-,\. ]{3,120}(?:Council|Authority|NHS Trust|Integrated Care Board|ICB|Police|Fire and Rescue Service))",
        fallback_text,
    )

    if council_match:
        return clean_text(council_match.group(1))[:255]

    return "Unknown Public Sector Buyer"


def extract_title(root, fallback_text=""):
    title_candidates = find_all_by_tag_contains(
        root,
        [
            "title",
            "object",
            "contract",
            "name",
        ],
        max_items=12,
    )

    for candidate in title_candidates:
        candidate = clean_text(candidate)

        if (
            candidate
            and len(candidate) >= 8
            and not candidate.lower().startswith("http")
            and not text_contains_any(candidate, ["united kingdom", "official journal"])
        ):
            return candidate[:500]

    return clean_text(fallback_text[:500]) or "Find a Tender opportunity"


def extract_description(root, fallback_text=""):
    description_candidates = find_all_by_tag_contains(
        root,
        [
            "description",
            "short_descr",
            "shortdescription",
            "descr",
            "text",
        ],
        max_items=10,
    )

    combined = clean_text(" ".join(description_candidates))

    if combined:
        return combined[:4000]

    return clean_text(fallback_text[:4000])


def extract_deadline(root, fallback_text=""):
    candidates = find_all_by_tag_contains(
        root,
        [
            "deadline",
            "receipt",
            "date_receipt",
            "tenderperiod",
            "enddate",
            "time_limit",
            "date",
        ],
        max_items=20,
    )

    combined = " ".join(candidates + [fallback_text or ""])

    patterns = [
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{2}/\d{2}/\d{4}\b",
        r"\b\d{2}-\d{2}-\d{4}\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, combined)

        if match:
            return match.group(0)

    return ""


def extract_value(root, fallback_text=""):
    candidates = find_all_by_tag_contains(
        root,
        [
            "value",
            "val_estimated",
            "amount",
            "currency",
        ],
        max_items=20,
    )

    combined = clean_text(" ".join(candidates + [fallback_text or ""]))

    money_match = re.search(
        r"(£\s?\d[\d,\.]+|\bGBP\s?\d[\d,\.]+|\b\d[\d,\.]+\s?GBP\b)",
        combined,
        flags=re.IGNORECASE,
    )

    if money_match:
        return money_match.group(0)

    return ""


def extract_region(root, fallback_text=""):
    candidates = find_all_by_tag_contains(
        root,
        [
            "region",
            "nuts",
            "locality",
            "country",
            "address",
        ],
        max_items=20,
    )

    for candidate in candidates:
        candidate = clean_text(candidate)

        if candidate and len(candidate) >= 3:
            return candidate[:120]

    if "england" in fallback_text.lower():
        return "England"

    if "wales" in fallback_text.lower():
        return "Wales"

    if "scotland" in fallback_text.lower():
        return "Scotland"

    if "northern ireland" in fallback_text.lower():
        return "Northern Ireland"

    return "Unknown"


def get_notice_link(notice_id, title=""):
    if notice_id:
        return FIND_TENDER_NOTICE_URL.format(notice_id=quote_plus(notice_id))

    return FIND_TENDER_SEARCH_URL.format(keyword=quote_plus(title or "Find a Tender"))


def should_create_find_tender_signal(title, description, buyer, full_text):
    combined = f"{title} {description} {buyer} {full_text}"

    has_hr_relevance = text_contains_any(combined, HR_TENDER_TERMS)
    has_public_sector_context = text_contains_any(combined, PUBLIC_SECTOR_TERMS)
    has_social_care_context = text_contains_any(combined, SOCIAL_CARE_TERMS)

    return has_hr_relevance and (has_public_sector_context or has_social_care_context)


def score_find_tender_signal(title, description, buyer, full_text):
    combined = f"{title} {description} {buyer} {full_text}"

    score = 7

    if text_contains_any(combined, ["employment law", "employee relations", "hr consultancy"]):
        score += 1

    if text_contains_any(combined, SOCIAL_CARE_TERMS):
        score += 1

    if text_contains_any(buyer, PUBLIC_SECTOR_TERMS):
        score += 1

    return min(10, score)


def find_or_create_company(company_name, region=None):
    company_name = company_name or "Unknown Public Sector Buyer"

    existing_company = find_company_by_name_or_alias(company_name)

    if existing_company:
        add_company_alias(
            existing_company,
            company_name,
            source="find_tender_match",
        )
        return existing_company, False

    company = Company(
        name=company_name[:255],
        sector="Public Sector",
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


def build_signal_raw_text(
    title,
    description,
    buyer,
    region,
    deadline,
    estimated_value,
    notice_id,
    source_link,
    resource_name,
):
    lines = [
        description or title,
        "",
        f"Buyer: {buyer or 'Unknown'}",
        f"Region: {region or 'Unknown'}",
        "Notice type: Find a Tender open data notice",
        "Status: Open / published data",
        f"Deadline: {deadline or 'Unknown'}",
        f"Estimated value: {estimated_value or 'Unknown'}",
        f"Notice ID: {notice_id or 'Unknown'}",
        f"Open data file: {resource_name or 'Unknown'}",
        "",
        "Why this matters: Find a Tender notices can reveal higher-value public-sector procurement opportunities for HR consultancy, employment law, employee relations, workforce planning, management training, organisational development, recruitment support and social-care workforce projects.",
        "",
        "Quality reason: Find a Tender open data XML notice matched HR, workforce, training, employment law or social-care procurement trigger terms.",
    ]

    if source_link:
        lines.append("")
        lines.append(f"Source link: {source_link}")

    return "\n".join(lines)


def get_recent_find_tender_packages(max_packages=4):
    response = requests.get(
        CKAN_PACKAGE_SEARCH_URL,
        params={
            "q": '"UK Public Procurement Notices"',
            "rows": max_packages,
            "sort": "metadata_modified desc",
        },
        timeout=30,
        headers={
            "User-Agent": "PeopleSignal/1.0",
        },
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("success"):
        return []

    return data.get("result", {}).get("results", []) or []


def parse_resource_date(resource):
    text = " ".join(
        [
            str(resource.get("name") or ""),
            str(resource.get("description") or ""),
            str(resource.get("url") or ""),
            str(resource.get("created") or ""),
            str(resource.get("last_modified") or ""),
        ]
    )

    patterns = [
        r"\b(20\d{2})[-_/](\d{2})[-_/](\d{2})\b",
        r"\b(\d{2})[-_/](\d{2})[-_/](20\d{2})\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if not match:
            continue

        try:
            groups = match.groups()

            if groups[0].startswith("20"):
                return datetime(int(groups[0]), int(groups[1]), int(groups[2]))

            return datetime(int(groups[2]), int(groups[1]), int(groups[0]))

        except Exception:
            continue

    return None


def get_candidate_resources(packages, recent_days=14, max_resources=10):
    cutoff = datetime.utcnow() - timedelta(days=recent_days)
    candidates = []

    for package in packages:
        for resource in package.get("resources", []) or []:
            url = resource.get("url") or ""
            name = resource.get("name") or ""

            if not url:
                continue

            lower_url = url.lower()
            lower_name = name.lower()

            if not (
                lower_url.endswith(".zip")
                or lower_url.endswith(".xml")
                or ".zip" in lower_url
                or ".xml" in lower_url
                or "zip" in lower_name
                or "xml" in lower_name
            ):
                continue

            resource_date = parse_resource_date(resource)

            if resource_date and resource_date < cutoff:
                continue

            candidates.append(
                {
                    "resource": resource,
                    "resource_date": resource_date,
                }
            )

    candidates.sort(
        key=lambda item: item["resource_date"] or datetime.min,
        reverse=True,
    )

    return [item["resource"] for item in candidates[:max_resources]]


def download_resource(resource):
    url = resource.get("url") or ""

    response = requests.get(
        url,
        timeout=60,
        headers={
            "User-Agent": "PeopleSignal/1.0",
        },
    )

    response.raise_for_status()

    return response.content


def iter_xml_documents_from_resource(resource):
    content = download_resource(resource)

    url = (resource.get("url") or "").lower()

    if url.endswith(".zip") or b"PK" in content[:4]:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for file_name in zf.namelist():
                if not file_name.lower().endswith(".xml"):
                    continue

                try:
                    yield file_name, zf.read(file_name)
                except Exception:
                    continue

        return

    yield resource.get("name") or resource.get("url") or "find_tender_notice.xml", content


def parse_find_tender_xml(xml_bytes):
    root = ET.fromstring(xml_bytes)
    full_text = all_element_text(root)

    title = extract_title(root, full_text)
    description = extract_description(root, full_text)
    buyer = extract_buyer_name(root, full_text)
    region = extract_region(root, full_text)
    deadline = extract_deadline(root, full_text)
    estimated_value = extract_value(root, full_text)
    notice_id = extract_notice_id(root, full_text)
    source_link = get_notice_link(notice_id, title)

    return {
        "title": title,
        "description": description,
        "buyer": buyer,
        "region": region,
        "deadline": deadline,
        "estimated_value": estimated_value,
        "notice_id": notice_id,
        "source_link": source_link,
        "full_text": full_text,
    }


def ingest_find_tender_open_data_signals(
    source_run_id=None,
    recent_days=14,
    max_packages=4,
    max_resources=10,
    max_notices=250,
):
    records_found = 0
    signals_created = 0
    companies_created = 0
    skipped = 0

    seen_links = set()

    packages = get_recent_find_tender_packages(max_packages=max_packages)
    resources = get_candidate_resources(
        packages=packages,
        recent_days=recent_days,
        max_resources=max_resources,
    )

    for resource in resources:
        resource_name = resource.get("name") or resource.get("url") or "Find a Tender resource"

        try:
            xml_documents = iter_xml_documents_from_resource(resource)
        except Exception:
            skipped += 1
            continue

        for xml_name, xml_bytes in xml_documents:
            if records_found >= max_notices:
                break

            records_found += 1

            try:
                parsed = parse_find_tender_xml(xml_bytes)
            except Exception:
                skipped += 1
                continue

            title = parsed["title"]
            description = parsed["description"]
            buyer = parsed["buyer"]
            region = parsed["region"]
            deadline = parsed["deadline"]
            estimated_value = parsed["estimated_value"]
            notice_id = parsed["notice_id"]
            source_link = parsed["source_link"]
            full_text = parsed["full_text"]

            if source_link and source_link in seen_links:
                skipped += 1
                continue

            if source_link:
                seen_links.add(source_link)

            if buyer == "Unknown Public Sector Buyer":
                skipped += 1
                continue

            if not should_create_find_tender_signal(
                title=title,
                description=description,
                buyer=buyer,
                full_text=full_text,
            ):
                skipped += 1
                continue

            company, created = find_or_create_company(
                company_name=buyer,
                region=region,
            )

            if created:
                companies_created += 1

            clean_title = f"Find a Tender: {title}"[:500]

            if signal_exists(
                company_id=company.id,
                title=clean_title,
                source="Find a Tender",
                source_link=source_link,
            ):
                skipped += 1
                continue

            signal = LeadSignal(
                company_id=company.id,
                source_run_id=source_run_id,
                signal_type="tender_opportunity",
                source="Find a Tender",
                title=clean_title,
                raw_text=build_signal_raw_text(
                    title=title,
                    description=description,
                    buyer=buyer,
                    region=region,
                    deadline=deadline,
                    estimated_value=estimated_value,
                    notice_id=notice_id,
                    source_link=source_link,
                    resource_name=f"{resource_name} / {xml_name}",
                ),
                confidence_score=score_find_tender_signal(
                    title=title,
                    description=description,
                    buyer=buyer,
                    full_text=full_text,
                ),
                review_status="new",
            )

            db.session.add(signal)
            signals_created += 1

        if records_found >= max_notices:
            break

    db.session.commit()

    return {
        "records_found": records_found,
        "signals_created": signals_created,
        "companies_created": companies_created,
        "skipped": skipped,
        "resources_checked": len(resources),
    }