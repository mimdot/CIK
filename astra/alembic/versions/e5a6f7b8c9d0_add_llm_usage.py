"""add llm_usage table

Revision ID: e5a6f7b8c9d0
Revises: b7f2d0e91a23
Create Date: 2026-08-09 00:00:00.000000

Adds: llm_usage (per-call LLM accounting for the cost guard + admin
dashboard). (Sprint 09, Track C1.)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a6f7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'b7f2d0e91a23'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('llm_usage',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('feature', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('prompt_tokens', sa.Integer(), nullable=False),
    sa.Column('completion_tokens', sa.Integer(), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_llm_usage_created_at'), 'llm_usage',
                    ['created_at'], unique=False)
    op.create_index(op.f('ix_llm_usage_user_id'), 'llm_usage', ['user_id'],
                    unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_llm_usage_user_id'), table_name='llm_usage')
    op.drop_index(op.f('ix_llm_usage_created_at'), table_name='llm_usage')
    op.drop_table('llm_usage')
