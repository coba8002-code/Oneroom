"""bank alerts — 휴대폰 입금 알림 연동 (계좌별 토큰, 알림 원문, 거래 출처)

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-17 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0014'
down_revision: Union[str, None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('transactions', sa.Column('source', sa.String(length=10), nullable=False, server_default='statement'))
    op.add_column('bank_accounts', sa.Column('alert_token_hash', sa.String(length=64), nullable=True))
    op.add_column('bank_accounts', sa.Column('alert_token_created_at', sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint('uq_bank_accounts_alert_token_hash', 'bank_accounts', ['alert_token_hash'])
    op.create_table('bank_alerts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('bank_account_id', sa.Uuid(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('parsed', sa.JSON(), nullable=True),
    sa.Column('transaction_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['bank_account_id'], ['bank_accounts.id'], ),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_bank_alerts_bank_account_id'), 'bank_alerts', ['bank_account_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_bank_alerts_bank_account_id'), table_name='bank_alerts')
    op.drop_table('bank_alerts')
    op.drop_constraint('uq_bank_accounts_alert_token_hash', 'bank_accounts', type_='unique')
    op.drop_column('bank_accounts', 'alert_token_created_at')
    op.drop_column('bank_accounts', 'alert_token_hash')
    op.drop_column('transactions', 'source')
