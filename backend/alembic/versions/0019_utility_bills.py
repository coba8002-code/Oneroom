"""utility settings and bills — 공과금 처리 방식(건물·항목별)·고지서·배분 청구 (charges.kind)

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-18 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0019'
down_revision: Union[str, None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('utility_settings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('property_id', sa.Uuid(), nullable=False),
    sa.Column('item', sa.String(length=20), nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('method', sa.String(length=20), nullable=True),
    sa.Column('vacant', sa.String(length=20), nullable=True),
    sa.Column('owner', sa.String(length=20), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('property_id', 'item', name='uq_utility_settings_item')
    )
    op.create_index(op.f('ix_utility_settings_property_id'), 'utility_settings', ['property_id'], unique=False)
    op.create_table('utility_bills',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('property_id', sa.Uuid(), nullable=False),
    sa.Column('item', sa.String(length=20), nullable=False),
    sa.Column('period', sa.String(length=7), nullable=False),
    sa.Column('total', sa.BigInteger(), nullable=False),
    sa.Column('note', sa.String(length=200), nullable=True),
    sa.Column('manual', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('split_json', sa.JSON(), nullable=True),
    sa.Column('charged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('total > 0', name='ck_utility_bills_total'),
    sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('property_id', 'item', 'period', name='uq_utility_bills_period')
    )
    op.create_index(op.f('ix_utility_bills_property_id'), 'utility_bills', ['property_id'], unique=False)
    op.add_column('charges', sa.Column('kind', sa.String(length=20), server_default='rent', nullable=False))
    op.add_column('charges', sa.Column('utility_bill_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_charges_utility_bill_id'), 'charges', ['utility_bill_id'], unique=False)
    op.create_foreign_key('fk_charges_utility_bill_id', 'charges', 'utility_bills', ['utility_bill_id'], ['id'])
    op.drop_constraint('uq_charges_lease_period', 'charges', type_='unique')
    op.create_unique_constraint('uq_charges_lease_period_kind', 'charges', ['lease_id', 'period', 'kind'])


def downgrade() -> None:
    op.drop_constraint('uq_charges_lease_period_kind', 'charges', type_='unique')
    op.execute("DELETE FROM payments WHERE charge_id IN (SELECT id FROM charges WHERE kind <> 'rent')")
    op.execute("DELETE FROM charges WHERE kind <> 'rent'")
    op.create_unique_constraint('uq_charges_lease_period', 'charges', ['lease_id', 'period'])
    op.drop_constraint('fk_charges_utility_bill_id', 'charges', type_='foreignkey')
    op.drop_index(op.f('ix_charges_utility_bill_id'), table_name='charges')
    op.drop_column('charges', 'utility_bill_id')
    op.drop_column('charges', 'kind')
    op.drop_index(op.f('ix_utility_bills_property_id'), table_name='utility_bills')
    op.drop_table('utility_bills')
    op.drop_index(op.f('ix_utility_settings_property_id'), table_name='utility_settings')
    op.drop_table('utility_settings')
