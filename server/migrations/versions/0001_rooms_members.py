"""정산방 · 구성원 (V1 요구 명세 1단계)

Revision ID: 0001
Revises:
Create Date: 2026-11-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BigId = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')


def upgrade() -> None:
    op.create_table('rooms',
    sa.Column('id', BigId, nullable=False),
    sa.Column('room_token', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('rounding', sa.String(length=8), server_default='WON_1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("rounding IN ('WON_1', 'WON_10')", name='ck_rooms_rounding'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('room_token', name='uq_rooms_room_token')
    )
    op.create_table('members',
    sa.Column('id', BigId, nullable=False),
    sa.Column('room_id', BigId, nullable=False),
    sa.Column('name', sa.String(length=20), nullable=False),
    sa.Column('display_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('room_id', 'name', name='uq_members_room_name')
    )
    with op.batch_alter_table('members', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_members_room_id'), ['room_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('members', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_members_room_id'))
    op.drop_table('members')
    op.drop_table('rooms')
