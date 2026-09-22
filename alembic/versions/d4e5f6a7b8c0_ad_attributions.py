"""Метки рекламы при подключении (utm, yclid) — учёт без cookie

Revision ID: d4e5f6a7b8c0
Revises: c3d4e5f6a7b9
"""
import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c0"
down_revision = "c3d4e5f6a7b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ad_attributions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("salon_id", sa.Integer(), sa.ForeignKey("salons.id", ondelete="SET NULL"), nullable=True),
        sa.Column("landing", sa.String(length=100), nullable=True),
        sa.Column("utm_source", sa.String(length=200), nullable=True),
        sa.Column("utm_medium", sa.String(length=200), nullable=True),
        sa.Column("utm_campaign", sa.String(length=200), nullable=True),
        sa.Column("utm_content", sa.String(length=200), nullable=True),
        sa.Column("utm_term", sa.String(length=200), nullable=True),
        sa.Column("yclid", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("ix_ad_attributions_user_id", "ad_attributions", ["user_id"])
    op.create_index("ix_ad_attributions_salon_id", "ad_attributions", ["salon_id"])
    op.create_index("ix_ad_attributions_yclid", "ad_attributions", ["yclid"])


def downgrade() -> None:
    op.drop_table("ad_attributions")
