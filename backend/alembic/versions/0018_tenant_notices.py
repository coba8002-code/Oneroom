"""tenant notices and building contact — 임차인 화면 공지·집주인 연락처

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-18 02:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0018'
down_revision: Union[str, None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('tenant_notices',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('property_id', sa.Uuid(), nullable=False),
    sa.Column('unit_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=100), nullable=False),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('starts_on', sa.Date(), nullable=False),
    sa.Column('ends_on', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
    sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tenant_notices_property_id'), 'tenant_notices', ['property_id'], unique=False)
    op.create_index(op.f('ix_tenant_notices_unit_id'), 'tenant_notices', ['unit_id'], unique=False)
    op.add_column('properties', sa.Column('contact_phone', sa.String(length=500), nullable=True))  # 암호문
    op.add_column('properties', sa.Column('contact_note', sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column('properties', 'contact_note')
    op.drop_column('properties', 'contact_phone')
    op.drop_index(op.f('ix_tenant_notices_unit_id'), table_name='tenant_notices')
    op.drop_index(op.f('ix_tenant_notices_property_id'), table_name='tenant_notices')
    op.drop_table('tenant_notices')
