#!/usr/bin/env python3
"""
Telegram Sticker Bot - Main Entry Point

This script can run the bot in different modes:
- Polling mode: Direct bot operation
- Webhook mode: Bot with webhook support
"""

import argparse
import logging
import sys

from sticker_telegram_bot.config import Config
from sticker_telegram_bot.bot import bot

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

MODE_CHOICES = ["polling", "webhook"]


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Telegram Sticker Bot")
    parser.add_argument(
        "--config-check", action="store_true", help="Check configuration and exit"
    )

    args = parser.parse_args()

    try:
        # Validate configuration
        Config.validate()
        logger.info("Configuration validated successfully")

        if args.config_check:
            logger.info("Configuration check passed. Exiting.")
            return 0

        if Config.MODE == "polling":
            logger.info("Starting polling")
            bot.start()
            bot.run_polling()
        elif Config.MODE == "webhook":
            logger.info("Starting webhook")
            bot.start()
            bot.run_webhook()
        else:
            logger.error(f"Unknown mode: {Config.MODE}")
            return 1

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        return 0
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
