"""add account consent columns

Revision ID: f1e2d3c4b5a6
Revises: e5a6f7b8c9d0
Create Date: 2026-08-10 12:00:00.000000

Adds users.marketing_consent / users.consent_updated_at for the
GET/PUT /api/account/consent data-subject endpoints (Sprint 10, D2).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1e2d3c4b5a6'
down_revision: Union[str, Sequence[str], None] = 'e5a6f7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('marketing_consent', sa.Boolean(),
                                     nullable=True))
    op.add_column('users', sa.Column('consent_updated_at', sa.DateTime(),
                                     nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'consent_updated_at')
    op.drop_column('users', 'marketing_consent')
