"""AI 총무 판단 기록 (말한 문장 · 모델 답 · 서버 보정 · 사용자 반응)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-18
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BigId = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')


def upgrade() -> None:
    op.create_table('nl_logs',
    sa.Column('id', BigId, nullable=False),
    sa.Column('room_id', BigId, nullable=False),
    sa.Column('text', sa.String(length=600), nullable=False),
    sa.Column('answers_id', BigId, nullable=True),
    sa.Column('provider', sa.String(length=16), nullable=False),
    sa.Column('raw', sa.Text(), nullable=False),
    sa.Column('model_rules', sa.JSON(), nullable=False),
    sa.Column('final_rules', sa.JSON(), nullable=False),
    sa.Column('repairs', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('changes', sa.JSON(), nullable=False),
    sa.Column('elapsed_ms', sa.Integer(), nullable=False),
    sa.Column('outcome', sa.String(length=16), nullable=True),
    sa.Column('outcome_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('manual_fixes', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('nl_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_nl_logs_room_id'), ['room_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('nl_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_nl_logs_room_id'))
    op.drop_table('nl_logs')
