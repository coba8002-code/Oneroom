"""expense receipts — 지출 증빙 파일

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-17 09:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0013'
down_revision: Union[str, None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('expense_receipts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('expense_id', sa.Uuid(), nullable=False),
    sa.Column('file_path', sa.String(length=64), nullable=False),
    sa.Column('content_type', sa.String(length=50), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('original_name', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['expense_id'], ['expenses.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_expense_receipts_expense_id'), 'expense_receipts', ['expense_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_expense_receipts_expense_id'), table_name='expense_receipts')
    op.drop_table('expense_receipts')
