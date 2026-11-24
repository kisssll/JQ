"""Add custom subscription offers to salons and sport organizations

Revision ID: e146f1a5d3c4
Revises: d935f0e4c2b3
Create Date: 2026-11-24 20:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e146f1a5d3c4'
down_revision = 'd935f0e4c2b3'
branch_labels = None
depends_on = None


def upgrade():
    # Salons custom offer fields
    op.add_column('salons', sa.Column('custom_subscription_price', sa.Integer(), nullable=True))
    op.add_column('salons', sa.Column('custom_subscription_notes', sa.String(length=255), nullable=True))

    # Sport organizations subscription & custom offer fields
    op.add_column('sport_organizations', sa.Column('subscription_tier', sa.String(length=30), nullable=True, server_default='gym'))
    op.add_column('sport_organizations', sa.Column('subscription_status', sa.String(length=20), nullable=False, server_default='trialing'))
    op.add_column('sport_organizations', sa.Column('subscription_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('sport_organizations', sa.Column('custom_subscription_price', sa.Integer(), nullable=True))
    op.add_column('sport_organizations', sa.Column('custom_subscription_notes', sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column('sport_organizations', 'custom_subscription_notes')
    op.drop_column('sport_organizations', 'custom_subscription_price')
    op.drop_column('sport_organizations', 'subscription_expires_at')
    op.drop_column('sport_organizations', 'subscription_status')
    op.drop_column('sport_organizations', 'subscription_tier')

    op.drop_column('salons', 'custom_subscription_notes')
    op.drop_column('salons', 'custom_subscription_price')
