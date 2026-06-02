from flask import Blueprint, redirect, url_for, flash
from flask_login import login_required, current_user

from app.services.ingestion_queue_service import queue_ingestion_job


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
    result = queue_ingestion_job(
        job_name="google_news",
        requested_by_user_id=current_user.id,
    )

    job = result["job"]

    if result["created"]:
        flash(
            f"Google News ingestion queued. Job ID: {job.id}. The Railway worker will process it shortly.",
            "success",
        )
    else:
        flash(
            f"Google News ingestion is already {job.status}. Job ID: {job.id}.",
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
