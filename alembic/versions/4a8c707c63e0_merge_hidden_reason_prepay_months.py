"""merge: hidden_reason + prepay months

Revision ID: 4a8c707c63e0
Revises: a3f5d2c81b40, fe484a8f7254
Create Date: 2026-08-23 07:20:59.484195

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4a8c707c63e0'
down_revision: Union[str, None] = ('a3f5d2c81b40', 'fe484a8f7254')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
