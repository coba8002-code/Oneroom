"""org api keys — 화면에서 넣는 Anthropic API 키 (암호화, 백업 제외)

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-23 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0022'
down_revision: Union[str, None] = '0021'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'org_api_keys',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('key', sa.String(length=500), nullable=False),
        sa.Column('last4', sa.String(length=4), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'provider'),
    )
    op.create_index('ix_org_api_keys_organization_id', 'org_api_keys', ['organization_id'])


def downgrade() -> None:
    op.drop_index('ix_org_api_keys_organization_id', table_name='org_api_keys')
    op.drop_table('org_api_keys')
