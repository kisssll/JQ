"""Merge staging roles and Sparta catalog

Revision ID: f6d1802a9b43
Revises: b27d8e9f1a04, c8a9426d7fe1
Create Date: 2026-11-26 02:46:08.799763

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6d1802a9b43'
down_revision: Union[str, None] = ('b27d8e9f1a04', 'c8a9426d7fe1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
