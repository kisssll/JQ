"""Add editable public site fields to existing Sport records."""

from alembic import op
import sqlalchemy as sa

revision = "e81937d52fa0"
down_revision = "c8a9426d7fe1"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("cover_url", "vk_url", "telegram_url"):
        op.add_column("sport_organizations", sa.Column(name, sa.String(500), nullable=True))
    op.add_column("sport_disciplines", sa.Column("photo_url", sa.String(500), nullable=True))
    op.execute("UPDATE sport_organizations SET vk_url = 'https://vk.ru/spartaplus' WHERE slug = 'sparta'")


def downgrade():
    op.drop_column("sport_disciplines", "photo_url")
    for name in ("telegram_url", "vk_url", "cover_url"):
        op.drop_column("sport_organizations", name)
