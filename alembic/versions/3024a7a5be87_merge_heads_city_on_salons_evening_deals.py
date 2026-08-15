"""merge heads: city on salons + evening deals

Revision ID: 3024a7a5be87
Revises: a3b4c5d6e7f8, c9e1a2b3d4f5
Create Date: 2026-08-15 23:30:56.532616

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3024a7a5be87'
down_revision: Union[str, None] = ('a3b4c5d6e7f8', 'c9e1a2b3d4f5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
