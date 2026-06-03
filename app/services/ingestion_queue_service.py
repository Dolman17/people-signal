import json

from app.extensions import db
from app.models import IngestionJob


def queue_ingestion_job(
    job_name,
    requested_by_user_id=None,
    profile_id=None,
    job_params=None,
):
    existing_query = (
        IngestionJob.query
        .filter_by(job_name=job_name)
        .filter(IngestionJob.status.in_(["pending", "running"]))
    )

    if profile_id:
        existing_query = existing_query.filter_by(profile_id=profile_id)

    existing_job = (
        existing_query
        .order_by(IngestionJob.created_at.desc())
        .first()
    )

    if existing_job:
        return {
            "created": False,
            "job": existing_job,
            "message": f"{job_name} ingestion is already {existing_job.status}. Job ID: {existing_job.id}.",
        }

    job = IngestionJob(
        job_name=job_name,
        status="pending",
        requested_by_user_id=requested_by_user_id,
        profile_id=profile_id,
        job_params=json.dumps(job_params or {}),
    )

    db.session.add(job)
    db.session.commit()

    return {
        "created": True,
        "job": job,
        "message": f"{job_name} ingestion queued. Job ID: {job.id}.",
    }
