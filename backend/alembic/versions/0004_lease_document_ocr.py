"""lease document ocr

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-16 11:19:22.773845

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('lease_documents', sa.Column('original_name', sa.String(length=255), nullable=True))
    op.add_column('lease_documents', sa.Column('content_type', sa.String(length=50), nullable=True))
    op.add_column('lease_documents', sa.Column('sha256', sa.String(length=64), nullable=True))
    # 기존 행이 있어도 적용되도록 기본값 (이전 단계엔 OCR 이 없었으므로 not_configured)
    op.add_column('lease_documents', sa.Column('ocr_status', sa.String(length=20), nullable=False,
                                               server_default='not_configured'))
    op.add_column('lease_documents', sa.Column('verified_fields', sa.JSON(), nullable=True))
    op.create_index(op.f('ix_lease_documents_sha256'), 'lease_documents', ['sha256'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_lease_documents_sha256'), table_name='lease_documents')
    op.drop_column('lease_documents', 'verified_fields')
    op.drop_column('lease_documents', 'ocr_status')
    op.drop_column('lease_documents', 'sha256')
    op.drop_column('lease_documents', 'content_type')
    op.drop_column('lease_documents', 'original_name')
