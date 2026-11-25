"""Preserve subsecond interview and plan-task ordering on MySQL."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "20261124_0052"
down_revision = "20261120_0051"
branch_labels = depends_on = None

APPLICATION_TABLES = {
    "users", "refresh_tokens", "scenes", "favorites", "scripts",
    "password_reset_requests", "skill_states", "mistake_states", "analysis_tasks",
    "training_sessions", "resume_contexts", "messages", "evaluations", "evaluation_evidence",
    "ability_attempts", "courses", "course_progress", "training_plans", "lesson_video_jobs",
    "audit_logs", "model_usage_daily", "password_reset_tokens",
}


def _precision(digits):
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return
    inspector = sa.inspect(bind)
    for table in inspector.get_table_names():
        if table not in APPLICATION_TABLES:
            continue
        for column in inspector.get_columns(table):
            if isinstance(column["type"], mysql.DATETIME):
                op.alter_column(table, column["name"], type_=mysql.DATETIME(fsp=digits),
                                existing_type=column["type"], existing_nullable=column["nullable"])


def upgrade():
    _precision(6)


def downgrade():
    _precision(0)
