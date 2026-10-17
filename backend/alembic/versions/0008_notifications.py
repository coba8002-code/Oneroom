"""notifications for alimtalk — 알림 문구·승인·발송 기록, 사업장별 알림 설정

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-17 02:00:05.825984

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('notification_settings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('grace_days', sa.Integer(), nullable=True),
    sa.Column('rent_template', sa.Text(), nullable=True),
    sa.Column('overdue_template', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id')
    )
    op.add_column('notifications', sa.Column('lease_id', sa.Uuid(), nullable=True))
    op.add_column('notifications', sa.Column('charge_id', sa.Uuid(), nullable=True))
    op.add_column('notifications', sa.Column('body', sa.Text(), nullable=True))
    op.add_column('notifications', sa.Column('sent_via', sa.String(length=20), nullable=True))
    op.add_column('notifications', sa.Column('error', sa.Text(), nullable=True))
    op.create_index(op.f('ix_notifications_charge_id'), 'notifications', ['charge_id'], unique=False)
    op.create_foreign_key('fk_notifications_lease_id', 'notifications', 'leases', ['lease_id'], ['id'])
    op.create_foreign_key('fk_notifications_charge_id', 'notifications', 'charges', ['charge_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_notifications_charge_id', 'notifications', type_='foreignkey')
    op.drop_constraint('fk_notifications_lease_id', 'notifications', type_='foreignkey')
    op.drop_index(op.f('ix_notifications_charge_id'), table_name='notifications')
    op.drop_column('notifications', 'error')
    op.drop_column('notifications', 'sent_via')
    op.drop_column('notifications', 'body')
    op.drop_column('notifications', 'charge_id')
    op.drop_column('notifications', 'lease_id')
    op.drop_table('notification_settings')
