from datetime import datetime

from flask_login import UserMixin

from app.extensions import db


class Organisation(db.Model):
    __tablename__ = "organisations"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(255), nullable=False)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    organisation_id = db.Column(
        db.Integer,
        db.ForeignKey("organisations.id")
    )

    email = db.Column(
        db.String(255),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    role = db.Column(
        db.String(50),
        default="user"
    )


class Company(db.Model):
    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(255), nullable=False)

    sector = db.Column(db.String(100))

    website = db.Column(db.String(255))

    city = db.Column(db.String(120))

    region = db.Column(db.String(120))

    company_size = db.Column(db.String(50))

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


class CompanyAlias(db.Model):
    __tablename__ = "company_aliases"

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("companies.id"),
        nullable=False
    )

    alias_name = db.Column(
        db.String(255),
        nullable=False
    )

    source = db.Column(
        db.String(100),
        default="manual"
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    company = db.relationship(
        "Company",
        backref="aliases"
    )


class SourceRunLog(db.Model):
    __tablename__ = "source_run_logs"

    id = db.Column(db.Integer, primary_key=True)

    source_name = db.Column(
        db.String(100),
        nullable=False
    )

    status = db.Column(
        db.String(50),
        default="started"
    )

    records_found = db.Column(
        db.Integer,
        default=0
    )

    signals_created = db.Column(
        db.Integer,
        default=0
    )

    error_message = db.Column(
        db.Text
    )

    started_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    finished_at = db.Column(
        db.DateTime
    )


class AIBatchJob(db.Model):
    __tablename__ = "ai_batch_jobs"

    id = db.Column(db.Integer, primary_key=True)

    source_run_id = db.Column(
        db.Integer,
        db.ForeignKey("source_run_logs.id"),
        nullable=True
    )

    openai_batch_id = db.Column(
        db.String(255),
        nullable=False
    )

    input_file_id = db.Column(
        db.String(255)
    )

    output_file_id = db.Column(
        db.String(255)
    )

    status = db.Column(
        db.String(50),
        default="submitted"
    )

    requested_count = db.Column(
        db.Integer,
        default=0
    )

    processed_count = db.Column(
        db.Integer,
        default=0
    )

    insights_created = db.Column(
        db.Integer,
        default=0
    )

    error_message = db.Column(
        db.Text
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    completed_at = db.Column(
        db.DateTime
    )

    source_run = db.relationship(
        "SourceRunLog",
        backref="ai_batch_jobs"
    )


class IngestionProfile(db.Model):
    __tablename__ = "ingestion_profiles"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(
        db.String(255),
        nullable=False
    )

    slug = db.Column(
        db.String(120),
        unique=True,
        nullable=False
    )

    sector_label = db.Column(
        db.String(120),
        nullable=False,
        default="Care"
    )

    description = db.Column(db.Text)

    ai_prompt = db.Column(db.Text)

    high_value_terms = db.Column(db.Text)

    low_value_terms = db.Column(db.Text)

    is_active = db.Column(
        db.Boolean,
        default=True
    )

    is_default = db.Column(
        db.Boolean,
        default=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )


class IngestionProfileQuery(db.Model):
    __tablename__ = "ingestion_profile_queries"

    id = db.Column(db.Integer, primary_key=True)

    profile_id = db.Column(
        db.Integer,
        db.ForeignKey("ingestion_profiles.id"),
        nullable=False
    )

    source_type = db.Column(
        db.String(100),
        nullable=False,
        default="google_news"
    )

    query = db.Column(db.Text)

    feed_url = db.Column(db.Text)

    signal_type = db.Column(
        db.String(100),
        default="negative_publicity"
    )

    confidence_score = db.Column(
        db.Float,
        default=7
    )

    is_active = db.Column(
        db.Boolean,
        default=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    profile = db.relationship(
        "IngestionProfile",
        backref="queries"
    )


class IngestionJob(db.Model):
    __tablename__ = "ingestion_jobs"

    id = db.Column(db.Integer, primary_key=True)

    job_name = db.Column(
        db.String(100),
        nullable=False
    )

    status = db.Column(
        db.String(50),
        default="pending",
        nullable=False
    )

    requested_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True
    )

    source_run_id = db.Column(
        db.Integer,
        db.ForeignKey("source_run_logs.id"),
        nullable=True
    )

    profile_id = db.Column(
        db.Integer,
        db.ForeignKey("ingestion_profiles.id"),
        nullable=True
    )

    job_params = db.Column(db.Text)

    error_message = db.Column(
        db.Text
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    started_at = db.Column(
        db.DateTime
    )

    finished_at = db.Column(
        db.DateTime
    )

    requested_by = db.relationship(
        "User",
        backref="ingestion_jobs"
    )

    source_run = db.relationship(
        "SourceRunLog",
        backref="ingestion_jobs"
    )

    profile = db.relationship(
        "IngestionProfile",
        backref="jobs"
    )


class LeadSignal(db.Model):
    __tablename__ = "lead_signals"

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("companies.id"),
        nullable=False
    )

    source_run_id = db.Column(
        db.Integer,
        db.ForeignKey("source_run_logs.id"),
        nullable=True
    )

    signal_type = db.Column(
        db.String(100)
    )

    source = db.Column(
        db.String(100)
    )

    title = db.Column(
        db.String(500)
    )

    raw_text = db.Column(
        db.Text
    )

    confidence_score = db.Column(
        db.Float
    )

    review_status = db.Column(
        db.String(50),
        default="new"
    )

    review_notes = db.Column(
        db.Text
    )

    detected_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    company = db.relationship(
        "Company",
        backref="signals"
    )

    source_run = db.relationship(
        "SourceRunLog",
        backref="signals"
    )


class AIInsight(db.Model):
    __tablename__ = "ai_insights"

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("companies.id")
    )

    signal_id = db.Column(
        db.Integer,
        db.ForeignKey("lead_signals.id")
    )

    summary = db.Column(db.Text)

    urgency_score = db.Column(db.Float)

    likely_hr_need = db.Column(
        db.String(255)
    )

    outreach_angle = db.Column(
        db.Text
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )
