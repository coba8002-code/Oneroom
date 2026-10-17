"""lease end and legal checks — 계약 종료일·사유, 계약 체결일, 계약 법정 체크

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-17 08:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0012'
down_revision: Union[str, None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('leases', sa.Column('signed_on', sa.Date(), nullable=True))
    op.add_column('leases', sa.Column('ended_on', sa.Date(), nullable=True))
    op.add_column('leases', sa.Column('end_reason', sa.Text(), nullable=True))
    op.create_table('lease_checks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('lease_id', sa.Uuid(), nullable=False),
    sa.Column('key', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('done_on', sa.Date(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('done', 'na')", name='ck_lease_checks_status'),
    sa.ForeignKeyConstraint(['lease_id'], ['leases.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lease_id', 'key')
    )
    op.create_index(op.f('ix_lease_checks_lease_id'), 'lease_checks', ['lease_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_lease_checks_lease_id'), table_name='lease_checks')
    op.drop_table('lease_checks')
    op.drop_column('leases', 'end_reason')
    op.drop_column('leases', 'ended_on')
    op.drop_column('leases', 'signed_on')
