"""Add source run link to lead signals

Revision ID: cf8088cb387c
Revises: cf4c2e3816c3
Create Date: 2026-05-19

"""
from alembic import op
import sqlalchemy as sa


revision = "cf8088cb387c"
down_revision = "cf4c2e3816c3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("lead_signals", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source_run_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_lead_signals_source_run_id_source_run_logs",
            "source_run_logs",
            ["source_run_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("lead_signals", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_lead_signals_source_run_id_source_run_logs",
            type_="foreignkey",
        )
        batch_op.drop_column("source_run_id")