"""Store expression risk flags reported by the scorer."""
from alembic import op
import sqlalchemy as sa

revision = "20261118_0049"
down_revision = "20261117_0049"
branch_labels = depends_on = None


def upgrade():
    op.add_column("evaluations", sa.Column("risk_flags", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("evaluations") as batch:
        batch.drop_column("risk_flags")
