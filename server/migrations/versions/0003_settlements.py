"""정산 결과 버전 (V1 요구 명세 5단계)

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-11
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BigId = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')


def upgrade() -> None:
    op.create_table('settlements',
    sa.Column('id', BigId, nullable=False),
    sa.Column('room_id', BigId, nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('rounding', sa.String(length=8), nullable=False),
    sa.Column('result', sa.JSON(), nullable=False),
    sa.Column('is_stale', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("rounding IN ('WON_1', 'WON_10')", name='ck_settlements_rounding'),
    sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('room_id', 'version', name='uq_settlements_room_version')
    )
    with op.batch_alter_table('settlements', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_settlements_room_id'), ['room_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('settlements', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_settlements_room_id'))
    op.drop_table('settlements')
