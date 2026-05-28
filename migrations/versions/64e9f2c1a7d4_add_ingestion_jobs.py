"""Add ingestion jobs

Revision ID: 64e9f2c1a7d4
Revises: 053bf5eb03b2
Create Date: 2026-05-28 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "64e9f2c1a7d4"
down_revision = "053bf5eb03b2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("source_run_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_run_id"], ["source_run_logs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )



def downgrade():
    op.drop_table("ingestion_jobs")
