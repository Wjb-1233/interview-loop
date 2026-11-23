"""drop share revocations

分享链接功能已在 65ed2ae 整体下线，撤销表随之移除。

Revision ID: 20261120_0051
Revises: 20261119_0050
"""

from alembic import op
import sqlalchemy as sa

revision: str = "20261120_0051"
down_revision: str | None = "20261119_0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "share_revocations" not in inspector.get_table_names():
        return
    # 索引随表一起消失：MySQL 上 DROP TABLE 会连带索引，这里显式先删以避免方言差异
    for index in inspector.get_indexes("share_revocations"):
        op.drop_index(index["name"], table_name="share_revocations")
    op.drop_table("share_revocations")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "share_revocations" in inspector.get_table_names():
        return
    op.create_table(
        "share_revocations",
        sa.Column("token_sig", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("token_sig"),
    )
    op.create_index("ix_share_revocations_session_id", "share_revocations", ["session_id"])
