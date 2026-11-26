"""Add hair survey columns to masters and bookings

Revision ID: c39e8a7d1f25
Revises: b27d8e9f1a04
Create Date: 2026-11-25 19:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c39e8a7d1f25'
down_revision = 'f103ab7289ec'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Master: hair_survey_enabled (Boolean, default False), hair_survey_settings (JSON)
    op.add_column(
        'masters',
        sa.Column('hair_survey_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false'))
    )
    op.add_column(
        'masters',
        sa.Column('hair_survey_settings', sa.JSON(), nullable=True)
    )

    # 2. Booking: hair_survey (JSON)
    op.add_column(
        'bookings',
        sa.Column('hair_survey', sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('bookings', 'hair_survey')
    op.drop_column('masters', 'hair_survey_settings')
    op.drop_column('masters', 'hair_survey_enabled')
