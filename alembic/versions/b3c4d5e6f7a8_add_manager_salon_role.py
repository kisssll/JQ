"""salonrole: +MANAGER (роль «Управляющий», между владельцем и админом)

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PG≥12 позволяет ADD VALUE в транзакции; использовать новое значение
    # в ЭТОЙ ЖЕ транзакции нельзя — здесь и не используем.
    op.execute("ALTER TYPE salonrole ADD VALUE IF NOT EXISTS 'MANAGER' AFTER 'OWNER'")


def downgrade() -> None:
    # Postgres не поддерживает удаление значения из ENUM штатно — оставляем
    # no-op (как и для аналогичной миграции userrole: +BUSINESS).
    pass
