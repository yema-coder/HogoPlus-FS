"""Phase 4: face verification, AI severity, SOP RAG, chat history

Revision ID: 0003
Revises: 0002
Create Date: 2026-06 (Phase 4)

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # employees: face reference selfie
    op.add_column("employees", sa.Column("reference_selfie_key", sa.String(500), nullable=True))
    op.add_column("employees", sa.Column("reference_selfie_set_at", sa.DateTime(timezone=True), nullable=True))

    # attendance: face verification result
    op.add_column("attendance", sa.Column("face_match_score", sa.Float(), nullable=True))
    op.add_column("attendance", sa.Column("face_verified", sa.Boolean(), nullable=True))

    # incidents: AI severity reason
    op.add_column("incidents", sa.Column("severity_reason", sa.String(300), nullable=True))

    # SOP documents (RAG source)
    op.create_table(
        "sop_docs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("file_key", sa.String(500), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("uploaded_by", UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # SOP chunks with pgvector embedding (384-dim: paraphrase-multilingual-MiniLM-L12-v2)
    op.create_table(
        "sop_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("doc_id", UUID(as_uuid=True), sa.ForeignKey("sop_docs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Sahayak chat history
    op.create_table(
        "chat_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False, index=True),
        sa.Column("conversation_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("sop_chunks")
    op.drop_table("sop_docs")
    op.drop_column("incidents", "severity_reason")
    op.drop_column("attendance", "face_verified")
    op.drop_column("attendance", "face_match_score")
    op.drop_column("employees", "reference_selfie_set_at")
    op.drop_column("employees", "reference_selfie_key")
