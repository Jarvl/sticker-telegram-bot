import os
from typing import List, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Configuration class for the Telegram Sticker Bot."""

    # Telegram Bot Configuration
    TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
    TELEGRAM_BOT_USERNAME: str = os.environ["TELEGRAM_BOT_USERNAME"]

    # Sticker Pack Configuration
    STICKER_PACKS: List[str] = [
        pack.strip() for pack in os.environ["STICKER_PACKS"].split(",") if pack.strip()
    ]
    STICKER_PACK_OWNER_USER_ID: int = int(os.environ["STICKER_PACK_OWNER_USER_ID"])

    # Bot running mode
    MODE: str = os.getenv("MODE", "polling")

    # API Configuration
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))

    # Webhook Configuration
    WEBHOOK_URL: Optional[str] = os.getenv("WEBHOOK_URL")

    # New: Allowlist of chat IDs
    ALLOWED_CHATS_ENV = os.getenv("ALLOWED_CHAT_IDS", "")
    ALLOWED_CHAT_IDS: Optional[List[int]] = (
        [
            int(cid.strip())
            for cid in os.getenv("ALLOWED_CHAT_IDS", "").split(",")
            if cid.strip()
        ]
        if ALLOWED_CHATS_ENV
        else None
    )

    @classmethod
    def validate(cls):
        """Validate required configuration."""
        if not cls.TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        if not cls.TELEGRAM_BOT_USERNAME:
            raise ValueError("TELEGRAM_BOT_USERNAME is required")

        if not cls.STICKER_PACKS or not any(cls.STICKER_PACKS):
            raise ValueError("At least one sticker pack must be configured")

        if cls.API_PORT < 1 or cls.API_PORT > 65535:
            raise ValueError("API_PORT must be a valid port number")
        # ALLOWED_CHATS is optional, but if present, must be a list of ints
        if cls.ALLOWED_CHAT_IDS is not None and not all(
            isinstance(cid, int) for cid in cls.ALLOWED_CHAT_IDS
        ):
            raise ValueError(
                "ALLOWED_CHAT_IDS must be a comma-separated list of integers"
            )

        return True
