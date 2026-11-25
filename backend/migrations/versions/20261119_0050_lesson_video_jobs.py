"""Queue micro-course video rendering as a background job."""
from alembic import op
import sqlalchemy as sa

revision = "20261119_0050"
down_revision = "20261118_0049"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "lesson_video_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("training_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_key", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("engine", sa.String(20), nullable=True),
        sa.Column("video_key", sa.String(80), nullable=True),
        sa.Column("chapters", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_lesson_video_jobs_plan_task", "lesson_video_jobs", ["plan_id", "task_key"])


def downgrade():
    # MySQL uses this index for plan_id's FK. Dropping the table removes its
    # constraints/indexes together; dropping the supporting index first fails.
    op.drop_table("lesson_video_jobs")
