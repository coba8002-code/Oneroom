"""routine tasks — 정기 점검·소모품 일정

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-17 18:40:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0015'
down_revision: Union[str, None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('routine_tasks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('property_id', sa.Uuid(), nullable=False),
    sa.Column('unit_id', sa.Uuid(), nullable=True),
    sa.Column('fixture_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=100), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=False),
    sa.Column('interval_months', sa.Integer(), nullable=True),
    sa.Column('next_due_on', sa.Date(), nullable=True),
    sa.Column('vendor', sa.String(length=100), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('interval_months IS NULL OR interval_months BETWEEN 1 AND 120', name='ck_routine_tasks_interval'),
    sa.ForeignKeyConstraint(['fixture_id'], ['fixtures.id'], ),
    sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
    sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_routine_tasks_fixture_id'), 'routine_tasks', ['fixture_id'], unique=False)
    op.create_index(op.f('ix_routine_tasks_property_id'), 'routine_tasks', ['property_id'], unique=False)
    op.create_index(op.f('ix_routine_tasks_unit_id'), 'routine_tasks', ['unit_id'], unique=False)
    op.create_table('routine_logs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.Uuid(), nullable=False),
    sa.Column('done_on', sa.Date(), nullable=False),
    sa.Column('cost', sa.BigInteger(), nullable=True),
    sa.Column('vendor', sa.String(length=100), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('prev_next_due_on', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('cost IS NULL OR cost >= 0', name='ck_routine_logs_cost'),
    sa.ForeignKeyConstraint(['task_id'], ['routine_tasks.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_routine_logs_task_id'), 'routine_logs', ['task_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_routine_logs_task_id'), table_name='routine_logs')
    op.drop_table('routine_logs')
    op.drop_index(op.f('ix_routine_tasks_unit_id'), table_name='routine_tasks')
    op.drop_index(op.f('ix_routine_tasks_property_id'), table_name='routine_tasks')
    op.drop_index(op.f('ix_routine_tasks_fixture_id'), table_name='routine_tasks')
    op.drop_table('routine_tasks')
