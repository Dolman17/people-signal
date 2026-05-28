from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy import func

from app.extensions import db
from app.models import Company, LeadSignal, AIInsight, CompanyAlias

companies_bp = Blueprint(
    "companies",
    __name__,
    url_prefix="/companies"
)


@companies_bp.route("/")
@login_required
def list_companies():
    companies = (
        Company.query
        .order_by(Company.created_at.desc())
        .all()
    )

    company_ids = [company.id for company in companies]

    signal_counts = {}
    ai_insight_counts = {}
    alias_counts = {}
    latest_signals = {}

    if company_ids:
        signal_count_rows = (
            db.session.query(
                LeadSignal.company_id,
                func.count(LeadSignal.id)
            )
            .filter(LeadSignal.company_id.in_(company_ids))
            .group_by(LeadSignal.company_id)
            .all()
        )

        signal_counts = {
            company_id: count
            for company_id, count in signal_count_rows
        }

        ai_insight_count_rows = (
            db.session.query(
                AIInsight.company_id,
                func.count(AIInsight.id)
            )
            .filter(AIInsight.company_id.in_(company_ids))
            .group_by(AIInsight.company_id)
            .all()
        )

        ai_insight_counts = {
            company_id: count
            for company_id, count in ai_insight_count_rows
        }

        alias_count_rows = (
            db.session.query(
                CompanyAlias.company_id,
                func.count(CompanyAlias.id)
            )
            .filter(CompanyAlias.company_id.in_(company_ids))
            .group_by(CompanyAlias.company_id)
            .all()
        )

        alias_counts = {
            company_id: count
            for company_id, count in alias_count_rows
        }

        latest_signal_rows = (
            LeadSignal.query
            .filter(LeadSignal.company_id.in_(company_ids))
            .order_by(
                LeadSignal.company_id.asc(),
                LeadSignal.detected_at.desc()
            )
            .all()
        )

        for signal in latest_signal_rows:
            if signal.company_id not in latest_signals:
                latest_signals[signal.company_id] = signal

    company_rows = []

    for company in companies:
        latest_signal = latest_signals.get(company.id)

        company_rows.append(
            {
                "company": company,
                "signal_count": signal_counts.get(company.id, 0),
                "ai_insight_count": ai_insight_counts.get(company.id, 0),
                "alias_count": alias_counts.get(company.id, 0),
                "latest_signal": latest_signal,
                "latest_signal_source": latest_signal.source if latest_signal else None,
                "latest_signal_date": latest_signal.detected_at if latest_signal else None,
                "latest_signal_status": latest_signal.review_status if latest_signal else None,
            }
        )

    return render_template(
        "companies/list.html",
        companies=companies,
        company_rows=company_rows
    )


@companies_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_company():
    if request.method == "POST":
        company = Company(
            name=request.form.get("name"),
            sector=request.form.get("sector"),
            website=request.form.get("website"),
            city=request.form.get("city"),
            region=request.form.get("region"),
            company_size=request.form.get("company_size")
        )

        db.session.add(company)

        db.session.commit()

        flash("Company created successfully.", "success")

        return redirect(
            url_for(
                "companies.company_detail",
                company_id=company.id
            )
        )

    return render_template("companies/create.html")


@companies_bp.route("/<int:company_id>")
@login_required
def company_detail(company_id):
    company = Company.query.get_or_404(company_id)

    signals = (
        LeadSignal.query
        .filter_by(company_id=company.id)
        .order_by(LeadSignal.detected_at.desc())
        .all()
    )

    insights = (
        AIInsight.query
        .filter_by(company_id=company.id)
        .order_by(AIInsight.created_at.desc())
        .all()
    )

    return render_template(
        "companies/detail.html",
        company=company,
        signals=signals,
        insights=insights
    )