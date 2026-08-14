"""add supervisors.fit_explanation and opportunities field/subfield

Phase 4C stores HOW a supervisor's 0-100 fit was arrived at, so clicking the
score can show its reasoning instead of a bare number.

Phase 1 stamps each opportunity with the field profile it was crawled under —
the columns already existed in the model but were never populated; this keeps
older databases in step with the model definition.

Revision ID: d9c4b1a7e230
Revises: f1e2d3c4b5a6
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d9c4b1a7e230"
down_revision: Union[str, Sequence[str], None] = "f1e2d3c4b5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    # Guarded: these databases are also created straight from the models
    # (db.init.init_db), so on a fresh install the columns are already there.
    existing = _columns("supervisors")
    if "fit_explanation" not in existing:
        op.add_column("supervisors",
                      sa.Column("fit_explanation", sa.Text(), nullable=True))

    existing = _columns("opportunities")
    for name in ("field", "subfield"):
        if name not in existing:
            op.add_column("opportunities",
                          sa.Column(name, sa.String(length=128), nullable=True))


def downgrade() -> None:
    existing = _columns("supervisors")
    if "fit_explanation" in existing:
        op.drop_column("supervisors", "fit_explanation")
    # `field`/`subfield` on opportunities predate this revision in the model,
    # so they are intentionally not dropped here.
