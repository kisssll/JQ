"""Add sport roles, closures, reviews and payroll.

Revision ID: d935f0e4c2b3
Revises: c824e9f3b1a2
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op


revision: str = "d935f0e4c2b3"
down_revision: Union[str, Sequence[str], None] = "c824e9f3b1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update sport_gym_members: add permissions and update check constraint
    op.add_column("sport_gym_members", sa.Column("permissions", sa.JSON(), server_default="{}", nullable=False))
    op.drop_constraint("ck_sport_gym_member_role", "sport_gym_members", type_="check")
    op.create_check_constraint(
        "ck_sport_gym_member_role",
        "sport_gym_members",
        "role IN ('owner', 'manager', 'admin')",
    )

    # 2. sport_schedule_closures
    op.create_table(
        "sport_schedule_closures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("coach_id", sa.Integer(), sa.ForeignKey("sport_coaches.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("sport_venues.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(255), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # 3. sport_reviews
    op.create_table(
        "sport_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("coach_id", sa.Integer(), sa.ForeignKey("sport_coaches.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("sport_bookings.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), server_default="", nullable=False),
        sa.Column("admin_response", sa.Text(), nullable=True),
        sa.Column("is_published", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # 4. sport_coach_payrolls
    op.create_table(
        "sport_coach_payrolls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("coach_id", sa.Integer(), sa.ForeignKey("sport_coaches.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("commission_percent", sa.Integer(), server_default="50", nullable=False),
        sa.Column("base_rate_per_session", sa.Integer(), server_default="0", nullable=False),
        sa.Column("bonus", sa.Integer(), server_default="0", nullable=False),
        sa.Column("notes", sa.String(255), server_default="", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sport_coach_payrolls")
    op.drop_table("sport_reviews")
    op.drop_table("sport_schedule_closures")
    op.drop_constraint("ck_sport_gym_member_role", "sport_gym_members", type_="check")
    op.create_check_constraint(
        "ck_sport_gym_member_role",
        "sport_gym_members",
        "role IN ('owner', 'admin')",
    )
    op.drop_column("sport_gym_members", "permissions")
