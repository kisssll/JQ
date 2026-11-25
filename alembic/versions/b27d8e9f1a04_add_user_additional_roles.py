"""add user additional_roles for multi-role assignment

Revision ID: b27d8e9f1a04
Revises: a16c7f8e4b30
Create Date: 2026-11-25 19:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b27d8e9f1a04'
down_revision = 'a16c7f8e4b30'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('additional_roles', sa.JSON(), server_default='[]', nullable=False))


def downgrade():
    op.drop_column('users', 'additional_roles')
