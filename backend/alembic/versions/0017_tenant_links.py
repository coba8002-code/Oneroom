"""tenant links and tenant repair requests — 임차인 화면 초대 링크·수리 요청 출처

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-18 01:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0017'
down_revision: Union[str, None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('tenant_links',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('lease_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['lease_id'], ['leases.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_tenant_links_lease_id'), 'tenant_links', ['lease_id'], unique=False)
    op.add_column('maintenance_tickets', sa.Column('source', sa.String(length=20), server_default='admin', nullable=False))


def downgrade() -> None:
    op.drop_column('maintenance_tickets', 'source')
    op.drop_index(op.f('ix_tenant_links_lease_id'), table_name='tenant_links')
    op.drop_table('tenant_links')
