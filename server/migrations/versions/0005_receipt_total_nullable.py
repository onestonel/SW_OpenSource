"""영수증 총액을 비워 둘 수 있게 (가게 이름 · 결제자만으로 '확인 중' 영수증 만들기, #47)

총액은 확정할 때 API에서 검사한다 (409 RECEIPT_INCOMPLETE).
'총액은 0보다 크다' 검사(ck_receipts_total_positive)는 그대로 둔다. 비어 있으면(NULL) 통과한다.

되돌리기(downgrade)는 총액이 빈 영수증이 있으면 실패한다. 먼저 총액을 채우거나 그 영수증을 지운다.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-27
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('receipts') as batch:
        batch.alter_column('total_amount', existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('receipts') as batch:
        batch.alter_column('total_amount', existing_type=sa.BigInteger(), nullable=False)
