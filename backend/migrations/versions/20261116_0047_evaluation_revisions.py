"""Preserve previous report revisions without changing report identifiers."""
from alembic import op
import sqlalchemy as sa

revision = "20261116_0047"
down_revision = "20261112_0046"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("evaluations", sa.Column("revision_history", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("evaluations") as batch:
        batch.drop_column("revision_history")
