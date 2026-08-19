"""add api_keys tables

Revision ID: b7f2d0e91a23
Revises: a1b2c3d4e5f6
Create Date: 2026-08-08 13:00:00.000000

Adds: api_keys (SHA-256-hashed developer keys), api_key_usage (per-key/day
request rollup). (Sprint 08, Track A1 + B4.)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7f2d0e91a23'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('api_keys',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('key_prefix', sa.String(length=16), nullable=False),
    sa.Column('scopes', sa.Text(), nullable=True),
    sa.Column('quota_limit', sa.Integer(), nullable=True),
    sa.Column('rate_limit', sa.Integer(), nullable=True),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_api_keys_key_hash'), 'api_keys', ['key_hash'],
                    unique=True)
    op.create_index(op.f('ix_api_keys_user_id'), 'api_keys', ['user_id'],
                    unique=False)
    op.create_table('api_key_usage',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key_id', sa.Integer(), nullable=False),
    sa.Column('usage_date', sa.String(length=10), nullable=False),
    sa.Column('requests', sa.Integer(), nullable=False),
    sa.Column('rate_limited', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['key_id'], ['api_keys.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key_id', 'usage_date', name='uq_api_key_usage_key_date')
    )
    op.create_index(op.f('ix_api_key_usage_key_id'), 'api_key_usage',
                    ['key_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_api_key_usage_key_id'), table_name='api_key_usage')
    op.drop_table('api_key_usage')
    op.drop_index(op.f('ix_api_keys_user_id'), table_name='api_keys')
    op.drop_index(op.f('ix_api_keys_key_hash'), table_name='api_keys')
    op.drop_table('api_keys')
