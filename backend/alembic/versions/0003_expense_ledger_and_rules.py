"""expense ledger and rules

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-16 10:58:07.823241

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('expense_rules',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('key', sa.String(length=200), nullable=False),
    sa.Column('label', sa.String(length=200), nullable=False),
    sa.Column('splits', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'key', name='uq_expense_rules_key')
    )
    op.create_index(op.f('ix_expense_rules_organization_id'), 'expense_rules', ['organization_id'], unique=False)
    # expenses 는 이 단계 전까지 쓰는 코드가 없었으므로 비어 있다 → NOT NULL 로 바로 추가
    op.add_column('expenses', sa.Column('organization_id', sa.Uuid(), nullable=False))
    op.add_column('expenses', sa.Column('memo', sa.String(length=200), nullable=True))
    op.create_index(op.f('ix_expenses_date'), 'expenses', ['date'], unique=False)
    op.create_index(op.f('ix_expenses_organization_id'), 'expenses', ['organization_id'], unique=False)
    op.create_index(op.f('ix_expenses_transaction_allocation_id'), 'expenses', ['transaction_allocation_id'], unique=False)
    op.create_foreign_key('fk_expenses_organization_id', 'expenses', 'organizations', ['organization_id'], ['id'])
    op.create_check_constraint('ck_expenses_amount', 'expenses', 'amount > 0')


def downgrade() -> None:
    op.drop_constraint('ck_expenses_amount', 'expenses', type_='check')
    op.drop_constraint('fk_expenses_organization_id', 'expenses', type_='foreignkey')
    op.drop_index(op.f('ix_expenses_transaction_allocation_id'), table_name='expenses')
    op.drop_index(op.f('ix_expenses_organization_id'), table_name='expenses')
    op.drop_index(op.f('ix_expenses_date'), table_name='expenses')
    op.drop_column('expenses', 'memo')
    op.drop_column('expenses', 'organization_id')
    op.drop_index(op.f('ix_expense_rules_organization_id'), table_name='expense_rules')
    op.drop_table('expense_rules')
