"""merge billing (tkassa) + consent journal heads

Revision ID: 7431cb422184
Revises: b12982aa0151, e1c2a3b4d5f6
Create Date: 2026-08-21 20:48:28.990110

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7431cb422184'
down_revision: Union[str, None] = ('b12982aa0151', 'e1c2a3b4d5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
