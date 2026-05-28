from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.extensions import db
from app.models import (
    Organisation,
    User,
    Company,
    CompanyAlias,
    LeadSignal,
    AIInsight,
    AIBatchJob,
    SourceRunLog
)
from app.services.seed_service import seed_demo_data
from app.services.google_news_service import ingest_google_news_signals
from app.services.employment_tribunal_service import ingest_employment_tribunal_signals
from app.services.find_tender_open_data_service import ingest_find_tender_open_data_signals
from app.services.sector_rss_service import ingest_sector_rss_signals
from app.services.local_authority_tender_service import ingest_local_authority_tender_signals
from app.services.companies_house_service import ingest_companies_house_signals
from app.services.openai_batch_insight_service import (
    create_openai_ai_insight_batch,
    import_completed_openai_ai_batch_job,
    refresh_openai_ai_batch_job,
)
from app.services.source_log_service import (
    start_source_run,
    complete_source_run,
    fail_source_run
)

admin_bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin"
)


def user_is_admin():
    return (
        current_user.is_authenticated
        and current_user.role in ["admin", "superuser"]
    )


@admin_bp.route("/")
@login_required
def admin_home():
    if not user_is_admin():
        return "Forbidden", 403

    stats = {
        "organisations": Organisation.query.count(),
        "users": User.query.count(),
        "companies": Company.query.count(),
        "company_aliases": CompanyAlias.query.count(),
        "signals": LeadSignal.query.count(),
        "insights": AIInsight.query.count(),
        "ai_batch_jobs": AIBatchJob.query.count(),
        "source_runs": SourceRunLog.query.count(),
    }

    recent_source_runs = (
        SourceRunLog.query
        .order_by(SourceRunLog.started_at.desc())
        .limit(10)
        .all()
    )

    recent_ai_batches = (
        AIBatchJob.query
        .order_by(AIBatchJob.created_at.desc())
        .limit(10)
        .all()
    )

    return render_template(
        "admin/index.html",
        stats=stats,
        recent_source_runs=recent_source_runs,
        recent_ai_batches=recent_ai_batches,
    )


@admin_bp.route("/companies/merge", methods=["GET", "POST"])
@login_required
def merge_companies():
    if not user_is_admin():
        return "Forbidden", 403

    if request.method == "POST":
        primary_company_id = request.form.get("primary_company_id")
        duplicate_company_id = request.form.get("duplicate_company_id")

        if not primary_company_id or not duplicate_company_id:
            flash("Choose both a primary company and a duplicate company.", "error")
            return redirect(url_for("admin.merge_companies"))

        if primary_company_id == duplicate_company_id:
            flash("Primary and duplicate company cannot be the same.", "error")
            return redirect(url_for("admin.merge_companies"))

        primary_company = Company.query.get_or_404(primary_company_id)
        duplicate_company = Company.query.get_or_404(duplicate_company_id)

        try:
            duplicate_name = duplicate_company.name

            LeadSignal.query.filter_by(company_id=duplicate_company.id).update(
                {"company_id": primary_company.id}
            )

            AIInsight.query.filter_by(company_id=duplicate_company.id).update(
                {"company_id": primary_company.id}
            )

            existing_alias = CompanyAlias.query.filter_by(
                company_id=primary_company.id,
                alias_name=duplicate_name
            ).first()

            if not existing_alias:
                alias = CompanyAlias(
                    company_id=primary_company.id,
                    alias_name=duplicate_name,
                    source="manual_merge"
                )
                db.session.add(alias)

            duplicate_aliases = CompanyAlias.query.filter_by(
                company_id=duplicate_company.id
            ).all()

            for old_alias in duplicate_aliases:
                existing = CompanyAlias.query.filter_by(
                    company_id=primary_company.id,
                    alias_name=old_alias.alias_name
                ).first()

                if not existing:
                    moved_alias = CompanyAlias(
                        company_id=primary_company.id,
                        alias_name=old_alias.alias_name,
                        source=old_alias.source or "manual_merge"
                    )
                    db.session.add(moved_alias)

                db.session.delete(old_alias)

            db.session.delete(duplicate_company)
            db.session.commit()

            flash(
                f"Merged '{duplicate_name}' into '{primary_company.name}'. Signals and insights moved.",
                "success"
            )

        except Exception as e:
            db.session.rollback()
            flash(f"Company merge failed: {e}", "error")

        return redirect(url_for("admin.merge_companies"))

    companies = (
        Company.query
        .order_by(Company.name.asc())
        .all()
    )

    aliases = (
        CompanyAlias.query
        .join(Company)
        .order_by(Company.name.asc(), CompanyAlias.alias_name.asc())
        .all()
    )

    return render_template(
        "admin/merge_companies.html",
        companies=companies,
        aliases=aliases
    )


@admin_bp.route("/source-runs/<int:run_id>")
@login_required
def source_run_detail(run_id):
    if not user_is_admin():
        return "Forbidden", 403

    run = SourceRunLog.query.get_or_404(run_id)

    matching_signals = (
        LeadSignal.query
        .filter_by(source_run_id=run.id)
        .order_by(LeadSignal.detected_at.desc())
        .all()
    )

    return render_template(
        "admin/source_run_detail.html",
        run=run,
        matching_signals=matching_signals
    )


@admin_bp.route("/source-runs/<int:run_id>/revert", methods=["POST"])
@login_required
def revert_source_run(run_id):
    if not user_is_admin():
        return "Forbidden", 403

    run = SourceRunLog.query.get_or_404(run_id)

    try:
        linked_signals = LeadSignal.query.filter_by(source_run_id=run.id).all()
        signal_ids = [signal.id for signal in linked_signals]

        deleted_insights = 0
        deleted_signals = 0

        if signal_ids:
            deleted_insights = (
                AIInsight.query
                .filter(AIInsight.signal_id.in_(signal_ids))
                .delete(synchronize_session=False)
            )

            deleted_signals = (
                LeadSignal.query
                .filter(LeadSignal.id.in_(signal_ids))
                .delete(synchronize_session=False)
            )

        db.session.commit()

        flash(
            f"Source run reverted. Signals deleted: {deleted_signals}. "
            f"Related AI insights deleted: {deleted_insights}.",
            "success"
        )

    except Exception as e:
        db.session.rollback()
        flash(f"Source run revert failed: {e}", "error")

    return redirect(url_for("admin.source_run_detail", run_id=run.id))


@admin_bp.route("/seed-demo-data", methods=["POST"])
@login_required
def seed_demo():
    if not user_is_admin():
        return "Forbidden", 403

    run_log = start_source_run("demo_seed_data")

    try:
        result = seed_demo_data(source_run_id=run_log.id)

        complete_source_run(
            run_log,
            records_found=result["companies_created"] + result["signals_created"],
            signals_created=result["signals_created"]
        )

        flash(
            f"Demo data seeded. Companies created: {result['companies_created']}. "
            f"Signals created: {result['signals_created']}.",
            "success"
        )

    except Exception as e:
        fail_source_run(run_log, e)
        flash("Demo seed failed. Check source run logs.", "error")

    return redirect(url_for("admin.admin_home"))


@admin_bp.route("/run-google-news", methods=["POST"])
@login_required
def run_google_news():
    if not user_is_admin():
        return "Forbidden", 403

    run_log = start_source_run("google_news_rss")

    try:
        result = ingest_google_news_signals(
            limit_per_query=1,
            source_run_id=run_log.id
        )

        complete_source_run(
            run_log,
            records_found=result["records_found"],
            signals_created=result["signals_created"]
        )

        flash(
            f"Google News run completed. Records found: {result['records_found']}. "
            f"Companies created: {result['companies_created']}. "
            f"Signals created: {result['signals_created']}. "
            f"Skipped: {result.get('skipped', 0)}.",
            "success"
        )

    except Exception as e:
        fail_source_run(run_log, e)
        flash("Google News run failed. Check source run logs.", "error")

    return redirect(url_for("admin.admin_home"))


@admin_bp.route("/run-companies-house", methods=["POST"])
@login_required
def run_companies_house():
    if not user_is_admin():
        return "Forbidden", 403

    run_log = start_source_run("companies_house")

    try:
        result = ingest_companies_house_signals(
            source_run_id=run_log.id,
            search_limit_per_term=5,
            officers_per_company=10,
            filings_per_company=25,
            recent_days=365,
        )

        complete_source_run(
            run_log,
            records_found=result["records_found"],
            signals_created=result["signals_created"],
        )

        flash(
            f"Companies House run completed. Records found: {result['records_found']}. "
            f"Companies created: {result['companies_created']}. "
            f"Signals created: {result['signals_created']}. "
            f"Skipped: {result.get('skipped', 0)}.",
            "success",
        )

    except Exception as e:
        fail_source_run(run_log, e)
        flash(f"Companies House run failed: {e}", "error")

    return redirect(url_for("admin.admin_home"))

@admin_bp.route("/run-employment-tribunals", methods=["POST"])
@login_required
def run_employment_tribunals():
    if not user_is_admin():
        return "Forbidden", 403

    run_log = start_source_run("employment_tribunals")

    try:
        result = ingest_employment_tribunal_signals(
            source_run_id=run_log.id,
            results_per_query=3,
            recent_days=730,
        )

        complete_source_run(
            run_log,
            records_found=result["records_found"],
            signals_created=result["signals_created"],
        )

        flash(
            f"Employment Tribunal run completed. Records found: {result['records_found']}. "
            f"Companies created: {result['companies_created']}. "
            f"Signals created: {result['signals_created']}. "
            f"Skipped: {result.get('skipped', 0)}.",
            "success",
        )

    except Exception as e:
        fail_source_run(run_log, e)
        flash(f"Employment Tribunal run failed: {e}", "error")

    return redirect(url_for("admin.admin_home"))


@admin_bp.route("/run-sector-rss", methods=["POST"])
@login_required
def run_sector_rss():
    if not user_is_admin():
        return "Forbidden", 403

    run_log = start_source_run("sector_rss")

    try:
        result = ingest_sector_rss_signals(
            source_run_id=run_log.id,
            entries_per_feed=10,
            recent_days=90,
        )

        complete_source_run(
            run_log,
            records_found=result["records_found"],
            signals_created=result["signals_created"],
        )

        flash(
            f"Sector RSS run completed. Records found: {result['records_found']}. "
            f"Companies created: {result['companies_created']}. "
            f"Signals created: {result['signals_created']}. "
            f"Skipped: {result.get('skipped', 0)}.",
            "success",
        )

    except Exception as e:
        fail_source_run(run_log, e)
        flash(f"Sector RSS run failed: {e}", "error")

    return redirect(url_for("admin.admin_home"))

@admin_bp.route("/run-local-authority-tenders", methods=["POST"])
@login_required
def run_local_authority_tenders():
    if not user_is_admin():
        return "Forbidden", 403

    run_log = start_source_run("local_authority_tenders")

    try:
        result = ingest_local_authority_tender_signals(
            source_run_id=run_log.id,
            results_per_query=10,
            recent_days=120,
        )

        complete_source_run(
            run_log,
            records_found=result["records_found"],
            signals_created=result["signals_created"],
        )

        flash(
            f"Local Authority Tender run completed. Records found: {result['records_found']}. "
            f"Companies created: {result['companies_created']}. "
            f"Signals created: {result['signals_created']}. "
            f"Skipped: {result.get('skipped', 0)}.",
            "success",
        )

    except Exception as e:
        fail_source_run(run_log, e)
        flash(f"Local Authority Tender run failed: {e}", "error")

    return redirect(url_for("admin.admin_home"))

@admin_bp.route("/run-find-tender-open-data", methods=["POST"])
@login_required
def run_find_tender_open_data():
    if not user_is_admin():
        return "Forbidden", 403

    run_log = start_source_run("find_tender_open_data")

    try:
        result = ingest_find_tender_open_data_signals(
            source_run_id=run_log.id,
            recent_days=14,
            max_packages=4,
            max_resources=10,
            max_notices=250,
        )

        complete_source_run(
            run_log,
            records_found=result["records_found"],
            signals_created=result["signals_created"],
        )

        flash(
            f"Find a Tender open data run completed. Records found: {result['records_found']}. "
            f"Resources checked: {result.get('resources_checked', 0)}. "
            f"Companies created: {result['companies_created']}. "
            f"Signals created: {result['signals_created']}. "
            f"Skipped: {result.get('skipped', 0)}.",
            "success",
        )

    except Exception as e:
        fail_source_run(run_log, e)
        flash(f"Find a Tender open data run failed: {e}", "error")

    return redirect(url_for("admin.admin_home"))

@admin_bp.route("/run-ai-insights", methods=["POST"])
@login_required
def run_ai_insights():
    if not user_is_admin():
        return "Forbidden", 403

    run_log = start_source_run("openai_ai_insight_batch")

    try:
        max_signals = int(request.form.get("max_signals") or 10)
        max_signals = max(1, min(100, max_signals))

        signals_without_insights = (
            LeadSignal.query
            .outerjoin(AIInsight, LeadSignal.id == AIInsight.signal_id)
            .filter(AIInsight.id.is_(None))
            .order_by(
                LeadSignal.confidence_score.desc(),
                LeadSignal.detected_at.desc()
            )
            .limit(max_signals)
            .all()
        )

        if not signals_without_insights:
            complete_source_run(
                run_log,
                records_found=0,
                signals_created=0
            )

            flash("No signals without AI insights were found.", "info")
            return redirect(url_for("admin.admin_home"))

        job = create_openai_ai_insight_batch(
            signals=signals_without_insights,
            source_run_id=run_log.id,
        )

        run_log.status = "submitted"
        run_log.records_found = len(signals_without_insights)
        run_log.signals_created = 0
        db.session.commit()

        flash(
            f"Discounted OpenAI Batch API job submitted. "
            f"Signals queued: {len(signals_without_insights)}. "
            f"Batch ID: {job.openai_batch_id}. Check/import later.",
            "success",
        )

    except Exception as e:
        db.session.rollback()
        fail_source_run(run_log, e)
        flash(f"OpenAI batch submission failed: {e}", "error")

    return redirect(url_for("admin.admin_home"))


@admin_bp.route("/ai-batches/<int:job_id>/refresh", methods=["POST"])
@login_required
def refresh_ai_batch(job_id):
    if not user_is_admin():
        return "Forbidden", 403

    job = AIBatchJob.query.get_or_404(job_id)

    try:
        refresh_openai_ai_batch_job(job)

        flash(
            f"AI batch refreshed. Current status: {job.status}.",
            "success",
        )

    except Exception as e:
        flash(f"AI batch refresh failed: {e}", "error")

    return redirect(url_for("admin.admin_home"))


@admin_bp.route("/ai-batches/<int:job_id>/import", methods=["POST"])
@login_required
def import_ai_batch(job_id):
    if not user_is_admin():
        return "Forbidden", 403

    job = AIBatchJob.query.get_or_404(job_id)

    try:
        result = import_completed_openai_ai_batch_job(job)

        if job.source_run:
            job.source_run.status = "completed" if job.status == "imported" else job.status
            job.source_run.signals_created = result.get("insights_created", 0)
            db.session.commit()

        flash(
            f"AI batch import checked. Status: {result.get('status')}. "
            f"Processed: {result.get('processed_count')}. "
            f"Insights created: {result.get('insights_created')}.",
            "success",
        )

    except Exception as e:
        db.session.rollback()
        flash(f"AI batch import failed: {e}", "error")

    return redirect(url_for("admin.admin_home"))


@admin_bp.route("/cleanup/google-news", methods=["POST"])
@login_required
def cleanup_google_news():
    if not user_is_admin():
        return "Forbidden", 403

    run_log = start_source_run("cleanup_google_news")

    try:
        google_news_signals = LeadSignal.query.filter_by(source="Google News RSS").all()
        signal_ids = [signal.id for signal in google_news_signals]

        deleted_insights = 0
        deleted_signals = 0

        if signal_ids:
            deleted_insights = (
                AIInsight.query
                .filter(AIInsight.signal_id.in_(signal_ids))
                .delete(synchronize_session=False)
            )

            deleted_signals = (
                LeadSignal.query
                .filter(LeadSignal.id.in_(signal_ids))
                .delete(synchronize_session=False)
            )

        db.session.commit()

        complete_source_run(
            run_log,
            records_found=len(signal_ids),
            signals_created=0
        )

        flash(
            f"Google News cleanup completed. Signals deleted: {deleted_signals}. "
            f"Related insights deleted: {deleted_insights}.",
            "success"
        )

    except Exception as e:
        db.session.rollback()
        fail_source_run(run_log, e)
        flash("Google News cleanup failed. Check source run logs.", "error")

    return redirect(url_for("admin.admin_home"))


@admin_bp.route("/cleanup/demo-data", methods=["POST"])
@login_required
def cleanup_demo_data():
    if not user_is_admin():
        return "Forbidden", 403

    run_log = start_source_run("cleanup_demo_data")

    try:
        demo_signals = LeadSignal.query.filter_by(source="Demo data").all()
        signal_ids = [signal.id for signal in demo_signals]

        deleted_insights = 0
        deleted_signals = 0

        if signal_ids:
            deleted_insights = (
                AIInsight.query
                .filter(AIInsight.signal_id.in_(signal_ids))
                .delete(synchronize_session=False)
            )

            deleted_signals = (
                LeadSignal.query
                .filter(LeadSignal.id.in_(signal_ids))
                .delete(synchronize_session=False)
            )

        demo_company_names = [
            "Oakbridge Care Group",
            "Hawthorne Supported Living",
            "Willowmere Residential Care",
        ]

        deleted_companies = (
            Company.query
            .filter(Company.name.in_(demo_company_names))
            .delete(synchronize_session=False)
        )

        db.session.commit()

        complete_source_run(
            run_log,
            records_found=len(signal_ids),
            signals_created=0
        )

        flash(
            f"Demo cleanup completed. Companies deleted: {deleted_companies}. "
            f"Signals deleted: {deleted_signals}. Related insights deleted: {deleted_insights}.",
            "success"
        )

    except Exception as e:
        db.session.rollback()
        fail_source_run(run_log, e)
        flash("Demo cleanup failed. Check source run logs.", "error")

    return redirect(url_for("admin.admin_home"))


@admin_bp.route("/cleanup/orphan-companies", methods=["POST"])
@login_required
def cleanup_orphan_companies():
    if not user_is_admin():
        return "Forbidden", 403

    run_log = start_source_run("cleanup_orphan_companies")

    try:
        orphan_companies = (
            Company.query
            .outerjoin(LeadSignal, Company.id == LeadSignal.company_id)
            .filter(LeadSignal.id.is_(None))
            .all()
        )

        orphan_company_ids = [company.id for company in orphan_companies]

        deleted_companies = 0

        if orphan_company_ids:
            deleted_companies = (
                Company.query
                .filter(Company.id.in_(orphan_company_ids))
                .delete(synchronize_session=False)
            )

        db.session.commit()

        complete_source_run(
            run_log,
            records_found=len(orphan_company_ids),
            signals_created=0
        )

        flash(
            f"Orphan company cleanup completed. Companies deleted: {deleted_companies}.",
            "success"
        )

    except Exception as e:
        db.session.rollback()
        fail_source_run(run_log, e)
        flash(f"Orphan company cleanup failed: {e}", "error")

    return redirect(url_for("admin.admin_home"))