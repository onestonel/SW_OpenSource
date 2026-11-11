"""영수증 · 품목 · 품목별 내는 사람 (V1 요구 명세 2~4단계)

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BigId = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')


def upgrade() -> None:
    op.create_table('receipts',
    sa.Column('id', BigId, nullable=False),
    sa.Column('room_id', BigId, nullable=False),
    sa.Column('store_name', sa.String(length=50), nullable=False),
    sa.Column('payer_member_id', BigId, nullable=False),
    sa.Column('total_amount', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(length=10), server_default='CHECKING', nullable=False),
    sa.Column('photo_path', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('CHECKING', 'CONFIRMED')", name='ck_receipts_status'),
    sa.CheckConstraint('total_amount > 0', name='ck_receipts_total_positive'),
    sa.ForeignKeyConstraint(['payer_member_id'], ['members.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('receipts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_receipts_payer_member_id'), ['payer_member_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_receipts_room_id'), ['room_id'], unique=False)

    op.create_table('receipt_items',
    sa.Column('id', BigId, nullable=False),
    sa.Column('receipt_id', BigId, nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('amount', sa.BigInteger(), nullable=False),
    sa.Column('kind', sa.String(length=10), server_default='ITEM', nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.CheckConstraint("(kind = 'ITEM' AND amount > 0) OR (kind = 'DISCOUNT' AND amount < 0)",
                       name='ck_receipt_items_amount_sign'),
    sa.CheckConstraint("kind IN ('ITEM', 'DISCOUNT')", name='ck_receipt_items_kind'),
    sa.ForeignKeyConstraint(['receipt_id'], ['receipts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('receipt_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_receipt_items_receipt_id'), ['receipt_id'], unique=False)

    op.create_table('receipt_item_payers',
    sa.Column('receipt_item_id', BigId, nullable=False),
    sa.Column('member_id', BigId, nullable=False),
    sa.ForeignKeyConstraint(['member_id'], ['members.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['receipt_item_id'], ['receipt_items.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('receipt_item_id', 'member_id')
    )
    with op.batch_alter_table('receipt_item_payers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_receipt_item_payers_member_id'), ['member_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('receipt_item_payers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_receipt_item_payers_member_id'))
    op.drop_table('receipt_item_payers')
    with op.batch_alter_table('receipt_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_receipt_items_receipt_id'))
    op.drop_table('receipt_items')
    with op.batch_alter_table('receipts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_receipts_room_id'))
        batch_op.drop_index(batch_op.f('ix_receipts_payer_member_id'))
    op.drop_table('receipts')
