from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.extensions import db
from app.models import IngestionProfile, IngestionProfileQuery
from app.services.ingestion_profile_service import slugify


admin_profiles_bp = Blueprint(
    "admin_profiles",
    __name__,
    url_prefix="/admin/ingestion-profiles"
)


VALID_SOURCE_TYPES = [
    "google_news",
    "rss",
    "tender",
    "tribunal",
    "companies_house",
]


VALID_SIGNAL_TYPES = [
    "leadership_change",
    "rapid_hiring",
    "regulatory_concern",
    "negative_publicity",
    "restructuring_signal",
]


def user_is_admin():
    return (
        current_user.is_authenticated
        and current_user.role in ["admin", "superuser"]
    )


@admin_profiles_bp.route("/", methods=["GET"])
@login_required
def list_profiles():
    if not user_is_admin():
        return "Forbidden", 403

    profiles = (
        IngestionProfile.query
        .order_by(IngestionProfile.is_default.desc(), IngestionProfile.name.asc())
        .all()
    )

    return render_template(
        "admin/ingestion_profiles.html",
        profiles=profiles,
        valid_source_types=VALID_SOURCE_TYPES,
        valid_signal_types=VALID_SIGNAL_TYPES,
    )


@admin_profiles_bp.route("/create", methods=["POST"])
@login_required
def create_profile():
    if not user_is_admin():
        return "Forbidden", 403

    name = request.form.get("name", "").strip()
    sector_label = request.form.get("sector_label", "").strip() or name
    description = request.form.get("description", "").strip()
    ai_prompt = request.form.get("ai_prompt", "").strip()
    high_value_terms = request.form.get("high_value_terms", "").strip()
    low_value_terms = request.form.get("low_value_terms", "").strip()

    if not name:
        flash("Profile name is required.", "error")
        return redirect(url_for("admin_profiles.list_profiles"))

    base_slug = slugify(name)
    slug = base_slug
    counter = 2

    while IngestionProfile.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    profile = IngestionProfile(
        name=name,
        slug=slug,
        sector_label=sector_label,
        description=description,
        ai_prompt=ai_prompt,
        high_value_terms=high_value_terms,
        low_value_terms=low_value_terms,
        is_active=True,
        is_default=False,
    )

    db.session.add(profile)
    db.session.commit()

    flash(f"Ingestion profile '{profile.name}' created.", "success")

    return redirect(url_for("admin_profiles.list_profiles"))


@admin_profiles_bp.route("/<int:profile_id>/update", methods=["POST"])
@login_required
def update_profile(profile_id):
    if not user_is_admin():
        return "Forbidden", 403

    profile = IngestionProfile.query.get_or_404(profile_id)

    profile.name = request.form.get("name", "").strip() or profile.name
    profile.sector_label = request.form.get("sector_label", "").strip() or profile.sector_label
    profile.description = request.form.get("description", "").strip()
    profile.ai_prompt = request.form.get("ai_prompt", "").strip()
    profile.high_value_terms = request.form.get("high_value_terms", "").strip()
    profile.low_value_terms = request.form.get("low_value_terms", "").strip()
    profile.is_active = request.form.get("is_active") == "on"

    if request.form.get("is_default") == "on":
        IngestionProfile.query.update({"is_default": False})
        profile.is_default = True

    db.session.commit()

    flash(f"Ingestion profile '{profile.name}' updated.", "success")

    return redirect(url_for("admin_profiles.list_profiles"))


@admin_profiles_bp.route("/<int:profile_id>/queries/create", methods=["POST"])
@login_required
def create_profile_query(profile_id):
    if not user_is_admin():
        return "Forbidden", 403

    profile = IngestionProfile.query.get_or_404(profile_id)

    source_type = request.form.get("source_type", "google_news").strip()
    query = request.form.get("query", "").strip()
    feed_url = request.form.get("feed_url", "").strip()
    signal_type = request.form.get("signal_type", "negative_publicity").strip()

    try:
        confidence_score = float(request.form.get("confidence_score") or 7)
    except ValueError:
        confidence_score = 7

    if source_type not in VALID_SOURCE_TYPES:
        source_type = "google_news"

    if signal_type not in VALID_SIGNAL_TYPES:
        signal_type = "negative_publicity"

    if source_type == "google_news" and not query:
        flash("Google News query is required.", "error")
        return redirect(url_for("admin_profiles.list_profiles"))

    profile_query = IngestionProfileQuery(
        profile_id=profile.id,
        source_type=source_type,
        query=query,
        feed_url=feed_url,
        signal_type=signal_type,
        confidence_score=max(1, min(10, confidence_score)),
        is_active=True,
    )

    db.session.add(profile_query)
    db.session.commit()

    flash(f"Query added to '{profile.name}'.", "success")

    return redirect(url_for("admin_profiles.list_profiles"))


@admin_profiles_bp.route("/queries/<int:query_id>/toggle", methods=["POST"])
@login_required
def toggle_profile_query(query_id):
    if not user_is_admin():
        return "Forbidden", 403

    profile_query = IngestionProfileQuery.query.get_or_404(query_id)
    profile_query.is_active = not profile_query.is_active
    db.session.commit()

    flash("Profile query updated.", "success")

    return redirect(url_for("admin_profiles.list_profiles"))


@admin_profiles_bp.route("/queries/<int:query_id>/delete", methods=["POST"])
@login_required
def delete_profile_query(query_id):
    if not user_is_admin():
        return "Forbidden", 403

    profile_query = IngestionProfileQuery.query.get_or_404(query_id)
    db.session.delete(profile_query)
    db.session.commit()

    flash("Profile query deleted.", "success")

    return redirect(url_for("admin_profiles.list_profiles"))
