import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Configuration class for the Telegram Sticker Bot."""

    # Telegram Bot Configuration
    TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
    TELEGRAM_BOT_USERNAME: str = os.environ["TELEGRAM_BOT_USERNAME"]

    # Database Configuration
    DATABASE_URL: str = os.environ["DATABASE_URL"]

    # Bot running mode
    MODE: str = os.getenv("MODE", "polling")

    # API Configuration
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))

    # Webhook Configuration
    WEBHOOK_URL: Optional[str] = os.getenv("WEBHOOK_URL")

    @classmethod
    def validate(cls):
        """Validate required configuration."""
        if not cls.TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        if not cls.TELEGRAM_BOT_USERNAME:
            raise ValueError("TELEGRAM_BOT_USERNAME is required")

        if not cls.DATABASE_URL:
            raise ValueError("DATABASE_URL is required")
        if not cls.DATABASE_URL.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must use postgresql+psycopg://")

        if cls.API_PORT < 1 or cls.API_PORT > 65535:
            raise ValueError("API_PORT must be a valid port number")
        return True
