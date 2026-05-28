from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy import or_

from app.extensions import db
from app.models import Company, LeadSignal, AIInsight
from app.services.ai_service import generate_ai_insight_for_signal

signals_bp = Blueprint(
    "signals",
    __name__,
    url_prefix="/signals"
)


VALID_REVIEW_STATUSES = [
    "new",
    "reviewed",
    "saved",
    "rejected",
    "contacted",
]


@signals_bp.route("/")
@login_required
def list_signals():
    source = request.args.get("source", "").strip()
    signal_type = request.args.get("signal_type", "").strip()
    search = request.args.get("search", "").strip()
    min_confidence = request.args.get("min_confidence", "").strip()
    review_status = request.args.get("review_status", "").strip()

    query = LeadSignal.query.join(Company)

    if source:
        query = query.filter(LeadSignal.source == source)

    if signal_type:
        query = query.filter(LeadSignal.signal_type == signal_type)

    if review_status:
        query = query.filter(LeadSignal.review_status == review_status)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Company.name.ilike(search_term),
                LeadSignal.title.ilike(search_term),
                LeadSignal.raw_text.ilike(search_term)
            )
        )

    if min_confidence:
        try:
            min_confidence_value = float(min_confidence)
            query = query.filter(LeadSignal.confidence_score >= min_confidence_value)
        except ValueError:
            flash("Minimum confidence must be a number.", "error")

    signals = (
        query
        .order_by(LeadSignal.detected_at.desc())
        .all()
    )

    source_options = [
        row[0]
        for row in db.session.query(LeadSignal.source)
        .filter(LeadSignal.source.isnot(None))
        .distinct()
        .order_by(LeadSignal.source.asc())
        .all()
        if row[0]
    ]

    signal_type_options = [
        row[0]
        for row in db.session.query(LeadSignal.signal_type)
        .filter(LeadSignal.signal_type.isnot(None))
        .distinct()
        .order_by(LeadSignal.signal_type.asc())
        .all()
        if row[0]
    ]

    active_filters = {
        "source": source,
        "signal_type": signal_type,
        "search": search,
        "min_confidence": min_confidence,
        "review_status": review_status,
    }

    return render_template(
        "signals/list.html",
        signals=signals,
        source_options=source_options,
        signal_type_options=signal_type_options,
        review_status_options=VALID_REVIEW_STATUSES,
        active_filters=active_filters,
    )


@signals_bp.route("/prospects")
@login_required
def prospects():
    search = request.args.get("search", "").strip()
    status = request.args.get("status", "").strip()

    query = (
        LeadSignal.query
        .join(Company)
        .filter(LeadSignal.review_status.in_(["saved", "contacted"]))
    )

    if status in ["saved", "contacted"]:
        query = query.filter(LeadSignal.review_status == status)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Company.name.ilike(search_term),
                LeadSignal.title.ilike(search_term),
                LeadSignal.raw_text.ilike(search_term),
                LeadSignal.review_notes.ilike(search_term),
            )
        )

    prospects = (
        query
        .order_by(LeadSignal.detected_at.desc())
        .all()
    )

    total_saved = LeadSignal.query.filter_by(review_status="saved").count()
    total_contacted = LeadSignal.query.filter_by(review_status="contacted").count()

    return render_template(
        "signals/prospects.html",
        prospects=prospects,
        search=search,
        status=status,
        total_saved=total_saved,
        total_contacted=total_contacted,
        review_status_options=VALID_REVIEW_STATUSES,
    )


@signals_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_signal():
    companies = (
        Company.query
        .order_by(Company.name.asc())
        .all()
    )

    if request.method == "POST":
        confidence_score_raw = request.form.get("confidence_score")

        try:
            confidence_score = float(confidence_score_raw) if confidence_score_raw else 0
        except ValueError:
            confidence_score = 0

        signal = LeadSignal(
            company_id=request.form.get("company_id"),
            signal_type=request.form.get("signal_type"),
            source=request.form.get("source"),
            title=request.form.get("title"),
            raw_text=request.form.get("raw_text"),
            confidence_score=confidence_score,
            review_status="new",
        )

        db.session.add(signal)
        db.session.commit()

        flash("Signal created successfully.", "success")

        return redirect(url_for("signals.list_signals"))

    return render_template(
        "signals/create.html",
        companies=companies
    )


@signals_bp.route("/<int:signal_id>/generate-insight", methods=["POST"])
@login_required
def generate_insight(signal_id):
    signal = LeadSignal.query.get_or_404(signal_id)

    existing_insight = AIInsight.query.filter_by(signal_id=signal.id).first()

    if existing_insight:
        flash("An AI insight already exists for this signal.", "error")
        return redirect(url_for("companies.company_detail", company_id=signal.company_id))

    insight_data = generate_ai_insight_for_signal(signal)

    insight = AIInsight(
        company_id=signal.company_id,
        signal_id=signal.id,
        summary=insight_data.get("summary"),
        urgency_score=insight_data.get("urgency_score"),
        likely_hr_need=insight_data.get("likely_hr_need"),
        outreach_angle=insight_data.get("outreach_angle"),
    )

    db.session.add(insight)
    db.session.commit()

    flash("AI insight generated successfully.", "success")

    return redirect(url_for("companies.company_detail", company_id=signal.company_id))


@signals_bp.route("/<int:signal_id>/review", methods=["POST"])
@login_required
def update_review_status(signal_id):
    signal = LeadSignal.query.get_or_404(signal_id)

    review_status = request.form.get("review_status", "").strip()
    review_notes = request.form.get("review_notes", "").strip()
    next_url = request.form.get("next_url") or url_for("signals.list_signals")

    if review_status not in VALID_REVIEW_STATUSES:
        flash("Invalid review status.", "error")
        return redirect(next_url)

    signal.review_status = review_status

    if review_notes:
        signal.review_notes = review_notes

    db.session.commit()

    flash(f"Signal marked as {review_status}.", "success")

    return redirect(next_url)