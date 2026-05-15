"""allow pack imports per chat

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "sticker_packs_telegram_name_key",
        "sticker_packs",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_sticker_packs_name_chat",
        "sticker_packs",
        ["telegram_name", "chat_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_sticker_packs_name_chat",
        "sticker_packs",
        type_="unique",
    )
    op.create_unique_constraint(
        "sticker_packs_telegram_name_key",
        "sticker_packs",
        ["telegram_name"],
    )
