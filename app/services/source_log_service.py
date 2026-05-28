from datetime import datetime

from app.extensions import db
from app.models import SourceRunLog


def start_source_run(source_name):
    run_log = SourceRunLog(
        source_name=source_name,
        status="started",
        started_at=datetime.utcnow()
    )

    db.session.add(run_log)
    db.session.commit()

    return run_log


def complete_source_run(run_log, records_found=0, signals_created=0):
    run_log.status = "completed"
    run_log.records_found = records_found
    run_log.signals_created = signals_created
    run_log.finished_at = datetime.utcnow()

    db.session.commit()

    return run_log


def fail_source_run(run_log, error_message):
    run_log.status = "failed"
    run_log.error_message = str(error_message)
    run_log.finished_at = datetime.utcnow()

    db.session.commit()

    return run_log