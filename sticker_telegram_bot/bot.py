import logging
import re
from typing import Dict, Optional
from telegram import InputSticker, Update, InlineKeyboardButton, InlineKeyboardMarkup
import telegram
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode
from PIL import Image
import io
import emoji

from sticker_telegram_bot.config import Config

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


class StickerBot:
    """Telegram bot for managing sticker packs."""

    PACK_PREFIX = "pack_"
    CALLBACK_DATA_SEPARATOR = "|"

    def __init__(self):
        self.application: Optional[Application] = None
        self.pending_stickers: Dict[int, Dict] = {}

    @staticmethod
    def is_chat_allowed(chat_id: int) -> bool:
        if Config.ALLOWED_CHAT_IDS is None:
            return True
        return chat_id in Config.ALLOWED_CHAT_IDS

    @staticmethod
    def make_sticker_set_name(title: str, username: str) -> str:
        cleaned_title = re.sub(r"\s+", "_", title)
        cleaned_title = re.sub(r"[^A-Za-z0-9_]", "", cleaned_title)
        cleaned_title = re.sub(r"_+", "_", cleaned_title)
        cleaned_title = re.sub(
            r"^([^A-Za-z]+)", "", cleaned_title
        )  # Remove leading non-letters
        cleaned_title = cleaned_title.rstrip("_")
        return f"{cleaned_title}_by_{username}"

    def start(self):
        """Initialize and start the bot."""
        # Validate configuration
        Config.validate()

        # Create application
        self.application = (
            Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()
        )

        # Add handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.start_command))
        self.application.add_handler(
            CommandHandler("sticker", self.handle_sticker_command)
        )
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_emoji_response)
        )
        self.application.add_handler(
            CallbackQueryHandler(
                self.handle_sticker_pack_selection,
                pattern=rf"^{re.escape(self.PACK_PREFIX)}",
            )
        )

        logger.info("Bot started successfully")

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        if update.message is None or not self.is_chat_allowed(update.message.chat_id):
            return

        welcome_message = (
            "🐐 Hello friends.\n\n"
            "To add an image to a sticker pack:\n"
            "1. Reply to an image with the command '/sticker'\n"
            "2. Send an emoji for the sticker\n"
            "3. Select which sticker pack to add it to\n"
            "4. The sticker will be added to your chosen pack\n\n"
        )
        await update.message.reply_text(welcome_message)

    async def handle_sticker_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle '/sticker' command when replied to an image."""
        if update.message is None or not self.is_chat_allowed(update.message.chat_id):
            return

        # Check if this is a reply to another message
        if not update.message.reply_to_message:
            await update.message.reply_text(
                "❌ Please reply to an image with the /sticker command.",
                reply_to_message_id=update.message.message_id,
            )
            return

        replied_message = update.message.reply_to_message

        # Check if the replied message contains an image
        if not (replied_message.photo or replied_message.document):
            await update.message.reply_text(
                "❌ The message you replied to doesn't contain an image. Please reply to an image.",
                reply_to_message_id=update.message.message_id,
            )
            return

        # Get the image file
        if replied_message.photo:
            # Get the highest quality photo (last in the list)
            photo = replied_message.photo[-1]
            file_id = photo.file_id
        elif replied_message.document:
            # Check if document is an image
            if (
                not replied_message.document.mime_type
                or not replied_message.document.mime_type.startswith("image/")
            ):
                await update.message.reply_text(
                    "❌ The file you replied to is not an image. Please reply to an image.",
                    reply_to_message_id=update.message.message_id,
                )
                return
            file_id = replied_message.document.file_id

        # Store pending sticker information (waiting for emoji)
        user_id = update.message.from_user.id if update.message.from_user else None
        if user_id is None:
            await update.message.reply_text(
                "❌ Could not determine user.",
                reply_to_message_id=update.message.message_id,
            )
            return

        self.pending_stickers[user_id] = {
            "message_id": replied_message.message_id,
            "file_id": file_id,
            "chat_id": update.message.chat_id,
            "user_message_id": update.message.message_id,
            "waiting_for_emoji": True,
        }

        await update.message.reply_text(
            "📸 Great! Now just reply to this message with a single emoji for this sticker, like 🗿, 🔫, or 💩.",
            reply_to_message_id=update.message.message_id,
        )

    async def handle_emoji_response(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle emoji response from user."""
        if update.message is None or not self.is_chat_allowed(update.message.chat_id):
            return

        user_id = update.message.from_user.id if update.message.from_user else None
        if user_id is None:
            return

        # Check if user has a pending sticker waiting for emoji
        if user_id not in self.pending_stickers or not self.pending_stickers[
            user_id
        ].get("waiting_for_emoji"):
            return

        emoji_text = update.message.text.strip() if update.message.text else ""

        # Validate that it's a single emoji using proper emoji detection
        if not emoji_text or not emoji.is_emoji(emoji_text):
            await update.message.reply_text(
                "❌ Please send just a single emoji (like 🗿, 🔫, or 💩)",
                reply_to_message_id=update.message.message_id,
            )
            return

        # Store the emoji and mark as ready for pack selection
        self.pending_stickers[user_id]["emoji"] = emoji_text
        self.pending_stickers[user_id]["waiting_for_emoji"] = False

        # Create inline keyboard with sticker pack options
        keyboard = []
        for pack in Config.STICKER_PACKS:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        pack,
                        callback_data=f"{self.PACK_PREFIX}{pack}{self.CALLBACK_DATA_SEPARATOR}{user_id}",
                    )
                ]
            )

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"📦 Choose a sticker pack to add this image with emoji {emoji_text}:",
            reply_markup=reply_markup,
            reply_to_message_id=update.message.message_id,
        )

    async def handle_sticker_pack_selection(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle sticker pack selection from inline keyboard."""
        query = update.callback_query
        if query is None:
            return

        # Answer the callback query immediately to stop the loading animation
        await query.answer()

        # Check if chat is allowed using query.message.chat_id
        if query.message is None or not self.is_chat_allowed(query.message.chat.id):
            logger.warning(
                f"Chat not allowed: {query.message.chat.id if query.message else 'None'}"
            )
            return

        user_id = query.from_user.id if query.from_user else None
        if user_id is None:
            logger.error("No user found in callback query. This shouldn't happen")
            return

        if query.data is None:
            logger.error("No data found in callback query. This shouldn't happen")
            return

        callback_data = tuple(
            query.data.replace(self.PACK_PREFIX, "").split(self.CALLBACK_DATA_SEPARATOR)
        )
        if not all(callback_data):
            logger.error(
                "Incorrect data found in callback query. This shouldn't happen"
            )
            return

        selected_pack, callback_user_id = callback_data

        # user_id is already an int
        if int(callback_user_id) != user_id:
            logger.info("Someone is being a naughty boy. This sometimes happens.")
            return

        # Check if user has a pending sticker
        pending_data = self.pending_stickers.get(user_id)
        if pending_data is None:
            logger.warning(
                f"No pending sticker found for user {user_id}. This can happen if the user clicks the button multiple times before the sticker is added."
            )
            return

        # Validate pack selection
        if selected_pack not in Config.STICKER_PACKS:
            await query.edit_message_text("❌ Invalid sticker pack selected.")
            return

        try:
            # Get the file
            file = await context.bot.get_file(pending_data["file_id"])

            # Download the image
            image_data = await file.download_as_bytearray()

            # Process the image for sticker requirements
            processed_image = await self.process_image_for_sticker(bytes(image_data))

            # Use the emoji provided by the user
            emoji = pending_data.get("emoji", "😀")

            sticker_set_name = self.make_sticker_set_name(
                title=selected_pack, username=context.bot.username
            )

            # Add sticker to the pack
            await self.add_sticker_to_pack(
                context=context,
                sticker_set_name=sticker_set_name,
                sticker_set_title=selected_pack,
                image_data=processed_image,
                emoji=emoji,
            )

            # Clean up pending sticker
            del self.pending_stickers[user_id]

            # Log the exact message being sent for debugging
            success_message = (
                f"Thank you daddy 💕. Sticker added to "
                f'<a href="https://t.me/addstickers/{sticker_set_name}">{selected_pack}</a>.\n\n'
                "ℹ️ The sticker might not immediately appear in the pack. If it doesn't, try re-adding the pack and restarting the app a few times."
            )

            try:
                await query.edit_message_text(
                    success_message, parse_mode=ParseMode.HTML
                )
            except Exception as format_error:
                logger.warning(
                    f"HTML formatting failed, trying without formatting: {format_error}"
                )
                # Fallback to plain text without any formatting
                await query.edit_message_text(success_message)

        except Exception as e:
            logger.error(f"Error adding sticker to pack: {e}")
            await query.edit_message_text(
                f"🗿 Hey that's a nice sticker suggestion, too bad I ain't reading it 🗿. I'm just playin here's the error: {str(e)}"
            )

    async def process_image_for_sticker(self, image_data: bytes) -> bytes:
        """Process image to meet Telegram sticker requirements."""
        try:
            # Open image with PIL
            image = Image.open(io.BytesIO(image_data))

            # Convert to RGBA if necessary
            if image.mode != "RGBA":
                image = image.convert("RGBA")

            # Resize to Telegram's recommended sticker size (512x512)
            # Maintain aspect ratio
            max_size = 512
            ratio = min(max_size / image.width, max_size / image.height)
            new_size = (int(image.width * ratio), int(image.height * ratio))
            image = image.resize(new_size, Image.Resampling.LANCZOS)

            # Create a 512x512 canvas with transparent background
            canvas = Image.new("RGBA", (max_size, max_size), 0)

            # Center the image on the canvas
            x = (max_size - new_size[0]) // 2
            y = (max_size - new_size[1]) // 2
            canvas.paste(image, (x, y))

            # Convert back to bytes
            output = io.BytesIO()
            canvas.save(output, format="PNG")
            return output.getvalue()

        except Exception as e:
            logger.error(f"Error processing image: {e}")
            raise

    async def add_sticker_to_pack(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        sticker_set_name: str,
        sticker_set_title: str,
        image_data: bytes,
        emoji: str,
    ):
        """Add sticker to a sticker pack."""
        logger.info(f"Adding sticker to pack: {sticker_set_name} with emoji {emoji}")
        sticker = InputSticker(sticker=image_data, emoji_list=[emoji], format="static")

        try:
            # Create sticker set if it doesn't exist
            try:
                await context.bot.create_new_sticker_set(
                    user_id=Config.STICKER_PACK_OWNER_USER_ID,
                    name=sticker_set_name,
                    title=sticker_set_title,
                    stickers=[sticker],
                )
            except telegram.error.TelegramError as e:
                logger.error(str(e))
                # Sticker set exists, add sticker to it
                await context.bot.add_sticker_to_set(
                    user_id=Config.STICKER_PACK_OWNER_USER_ID,
                    name=sticker_set_name,
                    sticker=sticker,
                )

        except Exception as e:
            logger.error(f"Error adding sticker to pack: {e}")
            raise e

    def run_polling(self):
        """Run the bot using polling."""
        if self.application is None:
            raise RuntimeError("Application is not initialized.")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

    def run_webhook(self):
        """Run the bot using webhooks."""
        if self.application is None:
            raise RuntimeError("Application is not initialized.")
        if not Config.WEBHOOK_URL:
            raise ValueError("WEBHOOK_URL must be set for webhook mode")
        if self.application.bot is None:
            raise RuntimeError("Bot is not initialized.")
        self.application.bot.set_webhook(url=Config.WEBHOOK_URL)
        self.application.run_webhook(
            listen=Config.API_HOST, port=Config.API_PORT, webhook_url=Config.WEBHOOK_URL
        )


# Global bot instance
bot = StickerBot()
