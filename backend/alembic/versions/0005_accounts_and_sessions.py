"""accounts and sessions — 로그인 계정(비밀번호 해시·동의·MFA) + 세션

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-16 11:57:34.224860

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('auth_sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('user_agent', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_auth_sessions_user_id'), 'auth_sessions', ['user_id'], unique=False)
    op.add_column('users', sa.Column('name', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('password_hash', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('users', sa.Column('mfa_secret', sa.String(length=500), nullable=True))  # 암호문 (app.crypto.EncryptedString)
    op.add_column('users', sa.Column('mfa_enabled_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('terms_agreed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('privacy_agreed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('marketing_agreed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'last_login_at')
    op.drop_column('users', 'marketing_agreed_at')
    op.drop_column('users', 'privacy_agreed_at')
    op.drop_column('users', 'terms_agreed_at')
    op.drop_column('users', 'mfa_enabled_at')
    op.drop_column('users', 'mfa_secret')
    op.drop_column('users', 'is_active')
    op.drop_column('users', 'password_hash')
    op.drop_column('users', 'name')
    op.drop_index(op.f('ix_auth_sessions_user_id'), table_name='auth_sessions')
    op.drop_table('auth_sessions')
