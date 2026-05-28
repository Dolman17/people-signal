import os
import json

from openai import OpenAI

from app.services.scoring_service import calculate_base_urgency, infer_likely_hr_need


def _fallback_insight(signal):
    """
    Safe fallback if OpenAI is unavailable or no API key is configured.
    """

    urgency_score = calculate_base_urgency(signal)
    likely_need = infer_likely_hr_need(signal)

    summary = (
        f"{signal.company.name} has been flagged due to a "
        f"{signal.signal_type.replace('_', ' ')} signal. "
        f"This may indicate people-related operational pressure."
    )

    outreach_angle = (
        f"Position outreach around {likely_need.lower()} in response to the detected signal."
    )

    return {
        "summary": summary,
        "urgency_score": urgency_score,
        "likely_hr_need": likely_need,
        "outreach_angle": outreach_angle,
    }


def generate_ai_insight_for_signal(signal):
    """
    Generates a structured AI insight from a LeadSignal.

    Returns:
        dict with:
        - summary
        - urgency_score
        - likely_hr_need
        - outreach_angle
    """

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key or api_key == "your_openai_api_key":
        return _fallback_insight(signal)

    client = OpenAI(api_key=api_key)

    prompt = f"""
You are an HR operations intelligence analyst.

Analyse the following signal for a UK care-sector organisation.

Company:
{signal.company.name}

Sector:
{signal.company.sector or "Unknown"}

Region:
{signal.company.region or "Unknown"}

Signal type:
{signal.signal_type}

Source:
{signal.source or "Unknown"}

Signal title:
{signal.title or "No title"}

Raw signal text:
{signal.raw_text or "No raw text provided"}

Confidence score:
{signal.confidence_score or "Unknown"}

Return ONLY valid JSON with these keys:
summary
urgency_score
likely_hr_need
outreach_angle

Rules:
- urgency_score must be a number from 1 to 10.
- summary must explain why this matters from an HR/people-risk perspective.
- likely_hr_need must describe the likely HR consultancy service required.
- outreach_angle must be professional, insight-led and non-spammy.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You produce concise, structured HR risk intelligence for consultants.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.3,
        )

        content = response.choices[0].message.content

        data = json.loads(content)

        return {
            "summary": data.get("summary") or _fallback_insight(signal)["summary"],
            "urgency_score": float(data.get("urgency_score") or calculate_base_urgency(signal)),
            "likely_hr_need": data.get("likely_hr_need") or infer_likely_hr_need(signal),
            "outreach_angle": data.get("outreach_angle") or _fallback_insight(signal)["outreach_angle"],
        }

    except Exception:
        return _fallback_insight(signal)