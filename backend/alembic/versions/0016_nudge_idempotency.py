"""v1.0.22 batch: offline-outbox idempotency for incidents + form submissions
(client_uuid, same pattern vehicle_logs shipped in 0013). Additive/inert.

Revision ID: 0016
Revises: 0015
"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("client_uuid", sa.String(64), nullable=True))
    op.create_index("uq_incidents_client_uuid", "incidents", ["client_uuid"], unique=True)
    op.add_column("form_submissions", sa.Column("client_uuid", sa.String(64), nullable=True))
    op.create_index("uq_form_submissions_client_uuid", "form_submissions", ["client_uuid"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_form_submissions_client_uuid", table_name="form_submissions")
    op.drop_column("form_submissions", "client_uuid")
    op.drop_index("uq_incidents_client_uuid", table_name="incidents")
    op.drop_column("incidents", "client_uuid")
