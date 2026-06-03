import os
import json
import re

from openai import OpenAI

from app.services.ingestion_profile_service import parse_terms


VALID_SIGNAL_TYPES = {
    "leadership_change",
    "rapid_hiring",
    "regulatory_concern",
    "negative_publicity",
    "restructuring_signal",
}

HIGH_VALUE_TRIGGER_TERMS = [
    "cqc",
    "inadequate",
    "requires improvement",
    "special measures",
    "warning notice",
    "safeguarding",
    "abuse",
    "neglect",
    "inspection",
    "closure",
    "closed",
    "administration",
    "administrator",
    "liquidation",
    "insolvency",
    "redundancy",
    "redundancies",
    "restructure",
    "restructuring",
    "merger",
    "acquisition",
    "takeover",
    "new home",
    "new service",
    "new site",
    "expansion",
    "opening",
    "staffing crisis",
    "staff shortage",
    "recruitment drive",
    "up to 20 staff",
    "job losses",
    "employment tribunal",
    "tribunal",
    "whistleblowing",
    "dismissal",
    "strike",
    "union",
    "manager resigns",
    "registered manager",
]

LOW_VALUE_TRIGGER_TERMS = [
    "charity",
    "fundraising",
    "fundraiser",
    "walking challenge",
    "coffee morning",
    "award",
    "awards",
    "celebrates",
    "celebration",
    "anniversary",
    "birthday",
    "community event",
    "open day",
    "donation",
    "dementia uk",
    "alzheimers society",
    "sponsored walk",
    "bake sale",
    "raffle",
]


def clean_company_name_from_title(title, fallback_name="Unknown Organisation"):
    if not title:
        return fallback_name

    cleaned = re.sub(r"\s+-\s+.*$", "", title).strip()

    stop_phrases = [
        "care home",
        "care provider",
        "supported living",
        "staffing",
        "safeguarding",
        "closure",
        "cqc",
        "uk",
        "staff",
        "residents",
        "watchdog",
        "council",
        "bbc",
        "the guardian",
        "care home professional",
        "homecare insight",
    ]

    for phrase in stop_phrases:
        cleaned = re.sub(
            phrase,
            "",
            cleaned,
            flags=re.IGNORECASE
        ).strip()

    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:|")

    if len(cleaned) < 4:
        return fallback_name

    return cleaned[:255]


def text_contains_any(text, terms):
    if not text:
        return False

    lowered = text.lower()

    return any(term.lower() in lowered for term in terms)


def should_create_signal_fallback(text, high_value_terms=None, low_value_terms=None):
    high_value_terms = high_value_terms or HIGH_VALUE_TRIGGER_TERMS
    low_value_terms = low_value_terms or LOW_VALUE_TRIGGER_TERMS

    has_high_value_trigger = text_contains_any(text, high_value_terms)
    has_low_value_trigger = text_contains_any(text, low_value_terms)

    if has_high_value_trigger:
        return True

    if has_low_value_trigger:
        return False

    return False


def extract_candidate_names(text):
    if not text:
        return []

    candidates = set()

    patterns = [
        r"([A-Z][A-Za-z0-9&'\- ]{2,80})\s+(Care Home|Nursing Home|Residential Home|Supported Living|Care Group|Care Ltd|Healthcare|Care Services|Care Centre)",
        r"(Care Home|Nursing Home|Residential Home|Supported Living|Care Centre)\s+([A-Z][A-Za-z0-9&'\- ]{2,80})",
        r"managed by\s+([A-Z][A-Za-z0-9&'\- \(\)]{2,100})",
        r"operated by\s+([A-Z][A-Za-z0-9&'\- \(\)]{2,100})",
        r"operator\s+([A-Z][A-Za-z0-9&'\- \(\)]{2,100})",
        r"provider\s+([A-Z][A-Za-z0-9&'\- \(\)]{2,100})",
        r"at\s+([A-Z][A-Za-z0-9&'\- ]{2,80})",
        r"by\s+([A-Z][A-Za-z0-9&'\- ]{2,80})",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text):
            groups = [group for group in match.groups() if group]

            if len(groups) == 2:
                if groups[0] in [
                    "Care Home",
                    "Nursing Home",
                    "Residential Home",
                    "Supported Living",
                    "Care Centre",
                ]:
                    candidate = f"{groups[1]} {groups[0]}"
                else:
                    candidate = " ".join(groups)
            else:
                candidate = groups[0]

            candidate = candidate.strip(" .,:;|-/")
            candidate = re.sub(r"\s+", " ", candidate)

            bad_terms = [
                "BBC",
                "Google",
                "News",
                "Council",
                "NHS",
                "CQC",
                "UK",
                "England",
                "Wales",
                "Scotland",
                "The",
                "This",
                "That",
                "By",
                "Published",
                "Updated",
                "Image",
                "Getty Images",
            ]

            if candidate and candidate not in bad_terms and len(candidate) >= 4:
                candidates.add(candidate[:255])

    return sorted(candidates)[:10]


def fallback_extract_news_signal(
    title,
    summary,
    default_signal_type,
    default_confidence,
    article_context=None,
    profile=None,
):
    article_context = article_context or {}
    profile_name = profile.name if profile else "Configured sector"
    fallback_name = f"Unknown {profile.sector_label} Organisation" if profile else "Unknown Organisation"
    high_value_terms = parse_terms(profile.high_value_terms) if profile else HIGH_VALUE_TRIGGER_TERMS
    low_value_terms = parse_terms(profile.low_value_terms) if profile else LOW_VALUE_TRIGGER_TERMS

    combined_text = " ".join(
        [
            title or "",
            summary or "",
            article_context.get("page_title", "") or "",
            article_context.get("meta_title", "") or "",
            article_context.get("meta_description", "") or "",
            article_context.get("h1", "") or "",
            article_context.get("body_preview", "") or "",
        ]
    )

    candidates = extract_candidate_names(combined_text)

    if candidates:
        company_name = candidates[0]
    else:
        company_name = clean_company_name_from_title(title, fallback_name=fallback_name)

    should_create = should_create_signal_fallback(
        combined_text,
        high_value_terms=high_value_terms,
        low_value_terms=low_value_terms,
    )

    reason = (
        f"This news item appears to include a relevant {profile_name} workforce, "
        "regulatory, leadership, restructuring, employee-relations or operational risk trigger."
    )

    return {
        "company_name": company_name,
        "signal_type": default_signal_type,
        "confidence_score": default_confidence if should_create else min(default_confidence, 3),
        "clean_title": title or "Untitled news item",
        "summary": summary or article_context.get("meta_description") or "",
        "reason": reason,
        "should_create_signal": should_create,
        "quality_reason": "Fallback keyword relevance gate applied.",
    }


def _safe_json_loads(content):
    if not content:
        raise ValueError("Empty AI response")

    cleaned = content.strip()

    cleaned = re.sub(r"^```json", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^```", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()

    return json.loads(cleaned)


def normalise_ai_boolean(value):
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() in ["true", "yes", "1"]

    return bool(value)


def extract_news_signal_with_ai(
    title,
    summary,
    link,
    default_signal_type,
    default_confidence,
    article_context=None,
    profile=None,
):
    article_context = article_context or {}
    profile_name = profile.name if profile else "Configured sector"
    sector_label = profile.sector_label if profile else "target sector"
    fallback_name = f"Unknown {sector_label} Organisation"
    high_value_terms = parse_terms(profile.high_value_terms) if profile else HIGH_VALUE_TRIGGER_TERMS
    low_value_terms = parse_terms(profile.low_value_terms) if profile else LOW_VALUE_TRIGGER_TERMS
    profile_prompt = profile.ai_prompt if profile and profile.ai_prompt else (
        "Track UK organisations that may need HR consultancy support. "
        "Create signals only where there is meaningful HR, workforce, leadership, regulatory, restructuring or employee-relations pressure."
    )

    combined_text_for_candidates = " ".join(
        [
            title or "",
            summary or "",
            article_context.get("page_title", "") or "",
            article_context.get("meta_title", "") or "",
            article_context.get("meta_description", "") or "",
            article_context.get("h1", "") or "",
            article_context.get("body_preview", "") or "",
        ]
    )

    candidate_names = extract_candidate_names(combined_text_for_candidates)

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key or api_key == "your_openai_api_key":
        return fallback_extract_news_signal(
            title,
            summary,
            default_signal_type,
            default_confidence,
            article_context=article_context,
            profile=profile,
        )

    client = OpenAI(api_key=api_key)

    prompt = f"""
You are cleaning UK Google News results for an HR risk intelligence platform.

Active ingestion profile: {profile_name}
Sector label: {sector_label}

Profile instructions:
{profile_prompt}

Your tasks:
1. Identify the actual organisation involved.
2. Decide whether this is a commercially useful HR/risk lead signal for the selected profile.
3. Classify the signal type.

Only create a signal if the article includes a meaningful trigger likely to create HR, workforce, leadership, regulatory, restructuring or employee-relations pressure.

HIGH-VALUE trigger terms for this profile include:
{', '.join(high_value_terms) if high_value_terms else 'No specific terms configured'}

LOW-VALUE items to SKIP include:
{', '.join(low_value_terms) if low_value_terms else 'No specific skip terms configured'}

Do NOT use:
- newspaper/publisher name
- BBC
- Google News
- council name, unless the council is the actual employer or organisation in scope
- regulator name, unless the article is genuinely about that regulator as an employer
- generic phrases like "staff", "residents", "unknown" or "organisation"

Google News title:
{title or "No title"}

Google News summary:
{summary or "No summary"}

Article URL:
{link or "No link"}

Final URL:
{article_context.get("final_url") or "Unknown"}

Article page title:
{article_context.get("page_title") or "Unknown"}

Article meta title:
{article_context.get("meta_title") or "Unknown"}

Article meta description:
{article_context.get("meta_description") or "Unknown"}

Article H1:
{article_context.get("h1") or "Unknown"}

Possible organisation-name candidates:
{candidate_names or "No candidates found"}

Article body preview:
{article_context.get("body_preview") or "No article body available"}

Default signal type from search query:
{default_signal_type}

Valid signal types:
- leadership_change
- rapid_hiring
- regulatory_concern
- negative_publicity
- restructuring_signal

Return ONLY valid JSON with these keys:
company_name
signal_type
confidence_score
clean_title
summary
reason
should_create_signal
quality_reason

Rules:
- company_name should be the actual organisation most likely to need HR/people support.
- If several organisations are mentioned, choose the one most likely to need HR/people support.
- If no organisation is identifiable, use "{fallback_name}".
- signal_type must be one of the valid signal types.
- confidence_score must be a number from 1 to 10.
- confidence_score should be lower if company_name is uncertain.
- clean_title should be a concise title for the signal.
- summary should explain what appears to have happened.
- reason should explain why this may matter from an HR, workforce, leadership, regulatory or people-risk perspective.
- should_create_signal must be false for low-value or non-commercially-useful items.
- quality_reason should briefly explain why the item was accepted or rejected.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You convert noisy news results into structured HR risk intelligence signals and reject weak leads.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.1,
        )

        content = response.choices[0].message.content
        data = _safe_json_loads(content)

        signal_type = data.get("signal_type") or default_signal_type

        if signal_type not in VALID_SIGNAL_TYPES:
            signal_type = default_signal_type

        try:
            confidence_score = float(data.get("confidence_score"))
        except (TypeError, ValueError):
            confidence_score = default_confidence

        confidence_score = max(1, min(10, confidence_score))

        should_create_signal = normalise_ai_boolean(data.get("should_create_signal"))

        company_name = data.get("company_name") or fallback_name

        generic_names = {
            "BBC",
            "Google News",
            "CQC",
            "Care Home",
            "Care Provider",
            "Supported Living",
            "Unknown",
            "News",
            "Unknown Care Organisation",
            fallback_name,
        }

        if company_name.strip() in generic_names:
            company_name = fallback_name
            confidence_score = min(confidence_score, 4)
            should_create_signal = False

        combined_text = combined_text_for_candidates.lower()
        has_low_value_trigger = text_contains_any(combined_text, low_value_terms)
        has_high_value_trigger = text_contains_any(combined_text, high_value_terms)

        if has_low_value_trigger and not has_high_value_trigger:
            should_create_signal = False
            confidence_score = min(confidence_score, 3)

        return {
            "company_name": company_name[:255],
            "signal_type": signal_type,
            "confidence_score": confidence_score,
            "clean_title": data.get("clean_title") or title or "Untitled news item",
            "summary": data.get("summary") or summary or article_context.get("meta_description") or "",
            "reason": data.get("reason") or "",
            "should_create_signal": should_create_signal,
            "quality_reason": data.get("quality_reason") or "",
        }

    except Exception:
        return fallback_extract_news_signal(
            title,
            summary,
            default_signal_type,
            default_confidence,
            article_context=article_context,
            profile=profile,
        )
