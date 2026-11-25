"""Club staff profiles and attendance history.

Revision ID: f23a9e5c40d1
Revises: e146f1a5d3c4
"""

import sqlalchemy as sa
from alembic import op

revision = "f23a9e5c40d1"
down_revision = "e146f1a5d3c4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sport_gym_members", sa.Column("display_name", sa.String(160)))
    op.add_column("sport_gym_members", sa.Column("contact_phone", sa.String(24)))
    op.add_column("sport_gym_members", sa.Column("bio", sa.Text()))
    op.add_column("sport_gym_members", sa.Column("photo_url", sa.String(500)))
    op.add_column("sport_coaches", sa.Column("contact_phone", sa.String(24)))
    op.create_index(
        "ix_sport_bookings_attendance_date",
        "sport_bookings",
        ["organization_id", "requested_date"],
        postgresql_where=sa.text("status = 'came'"),
    )
    op.execute("""
        UPDATE sport_bookings AS booking
        SET start_time = booking.requested_date + training.start_time,
            end_time = booking.requested_date + training.end_time
        FROM sport_trainings AS training
        WHERE booking.training_id = training.id
          AND booking.organization_id = training.organization_id
          AND booking.status = 'came'
          AND booking.requested_date IS NOT NULL
          AND booking.start_time IS NULL
    """)


def downgrade():
    op.drop_index("ix_sport_bookings_attendance_date", table_name="sport_bookings")
    op.drop_column("sport_coaches", "contact_phone")
    for column in ("photo_url", "bio", "contact_phone", "display_name"):
        op.drop_column("sport_gym_members", column)
