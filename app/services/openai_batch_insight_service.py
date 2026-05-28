import json
import os
import re
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from app.extensions import db
from app.models import AIInsight, AIBatchJob, LeadSignal


BATCH_DIR = Path("instance") / "openai_batches"
BATCH_DIR.mkdir(parents=True, exist_ok=True)


def _clean_text(value, max_chars=1500):
    if not value:
        return ""

    value = re.sub(r"\s+", " ", value).strip()

    if len(value) > max_chars:
        return value[:max_chars] + "..."

    return value


def _safe_json_loads(content):
    if not content:
        raise ValueError("Empty AI response")

    cleaned = content.strip()
    cleaned = re.sub(r"^```json", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^```", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()

    return json.loads(cleaned)


def _build_signal_messages(signal):
    company = signal.company

    payload = {
        "signal_id": signal.id,
        "company_name": company.name if company else "Unknown company",
        "sector": company.sector if company else None,
        "region": company.region if company else None,
        "signal_type": signal.signal_type,
        "source": signal.source,
        "title": signal.title,
        "confidence_score": signal.confidence_score,
        "raw_text": _clean_text(signal.raw_text),
    }

    return [
        {
            "role": "system",
            "content": (
                "You create structured HR consultancy lead insights from company trigger signals. "
                "Return only valid JSON."
            ),
        },
        {
            "role": "user",
            "content": f"""
Analyse this UK HR consultancy lead signal and return JSON with these exact keys:

summary
urgency_score
likely_hr_need
outreach_angle

Rules:
- urgency_score must be a number from 1 to 10.
- Be commercially useful but cautious.
- Do not invent facts.
- Keep summary concise.
- likely_hr_need should describe probable HR/employment law support need.
- outreach_angle should suggest a practical, non-spammy reason to contact the organisation.

Signal:
{json.dumps(payload, ensure_ascii=False)}
""",
        },
    ]


def _build_batch_line(signal):
    return {
        "custom_id": f"signal-{signal.id}",
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": "gpt-4o-mini",
            "messages": _build_signal_messages(signal),
            "temperature": 0.2,
            "response_format": {
                "type": "json_object"
            },
        },
    }


def _read_file_response_text(file_response):
    """
    Handles different OpenAI SDK response wrappers safely.
    """

    if hasattr(file_response, "text"):
        return file_response.text

    if hasattr(file_response, "content"):
        content = file_response.content

        if isinstance(content, bytes):
            return content.decode("utf-8")

        return str(content)

    if hasattr(file_response, "read"):
        content = file_response.read()

        if isinstance(content, bytes):
            return content.decode("utf-8")

        return str(content)

    return str(file_response)


def create_openai_ai_insight_batch(signals, source_run_id=None):
    """
    Creates an OpenAI Batch API job for signals without AI insights.

    Returns:
        AIBatchJob
    """

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key or api_key == "your_openai_api_key":
        raise ValueError("OPENAI_API_KEY is missing or still set to placeholder.")

    if not signals:
        raise ValueError("No signals supplied for batch processing.")

    client = OpenAI(api_key=api_key)

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    batch_path = BATCH_DIR / f"ai_insights_{timestamp}.jsonl"

    with batch_path.open("w", encoding="utf-8") as f:
        for signal in signals:
            f.write(json.dumps(_build_batch_line(signal), ensure_ascii=False) + "\n")

    with batch_path.open("rb") as batch_file:
        uploaded_file = client.files.create(
            file=batch_file,
            purpose="batch",
        )

    batch = client.batches.create(
        input_file_id=uploaded_file.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
    )

    job = AIBatchJob(
        source_run_id=source_run_id,
        openai_batch_id=batch.id,
        input_file_id=uploaded_file.id,
        status=batch.status or "submitted",
        requested_count=len(signals),
    )

    db.session.add(job)
    db.session.commit()

    return job


def refresh_openai_ai_batch_job(job):
    """
    Refreshes the OpenAI batch status and stores output_file_id when available.
    """

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key or api_key == "your_openai_api_key":
        raise ValueError("OPENAI_API_KEY is missing or still set to placeholder.")

    client = OpenAI(api_key=api_key)

    batch = client.batches.retrieve(job.openai_batch_id)

    job.status = batch.status or job.status
    job.output_file_id = getattr(batch, "output_file_id", None) or job.output_file_id

    if job.status in ["completed", "failed", "expired", "cancelled"]:
        job.completed_at = datetime.utcnow()

    if job.status in ["failed", "expired", "cancelled"]:
        job.error_message = f"OpenAI batch ended with status: {job.status}"

    db.session.commit()

    return job


def import_completed_openai_ai_batch_job(job):
    """
    Imports completed OpenAI batch results and creates AIInsight records.

    Safe to rerun: skips signals that already have an insight.
    """

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key or api_key == "your_openai_api_key":
        raise ValueError("OPENAI_API_KEY is missing or still set to placeholder.")

    client = OpenAI(api_key=api_key)

    job = refresh_openai_ai_batch_job(job)

    if job.status != "completed":
        return {
            "status": job.status,
            "processed_count": 0,
            "insights_created": 0,
        }

    if not job.output_file_id:
        raise ValueError("Batch completed but no output_file_id was available.")

    file_response = client.files.content(job.output_file_id)
    raw_output = _read_file_response_text(file_response)

    processed_count = 0
    insights_created = 0

    for line in raw_output.splitlines():
        if not line.strip():
            continue

        processed_count += 1
        row = json.loads(line)

        custom_id = row.get("custom_id", "")

        if not custom_id.startswith("signal-"):
            continue

        try:
            signal_id = int(custom_id.replace("signal-", ""))
        except ValueError:
            continue

        existing = AIInsight.query.filter_by(signal_id=signal_id).first()

        if existing:
            continue

        response = row.get("response") or {}
        body = response.get("body") or {}
        choices = body.get("choices") or []

        if not choices:
            continue

        content = (
            choices[0]
            .get("message", {})
            .get("content", "")
        )

        try:
            insight_data = _safe_json_loads(content)
        except Exception:
            continue

        signal = LeadSignal.query.get(signal_id)

        if not signal:
            continue

        try:
            urgency_score = float(insight_data.get("urgency_score") or 5)
        except (TypeError, ValueError):
            urgency_score = 5

        urgency_score = max(1, min(10, urgency_score))

        insight = AIInsight(
            company_id=signal.company_id,
            signal_id=signal.id,
            summary=insight_data.get("summary") or "",
            urgency_score=urgency_score,
            likely_hr_need=insight_data.get("likely_hr_need") or "",
            outreach_angle=insight_data.get("outreach_angle") or "",
        )

        db.session.add(insight)
        insights_created += 1

    job.processed_count = processed_count
    job.insights_created = job.insights_created + insights_created
    job.status = "imported"
    job.completed_at = datetime.utcnow()

    db.session.commit()

    return {
        "status": job.status,
        "processed_count": processed_count,
        "insights_created": insights_created,
    }