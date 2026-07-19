"""Prompt 14: demo showcase bubble — is_demo on employees + all user-generated
tables, is_demo_seed on data tables (permanent showcase rows the cleanup spares).

Revision ID: 0008_demo_isolation
Revises: 0007_anpr_pipeline
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

DEMO_TABLES = [
    "employees",
    "incidents",
    "form_submissions",
    "attendance",
    "shift_swap_requests",
    "notifications",
    "audit_events",
    "chat_messages",
]
SEED_TABLES = [t for t in DEMO_TABLES if t != "employees"]


def upgrade() -> None:
    for t in DEMO_TABLES:
        op.add_column(
            t, sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        op.create_index(f"ix_{t}_is_demo", t, ["is_demo"])
    for t in SEED_TABLES:
        op.add_column(
            t, sa.Column("is_demo_seed", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    for t in SEED_TABLES:
        op.drop_column(t, "is_demo_seed")
    for t in DEMO_TABLES:
        op.drop_index(f"ix_{t}_is_demo", table_name=t)
        op.drop_column(t, "is_demo")
