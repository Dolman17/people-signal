from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import func

from app.extensions import db
from app.models import (
    Company,
    LeadSignal,
    AIInsight,
    SourceRunLog,
    AIBatchJob,
)


dashboard_bp = Blueprint(
    "dashboard",
    __name__,
    url_prefix="/dashboard"
)


@dashboard_bp.route("/")
@login_required
def dashboard_home():
    new_signals_count = (
        LeadSignal.query
        .filter(LeadSignal.review_status == "new")
        .count()
    )

    saved_prospects_count = (
        LeadSignal.query
        .filter(LeadSignal.review_status == "saved")
        .count()
    )

    contacted_prospects_count = (
        LeadSignal.query
        .filter(LeadSignal.review_status == "contacted")
        .count()
    )

    rejected_signals_count = (
        LeadSignal.query
        .filter(LeadSignal.review_status == "rejected")
        .count()
    )

    companies_with_signals_count = (
        db.session.query(func.count(func.distinct(LeadSignal.company_id)))
        .scalar()
        or 0
    )

    signals_missing_ai_count = (
        LeadSignal.query
        .outerjoin(AIInsight, LeadSignal.id == AIInsight.signal_id)
        .filter(AIInsight.id.is_(None))
        .count()
    )

    google_news_signals_count = (
        LeadSignal.query
        .filter(LeadSignal.source == "Google News RSS")
        .count()
    )

    companies_house_signals_count = (
        LeadSignal.query
        .filter(LeadSignal.source == "Companies House")
        .count()
    )

    employment_tribunal_signals_count = (
        LeadSignal.query
        .filter(LeadSignal.source == "Employment Tribunal Decisions")
        .count()
    )

    sector_rss_signals_count = (
        LeadSignal.query
        .filter(LeadSignal.source == "Sector RSS")
        .count()
    )

    local_authority_tenders_count = (
        LeadSignal.query
        .filter(LeadSignal.source == "Local Authority Tenders")
        .count()
    )

    find_tender_signals_count = (
        LeadSignal.query
        .filter(LeadSignal.source == "Find a Tender")
        .count()
    )

    manual_signals_count = (
        LeadSignal.query
        .filter(LeadSignal.source == "Manual Source")
        .count()
    )

    source_breakdown = [
        {
            "label": "Google News",
            "source": "Google News RSS",
            "count": google_news_signals_count,
            "description": "Public news trigger events",
            "text_class": "text-cyan-300",
        },
        {
            "label": "Companies House",
            "source": "Companies House",
            "count": companies_house_signals_count,
            "description": "Officer, filing and status changes",
            "text_class": "text-indigo-300",
        },
        {
            "label": "Employment Tribunals",
            "source": "Employment Tribunal Decisions",
            "count": employment_tribunal_signals_count,
            "description": "ER, dismissal and legal-risk signals",
            "text_class": "text-rose-300",
        },
        {
            "label": "Sector RSS",
            "source": "Sector RSS",
            "count": sector_rss_signals_count,
            "description": "Sector news and workforce triggers",
            "text_class": "text-amber-300",
        },
        {
            "label": "LA Tenders",
            "source": "Local Authority Tenders",
            "count": local_authority_tenders_count,
            "description": "HR and workforce tender opportunities",
            "text_class": "text-emerald-300",
        },
        {
            "label": "Find a Tender",
            "source": "Find a Tender",
            "count": find_tender_signals_count,
            "description": "Higher-value public tender notices",
            "text_class": "text-teal-300",
        },
        {
            "label": "Manual",
            "source": "Manual Source",
            "count": manual_signals_count,
            "description": "Manually-created signals",
            "text_class": "text-slate-200",
        },
    ]

    total_signals_count = LeadSignal.query.count()
    total_companies_count = Company.query.count()
    total_insights_count = AIInsight.query.count()

    latest_source_run = (
        SourceRunLog.query
        .order_by(SourceRunLog.started_at.desc())
        .first()
    )

    latest_ai_batch = (
        AIBatchJob.query
        .order_by(AIBatchJob.created_at.desc())
        .first()
    )

    recent_new_signals = (
        LeadSignal.query
        .filter(LeadSignal.review_status == "new")
        .order_by(
            LeadSignal.confidence_score.desc(),
            LeadSignal.detected_at.desc()
        )
        .limit(8)
        .all()
    )

    recent_saved_prospects = (
        LeadSignal.query
        .filter(LeadSignal.review_status.in_(["saved", "contacted"]))
        .order_by(LeadSignal.detected_at.desc())
        .limit(6)
        .all()
    )

    latest_runs = (
        SourceRunLog.query
        .order_by(SourceRunLog.started_at.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "dashboard.html",
        new_signals_count=new_signals_count,
        saved_prospects_count=saved_prospects_count,
        contacted_prospects_count=contacted_prospects_count,
        rejected_signals_count=rejected_signals_count,
        companies_with_signals_count=companies_with_signals_count,
        signals_missing_ai_count=signals_missing_ai_count,
        google_news_signals_count=google_news_signals_count,
        companies_house_signals_count=companies_house_signals_count,
        employment_tribunal_signals_count=employment_tribunal_signals_count,
        sector_rss_signals_count=sector_rss_signals_count,
        local_authority_tenders_count=local_authority_tenders_count,
        find_tender_signals_count=find_tender_signals_count,
        manual_signals_count=manual_signals_count,
        source_breakdown=source_breakdown,
        total_signals_count=total_signals_count,
        total_companies_count=total_companies_count,
        total_insights_count=total_insights_count,
        latest_source_run=latest_source_run,
        latest_ai_batch=latest_ai_batch,
        recent_new_signals=recent_new_signals,
        recent_saved_prospects=recent_saved_prospects,
        latest_runs=latest_runs,
    )