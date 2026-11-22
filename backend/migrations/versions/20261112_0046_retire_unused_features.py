"""Remove retired feature tables; historical migrations remain available.

Downgrade restores schemas only. Retired feature records are removed on upgrade.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261112_0046"
down_revision = "20261109_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("scripts") as batch:
        batch.alter_column("scene_id", existing_type=sa.String(36), nullable=True)
    for table in ("stories", "resume_diagnoses", "group_interviews", "coding_submissions"):
        op.drop_table(table)


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM scripts WHERE scene_id IS NULL"))
    with op.batch_alter_table("scripts") as batch:
        batch.alter_column("scene_id", existing_type=sa.String(36), nullable=False)
    op.create_table(
        "stories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(60), nullable=False),
        sa.Column("situation", sa.Text(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("source_session_id", sa.String(36), nullable=True),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_stories_user_id", "stories", ["user_id"])
    op.create_table(
        "resume_diagnoses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=180), nullable=False, server_default=""),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coverage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("jd_excerpt", sa.Text(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_resume_diagnoses_user_id", "resume_diagnoses", ["user_id"])
    op.create_index("ix_resume_diagnoses_created_at", "resume_diagnoses", ["created_at"])
    op.create_table(
        "group_interviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("topic_id", sa.String(length=40), nullable=False),
        sa.Column("topic_title", sa.String(length=120), nullable=False),
        sa.Column("topic_prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("turns", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_group_interviews_user_id", "group_interviews", ["user_id"])
    op.create_index("ix_group_interviews_status", "group_interviews", ["status"])
    op.create_index("ix_group_interviews_created_at", "group_interviews", ["created_at"])
    op.create_table(
        "coding_submissions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("problem_id", sa.String(length=60), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("results", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_coding_submissions_user_id", "coding_submissions", ["user_id"])
    op.create_index("ix_coding_submissions_problem_id", "coding_submissions", ["problem_id"])
    op.create_index("ix_coding_submissions_created_at", "coding_submissions", ["created_at"])
