"""Persist interview assessment context and report consistency state."""
from alembic import op
import sqlalchemy as sa
import re

revision = "20261117_0049"
down_revision = "20261117_0048"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("kind", sa.String(12), nullable=False, server_default="DIALOGUE"))
    with op.batch_alter_table("training_sessions") as batch:
        batch.add_column(sa.Column("assessment_context", sa.JSON(), nullable=True))
    with op.batch_alter_table("evaluations") as batch:
        batch.add_column(sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("assessment", sa.JSON(), nullable=True))
    db = op.get_bind()
    messages = sa.table("messages", sa.column("id", sa.String()), sa.column("speaker", sa.String()),
                        sa.column("content", sa.Text()), sa.column("kind", sa.String()))
    repeat = re.compile(r"(再说(一遍|一次)|没听清|没听懂|重复(一下|一遍)?|能再说|pardon|repeat|say that again|didn'?t catch)", re.IGNORECASE)
    for row in db.execute(sa.select(messages.c.id, messages.c.speaker, messages.c.content)).mappings():
        text = (row["content"] or "").strip()
        match = repeat.search(text)
        control = row["speaker"] == "USER" and match and len(text) <= 40 and not text[match.end():].strip("？?。.!！一下遍次吗呢可以好谢你了 ")
        if control or row["speaker"] == "AI" and text.startswith("当然，我再说一遍："):
            db.execute(messages.update().where(messages.c.id == row["id"]).values(kind="CONTROL"))
    reports = sa.table("evaluations", sa.column("id", sa.String()), sa.column("logic_score", sa.Integer()),
                       sa.column("speech_stats", sa.JSON()), sa.column("review_required", sa.Boolean()))
    for report in db.execute(sa.select(reports.c.id, reports.c.speech_stats).where(reports.c.logic_score == 5)).mappings():
        checks = (report["speech_stats"] or {}).get("technicalChecks", [])
        if any(isinstance(check, dict) and check.get("verdict") == "ERROR" for check in checks):
            db.execute(reports.update().where(reports.c.id == report["id"]).values(review_required=True))


def downgrade():
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("kind")
    with op.batch_alter_table("evaluations") as batch:
        batch.drop_column("assessment")
        batch.drop_column("review_required")
    with op.batch_alter_table("training_sessions") as batch:
        batch.drop_column("assessment_context")
