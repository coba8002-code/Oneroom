"""rental business — 등록임대사업자 정보·등록 임대주택·임대보증금 보증

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-22 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0021'
down_revision: Union[str, None] = '0020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'rental_business_profiles',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('registration_no', sa.String(length=50), nullable=True),
        sa.Column('registered_on', sa.Date(), nullable=True),
        sa.Column('tax_business_no', sa.String(length=20), nullable=True),
        sa.Column('increase_cap_pct', sa.Numeric(5, 2), nullable=False),
        sa.Column('report_months', sa.Integer(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id'),
    )
    op.create_table(
        'registered_rentals',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('property_id', sa.Uuid(), nullable=False),
        sa.Column('unit_id', sa.Uuid(), nullable=True),
        sa.Column('housing_type', sa.String(length=30), nullable=False),
        sa.Column('rental_type', sa.String(length=30), nullable=False),
        sa.Column('registered_on', sa.Date(), nullable=True),
        sa.Column('rental_start_on', sa.Date(), nullable=True),
        sa.Column('obligation_years', sa.Integer(), nullable=True),
        sa.Column('lien_status', sa.String(length=10), nullable=True),
        sa.Column('lien_done_on', sa.Date(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("lien_status IS NULL OR lien_status IN ('done', 'na')", name='ck_registered_rentals_lien'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id']),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_registered_rentals_organization_id', 'registered_rentals', ['organization_id'])
    op.create_index('ix_registered_rentals_property_id', 'registered_rentals', ['property_id'])
    op.create_table(
        'rental_guarantees',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('registration_id', sa.Uuid(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('policy_no', sa.String(length=50), nullable=True),
        sa.Column('start_on', sa.Date(), nullable=True),
        sa.Column('end_on', sa.Date(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['registration_id'], ['registered_rentals.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_rental_guarantees_registration_id', 'rental_guarantees', ['registration_id'])


def downgrade() -> None:
    op.drop_index('ix_rental_guarantees_registration_id', table_name='rental_guarantees')
    op.drop_table('rental_guarantees')
    op.drop_index('ix_registered_rentals_property_id', table_name='registered_rentals')
    op.drop_index('ix_registered_rentals_organization_id', table_name='registered_rentals')
    op.drop_table('registered_rentals')
    op.drop_table('rental_business_profiles')
    op.execute("DELETE FROM lease_checks WHERE key IN ('rental_contract_report', 'standard_contract')")
