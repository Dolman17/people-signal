"""Add ingestion profiles

Revision ID: 8b2f4d6a9c31
Revises: 64e9f2c1a7d4
Create Date: 2026-06-02 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "8b2f4d6a9c31"
down_revision = "64e9f2c1a7d4"
branch_labels = None
depends_on = None


CARE_HIGH_VALUE_TERMS = """cqc
inadequate
requires improvement
special measures
warning notice
safeguarding
abuse
neglect
inspection
closure
closed
administration
administrator
liquidation
insolvency
redundancy
redundancies
restructure
restructuring
merger
acquisition
takeover
new home
new service
new site
expansion
opening
staffing crisis
staff shortage
recruitment drive
job losses
employment tribunal
tribunal
whistleblowing
dismissal
strike
union
manager resigns
registered manager"""


CARE_LOW_VALUE_TERMS = """charity
fundraising
fundraiser
walking challenge
coffee morning
award
awards
celebrates
celebration
anniversary
birthday
community event
open day
donation
dementia uk
alzheimers society
sponsored walk
bake sale
raffle"""


CARE_AI_PROMPT = """The platform tracks UK care-sector organisations that may need HR consultancy support.
Identify the actual care provider, care home, supported living provider, operator, charity or organisation involved.
Create signals only where the article suggests meaningful HR, workforce, leadership, regulatory, restructuring or employee-relations pressure.
Skip charity events, awards, generic sector commentary, no named organisation, and low-value community-good-news stories."""


CARE_QUERIES = [
    ('"care home" "CQC" "inadequate" UK', "regulatory_concern", 9),
    ('"care home" "special measures" "CQC" UK', "regulatory_concern", 9),
    ('"care home" "requires improvement" "CQC" UK', "regulatory_concern", 8),
    ('"care provider" "warning notice" "CQC" UK', "regulatory_concern", 9),
    ('"care home" safeguarding UK', "regulatory_concern", 8),
    ('"care home" neglect UK', "negative_publicity", 8),
    ('"care home" "unacceptable conditions" UK', "regulatory_concern", 8),
    ('"care home" closure UK', "restructuring_signal", 7),
    ('"care home operator" administration UK', "restructuring_signal", 9),
    ('"care provider" insolvency UK', "restructuring_signal", 9),
    ('"nursing home" closure UK', "restructuring_signal", 7),
    ('"care home" "staff shortage" UK', "rapid_hiring", 7),
    ('"care provider" "recruitment drive" UK', "rapid_hiring", 7),
    ('"care home" "up to" "staff" UK', "rapid_hiring", 6),
    ('"supported living" "staff" UK', "rapid_hiring", 6),
    ('"new care home" opening UK', "rapid_hiring", 7),
    ('"care provider" expansion UK', "rapid_hiring", 6),
    ('"supported living" "planning permission" UK', "rapid_hiring", 6),
    ('"supported living" "new development" UK', "rapid_hiring", 6),
    ('"care provider" acquisition UK', "restructuring_signal", 7),
    ('"care home group" acquisition UK', "restructuring_signal", 7),
    ('"registered manager" "care home" "resigned" UK', "leadership_change", 7),
    ('"care provider" "employment tribunal" UK', "negative_publicity", 8),
    ('"care home" "employment tribunal" UK', "negative_publicity", 8),
    ('"care provider" whistleblowing UK', "negative_publicity", 8),
]


def upgrade():
    op.create_table(
        "ingestion_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("sector_label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("ai_prompt", sa.Text(), nullable=True),
        sa.Column("high_value_terms", sa.Text(), nullable=True),
        sa.Column("low_value_terms", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    op.create_table(
        "ingestion_profile_queries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=100), nullable=False),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("feed_url", sa.Text(), nullable=True),
        sa.Column("signal_type", sa.String(length=100), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["profile_id"], ["ingestion_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.add_column("ingestion_jobs", sa.Column("profile_id", sa.Integer(), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("job_params", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_ingestion_jobs_profile_id_ingestion_profiles",
        "ingestion_jobs",
        "ingestion_profiles",
        ["profile_id"],
        ["id"],
    )

    ingestion_profiles = sa.table(
        "ingestion_profiles",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("slug", sa.String),
        sa.column("sector_label", sa.String),
        sa.column("description", sa.Text),
        sa.column("ai_prompt", sa.Text),
        sa.column("high_value_terms", sa.Text),
        sa.column("low_value_terms", sa.Text),
        sa.column("is_active", sa.Boolean),
        sa.column("is_default", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )

    ingestion_profile_queries = sa.table(
        "ingestion_profile_queries",
        sa.column("profile_id", sa.Integer),
        sa.column("source_type", sa.String),
        sa.column("query", sa.Text),
        sa.column("signal_type", sa.String),
        sa.column("confidence_score", sa.Float),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
    )

    now = sa.func.now()

    op.bulk_insert(
        ingestion_profiles,
        [
            {
                "id": 1,
                "name": "Care Sector",
                "slug": "care-sector",
                "sector_label": "Care",
                "description": "Default care-sector ingestion profile for care homes, supported living, CQC, workforce and employee-relations risk signals.",
                "ai_prompt": CARE_AI_PROMPT,
                "high_value_terms": CARE_HIGH_VALUE_TERMS,
                "low_value_terms": CARE_LOW_VALUE_TERMS,
                "is_active": True,
                "is_default": True,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )

    op.bulk_insert(
        ingestion_profile_queries,
        [
            {
                "profile_id": 1,
                "source_type": "google_news",
                "query": query,
                "signal_type": signal_type,
                "confidence_score": confidence,
                "is_active": True,
                "created_at": now,
            }
            for query, signal_type, confidence in CARE_QUERIES
        ],
    )


def downgrade():
    op.drop_constraint(
        "fk_ingestion_jobs_profile_id_ingestion_profiles",
        "ingestion_jobs",
        type_="foreignkey",
    )
    op.drop_column("ingestion_jobs", "job_params")
    op.drop_column("ingestion_jobs", "profile_id")
    op.drop_table("ingestion_profile_queries")
    op.drop_table("ingestion_profiles")
