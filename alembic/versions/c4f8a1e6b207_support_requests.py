"""support_requests — обращения в поддержку из ботов

Revision ID: c4f8a1e6b207
Revises: b2c7e4f9a015
Create Date: 2026-09-02

Писать может кто угодно, кто открыл бота, — поэтому user_id необязателен,
а chat_id хранится всегда: без аккаунта отвечать больше некуда.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c4f8a1e6b207"
down_revision = "b2c7e4f9a015"
branch_labels = None
depends_on = None

# create_type=False: типы создаём явно в upgrade() (checkfirst), иначе
# create_table попытается создать их второй раз и упадёт на дубле.
_TOPIC = postgresql.ENUM(
    "QUESTION", "BUG", "COMPLAINT", "IDEA", "NPS",
    name="supporttopic", create_type=False,
)
_STATUS = postgresql.ENUM(
    "NEW", "IN_PROGRESS", "CLOSED", name="supportstatus", create_type=False,
)
_TOPIC_DDL = postgresql.ENUM("QUESTION", "BUG", "COMPLAINT", "IDEA", "NPS", name="supporttopic")
_STATUS_DDL = postgresql.ENUM("NEW", "IN_PROGRESS", "CLOSED", name="supportstatus")


def upgrade() -> None:
    bind = op.get_bind()
    _TOPIC_DDL.create(bind, checkfirst=True)
    _STATUS_DDL.create(bind, checkfirst=True)

    op.create_table(
        "support_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic", _TOPIC, nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        # NotifyChannel уже есть в базе (миграция d4a71e9b6c02) — переиспользуем
        # существующий тип, create_type=False, иначе Postgres ругнётся дублем.
        sa.Column("channel",
                  postgresql.ENUM(name="notifychannel", create_type=False), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("photos", sa.JSON(), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("status", _STATUS, server_default="NEW", nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("answered_by_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("rating IS NULL OR (rating BETWEEN 1 AND 5)",
                           name="check_support_rating_range"),
    )
    op.create_index("ix_support_requests_user_id", "support_requests", ["user_id"])
    op.create_index("ix_support_requests_chat_id", "support_requests", ["chat_id"])
    op.create_index("ix_support_requests_status", "support_requests", ["status"])
    op.create_index("ix_support_requests_created_at", "support_requests", ["created_at"])


def downgrade() -> None:
    op.drop_table("support_requests")
    bind = op.get_bind()
    _STATUS_DDL.drop(bind, checkfirst=True)
    _TOPIC_DDL.drop(bind, checkfirst=True)
