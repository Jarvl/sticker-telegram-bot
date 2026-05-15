"""create sticker packs

Revision ID: 0001
Revises:
Create Date: 2026-05-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sticker_packs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_name", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=64), nullable=False),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("is_visible", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("telegram_name"),
    )
    op.create_index("ix_sticker_packs_chat_id", "sticker_packs", ["chat_id"])
    op.create_index(
        "ix_sticker_packs_owner_user_id", "sticker_packs", ["owner_user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_sticker_packs_owner_user_id", table_name="sticker_packs")
    op.drop_index("ix_sticker_packs_chat_id", table_name="sticker_packs")
    op.drop_table("sticker_packs")
