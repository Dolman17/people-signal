import os
import re

import requests

from app.models import AIInsight


class TheHiveExportError(Exception):
    pass


def clean_text(value):
    if not value:
        return ""

    value = re.sub(r"<[^>]+>", " ", str(value))
    value = re.sub(r"&nbsp;", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def extract_source_url(raw_text):
    if not raw_text:
        return ""

    markers = [
        "Source link:",
        "PDF link:",
    ]

    for marker in markers:
        if marker not in raw_text:
            continue

        value = raw_text.split(marker, 1)[1].strip()
        first_line = value.splitlines()[0].strip() if value else ""

        if first_line.startswith("http"):
            return first_line

    url_match = re.search(r"https?://\S+", raw_text)

    if url_match:
        return url_match.group(0).strip().rstrip(".,)")

    return ""


def first_present_line(raw_text, label):
    if not raw_text or label not in raw_text:
        return ""

    value = raw_text.split(label, 1)[1].strip()

    return value.splitlines()[0].strip() if value else ""


def build_summary(signal, insight=None):
    raw_text = signal.raw_text or ""

    if insight and insight.summary:
        return clean_text(insight.summary)

    if "Why this matters:" in raw_text:
        before_why = raw_text.split("Why this matters:", 1)[0].strip()
        if before_why:
            return clean_text(before_why[:1200])

    return clean_text(raw_text[:1200] or signal.title or "PeopleSignal lead")


def build_payload(signal):
    insight = AIInsight.query.filter_by(signal_id=signal.id).first()
    raw_text = signal.raw_text or ""

    likely_hr_need = ""
    outreach_angle = ""
    urgency_score = None

    if insight:
        likely_hr_need = insight.likely_hr_need or ""
        outreach_angle = insight.outreach_angle or ""
        urgency_score = insight.urgency_score

    if not likely_hr_need:
        likely_hr_need = first_present_line(raw_text, "Why this matters:") or signal.signal_type or "HR support opportunity"

    return {
        "external_signal_id": signal.id,
        "company_name": signal.company.name if signal.company else "Unknown organisation",
        "source": "PeopleSignal",
        "signal_source": signal.source,
        "signal_type": signal.signal_type,
        "title": signal.title,
        "summary": build_summary(signal, insight),
        "confidence_score": signal.confidence_score,
        "urgency_score": urgency_score,
        "likely_hr_need": likely_hr_need,
        "outreach_angle": outreach_angle,
        "source_url": extract_source_url(raw_text),
        "raw_text": raw_text,
        "detected_at": signal.detected_at.isoformat() if signal.detected_at else None,
    }


def send_signal_to_the_hive(signal):
    api_url = os.getenv("THE_HIVE_API_URL", "").strip()
    api_token = os.getenv("THE_HIVE_API_TOKEN", "").strip()

    if not api_url:
        raise TheHiveExportError("THE_HIVE_API_URL is not configured.")

    if not api_token:
        raise TheHiveExportError("THE_HIVE_API_TOKEN is not configured.")

    payload = build_payload(signal)

    response = requests.post(
        api_url,
        json=payload,
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "User-Agent": "PeopleSignal/1.0",
        },
        timeout=30,
    )

    try:
        response_data = response.json()
    except ValueError:
        response_data = {"error": response.text}

    if response.status_code not in [200, 201]:
        error_message = response_data.get("error") or response_data.get("message") or response.text
        raise TheHiveExportError(f"The Hive import failed: {error_message}")

    return response_data
