"""Freeze historical plan task contracts; retire unfinished legacy video jobs."""
from alembic import op
import sqlalchemy as sa
from migrations.plan_tasks_v2 import LABELS, upgrade_tasks

revision = "20261117_0048"
down_revision = "20261116_0047"
branch_labels = depends_on = None


def upgrade():
    op.add_column("training_plans", sa.Column("tasks_version", sa.Integer(), nullable=False, server_default="1"))
    db = op.get_bind()
    plans = sa.table("training_plans", sa.column("id"), sa.column("user_id"), sa.column("focus_dimension"), sa.column("status"), sa.column("tasks", sa.JSON()), sa.column("tasks_version", sa.Integer()))
    courses = list(db.execute(sa.text("SELECT id, dimension, title, content FROM courses WHERE active = true ORDER BY created_at, id")).mappings())
    sources = {r["id"]: dict(r) for r in db.execute(sa.text("SELECT id, user_id, scene_id, channel, depth FROM training_sessions")).mappings()}
    for plan in list(db.execute(sa.select(plans)).mappings()):
        owned = {k:v for k,v in sources.items() if v["user_id"] == plan["user_id"]}
        course = next((c for c in courses if c["dimension"] == plan["focus_dimension"]), None)
        focus = LABELS.get(plan["focus_dimension"], plan["focus_dimension"])
        tasks = upgrade_tasks(plan["tasks"], focus, course, owned, plan["status"] == "ACTIVE")
        db.execute(plans.update().where(plans.c.id == plan["id"]).values(tasks=tasks, focus_dimension=focus, tasks_version=2))
    with op.batch_alter_table("training_plans") as batch:
        batch.alter_column("tasks_version", existing_type=sa.Integer(), server_default="2", existing_nullable=False)
    db.execute(sa.text("UPDATE analysis_tasks SET status='FAILED', stage='旧录像分析已停用', error='VIDEO_UPLOAD_RETIRED' WHERE kind='VIDEO_INTERVIEW' AND status IN ('PENDING','RUNNING')"))


def downgrade():
    # Materialized JSON remains readable by the previous compatibility reader.
    with op.batch_alter_table("training_plans") as batch:
        batch.drop_column("tasks_version")
