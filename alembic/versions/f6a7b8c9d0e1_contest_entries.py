"""Заявки на конкурс из ботов

Заявку принимаем в боте и храним у себя: гугл-форма — это персональные данные
россиян в базе за границей (152-ФЗ) и противоречие нашей же политике.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE consentdocument ADD VALUE IF NOT EXISTS 'CONTEST_RULES'")

    op.create_table(
        "contest_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contest", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel", postgresql.ENUM(name="notifychannel", create_type=False), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("city", sa.String(length=300), nullable=False),
        sa.Column("work_url", sa.String(length=300), nullable=False),
        sa.Column("contact", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("ix_contest_entries_contest", "contest_entries", ["contest"])
    op.create_index("ix_contest_entries_user_id", "contest_entries", ["user_id"])
    op.create_index("ix_contest_entries_chat_id", "contest_entries", ["chat_id"])


def downgrade() -> None:
    op.drop_table("contest_entries")
