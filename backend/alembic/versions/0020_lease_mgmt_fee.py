"""lease mgmt_fee — 정액 관리비를 월세와 따로 (charges.kind='mgmt'), 공실 광고의 관리비

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-18 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0020'
down_revision: Union[str, None] = '0019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 기존 계약은 비워 둔다 (= 따로 적지 않음). 월세 값은 그대로라 청구·매칭이 바뀌지 않는다
    op.add_column('leases', sa.Column('mgmt_fee', sa.BigInteger(), nullable=True))
    op.create_check_constraint('ck_leases_mgmt_fee', 'leases', 'mgmt_fee IS NULL OR mgmt_fee >= 0')
    op.add_column('vacancy_listings', sa.Column('asking_mgmt_fee', sa.BigInteger(), nullable=True))
    op.add_column('vacancy_listings', sa.Column('mgmt_includes', sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column('vacancy_listings', 'mgmt_includes')
    op.drop_column('vacancy_listings', 'asking_mgmt_fee')
    op.execute("DELETE FROM payments WHERE charge_id IN (SELECT id FROM charges WHERE kind = 'mgmt')")
    op.execute("DELETE FROM charges WHERE kind = 'mgmt'")
    op.drop_constraint('ck_leases_mgmt_fee', 'leases', type_='check')
    op.drop_column('leases', 'mgmt_fee')
