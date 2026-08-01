"""add published_at to salons

Revision ID: f8b2c4d6e0a1
Revises: f7a1b2c3d4e5
Create Date: 2026-07-29

Публикация салона после модерации. Одобрение админом больше не выбрасывает
салон в каталог автоматически — владелец сам жмёт «Опубликовать». Новое поле
published_at (nullable): NULL = прошёл модерацию, но ещё не публиковался.

Бэкфилл: всем УЖЕ одобренным салонам (moderation_status=approved), включая
скрытых владельцем, проставляем published_at = created_at — иначе они разом
пропадут из ленты и получат баннер «опубликуйте».
"""
from alembic import op
import sqlalchemy as sa

revision = "f8b2c4d6e0a1"
down_revision = "f7a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "salons",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Существующие одобренные салоны считаем уже опубликованными (по времени
    # создания). Enum в БД хранит ИМЯ члена — сравниваем с 'APPROVED'.
    op.execute(
        "UPDATE salons SET published_at = created_at "
        "WHERE moderation_status = 'APPROVED' AND published_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("salons", "published_at")
