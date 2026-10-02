"""merge staging and warehouse migrations

Revision ID: 6aab9576f0fa
Revises: 6b91d3a2c8f4, c3e7f1a9d402
Create Date: 2026-10-03 00:58:23.636889

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6aab9576f0fa'
down_revision: Union[str, None] = ('6b91d3a2c8f4', 'c3e7f1a9d402')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
