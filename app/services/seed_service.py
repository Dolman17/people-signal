from app.extensions import db
from app.models import Company, LeadSignal


def seed_demo_data(source_run_id=None):
    """
    Creates a small set of demo companies and signals.
    Safe to run multiple times because it checks existing company names.
    """

    demo_items = [
        {
            "company": {
                "name": "Oakbridge Care Group",
                "sector": "Care",
                "website": "https://example.com/oakbridge",
                "city": "Birmingham",
                "region": "West Midlands",
                "company_size": "100-250",
            },
            "signals": [
                {
                    "signal_type": "rapid_hiring",
                    "source": "Demo data",
                    "title": "Multiple care vacancies detected across three locations",
                    "raw_text": "The organisation appears to be recruiting for care workers, senior carers and deputy managers across several services.",
                    "confidence_score": 7,
                },
                {
                    "signal_type": "leadership_change",
                    "source": "Demo data",
                    "title": "Senior operational leadership change identified",
                    "raw_text": "A change in operational leadership may create a short-term need for management alignment and HR process consistency.",
                    "confidence_score": 6,
                },
            ],
        },
        {
            "company": {
                "name": "Hawthorne Supported Living",
                "sector": "Care",
                "website": "https://example.com/hawthorne",
                "city": "Manchester",
                "region": "North West",
                "company_size": "50-100",
            },
            "signals": [
                {
                    "signal_type": "regulatory_concern",
                    "source": "Demo data",
                    "title": "Regulatory concern signal detected",
                    "raw_text": "A public regulatory concern may indicate pressure around management oversight, documentation, staffing or employee relations processes.",
                    "confidence_score": 8,
                }
            ],
        },
        {
            "company": {
                "name": "Willowmere Residential Care",
                "sector": "Care",
                "website": "https://example.com/willowmere",
                "city": "Leeds",
                "region": "Yorkshire",
                "company_size": "25-50",
            },
            "signals": [
                {
                    "signal_type": "negative_publicity",
                    "source": "Demo data",
                    "title": "Negative local publicity around staffing concerns",
                    "raw_text": "Local reporting suggests possible workforce pressure and management consistency issues.",
                    "confidence_score": 7,
                }
            ],
        },
    ]

    companies_created = 0
    signals_created = 0

    for item in demo_items:
        company_data = item["company"]

        company = Company.query.filter_by(name=company_data["name"]).first()

        if not company:
            company = Company(**company_data)
            db.session.add(company)
            db.session.flush()
            companies_created += 1

        for signal_data in item["signals"]:
            existing_signal = LeadSignal.query.filter_by(
                company_id=company.id,
                title=signal_data["title"]
            ).first()

            if not existing_signal:
                signal = LeadSignal(
                    company_id=company.id,
                    source_run_id=source_run_id,
                    **signal_data
                )
                db.session.add(signal)
                signals_created += 1

    db.session.commit()

    return {
        "companies_created": companies_created,
        "signals_created": signals_created,
    }