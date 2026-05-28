def calculate_base_urgency(signal):
    """
    Simple weighted scoring for V1.
    This gives us a useful baseline before AI refinement.
    """

    signal_weights = {
        "regulatory_concern": 8,
        "negative_publicity": 7,
        "restructuring_signal": 6,
        "leadership_change": 5,
        "rapid_hiring": 4,
    }

    base_score = signal_weights.get(signal.signal_type, 3)

    confidence = signal.confidence_score or 0

    if confidence >= 8:
        base_score += 1
    elif confidence <= 3:
        base_score -= 1

    return max(1, min(10, base_score))


def infer_likely_hr_need(signal):
    """
    Non-AI fallback logic.
    Useful for testing and for when no OpenAI key is available.
    """

    needs = {
        "regulatory_concern": "Regulatory response, ER process review, manager capability support",
        "negative_publicity": "Investigation support, culture review, leadership coaching",
        "restructuring_signal": "Change management, consultation support, communications planning",
        "leadership_change": "Manager transition support, leadership alignment, HR process review",
        "rapid_hiring": "Onboarding, manager training, policy/process support",
    }

    return needs.get(signal.signal_type, "General HR advisory support")