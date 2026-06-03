import os
import sys
import time
import traceback
from datetime import datetime

from app import create_app
from app.extensions import db
from app.models import SourceRunLog, IngestionJob

from app.services.google_news_service import ingest_google_news_signals
from app.services.companies_house_service import ingest_companies_house_signals
from app.services.employment_tribunal_service import ingest_employment_tribunal_signals
from app.services.sector_rss_service import ingest_sector_rss_signals
from app.services.local_authority_tender_service import ingest_local_authority_tender_signals
from app.services.find_tender_open_data_service import ingest_find_tender_open_data_signals


JOB_MAP = {
    "google_news": {
        "source_name": "google_news_rss",
        "runner": lambda source_run_id, ingestion_job=None: ingest_google_news_signals(
            limit_per_query=1,
            source_run_id=source_run_id,
            profile_id=ingestion_job.profile_id if ingestion_job else None,
        ),
    },
    "companies_house": {
        "source_name": "companies_house",
        "runner": lambda source_run_id, ingestion_job=None: ingest_companies_house_signals(
            source_run_id=source_run_id,
            search_limit_per_term=5,
            officers_per_company=10,
            filings_per_company=25,
            recent_days=365,
        ),
    },
    "employment_tribunals": {
        "source_name": "employment_tribunals",
        "runner": lambda source_run_id, ingestion_job=None: ingest_employment_tribunal_signals(
            source_run_id=source_run_id,
            results_per_query=3,
            recent_days=730,
        ),
    },
    "sector_rss": {
        "source_name": "sector_rss",
        "runner": lambda source_run_id, ingestion_job=None: ingest_sector_rss_signals(
            source_run_id=source_run_id,
            entries_per_feed=10,
            recent_days=90,
        ),
    },
    "local_authority_tenders": {
        "source_name": "local_authority_tenders",
        "runner": lambda source_run_id, ingestion_job=None: ingest_local_authority_tender_signals(
            source_run_id=source_run_id,
            results_per_query=10,
            recent_days=120,
        ),
    },
    "find_tender_open_data": {
        "source_name": "find_tender_open_data",
        "runner": lambda source_run_id, ingestion_job=None: ingest_find_tender_open_data_signals(
            source_run_id=source_run_id,
            recent_days=14,
            max_packages=4,
            max_resources=10,
            max_notices=250,
        ),
    },
}


def start_source_run(source_name, ingestion_job=None):
    profile_suffix = ""

    if ingestion_job and ingestion_job.profile:
        profile_suffix = f":{ingestion_job.profile.slug}"

    run_log = SourceRunLog(
        source_name=f"{source_name}{profile_suffix}",
        status="running",
        records_found=0,
        signals_created=0,
        started_at=datetime.utcnow(),
    )

    db.session.add(run_log)
    db.session.commit()

    return run_log


def complete_source_run(run_log, records_found=0, signals_created=0):
    run_log.status = "completed"
    run_log.records_found = records_found or 0
    run_log.signals_created = signals_created or 0
    run_log.finished_at = datetime.utcnow()

    db.session.commit()


def fail_source_run(run_log, error):
    run_log.status = "failed"
    run_log.error_message = str(error)
    run_log.finished_at = datetime.utcnow()

    db.session.commit()


def mark_job_running(job, run_log):
    if not job:
        return

    job.status = "running"
    job.started_at = datetime.utcnow()
    job.source_run_id = run_log.id
    job.error_message = None

    db.session.commit()


def mark_job_completed(job):
    if not job:
        return

    job.status = "completed"
    job.finished_at = datetime.utcnow()

    db.session.commit()


def mark_job_failed(job, error):
    if not job:
        return

    job.status = "failed"
    job.error_message = str(error)
    job.finished_at = datetime.utcnow()

    db.session.commit()


def execute_job(job_name, ingestion_job=None):
    if job_name not in JOB_MAP:
        available_jobs = ", ".join(sorted(JOB_MAP.keys()))
        raise ValueError(
            f"Unknown job '{job_name}'. Available jobs: {available_jobs}"
        )

    job_config = JOB_MAP[job_name]
    source_name = job_config["source_name"]
    runner = job_config["runner"]

    run_log = start_source_run(source_name, ingestion_job=ingestion_job)
    mark_job_running(ingestion_job, run_log)

    print(f"Starting job: {job_name}", flush=True)

    if ingestion_job and ingestion_job.profile:
        print(f"Ingestion profile: {ingestion_job.profile.name}", flush=True)

    print(f"Source run ID: {run_log.id}", flush=True)

    try:
        result = runner(run_log.id, ingestion_job=ingestion_job)

        complete_source_run(
            run_log,
            records_found=result.get("records_found", 0),
            signals_created=result.get("signals_created", 0),
        )
        mark_job_completed(ingestion_job)

        print("Job completed successfully.", flush=True)
        print(f"Records found: {result.get('records_found', 0)}", flush=True)
        print(f"Signals created: {result.get('signals_created', 0)}", flush=True)
        print(f"Companies created: {result.get('companies_created', 0)}", flush=True)
        print(f"Skipped: {result.get('skipped', 0)}", flush=True)

        if result.get("profile"):
            print(f"Profile: {result.get('profile')}", flush=True)

        return 0

    except Exception as error:
        fail_source_run(run_log, error)
        mark_job_failed(ingestion_job, error)

        print("Job failed.", flush=True)
        print(str(error), flush=True)
        traceback.print_exc()

        return 1


def run_job(job_name):
    return execute_job(job_name)


def process_pending_jobs_once(limit=1):
    pending_jobs = (
        IngestionJob.query
        .filter_by(status="pending")
        .order_by(IngestionJob.created_at.asc())
        .limit(limit)
        .all()
    )

    if not pending_jobs:
        print("No pending ingestion jobs found.", flush=True)
        return 0

    exit_code = 0

    for job in pending_jobs:
        print(f"Processing queued job {job.id}: {job.job_name}", flush=True)
        result = execute_job(job.job_name, ingestion_job=job)

        if result != 0:
            exit_code = result

    return exit_code


def worker_loop():
    poll_seconds = int(os.getenv("INGESTION_WORKER_POLL_SECONDS", "20"))
    batch_size = int(os.getenv("INGESTION_WORKER_BATCH_SIZE", "1"))

    print("Starting PeopleSignal ingestion worker.", flush=True)
    print(f"Poll seconds: {poll_seconds}", flush=True)
    print(f"Batch size: {batch_size}", flush=True)

    while True:
        try:
            process_pending_jobs_once(limit=batch_size)
        except Exception as error:
            print(f"Worker loop error: {error}", flush=True)
            traceback.print_exc()

        time.sleep(poll_seconds)


def main():
    if len(sys.argv) < 2:
        available_jobs = ", ".join(sorted(JOB_MAP.keys()))
        print("Usage: python railway_job_runner.py <job_name|process_pending|worker>")
        print(f"Available jobs: {available_jobs}")
        return 1

    command = sys.argv[1].strip()

    app = create_app()

    with app.app_context():
        if command == "process_pending":
            return process_pending_jobs_once(limit=1)

        if command == "worker":
            worker_loop()
            return 0

        return run_job(command)


if __name__ == "__main__":
    raise SystemExit(main())
