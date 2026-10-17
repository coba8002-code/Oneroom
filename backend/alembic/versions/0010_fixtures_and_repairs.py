"""fixtures and repairs — 자산대장(옵션·집기·공용 설비) + 수리 이력 확장

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-17 06:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('fixtures',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('property_id', sa.Uuid(), nullable=False),
    sa.Column('unit_id', sa.Uuid(), nullable=True),
    sa.Column('category', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('brand', sa.String(length=50), nullable=True),
    sa.Column('model', sa.String(length=100), nullable=True),
    sa.Column('manufactured', sa.String(length=7), nullable=True),
    sa.Column('installed_on', sa.Date(), nullable=True),
    sa.Column('price', sa.BigInteger(), nullable=True),
    sa.Column('warranty_until', sa.Date(), nullable=True),
    sa.Column('owner', sa.String(length=20), nullable=False),
    sa.Column('replace_by', sa.String(length=7), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('removed_on', sa.Date(), nullable=True),
    sa.Column('removed_reason', sa.Text(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("owner IN ('landlord', 'tenant')", name='ck_fixtures_owner'),
    sa.CheckConstraint('price IS NULL OR price >= 0', name='ck_fixtures_price'),
    sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
    sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_fixtures_property_id'), 'fixtures', ['property_id'], unique=False)
    op.create_index(op.f('ix_fixtures_unit_id'), 'fixtures', ['unit_id'], unique=False)

    # 수리 이력: 건물 공용 수리도 담도록 property_id 를 두고 unit_id 는 비워도 되게
    op.add_column('maintenance_tickets', sa.Column('property_id', sa.Uuid(), nullable=True))
    op.execute("UPDATE maintenance_tickets SET property_id = "
               "(SELECT units.property_id FROM units WHERE units.id = maintenance_tickets.unit_id)")
    op.alter_column('maintenance_tickets', 'property_id', nullable=False)
    op.alter_column('maintenance_tickets', 'unit_id', existing_type=sa.Uuid(), nullable=True)
    op.add_column('maintenance_tickets', sa.Column('fixture_id', sa.Uuid(), nullable=True))
    op.add_column('maintenance_tickets', sa.Column('reported_on', sa.Date(), nullable=True))
    # 날짜는 한국 시각 기준 (저장은 UTC)
    op.execute("UPDATE maintenance_tickets SET reported_on = CAST(created_at AT TIME ZONE 'Asia/Seoul' AS DATE)")
    op.alter_column('maintenance_tickets', 'reported_on', nullable=False)
    op.add_column('maintenance_tickets', sa.Column('completed_on', sa.Date(), nullable=True))
    op.add_column('maintenance_tickets', sa.Column('vendor', sa.String(length=100), nullable=True))
    op.add_column('maintenance_tickets', sa.Column('cost', sa.BigInteger(), nullable=True))
    op.add_column('maintenance_tickets', sa.Column('payer', sa.String(length=20), nullable=False,
                                                   server_default='undecided'))
    op.alter_column('maintenance_tickets', 'payer', server_default=None)
    op.add_column('maintenance_tickets', sa.Column('note', sa.Text(), nullable=True))
    op.create_index(op.f('ix_maintenance_tickets_property_id'), 'maintenance_tickets', ['property_id'], unique=False)
    op.create_index(op.f('ix_maintenance_tickets_fixture_id'), 'maintenance_tickets', ['fixture_id'], unique=False)
    op.create_foreign_key('fk_maintenance_tickets_property_id', 'maintenance_tickets', 'properties',
                          ['property_id'], ['id'])
    op.create_foreign_key('fk_maintenance_tickets_fixture_id', 'maintenance_tickets', 'fixtures',
                          ['fixture_id'], ['id'])
    op.create_check_constraint('ck_maintenance_cost', 'maintenance_tickets', 'cost IS NULL OR cost >= 0')
    op.create_check_constraint('ck_maintenance_payer', 'maintenance_tickets',
                               "payer IN ('landlord', 'tenant', 'undecided')")


def downgrade() -> None:
    op.drop_constraint('ck_maintenance_payer', 'maintenance_tickets', type_='check')
    op.drop_constraint('ck_maintenance_cost', 'maintenance_tickets', type_='check')
    op.drop_constraint('fk_maintenance_tickets_fixture_id', 'maintenance_tickets', type_='foreignkey')
    op.drop_constraint('fk_maintenance_tickets_property_id', 'maintenance_tickets', type_='foreignkey')
    op.drop_index(op.f('ix_maintenance_tickets_fixture_id'), table_name='maintenance_tickets')
    op.drop_index(op.f('ix_maintenance_tickets_property_id'), table_name='maintenance_tickets')
    for col in ('note', 'payer', 'cost', 'vendor', 'completed_on', 'reported_on', 'fixture_id'):
        op.drop_column('maintenance_tickets', col)
    # 건물 공용 수리(unit_id 없음)는 되돌린 스키마에 담을 수 없어 지운다
    op.execute("DELETE FROM maintenance_tickets WHERE unit_id IS NULL")
    op.alter_column('maintenance_tickets', 'unit_id', existing_type=sa.Uuid(), nullable=False)
    op.drop_column('maintenance_tickets', 'property_id')
    op.drop_index(op.f('ix_fixtures_unit_id'), table_name='fixtures')
    op.drop_index(op.f('ix_fixtures_property_id'), table_name='fixtures')
    op.drop_table('fixtures')
