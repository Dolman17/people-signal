import sys
import traceback

from app import create_app
from app.extensions import db
from app.models import SourceRunLog

from app.services.google_news_service import ingest_google_news_signals
from app.services.companies_house_service import ingest_companies_house_signals
from app.services.employment_tribunal_service import ingest_employment_tribunal_signals
from app.services.sector_rss_service import ingest_sector_rss_signals
from app.services.local_authority_tender_service import ingest_local_authority_tender_signals
from app.services.find_tender_open_data_service import ingest_find_tender_open_data_signals


JOB_MAP = {
    "google_news": {
        "source_name": "google_news",
        "runner": lambda source_run_id: ingest_google_news_signals(
            source_run_id=source_run_id,
        ),
    },
    "companies_house": {
        "source_name": "companies_house",
        "runner": lambda source_run_id: ingest_companies_house_signals(
            source_run_id=source_run_id,
        ),
    },
    "employment_tribunals": {
        "source_name": "employment_tribunals",
        "runner": lambda source_run_id: ingest_employment_tribunal_signals(
            source_run_id=source_run_id,
            max_results=25,
        ),
    },
    "sector_rss": {
        "source_name": "sector_rss",
        "runner": lambda source_run_id: ingest_sector_rss_signals(
            source_run_id=source_run_id,
            entries_per_feed=10,
            recent_days=90,
        ),
    },
    "local_authority_tenders": {
        "source_name": "local_authority_tenders",
        "runner": lambda source_run_id: ingest_local_authority_tender_signals(
            source_run_id=source_run_id,
            results_per_query=10,
            recent_days=120,
        ),
    },
    "find_tender_open_data": {
        "source_name": "find_tender_open_data",
        "runner": lambda source_run_id: ingest_find_tender_open_data_signals(
            source_run_id=source_run_id,
            recent_days=14,
            max_packages=4,
            max_resources=10,
            max_notices=250,
        ),
    },
}


def start_source_run(source_name):
    run_log = SourceRunLog(
        source_name=source_name,
        status="running",
        records_found=0,
        signals_created=0,
    )

    db.session.add(run_log)
    db.session.commit()

    return run_log


def complete_source_run(run_log, records_found=0, signals_created=0):
    run_log.status = "completed"
    run_log.records_found = records_found or 0
    run_log.signals_created = signals_created or 0

    db.session.commit()


def fail_source_run(run_log, error):
    run_log.status = "failed"
    run_log.error_message = str(error)

    db.session.commit()


def run_job(job_name):
    if job_name not in JOB_MAP:
        available_jobs = ", ".join(sorted(JOB_MAP.keys()))
        raise ValueError(
            f"Unknown job '{job_name}'. Available jobs: {available_jobs}"
        )

    job_config = JOB_MAP[job_name]
    source_name = job_config["source_name"]
    runner = job_config["runner"]

    run_log = start_source_run(source_name)

    print(f"Starting job: {job_name}")
    print(f"Source run ID: {run_log.id}")

    try:
        result = runner(run_log.id)

        complete_source_run(
            run_log,
            records_found=result.get("records_found", 0),
            signals_created=result.get("signals_created", 0),
        )

        print("Job completed successfully.")
        print(f"Records found: {result.get('records_found', 0)}")
        print(f"Signals created: {result.get('signals_created', 0)}")
        print(f"Companies created: {result.get('companies_created', 0)}")
        print(f"Skipped: {result.get('skipped', 0)}")

        return 0

    except Exception as error:
        fail_source_run(run_log, error)

        print("Job failed.")
        print(str(error))
        traceback.print_exc()

        return 1


def main():
    if len(sys.argv) < 2:
        available_jobs = ", ".join(sorted(JOB_MAP.keys()))
        print(f"Usage: python railway_job_runner.py <job_name>")
        print(f"Available jobs: {available_jobs}")
        return 1

    job_name = sys.argv[1].strip()

    app = create_app()

    with app.app_context():
        return run_job(job_name)


if __name__ == "__main__":
    raise SystemExit(main())