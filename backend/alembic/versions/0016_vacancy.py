"""vacancy listings and activities — 공실 모집 조건·활동 기록

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-17 19:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0016'
down_revision: Union[str, None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('vacancy_activities',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('unit_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('happened_on', sa.Date(), nullable=False),
    sa.Column('agent_name', sa.String(length=100), nullable=True),
    sa.Column('agent_phone', sa.String(length=500), nullable=True),  # 암호문 (app.crypto.EncryptedString)
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vacancy_activities_unit_id'), 'vacancy_activities', ['unit_id'], unique=False)
    op.create_table('vacancy_listings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('unit_id', sa.Uuid(), nullable=False),
    sa.Column('asking_deposit', sa.BigInteger(), nullable=True),
    sa.Column('asking_rent', sa.BigInteger(), nullable=True),
    sa.Column('available_on', sa.Date(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('(asking_deposit IS NULL OR asking_deposit >= 0) AND (asking_rent IS NULL OR asking_rent >= 0)', name='ck_vacancy_listings_amounts'),
    sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('unit_id', name='uq_vacancy_listings_unit')
    )
    op.create_index(op.f('ix_vacancy_listings_unit_id'), 'vacancy_listings', ['unit_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_vacancy_listings_unit_id'), table_name='vacancy_listings')
    op.drop_table('vacancy_listings')
    op.drop_index(op.f('ix_vacancy_activities_unit_id'), table_name='vacancy_activities')
    op.drop_table('vacancy_activities')
