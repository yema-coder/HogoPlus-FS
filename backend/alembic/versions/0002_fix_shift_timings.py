"""fix shift timings (FIX 0, Phase 2)

A = 08:00-16:00, B = 16:00-00:00, C = 00:00-08:00, GEN unchanged.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-14

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE shifts SET start_time='08:00', end_time='16:00', label='Shift A (08:00-16:00)' WHERE code='A'")
    op.execute("UPDATE shifts SET start_time='16:00', end_time='00:00', label='Shift B (16:00-00:00)' WHERE code='B'")
    op.execute("UPDATE shifts SET start_time='00:00', end_time='08:00', label='Shift C (00:00-08:00)' WHERE code='C'")


def downgrade() -> None:
    op.execute("UPDATE shifts SET start_time='06:00', end_time='14:00', label='Shift A (06:00-14:00)' WHERE code='A'")
    op.execute("UPDATE shifts SET start_time='14:00', end_time='22:00', label='Shift B (14:00-22:00)' WHERE code='B'")
    op.execute("UPDATE shifts SET start_time='22:00', end_time='06:00', label='Shift C (22:00-06:00)' WHERE code='C'")
