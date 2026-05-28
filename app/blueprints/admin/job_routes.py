from flask import Blueprint, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models import IngestionJob


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


@admin_jobs_bp.route("/queue-google-news", methods=["POST"])
@login_required
def queue_google_news():
    if not user_is_admin():
        return "Forbidden", 403

    existing_job = (
        IngestionJob.query
        .filter_by(job_name="google_news")
        .filter(IngestionJob.status.in_(["pending", "running"]))
        .order_by(IngestionJob.created_at.desc())
        .first()
    )

    if existing_job:
        flash(
            f"Google News ingestion is already {existing_job.status}. Job ID: {existing_job.id}.",
            "info",
        )
        return redirect(url_for("admin.admin_home"))

    job = IngestionJob(
        job_name="google_news",
        status="pending",
        requested_by_user_id=current_user.id,
    )

    db.session.add(job)
    db.session.commit()

    flash(
        f"Google News ingestion queued. Job ID: {job.id}. The Railway worker will process it shortly.",
        "success",
    )

    return redirect(url_for("admin.admin_home"))
