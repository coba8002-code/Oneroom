"""renewal notice — 계약 만료 안내 문구 (주임법 §6 갱신 통지)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-17 05:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('notification_settings', sa.Column('renewal_template', sa.Text(), nullable=True))
    op.add_column('notifications', sa.Column('term_end', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('notifications', 'term_end')
    op.drop_column('notification_settings', 'renewal_template')
