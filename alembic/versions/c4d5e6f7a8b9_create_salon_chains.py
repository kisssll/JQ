"""create salon_chains + chain_id on salons + merge request/vote tables

Сеть салонов: несколько независимых салонов (разные владельцы) показывают
друг друга на публичной странице как «другой адрес этой же сети».
Формируется только через SalonChainRequest + единогласные SalonChainVote
от создателя каждого затронутого салона — см. app/services/salon_chain_service.py.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-07-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'salon_chains',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.add_column('salons', sa.Column(
        'chain_id', sa.Integer(), sa.ForeignKey('salon_chains.id', ondelete='SET NULL'), nullable=True
    ))

    op.create_table(
        'salon_chain_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('initiator_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('from_salon_id', sa.Integer(), sa.ForeignKey('salons.id', ondelete='CASCADE'), nullable=False),
        sa.Column('to_salon_id', sa.Integer(), sa.ForeignKey('salons.id', ondelete='CASCADE'), nullable=False),
        sa.Column('salon_ids', sa.JSON(), nullable=False),
        sa.Column('status', sa.Enum('PENDING', 'ACCEPTED', 'REJECTED', 'CANCELLED', name='salonchainrequeststatus'),
                  nullable=False, server_default='PENDING'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_chain_requests_status', 'salon_chain_requests', ['status'])

    op.create_table(
        'salon_chain_votes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('request_id', sa.Integer(), sa.ForeignKey('salon_chain_requests.id', ondelete='CASCADE'), nullable=False),
        sa.Column('salon_id', sa.Integer(), sa.ForeignKey('salons.id', ondelete='CASCADE'), nullable=False),
        sa.Column('approved', sa.Boolean(), nullable=False),
        sa.Column('voted_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('voted_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('request_id', 'salon_id', name='uq_chain_vote_request_salon'),
    )


def downgrade() -> None:
    op.drop_table('salon_chain_votes')
    op.drop_index('ix_chain_requests_status', table_name='salon_chain_requests')
    op.drop_table('salon_chain_requests')
    sa.Enum(name='salonchainrequeststatus').drop(op.get_bind(), checkfirst=True)
    op.drop_column('salons', 'chain_id')
    op.drop_table('salon_chains')
