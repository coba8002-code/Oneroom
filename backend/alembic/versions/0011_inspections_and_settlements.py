"""inspections and move-out settlements — 입주·퇴실 점검(항목·사진) + 퇴실 정산

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-17 07:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0011'
down_revision: Union[str, None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('inspections',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('lease_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('inspected_on', sa.Date(), nullable=False),
    sa.Column('tenant_confirmed_on', sa.Date(), nullable=True),
    sa.Column('confirm_note', sa.Text(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('move_in', 'move_out')", name='ck_inspections_kind'),
    sa.ForeignKeyConstraint(['lease_id'], ['leases.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lease_id', 'kind')
    )
    op.create_index(op.f('ix_inspections_lease_id'), 'inspections', ['lease_id'], unique=False)
    op.create_table('move_out_settlements',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('lease_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('snapshot', sa.JSON(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['lease_id'], ['leases.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lease_id')
    )
    op.create_table('inspection_items',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('inspection_id', sa.Uuid(), nullable=False),
    sa.Column('fixture_id', sa.Uuid(), nullable=True),
    sa.Column('area', sa.String(length=50), nullable=False),
    sa.Column('condition', sa.String(length=20), nullable=True),
    sa.Column('reading', sa.String(length=30), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['fixture_id'], ['fixtures.id'], ),
    sa.ForeignKeyConstraint(['inspection_id'], ['inspections.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_inspection_items_inspection_id'), 'inspection_items', ['inspection_id'], unique=False)
    op.create_table('inspection_photos',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('item_id', sa.Uuid(), nullable=False),
    sa.Column('file_path', sa.String(length=64), nullable=False),
    sa.Column('content_type', sa.String(length=50), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['inspection_items.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_inspection_photos_item_id'), 'inspection_photos', ['item_id'], unique=False)
    op.create_table('settlement_deductions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('settlement_id', sa.Uuid(), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('label', sa.String(length=100), nullable=False),
    sa.Column('amount', sa.BigInteger(), nullable=False),
    sa.Column('disputed', sa.Boolean(), nullable=False),
    sa.Column('inspection_item_id', sa.Uuid(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('amount >= 0', name='ck_settlement_deductions_amount'),
    sa.ForeignKeyConstraint(['inspection_item_id'], ['inspection_items.id'], ),
    sa.ForeignKeyConstraint(['settlement_id'], ['move_out_settlements.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_settlement_deductions_settlement_id'), 'settlement_deductions', ['settlement_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_settlement_deductions_settlement_id'), table_name='settlement_deductions')
    op.drop_table('settlement_deductions')
    op.drop_index(op.f('ix_inspection_photos_item_id'), table_name='inspection_photos')
    op.drop_table('inspection_photos')
    op.drop_index(op.f('ix_inspection_items_inspection_id'), table_name='inspection_items')
    op.drop_table('inspection_items')
    op.drop_table('move_out_settlements')
    op.drop_index(op.f('ix_inspections_lease_id'), table_name='inspections')
    op.drop_table('inspections')
