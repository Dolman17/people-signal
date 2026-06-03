from flask import Blueprint, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.models import IngestionProfile
from app.services.ingestion_queue_service import queue_ingestion_job
from app.services.ingestion_profile_service import get_profile_or_default


admin_jobs_bp = Blueprint(
    "admin_jobs",
    __name__,
    url_prefix="/admin"
)


def user_is_admin():
    return (
        current_user.is_authenticated
        and current_user.role in ["admin", "superuser"]
    )


def create_google_news_job():
    profile_id_raw = request.form.get("profile_id") or request.args.get("profile_id")

    try:
        profile_id = int(profile_id_raw) if profile_id_raw else None
    except ValueError:
        profile_id = None

    profile = get_profile_or_default(profile_id)

    if not profile:
        flash("No active ingestion profile is available. Create one first.", "error")
        return redirect(url_for("admin.admin_home"))

    result = queue_ingestion_job(
        job_name="google_news",
        requested_by_user_id=current_user.id,
        profile_id=profile.id,
    )

    job = result["job"]

    if result["created"]:
        flash(
            f"Google News ingestion queued for '{profile.name}'. Job ID: {job.id}. The Railway worker will process it shortly.",
            "success",
        )
    else:
        existing_profile = IngestionProfile.query.get(job.profile_id) if job.profile_id else profile
        profile_name = existing_profile.name if existing_profile else profile.name
        flash(
            f"Google News ingestion for '{profile_name}' is already {job.status}. Job ID: {job.id}.",
            "info",
        )

    return redirect(url_for("admin.admin_home"))


@admin_jobs_bp.route("/run-google-news", methods=["POST"])
@login_required
def run_google_news_queued():
    if not user_is_admin():
        return "Forbidden", 403

    return create_google_news_job()


@admin_jobs_bp.route("/queue-google-news", methods=["POST"])
@login_required
def queue_google_news():
    if not user_is_admin():
        return "Forbidden", 403

    return create_google_news_job()
