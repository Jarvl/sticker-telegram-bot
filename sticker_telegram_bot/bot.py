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
from moviepy.editor import VideoFileClip
import moviepy.video.fx.all as vfx
import tempfile
import os

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

    # Message templates
    EMOJI_PROMPT_BASE = (
        "Great! Now just reply to this message with a single emoji for this sticker, "
        "like 🗿, 🔫, or 💩.\n\n❌ Use '/cancel' to cancel this request."
    )

    def __init__(self):
        self.application: Optional[Application] = None
        self.pending_stickers: Dict[int, Dict] = {}

    def _get_user_id(self, update: Update) -> Optional[int]:
        """Extract and validate user_id from update. Returns None if invalid."""
        if update.message is None or update.message.from_user is None:
            return None
        return update.message.from_user.id

    async def _validate_user_id(
        self, update: Update, user_id: Optional[int]
    ) -> bool:
        """
        Validate user_id and send error message if invalid.
        Returns True if user_id is valid, False if invalid (caller should abort).
        """
        if user_id is None:
            if update.message:
                await update.message.reply_text(
                    "❌ Could not determine user.",
                    reply_to_message_id=update.message.message_id,
                )
            return False
        return True

    @staticmethod
    def is_chat_allowed(chat_id: int) -> bool:
        if Config.ALLOWED_CHAT_IDS is None:
            return True
        return chat_id in Config.ALLOWED_CHAT_IDS

    @staticmethod
    def is_direct_message_allowed(chat_id: int) -> bool:
        """Check if direct message (positive chat ID) is allowed."""
        # Direct messages have positive chat IDs, group chats have negative
        return StickerBot.is_chat_allowed(chat_id) and chat_id > 0

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

    async def _process_image_message(self, message, error_message_id=None):
        """Shared method to process image messages and extract file ID."""
        # Check if the message contains an image
        if not (message.photo or message.document):
            return (
                None,
                "❌ The message doesn't contain an image. Please provide an image.",
            )

        # Get the image file
        if message.photo:
            # Get the highest quality photo (last in the list)
            photo = message.photo[-1]
            file_id = photo.file_id
        elif message.document:
            # Check if document is an image
            if (
                not message.document.mime_type
                or not message.document.mime_type.startswith("image/")
            ):
                return None, "❌ The file is not an image. Please provide an image."
            file_id = message.document.file_id
        else:
            return None, "❌ No image found in the message."

        return file_id, None

    async def _process_animation_message(self, message):
        """Shared method to process animation messages and extract file ID and duration."""
        # Check if the message contains an animation
        if not message.animation:
            return (
                None,
                None,
                "❌ The message doesn't contain an animation. Please provide a GIF or animation.",
            )

        # Get the animation file
        animation = message.animation
        file_id = animation.file_id
        duration = animation.duration

        return file_id, duration, None

    async def _store_pending_sticker(
        self,
        update: Update,
        file_id: str,
        media_message_id: int,
        media_type: str,
        duration: Optional[float] = None,
    ) -> bool:
        """Store pending sticker data. Returns True if successful, False otherwise."""
        # Get and validate user ID
        user_id = self._get_user_id(update)
        if not await self._validate_user_id(update, user_id):
            return False

        # Set up pending sticker
        self.pending_stickers[user_id] = {
            "message_id": media_message_id,
            "file_id": file_id,
            "chat_id": update.message.chat_id,
            "user_message_id": update.message.message_id,
            "waiting_for_emoji": True,
            "media_type": media_type,
        }

        if duration is not None:
            self.pending_stickers[user_id]["duration"] = duration

        return True

    async def _setup_pending_image_sticker(
        self, update: Update, file_id: Optional[str], image_message_id: int
    ):
        """Set up pending image sticker and prompt for emoji."""
        if update.message is None or file_id is None:
            return False

        # Store pending sticker (validates user_id internally)
        if not await self._store_pending_sticker(
            update, file_id, image_message_id, media_type="static"
        ):
            return False

        # Prompt for emoji
        await update.message.reply_text(
            f"📸 {self.EMOJI_PROMPT_BASE}",
            reply_to_message_id=update.message.message_id,
        )
        return True

    async def _setup_pending_animation_sticker(
        self,
        update: Update,
        file_id: Optional[str],
        animation_message_id: int,
        duration: float,
    ):
        """Set up pending animation sticker and prompt for emoji."""
        if update.message is None or file_id is None:
            return False

        # Store pending sticker (validates user_id internally)
        if not await self._store_pending_sticker(
            update, file_id, animation_message_id, media_type="video", duration=duration
        ):
            return False

        # Prompt for emoji
        await update.message.reply_text(
            f"🎬 {self.EMOJI_PROMPT_BASE}",
            reply_to_message_id=update.message.message_id,
        )
        return True

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
            CommandHandler("cancel", self.handle_cancel_command)
        )
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_emoji_response)
        )
        self.application.add_handler(
            MessageHandler(
                filters.PHOTO | filters.Document.IMAGE, self.handle_direct_image
            )
        )
        self.application.add_handler(
            MessageHandler(filters.ANIMATION, self.handle_direct_animation)
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
            "💡 You can also send an image directly to me (if you're in an allowed chat).\n"
            "❌ Use '/cancel' to clear any pending sticker submissions."
        )
        await update.message.reply_text(welcome_message)

    async def handle_cancel_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle /cancel command to clear pending stickers."""
        if update.message is None or not self.is_chat_allowed(update.message.chat_id):
            return

        user_id = self._get_user_id(update)
        if user_id is None:
            return

        # Check if user has pending stickers
        if user_id in self.pending_stickers:
            # Clear the pending sticker
            del self.pending_stickers[user_id]
            await update.message.reply_text(
                "❌ Cancelled! Your pending request has been cleared.",
                reply_to_message_id=update.message.message_id,
            )
        else:
            await update.message.reply_text(
                "ℹ️ You don't have any pending requests to cancel.",
                reply_to_message_id=update.message.message_id,
            )

    async def handle_sticker_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle '/sticker' command when replied to an image or animation."""
        if update.message is None or not self.is_chat_allowed(update.message.chat_id):
            return

        # Check if this is a reply to another message
        if not update.message.reply_to_message:
            await update.message.reply_text(
                "❌ Please reply to an image or animation with the /sticker command.",
                reply_to_message_id=update.message.message_id,
            )
            return

        replied_message = update.message.reply_to_message

        # Check if it's an animation first
        if replied_message.animation:
            file_id, duration, error_message = await self._process_animation_message(
                replied_message
            )
            if error_message:
                await update.message.reply_text(
                    error_message,
                    reply_to_message_id=update.message.message_id,
                )
                return

            # Set up pending animation sticker and prompt for emoji
            await self._setup_pending_animation_sticker(
                update, file_id, replied_message.message_id, duration
            )
        else:
            # Process as image
            file_id, error_message = await self._process_image_message(replied_message)
            if error_message:
                await update.message.reply_text(
                    error_message,
                    reply_to_message_id=update.message.message_id,
                )
                return

            # Set up pending image sticker and prompt for emoji
            await self._setup_pending_image_sticker(
                update, file_id, replied_message.message_id
            )

    async def handle_emoji_response(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle emoji response from user."""
        if update.message is None or not self.is_chat_allowed(update.message.chat_id):
            return

        user_id = self._get_user_id(update)
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
            f"📦 Choose a sticker pack to add this image with emoji {emoji_text}:\n\n❌ Use '/cancel' to cancel this request.",
            reply_markup=reply_markup,
            reply_to_message_id=update.message.message_id,
        )

    async def handle_direct_image(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle direct messages containing images from allowed users."""
        if update.message is None or not self.is_direct_message_allowed(
            update.message.chat_id
        ):
            return

        # Process the image using shared method
        file_id, error_message = await self._process_image_message(update.message)
        if error_message:
            # For direct messages, we silently ignore non-image messages
            return

        # Set up pending sticker and prompt for emoji
        await self._setup_pending_image_sticker(
            update, file_id, update.message.message_id
        )

    async def handle_direct_animation(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle direct messages containing animations from allowed users."""
        if update.message is None or not self.is_direct_message_allowed(
            update.message.chat_id
        ):
            return

        # Process the animation using shared method
        file_id, duration, error_message = await self._process_animation_message(
            update.message
        )
        if error_message:
            # For direct messages, we silently ignore non-animation messages
            return

        # Set up pending sticker and prompt for emoji
        await self._setup_pending_animation_sticker(
            update, file_id, update.message.message_id, duration
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

            # Download the media
            media_data = await file.download_as_bytearray()

            # Check media type and process accordingly
            media_type = pending_data.get("media_type", "static")

            if media_type == "video":
                # Process video/animation for sticker requirements
                duration = pending_data.get("duration", 0)
                processed_media = await self.process_video_for_sticker(
                    bytes(media_data), duration
                )
                sticker_format = "video"
            else:
                # Process image for sticker requirements
                processed_media = await self.process_image_for_sticker(
                    bytes(media_data)
                )
                sticker_format = "static"

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
                image_data=processed_media,
                emoji=emoji,
                format=sticker_format,
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

    async def process_video_for_sticker(
        self, video_data: bytes, duration: float
    ) -> bytes:
        """Process video/animation to meet Telegram sticker requirements (WEBM VP9)."""
        temp_input = None
        temp_output = None
        clip = None

        try:
            # Create temporary files
            with tempfile.NamedTemporaryFile(
                suffix=".mp4", delete=False
            ) as temp_input_file:
                temp_input = temp_input_file.name
                temp_input_file.write(video_data)

            temp_output = tempfile.NamedTemporaryFile(
                suffix=".webm", delete=False
            ).name

            # Load video clip
            clip = VideoFileClip(temp_input)

            # Get dimensions
            width, height = clip.size

            # Speed up video if longer than 3 seconds
            if duration > 3.0:
                speed_multiplier = duration / 3.0
                logger.info(
                    f"Video duration {duration}s > 3s, speeding up by {speed_multiplier}x"
                )
                clip = clip.fx(vfx.speedx, speed_multiplier)

            # Calculate new dimensions (512px on longest side)
            if width > height:
                new_width = 512
                new_height = int(height * (512 / width))
            else:
                new_height = 512
                new_width = int(width * (512 / height))

            # Ensure dimensions are even (required by VP9)
            new_width = new_width if new_width % 2 == 0 else new_width - 1
            new_height = new_height if new_height % 2 == 0 else new_height - 1

            # Resize clip
            clip = clip.resize((new_width, new_height))

            # Set FPS
            clip = clip.set_fps(30)

            # Write to WEBM with VP9 codec
            clip.write_videofile(
                temp_output,
                codec="libvpx-vp9",
                audio=False,
                ffmpeg_params=[
                    "-crf",
                    "30",  # Quality (lower = better, 23-30 recommended)
                    "-b:v",
                    "0",  # Use constant quality mode
                    "-deadline",
                    "good",  # Encoding speed vs quality tradeoff
                    "-cpu-used",
                    "4",  # Faster encoding (0-5, higher = faster)
                ],
                verbose=False,
                logger=None,
            )

            # Read the output file
            with open(temp_output, "rb") as f:
                webm_data = f.read()

            # Check file size
            file_size_kb = len(webm_data) / 1024
            logger.info(f"Processed video size: {file_size_kb:.2f} KB")

            if file_size_kb > 256:
                raise ValueError(
                    f"Processed video is too large ({file_size_kb:.2f} KB > 256 KB). "
                    "Try using a shorter or lower quality animation."
                )

            return webm_data

        except Exception as e:
            logger.error(f"Error processing video: {e}")
            raise
        finally:
            # Close clip
            if clip is not None:
                clip.close()
            # Clean up temporary files
            if temp_input and os.path.exists(temp_input):
                os.unlink(temp_input)
            if temp_output and os.path.exists(temp_output):
                os.unlink(temp_output)

    async def add_sticker_to_pack(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        sticker_set_name: str,
        sticker_set_title: str,
        image_data: bytes,
        emoji: str,
        format: str = "static",
    ):
        """Add sticker to a sticker pack."""
        logger.info(
            f"Adding {format} sticker to pack: {sticker_set_name} with emoji {emoji}"
        )
        sticker = InputSticker(sticker=image_data, emoji_list=[emoji], format=format)

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
