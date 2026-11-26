"""Add colors to sport trainings."""

from alembic import op
import sqlalchemy as sa

revision = "d7b14a2e0c83"
down_revision = "e81937d52fa0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sport_trainings", sa.Column("color", sa.String(7), nullable=False, server_default="#c72527"))


def downgrade() -> None:
    op.drop_column("sport_trainings", "color")
