import re

from app.extensions import db
from app.models import IngestionProfile, IngestionProfileQuery


def slugify(value):
    value = (value or "profile").lower().strip()
    value = re.sub(r"[^a-z0-9\s-]", "", value)
    value = re.sub(r"[\s-]+", "-", value)
    return value.strip("-") or "profile"


def get_default_ingestion_profile():
    profile = (
        IngestionProfile.query
        .filter_by(is_active=True, is_default=True)
        .order_by(IngestionProfile.id.asc())
        .first()
    )

    if profile:
        return profile

    return (
        IngestionProfile.query
        .filter_by(is_active=True)
        .order_by(IngestionProfile.id.asc())
        .first()
    )


def get_active_ingestion_profiles():
    return (
        IngestionProfile.query
        .filter_by(is_active=True)
        .order_by(IngestionProfile.is_default.desc(), IngestionProfile.name.asc())
        .all()
    )


def get_profile_or_default(profile_id=None):
    if profile_id:
        profile = IngestionProfile.query.filter_by(id=profile_id, is_active=True).first()
        if profile:
            return profile

    return get_default_ingestion_profile()


def parse_terms(value):
    if not value:
        return []

    terms = []

    for line in value.replace(",", "\n").splitlines():
        term = line.strip()
        if term:
            terms.append(term)

    return terms


def get_profile_queries(profile, source_type="google_news"):
    if not profile:
        return []

    return (
        IngestionProfileQuery.query
        .filter_by(
            profile_id=profile.id,
            source_type=source_type,
            is_active=True,
        )
        .order_by(IngestionProfileQuery.id.asc())
        .all()
    )


def create_profile_query(profile, source_type, query, signal_type, confidence_score, feed_url=None):
    profile_query = IngestionProfileQuery(
        profile_id=profile.id,
        source_type=source_type,
        query=query,
        feed_url=feed_url,
        signal_type=signal_type,
        confidence_score=confidence_score,
        is_active=True,
    )

    db.session.add(profile_query)
    db.session.commit()

    return profile_query
