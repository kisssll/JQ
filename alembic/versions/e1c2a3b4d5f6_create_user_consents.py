"""Журнал согласий на обработку персональных данных.

Пункт 8 Согласия называет моментом согласия проставление отметки в форме —
значит этот факт надо хранить: что подтвердили, когда, в какой редакции
документа и с какого адреса. Раньше галочка нигде не сохранялась, и доказать
согласие при проверке было нечем.

Revision ID: e1c2a3b4d5f6
Revises: b7e3f1a9c2d4
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e1c2a3b4d5f6"
down_revision = "b7e3f1a9c2d4"
branch_labels = None
depends_on = None

# Тип создаём явно ниже, поэтому в create_table он идёт с create_type=False —
# иначе SQLAlchemy выпускает CREATE TYPE второй раз и миграция падает на
# «type consentdocument already exists».
_DOC_NAME = "consentdocument"
# Метки — ИМЕНА членов перечисления, а не значения: SQLAlchemy по умолчанию
# пишет в такой столбец именно имя, и остальные типы в проекте заведены
# так же (WORKING/BROKEN, PENDING/RESOLVED).
_DOC_VALUES = ("PD_CONSENT", "TERMS", "OFFER")
_DOC_CREATE = postgresql.ENUM(*_DOC_VALUES, name=_DOC_NAME)
_DOC_COL = postgresql.ENUM(*_DOC_VALUES, name=_DOC_NAME, create_type=False)


def upgrade() -> None:
    _DOC_CREATE.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "user_consents",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        # Гостевая запись оформляется без учётной записи, поэтому user_id
        # необязателен, а человек опознаётся по телефону.
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("document", _DOC_COL, nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_consents_user", "user_consents", ["user_id"])
    op.create_index("ix_user_consents_phone", "user_consents", ["phone"])


def downgrade() -> None:
    op.drop_index("ix_user_consents_phone", table_name="user_consents")
    op.drop_index("ix_user_consents_user", table_name="user_consents")
    op.drop_table("user_consents")
    _DOC_CREATE.drop(op.get_bind(), checkfirst=True)
