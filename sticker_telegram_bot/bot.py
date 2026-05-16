import logging
import re
from typing import Optional, Tuple

from telegram import (
    InputSticker,
    ReplyKeyboardRemove,
    Sticker,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode
from PIL import Image
import io
import emoji
import subprocess
import tempfile

from sticker_telegram_bot.config import Config
from sticker_telegram_bot.db.repositories import StickerPackRepository
from sticker_telegram_bot.db.session import session_scope

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


class StickerBot:
    """Telegram bot for managing sticker packs."""

    (
        MANAGE_MENU,
        MANAGE_CREATE_NAME,
        MANAGE_IMPORT_STICKER,
        STICKER_EMOJI,
        STICKER_PACK_SELECT,
    ) = range(5)

    # Message templates
    EMOJI_PROMPT_BASE = (
        "Great! Now just reply to this message with a single emoji for this sticker, "
        "like 🗿, 🔫, or 💩.\n\n❌ Use '/cancel' to cancel this request."
    )
    STICKER_ADDED_MESSAGE = (
        'Thank you daddy 💕. Sticker added to <a href="https://t.me/addstickers/{telegram_name}">{title}</a>.\n\n'
        "ℹ️ The sticker might not immediately appear in the pack. If it doesn't, "
        "try re-adding the pack and restarting the app a few times."
    )
    MAX_STATIC_STICKER_BYTES = 512 * 1024

    def __init__(self):
        self.application: Optional[Application] = None

    def _sticker_added_message(self, pack) -> str:
        return self.STICKER_ADDED_MESSAGE.format(
            telegram_name=pack.telegram_name,
            title=pack.title,
        )

    def _get_user_id(self, update: Update) -> Optional[int]:
        """Extract and validate user_id from update. Returns None if invalid."""
        if update.message is None or update.message.from_user is None:
            return None
        return update.message.from_user.id

    async def _validate_user_id(self, update: Update, user_id: Optional[int]) -> bool:
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
    def is_group_chat(update: Update) -> bool:
        chat = update.effective_chat
        return chat is not None and chat.type in {"group", "supergroup"}

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

    @staticmethod
    def _plain_pack_name(title: str) -> str:
        name = re.sub(r"\s+", "_", title.strip())
        name = re.sub(r"[^A-Za-z0-9_]", "", name)
        name = re.sub(r"_+", "_", name)
        name = re.sub(r"^([^A-Za-z]+)", "", name)
        return name.rstrip("_")

    @staticmethod
    def _is_bot_managed_pack_name(pack_name: str, bot_username: str) -> bool:
        return pack_name.endswith(f"_by_{bot_username}")

    @staticmethod
    def _normalize_single_emoji(value: Optional[str]) -> Optional[str]:
        if not value:
            return None

        candidate = value.strip()
        matches = emoji.emoji_list(candidate)
        if len(matches) != 1:
            return None

        match = matches[0]
        unmatched = candidate[: match["match_start"]] + candidate[match["match_end"] :]
        # Some Telegram clients can leave repeated variation selectors after
        # the emoji. They don't change the chosen emoji, so ignore them.
        if unmatched.replace("\ufe0e", "").replace("\ufe0f", ""):
            return None
        return match["emoji"]

    def _make_placeholder_sticker(self) -> bytes:
        image = Image.new("RGBA", (512, 512), "white")
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    async def _show_group_only_message(self, update: Update) -> int:
        if update.message:
            await update.message.reply_text(
                "❌ This command is only available in group chats.",
                reply_to_message_id=update.message.message_id,
            )
        return ConversationHandler.END

    async def _load_visible_group_packs(self, chat_id: int):
        async with session_scope() as session:
            return await StickerPackRepository(session).list_visible_group_packs(
                chat_id
            )

    async def _load_group_packs(self, chat_id: int):
        async with session_scope() as session:
            return await StickerPackRepository(session).list_group_packs(chat_id)

    async def _get_group_pack(self, pack_id: int, chat_id: int):
        async with session_scope() as session:
            return await StickerPackRepository(session).get_group_pack(
                pack_id=pack_id, chat_id=chat_id
            )

    def _flow_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict:
        chat = update.effective_chat
        if chat is None:
            return {}
        flows = context.user_data.setdefault("chat_flows", {})
        return flows.setdefault(str(chat.id), {})

    def _clear_flow_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if chat is None:
            return
        flows = context.user_data.setdefault("chat_flows", {})
        flows.pop(str(chat.id), None)

    async def _send_reply_prompt(self, message, text: str) -> int:
        prompt = await message.reply_text(text)
        return prompt.message_id

    async def _cleanup_reply_prompts(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        flow = self._flow_data(update, context)
        for key in (
            "pack_name_prompt_message_id",
            "pack_import_prompt_message_id",
            "emoji_prompt_message_id",
        ):
            flow.pop(key, None)

    @staticmethod
    def _is_reply_to_prompt(update: Update, prompt_message_id: Optional[int]) -> bool:
        if prompt_message_id is None or update.message is None:
            return True
        reply_to_message = update.message.reply_to_message
        return (
            reply_to_message is not None
            and reply_to_message.message_id == prompt_message_id
        )

    async def _replace_action_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        text: str,
    ):
        chat = update.effective_chat
        flow = self._flow_data(update, context)
        message_id = flow.get("action_message_id")
        if chat is None or message_id is None:
            return

        try:
            await context.bot.edit_message_text(
                chat_id=chat.id,
                message_id=message_id,
                text=text,
            )
        except Exception as exc:
            logger.warning(f"Could not update stale action message: {exc}")

    async def _process_image_message(self, message, error_message_id=None):
        """Shared method to process image messages and extract file ID."""
        photo = getattr(message, "photo", None)
        document = getattr(message, "document", None)

        # Check if the message contains an image
        if not (photo or document):
            return (
                None,
                "❌ The message doesn't contain an image. Please provide an image.",
            )

        # Get the image file
        if photo:
            # Get the highest quality photo (last in the list)
            image = photo[-1]
            file_id = image.file_id
        elif document:
            # Check if document is an image
            if not document.mime_type or not document.mime_type.startswith("image/"):
                return None, "❌ The file is not an image. Please provide an image."
            file_id = document.file_id
        else:
            return None, "❌ No image found in the message."

        return file_id, None

    async def _process_animation_message(self, message):
        """Shared method to process animation messages and extract file ID and duration."""
        animation = getattr(message, "animation", None)

        # Check if the message contains an animation
        if not animation:
            return (
                None,
                None,
                "❌ The message doesn't contain an animation. Please provide a GIF or animation.",
            )

        # Get the animation file
        file_id = animation.file_id
        duration = animation.duration

        return file_id, duration, None

    async def _process_video_message(self, message):
        """Shared method to process video messages and extract file ID and duration."""
        video = getattr(message, "video", None)
        if not video:
            return (
                None,
                None,
                "❌ The message doesn't contain a video.",
            )
        return video.file_id, video.duration, None

    def _classify_telegram_sticker(
        self, sticker: Sticker
    ) -> Tuple[Optional[dict], Optional[str]]:
        """
        Map a Telegram Sticker object to our pending-sticker pipeline.

        Returns (info_dict, None) on success, or (None, error_message).
        info_dict keys: file_id, media_type ('static'|'video'), duration, suggested_emoji
        """
        if sticker.is_video:
            duration = 0.0
            return (
                {
                    "file_id": sticker.file_id,
                    "media_type": "video",
                    "duration": duration,
                    "suggested_emoji": sticker.emoji,
                },
                None,
            )

        if sticker.is_animated:
            return (
                None,
                "❌ Animated Telegram stickers (TGS/Lottie) are not supported yet. "
                "Try a static sticker, a video sticker, a photo, or a GIF.",
            )

        return (
            {
                "file_id": sticker.file_id,
                "media_type": "static",
                "duration": None,
                "suggested_emoji": sticker.emoji,
            },
            None,
        )

    @staticmethod
    def _get_replied_media_source(message):
        return getattr(message, "reply_to_message", None) or getattr(
            message, "external_reply", None
        )

    @staticmethod
    def _log_sticker_command_reply_context(message):
        reply_to_message = getattr(message, "reply_to_message", None)
        external_reply = getattr(message, "external_reply", None)
        quote = getattr(message, "quote", None)
        logger.info(
            "Sticker command reply context: "
            "message_id=%s reply_to_message=%s external_reply=%s quote=%s "
            "entities=%s text=%r",
            getattr(message, "message_id", None),
            bool(reply_to_message),
            bool(external_reply),
            bool(quote),
            getattr(message, "entities", None),
            getattr(message, "text", None),
        )
        if reply_to_message:
            logger.info(
                "reply_to_message media: id=%s photo=%s document=%s animation=%s "
                "video=%s sticker=%s",
                getattr(reply_to_message, "message_id", None),
                bool(getattr(reply_to_message, "photo", None)),
                bool(getattr(reply_to_message, "document", None)),
                bool(getattr(reply_to_message, "animation", None)),
                bool(getattr(reply_to_message, "video", None)),
                bool(getattr(reply_to_message, "sticker", None)),
            )
        if external_reply:
            logger.info(
                "external_reply media: id=%s photo=%s document=%s animation=%s "
                "video=%s sticker=%s",
                getattr(external_reply, "message_id", None),
                bool(getattr(external_reply, "photo", None)),
                bool(getattr(external_reply, "document", None)),
                bool(getattr(external_reply, "animation", None)),
                bool(getattr(external_reply, "video", None)),
                bool(getattr(external_reply, "sticker", None)),
            )

    @staticmethod
    def _suggested_emoji_hint(suggested_emoji: Optional[str]) -> str:
        normalized_emoji = StickerBot._normalize_single_emoji(suggested_emoji)
        if normalized_emoji:
            return (
                f"\n\n💡 The source sticker is associated with {normalized_emoji} "
                "if you want to reuse it."
            )
        return ""

    def start(self):
        """Initialize and start the bot."""
        # Validate configuration
        Config.validate()

        # Create application
        self.application = (
            Application.builder()
            .token(Config.TELEGRAM_BOT_TOKEN)
            .concurrent_updates(False)
            .build()
        )

        manage_conversation = ConversationHandler(
            entry_points=[
                CommandHandler("manage", self.handle_manage_command),
            ],
            states={
                self.MANAGE_MENU: [
                    CallbackQueryHandler(self.handle_manage_callback, pattern=r"^mg:"),
                ],
                self.MANAGE_CREATE_NAME: [
                    CallbackQueryHandler(self.handle_manage_callback, pattern=r"^mg:"),
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.handle_manage_create_name,
                    ),
                ],
                self.MANAGE_IMPORT_STICKER: [
                    CallbackQueryHandler(self.handle_manage_callback, pattern=r"^mg:"),
                    MessageHandler(
                        filters.Sticker.ALL,
                        self.handle_manage_import_sticker,
                    ),
                ],
            },
            fallbacks=[CommandHandler("cancel", self.handle_cancel_command)],
            per_chat=True,
            per_user=True,
            allow_reentry=True,
        )

        sticker_conversation = ConversationHandler(
            entry_points=[
                CommandHandler("sticker", self.handle_sticker_command),
            ],
            states={
                self.STICKER_EMOJI: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.handle_sticker_emoji,
                    ),
                ],
                self.STICKER_PACK_SELECT: [
                    CallbackQueryHandler(self.handle_sticker_callback, pattern=r"^st:"),
                    MessageHandler(
                        filters.Sticker.ALL,
                        self.handle_sticker_import_sticker,
                    ),
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.handle_sticker_create_name,
                    ),
                ],
            },
            fallbacks=[CommandHandler("cancel", self.handle_cancel_command)],
            per_chat=True,
            per_user=True,
            allow_reentry=True,
        )

        # Add handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.start_command))
        self.application.add_handler(sticker_conversation)
        self.application.add_handler(manage_conversation)
        self.application.add_handler(
            CommandHandler("cancel", self.handle_cancel_command)
        )

        logger.info("Bot started successfully")

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        if update.message is None:
            return

        welcome_message = (
            "🐐 Hello friends.\n\n"
            "To add media to a group sticker pack:\n"
            "1. Reply to an image, GIF, or Telegram sticker (static or video) with "
            "the command '/sticker'\n"
            "2. Send an emoji for the sticker\n"
            "3. Select which group sticker pack to add it to, or create one\n"
            "4. The sticker will be added to your chosen pack\n\n"
            "🛠 Use '/manage' in a group to list, show/hide, or create packs.\n"
            "❌ Use '/cancel' to clear any pending sticker submissions."
        )
        await update.message.reply_text(welcome_message)

    async def handle_cancel_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle /cancel command to end an active conversation."""
        await self._cleanup_reply_prompts(update, context)
        self._clear_flow_data(update, context)
        if update.message:
            await update.message.reply_text(
                "❌ Cancelled! Your pending request has been cleared.",
                reply_to_message_id=update.message.message_id,
                reply_markup=ReplyKeyboardRemove(),
            )
        return ConversationHandler.END

    async def handle_manage_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Entry point for group pack management."""
        if update.message is None:
            return ConversationHandler.END
        if not self.is_group_chat(update):
            return await self._show_group_only_message(update)

        self._clear_flow_data(update, context)
        await update.message.reply_text(
            "🛠 Manage this group's sticker packs:",
            reply_markup=self._manage_home_keyboard(),
            reply_to_message_id=update.message.message_id,
        )
        return self.MANAGE_MENU

    def _manage_home_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "List Sticker Packs",
                        callback_data="mg:list",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "Import Sticker Set",
                        callback_data="mg:import",
                    ),
                    InlineKeyboardButton(
                        "Create Sticker Set",
                        callback_data="mg:create",
                    ),
                ],
            ]
        )

    @staticmethod
    def _manage_back_button(callback_data: str = "mg:home") -> InlineKeyboardButton:
        return InlineKeyboardButton("Back", callback_data=callback_data)

    async def _render_manage_home(self, update: Update):
        query = update.callback_query
        if query is None:
            return
        await query.edit_message_text(
            "🛠 Manage this group's sticker packs:",
            reply_markup=self._manage_home_keyboard(),
        )

    async def _render_pack_list(self, update: Update, chat_id: int):
        query = update.callback_query
        packs = await self._load_group_packs(chat_id)
        keyboard = []
        for pack in packs:
            label = pack.title if pack.is_visible else f"{pack.title} (Hidden)"
            keyboard.append(
                [
                    InlineKeyboardButton(
                        label,
                        callback_data=f"mg:pack:{pack.id}",
                    )
                ]
            )
        keyboard.append([self._manage_back_button()])
        text = "📦 Sticker packs managed for this group:"
        if not packs:
            text = "📦 No sticker packs have been created for this group yet."
        if query is not None:
            await query.edit_message_text(
                text, reply_markup=InlineKeyboardMarkup(keyboard)
            )

    async def _render_pack_detail(self, update: Update, chat_id: int, pack_id: int):
        query = update.callback_query
        pack = await self._get_group_pack(pack_id, chat_id)
        if query is None:
            return
        if pack is None:
            await query.edit_message_text(
                "❌ Sticker pack not found.",
                reply_markup=InlineKeyboardMarkup([[self._manage_back_button()]]),
            )
            return
        action = "Hide" if pack.is_visible else "Show"
        await query.edit_message_text(
            f"📦 {pack.title}\n"
            f"Link: https://t.me/addstickers/{pack.telegram_name}\n"
            f"Status: {'Shown' if pack.is_visible else 'Hidden'}",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            action,
                            callback_data=f"mg:toggle:{pack.id}",
                        )
                    ],
                    [self._manage_back_button("mg:list")],
                ]
            ),
            disable_web_page_preview=True,
        )

    async def handle_manage_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        if query is None or query.data is None:
            return self.MANAGE_MENU
        await query.answer()
        if not self.is_group_chat(update):
            await query.edit_message_text(
                "❌ This command is only available in groups."
            )
            return ConversationHandler.END

        chat_id = query.message.chat_id if query.message else update.effective_chat.id
        data = query.data
        flow = self._flow_data(update, context)

        if data == "mg:home":
            await self._cleanup_reply_prompts(update, context)
            flow.pop("manage_action", None)
            await self._render_manage_home(update)
            return self.MANAGE_MENU
        if data == "mg:list":
            await self._render_pack_list(update, chat_id)
            return self.MANAGE_MENU
        if data == "mg:create":
            flow["manage_action"] = "create_pack"
            if query.message is not None:
                flow["action_message_id"] = query.message.message_id
            await query.edit_message_text(
                "Create a new sticker pack. Reply to the prompt below with the pack name.",
                reply_markup=InlineKeyboardMarkup([[self._manage_back_button()]]),
            )
            if query.message is not None:
                flow["pack_name_prompt_message_id"] = await self._send_reply_prompt(
                    query.message,
                    "Reply to this message with the name for the new sticker pack.",
                )
            return self.MANAGE_CREATE_NAME
        if data == "mg:import":
            flow["manage_action"] = "import_pack"
            if query.message is not None:
                flow["action_message_id"] = query.message.message_id
            await query.edit_message_text(
                "Import an existing bot-managed sticker pack. Reply to the prompt below with any sticker from that pack.",
                reply_markup=InlineKeyboardMarkup([[self._manage_back_button()]]),
            )
            if query.message is not None:
                flow["pack_import_prompt_message_id"] = await self._send_reply_prompt(
                    query.message,
                    "Reply to this message with any sticker from the sticker pack you want to import.",
                )
            return self.MANAGE_IMPORT_STICKER
        if data.startswith("mg:pack:"):
            await self._render_pack_detail(update, chat_id, int(data.split(":")[-1]))
            return self.MANAGE_MENU
        if data.startswith("mg:toggle:"):
            pack_id = int(data.split(":")[-1])
            async with session_scope() as session:
                repo = StickerPackRepository(session)
                pack = await repo.get_group_pack(pack_id=pack_id, chat_id=chat_id)
                if pack is None:
                    await query.edit_message_text(
                        "❌ Sticker pack not found.",
                        reply_markup=InlineKeyboardMarkup(
                            [[self._manage_back_button()]]
                        ),
                    )
                    return self.MANAGE_MENU
                await repo.set_pack_visibility(
                    pack_id=pack_id,
                    chat_id=chat_id,
                    is_visible=not pack.is_visible,
                )
            await self._render_pack_detail(update, chat_id, pack_id)
            return self.MANAGE_MENU

        return self.MANAGE_MENU

    async def handle_manage_create_name(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if update.message is None:
            return self.MANAGE_CREATE_NAME
        if not self.is_group_chat(update):
            return await self._show_group_only_message(update)
        flow = self._flow_data(update, context)
        if not self._is_reply_to_prompt(
            update, flow.get("pack_name_prompt_message_id")
        ):
            await update.message.reply_text(
                "Please reply to the pack-name prompt so I can see the message.",
                reply_to_message_id=update.message.message_id,
            )
            return self.MANAGE_CREATE_NAME
        title = update.message.text.strip() if update.message.text else ""
        if not title:
            await update.message.reply_text("❌ Please send a sticker pack name.")
            return self.MANAGE_CREATE_NAME

        try:
            pack = await self.create_empty_group_pack(update, context, title)
        except Exception as exc:
            logger.error(f"Error creating sticker pack: {exc}")
            await update.message.reply_text(
                f"❌ Could not create sticker pack: {exc}",
                reply_to_message_id=update.message.message_id,
            )
            return self.MANAGE_CREATE_NAME

        await self._replace_action_message(
            update,
            context,
            f"✅ Created sticker pack: {pack.title}",
        )
        await self._cleanup_reply_prompts(update, context)
        self._clear_flow_data(update, context)
        await update.message.reply_text(
            f'✅ Created <a href="https://t.me/addstickers/{pack.telegram_name}">{pack.title}</a>.',
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    async def handle_manage_import_sticker(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if update.message is None:
            return self.MANAGE_IMPORT_STICKER
        if not self.is_group_chat(update):
            return await self._show_group_only_message(update)

        flow = self._flow_data(update, context)
        if not self._is_reply_to_prompt(
            update, flow.get("pack_import_prompt_message_id")
        ):
            await update.message.reply_text(
                "Please reply to the import prompt so I can see the message.",
                reply_to_message_id=update.message.message_id,
            )
            return self.MANAGE_IMPORT_STICKER

        sticker = update.message.sticker
        imported = await self._import_group_pack_from_sticker(update, context, sticker)
        if imported is None:
            return self.MANAGE_IMPORT_STICKER
        pack, already_imported = imported

        await self._replace_action_message(
            update,
            context,
            f"✅ Imported sticker pack: {pack.title}",
        )
        await self._cleanup_reply_prompts(update, context)
        self._clear_flow_data(update, context)

        verb = "Imported" if not already_imported else "Re-shown"
        await update.message.reply_text(
            f'✅ {verb} <a href="https://t.me/addstickers/{pack.telegram_name}">{pack.title}</a> for this group.',
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    async def handle_sticker_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle '/sticker' when replying to an image, GIF, or Telegram sticker."""
        if update.message is None:
            return ConversationHandler.END
        if not self.is_group_chat(update):
            return await self._show_group_only_message(update)

        # Check if this is a reply to another message. Telegram may put quoted
        # media in external_reply instead of reply_to_message in some group cases.
        self._log_sticker_command_reply_context(update.message)
        replied_message = self._get_replied_media_source(update.message)
        if not replied_message:
            await update.message.reply_text(
                "❌ Please reply to an image, GIF, or sticker (static or video) with "
                "the /sticker command.",
                reply_to_message_id=update.message.message_id,
            )
            return ConversationHandler.END

        pending_data = {
            "chat_id": update.message.chat_id,
            "user_id": (
                update.message.from_user.id if update.message.from_user else None
            ),
            "user_message_id": update.message.message_id,
            "source_message_id": getattr(replied_message, "message_id", None),
        }

        # Check if it's an animation first
        if getattr(replied_message, "animation", None):
            file_id, duration, error_message = await self._process_animation_message(
                replied_message
            )
            if error_message:
                await update.message.reply_text(
                    error_message,
                    reply_to_message_id=update.message.message_id,
                )
                return ConversationHandler.END

            pending_data.update(
                {"file_id": file_id, "media_type": "video", "duration": duration}
            )
        elif getattr(replied_message, "video", None):
            file_id, duration, error_message = await self._process_video_message(
                replied_message
            )
            if error_message:
                await update.message.reply_text(
                    error_message,
                    reply_to_message_id=update.message.message_id,
                )
                return ConversationHandler.END

            pending_data.update(
                {"file_id": file_id, "media_type": "video", "duration": duration}
            )
        elif getattr(replied_message, "sticker", None):
            info, sticker_error = self._classify_telegram_sticker(
                replied_message.sticker
            )
            if sticker_error:
                await update.message.reply_text(
                    sticker_error,
                    reply_to_message_id=update.message.message_id,
                )
                return ConversationHandler.END
            assert info is not None
            pending_data.update(info)
        else:
            # Process as image
            file_id, error_message = await self._process_image_message(replied_message)
            if error_message:
                await update.message.reply_text(
                    error_message,
                    reply_to_message_id=update.message.message_id,
                )
                return ConversationHandler.END

            pending_data.update({"file_id": file_id, "media_type": "static"})

        if pending_data.get("user_id") is None:
            await update.message.reply_text("❌ Could not determine user.")
            return ConversationHandler.END

        self._clear_flow_data(update, context)
        flow = self._flow_data(update, context)
        flow["pending_sticker"] = pending_data
        media_type = pending_data.get("media_type", "static")
        prefix = "🎬" if media_type == "video" else "📸"
        hint = self._suggested_emoji_hint(pending_data.get("suggested_emoji"))
        emoji_prompt = await update.message.reply_text(
            f"{prefix} {self.EMOJI_PROMPT_BASE}{hint}",
            reply_to_message_id=update.message.message_id,
        )
        flow["emoji_prompt_message_id"] = emoji_prompt.message_id
        return self.STICKER_EMOJI

    async def handle_sticker_emoji(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if update.message is None:
            return self.STICKER_EMOJI
        flow = self._flow_data(update, context)
        pending_data = flow.get("pending_sticker")
        if not pending_data:
            await update.message.reply_text("❌ No pending sticker request found.")
            return ConversationHandler.END
        if not self._is_reply_to_prompt(update, flow.get("emoji_prompt_message_id")):
            await update.message.reply_text(
                "Please reply to the emoji prompt so I can see the message.",
                reply_to_message_id=update.message.message_id,
            )
            return self.STICKER_EMOJI

        emoji_text = self._normalize_single_emoji(update.message.text)
        if not emoji_text:
            await update.message.reply_text(
                "❌ Please send just a single emoji (like 🗿, 🔫, or 💩)",
                reply_to_message_id=update.message.message_id,
            )
            return self.STICKER_EMOJI

        pending_data["emoji"] = emoji_text
        packs = await self._load_visible_group_packs(pending_data["chat_id"])
        keyboard = [
            [
                InlineKeyboardButton(
                    pack.title,
                    callback_data=f"st:add:{pack.id}",
                )
            ]
            for pack in packs
        ]
        keyboard.append(
            [
                InlineKeyboardButton("Import Sticker Set", callback_data="st:import"),
                InlineKeyboardButton("Create Sticker Set", callback_data="st:create"),
            ]
        )
        await update.message.reply_text(
            f"📦 Choose a sticker pack for {emoji_text}, create one, or import one:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            reply_to_message_id=update.message.message_id,
        )
        return self.STICKER_PACK_SELECT

    async def handle_sticker_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        if query is None or query.data is None:
            return self.STICKER_PACK_SELECT
        await query.answer()
        flow = self._flow_data(update, context)
        pending_data = flow.get("pending_sticker")
        if not pending_data:
            await query.edit_message_text("❌ No pending sticker request found.")
            return ConversationHandler.END

        if query.data == "st:create":
            flow["sticker_action"] = "create_pack"
            if query.message is not None:
                flow["action_message_id"] = query.message.message_id
            await query.edit_message_text(
                "Create a new sticker pack from this sticker. Reply to the prompt below with the pack name."
            )
            if query.message is not None:
                flow["pack_name_prompt_message_id"] = await self._send_reply_prompt(
                    query.message,
                    "Reply to this message with the name for the new sticker pack.",
                )
            return self.STICKER_PACK_SELECT

        if query.data == "st:import":
            flow["sticker_action"] = "import_pack"
            if query.message is not None:
                flow["action_message_id"] = query.message.message_id
            await query.edit_message_text(
                "Import an existing bot-managed sticker pack for this sticker. "
                "Reply to the prompt below with any sticker from that pack."
            )
            if query.message is not None:
                flow["pack_import_prompt_message_id"] = await self._send_reply_prompt(
                    query.message,
                    "Reply to this message with any sticker from the sticker pack you want to import.",
                )
            return self.STICKER_PACK_SELECT

        if query.data.startswith("st:add:"):
            pack_id = int(query.data.split(":")[-1])
            pack = await self._get_group_pack(pack_id, pending_data["chat_id"])
            if pack is None or not pack.is_visible:
                await query.edit_message_text("❌ Sticker pack not found.")
                return ConversationHandler.END
            try:
                await self.add_pending_sticker_to_pack(context, pending_data, pack)
            except Exception as exc:
                logger.error(f"Error adding sticker to pack: {exc}")
                await query.edit_message_text(f"❌ Could not add sticker: {exc}")
                return ConversationHandler.END

            self._clear_flow_data(update, context)
            await query.edit_message_text(
                self._sticker_added_message(pack),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return ConversationHandler.END

        return self.STICKER_PACK_SELECT

    async def handle_sticker_import_sticker(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if update.message is None:
            return self.STICKER_PACK_SELECT
        flow = self._flow_data(update, context)
        if flow.get("sticker_action") != "import_pack":
            return self.STICKER_PACK_SELECT
        pending_data = flow.get("pending_sticker")
        if not pending_data:
            await update.message.reply_text("❌ No pending sticker request found.")
            return ConversationHandler.END
        if not self._is_reply_to_prompt(
            update, flow.get("pack_import_prompt_message_id")
        ):
            await update.message.reply_text(
                "Please reply to the import prompt so I can see the message.",
                reply_to_message_id=update.message.message_id,
            )
            return self.STICKER_PACK_SELECT

        imported = await self._import_group_pack_from_sticker(
            update, context, update.message.sticker
        )
        if imported is None:
            return self.STICKER_PACK_SELECT
        pack, _ = imported

        try:
            await self.add_pending_sticker_to_pack(context, pending_data, pack)
        except Exception as exc:
            logger.error(f"Error adding sticker to imported pack: {exc}")
            await update.message.reply_text(
                f"❌ Imported the pack, but could not add sticker: {exc}",
                reply_to_message_id=update.message.message_id,
            )
            return ConversationHandler.END

        await self._replace_action_message(
            update,
            context,
            f"✅ Imported sticker pack: {pack.title}",
        )
        await self._cleanup_reply_prompts(update, context)
        self._clear_flow_data(update, context)
        await update.message.reply_text(
            self._sticker_added_message(pack),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    async def handle_sticker_create_name(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if update.message is None:
            return self.STICKER_PACK_SELECT
        flow = self._flow_data(update, context)
        if flow.get("sticker_action") != "create_pack":
            return self.STICKER_PACK_SELECT
        pending_data = flow.get("pending_sticker")
        if not pending_data:
            await update.message.reply_text("❌ No pending sticker request found.")
            return ConversationHandler.END
        if not self._is_reply_to_prompt(
            update, flow.get("pack_name_prompt_message_id")
        ):
            await update.message.reply_text(
                "Please reply to the pack-name prompt so I can see the message.",
                reply_to_message_id=update.message.message_id,
            )
            return self.STICKER_PACK_SELECT
        title = update.message.text.strip() if update.message.text else ""
        if not title:
            await update.message.reply_text("❌ Please send a sticker pack name.")
            return self.STICKER_PACK_SELECT

        try:
            pack = await self.create_group_pack_from_pending_sticker(
                update, context, title, pending_data
            )
        except Exception as exc:
            logger.error(f"Error creating sticker pack from pending sticker: {exc}")
            await update.message.reply_text(
                f"❌ Could not create sticker pack: {exc}",
                reply_to_message_id=update.message.message_id,
            )
            return self.STICKER_PACK_SELECT

        await self._replace_action_message(
            update,
            context,
            f"✅ Created sticker pack: {pack.title}",
        )
        await self._cleanup_reply_prompts(update, context)
        self._clear_flow_data(update, context)
        await update.message.reply_text(
            self._sticker_added_message(pack),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

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

            # Convert back to bytes, using PNG optimization to stay under Telegram's
            # static sticker upload limit when possible.
            output = io.BytesIO()
            canvas.save(output, format="PNG", optimize=True)
            sticker_data = output.getvalue()
            if len(sticker_data) > self.MAX_STATIC_STICKER_BYTES:
                file_size_kb = len(sticker_data) / 1024
                raise ValueError(
                    f"Processed image is too large ({file_size_kb:.2f} KB > 512 KB). "
                    "Try using a simpler image."
                )
            return sticker_data

        except Exception as e:
            logger.error(f"Error processing image: {e}")
            raise

    async def process_video_for_sticker(
        self, video_data: bytes, duration: float
    ) -> bytes:
        """Process video/animation to meet Telegram sticker requirements (WEBM VP9)."""
        try:
            # Build video filter string
            filters = []

            # Telegram video stickers must be 3 seconds or shorter.
            if duration > 3.0:
                speed_multiplier = duration / 3.0
                logger.info(
                    f"Video duration {duration}s > 3s, speeding up by {speed_multiplier}x"
                )
                filters.append(f"setpts=PTS/{speed_multiplier}")

            # Scale to fit within 512x512 while maintaining aspect ratio
            # force_original_aspect_ratio=decrease ensures longest dimension becomes 512px
            filters.append("scale=512:512:force_original_aspect_ratio=decrease")

            # Pad to 512x512 with black background and center the video
            # (ow-iw)/2 and (oh-ih)/2 center the video on the canvas
            # Using opaque black (0x000000) instead of transparent
            filters.append("pad=512:512:(ow-iw)/2:(oh-ih)/2:color=black")

            # Set FPS to 30
            filters.append("fps=30")

            # Combine filters
            vf_string = ",".join(filters)

            # Log input info before processing
            logger.info(
                f"Processing video: size={len(video_data)} bytes, "
                f"duration={duration}s, filters={vf_string}"
            )

            # Neutral suffix so WEBM (video stickers) and MP4 (GIF animations) probe correctly.
            with tempfile.NamedTemporaryFile(suffix=".bin") as input_file:
                input_file.write(video_data)
                input_file.flush()

                # Build ffmpeg command with seekable input and in-memory output.
                ffmpeg_cmd = [
                    "ffmpeg",
                    "-i",
                    input_file.name,
                    "-vf",
                    vf_string,  # Apply video filters
                    "-c:v",
                    "libvpx-vp9",  # VP9 codec
                    "-crf",
                    "30",  # Quality (lower = better, 23-30 recommended)
                    "-b:v",
                    "0",  # Use constant quality mode
                    "-deadline",
                    "good",  # Encoding speed vs quality tradeoff
                    "-cpu-used",
                    "4",  # Faster encoding (0-5, higher = faster)
                    "-an",  # No audio
                    "-f",
                    "webm",  # Output format
                    "pipe:1",  # Write to stdout
                ]

                process = subprocess.Popen(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

                webm_data, stderr = process.communicate()
            stderr_text = stderr.decode("utf-8", errors="ignore")

            # Check for errors
            if process.returncode != 0:
                error_msg = stderr_text
                logger.error(f"ffmpeg failed with return code {process.returncode}")
                logger.error(f"Input data size: {len(video_data)} bytes")

                # Check for common error patterns
                if (
                    "partial file" in error_msg.lower()
                    or "invalid data" in error_msg.lower()
                ):
                    raise RuntimeError(
                        f"Video file appears corrupted or incomplete. "
                        f"Try uploading the animation again. Error: {error_msg}"
                    )
                else:
                    raise RuntimeError(f"ffmpeg failed: {error_msg}")

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

    def _make_group_sticker_set_name(
        self, *, title: str, username: str, chat_id: int
    ) -> str:
        suffix = f"_by_{username}"
        chat_fragment = str(abs(chat_id))
        base = self._plain_pack_name(title)
        if not base:
            raise ValueError("Sticker pack name must start with a letter.")
        max_base_length = 64 - len(suffix) - len(chat_fragment) - 1
        if max_base_length < 1:
            raise ValueError("Bot username is too long for sticker set names.")
        base = base[:max_base_length].rstrip("_")
        if not base:
            raise ValueError("Sticker pack name must start with a letter.")
        return f"{base}_{chat_fragment}{suffix}"

    async def _process_pending_media(
        self, context: ContextTypes.DEFAULT_TYPE, pending_data: dict
    ) -> tuple[bytes, str]:
        file = await context.bot.get_file(pending_data["file_id"])
        logger.info(
            f"Downloading file: size={file.file_size} bytes, path={file.file_path}"
        )
        media_data = await file.download_as_bytearray()
        if not media_data:
            raise ValueError("Downloaded file is empty")

        if file.file_size and len(media_data) != file.file_size:
            logger.warning(
                f"Download size mismatch: expected {file.file_size}, got {len(media_data)}"
            )
            media_data = await file.download_as_bytearray()
            if len(media_data) != file.file_size:
                raise ValueError(
                    f"Download incomplete: expected {file.file_size} bytes, "
                    f"received {len(media_data)} bytes"
                )

        if pending_data.get("media_type") == "video":
            processed_media = await self.process_video_for_sticker(
                bytes(media_data), pending_data.get("duration", 0)
            )
            return processed_media, "video"

        processed_media = await self.process_image_for_sticker(bytes(media_data))
        return processed_media, "static"

    async def _create_pack_record(
        self,
        *,
        telegram_name: str,
        title: str,
        owner_user_id: int,
        chat_id: int,
        created_by_user_id: int,
    ):
        async with session_scope() as session:
            return await StickerPackRepository(session).create_pack_record(
                telegram_name=telegram_name,
                title=title,
                owner_user_id=owner_user_id,
                chat_id=chat_id,
                created_by_user_id=created_by_user_id,
                is_visible=True,
            )

    async def create_empty_group_pack(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, title: str
    ):
        if update.effective_chat is None or update.effective_user is None:
            raise ValueError("Could not determine chat or user.")
        bot_username = context.bot.username or Config.TELEGRAM_BOT_USERNAME
        sticker_set_title = title[:64]
        sticker_set_name = self._make_group_sticker_set_name(
            title=sticker_set_title,
            username=bot_username,
            chat_id=update.effective_chat.id,
        )
        placeholder = InputSticker(
            sticker=self._make_placeholder_sticker(),
            emoji_list=["⬜"],
            format="static",
        )
        await context.bot.create_new_sticker_set(
            user_id=update.effective_user.id,
            name=sticker_set_name,
            title=sticker_set_title,
            stickers=[placeholder],
        )
        pack = await self._create_pack_record(
            telegram_name=sticker_set_name,
            title=sticker_set_title,
            owner_user_id=update.effective_user.id,
            chat_id=update.effective_chat.id,
            created_by_user_id=update.effective_user.id,
        )
        cleanup_failed = await self._delete_first_sticker_best_effort(
            context, sticker_set_name
        )
        if cleanup_failed and update.message:
            await update.message.reply_text(
                "⚠️ The pack was created, but I couldn't remove the temporary placeholder sticker.",
                reply_to_message_id=update.message.message_id,
            )
        return pack

    async def import_group_pack(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, telegram_name: str
    ):
        if update.effective_chat is None or update.effective_user is None:
            raise ValueError("Could not determine chat or user.")

        sticker_set = await context.bot.get_sticker_set(telegram_name)
        title = sticker_set.title[:64]
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id

        async with session_scope() as session:
            repo = StickerPackRepository(session)
            existing_pack = await repo.get_group_pack_by_telegram_name(
                telegram_name=telegram_name,
                chat_id=chat_id,
            )
            if existing_pack is not None:
                if not existing_pack.is_visible:
                    existing_pack = await repo.set_pack_visibility(
                        pack_id=existing_pack.id,
                        chat_id=chat_id,
                        is_visible=True,
                    )
                return existing_pack, True

            pack = await repo.create_pack_record(
                telegram_name=telegram_name,
                title=title,
                owner_user_id=user_id,
                chat_id=chat_id,
                created_by_user_id=user_id,
                is_visible=True,
            )
            return pack, False

    async def _import_group_pack_from_sticker(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, sticker
    ):
        if update.message is None:
            return None

        pack_name = sticker.set_name if sticker else None
        if pack_name is None:
            await update.message.reply_text(
                "❌ Please reply with a sticker from the sticker pack you want to import.",
                reply_to_message_id=update.message.message_id,
            )
            return None

        bot_username = context.bot.username or Config.TELEGRAM_BOT_USERNAME
        if not self._is_bot_managed_pack_name(pack_name, bot_username):
            await update.message.reply_text(
                "❌ I can only import sticker packs that were originally created by me.",
                reply_to_message_id=update.message.message_id,
            )
            return None

        try:
            return await self.import_group_pack(update, context, pack_name)
        except Exception as exc:
            logger.error(f"Error importing sticker pack: {exc}")
            await update.message.reply_text(
                f"❌ Could not import sticker pack: {exc}",
                reply_to_message_id=update.message.message_id,
            )
            return None

    async def create_group_pack_from_pending_sticker(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        title: str,
        pending_data: dict,
    ):
        if update.effective_chat is None or update.effective_user is None:
            raise ValueError("Could not determine chat or user.")
        bot_username = context.bot.username or Config.TELEGRAM_BOT_USERNAME
        sticker_set_title = title[:64]
        sticker_set_name = self._make_group_sticker_set_name(
            title=sticker_set_title,
            username=bot_username,
            chat_id=update.effective_chat.id,
        )
        image_data, sticker_format = await self._process_pending_media(
            context, pending_data
        )
        sticker = InputSticker(
            sticker=image_data,
            emoji_list=[pending_data.get("emoji", "😀")],
            format=sticker_format,
        )
        await context.bot.create_new_sticker_set(
            user_id=update.effective_user.id,
            name=sticker_set_name,
            title=sticker_set_title,
            stickers=[sticker],
        )
        return await self._create_pack_record(
            telegram_name=sticker_set_name,
            title=sticker_set_title,
            owner_user_id=update.effective_user.id,
            chat_id=update.effective_chat.id,
            created_by_user_id=update.effective_user.id,
        )

    async def _delete_first_sticker_best_effort(
        self, context: ContextTypes.DEFAULT_TYPE, sticker_set_name: str
    ) -> bool:
        try:
            sticker_set = await context.bot.get_sticker_set(sticker_set_name)
            if not sticker_set.stickers:
                return False
            await context.bot.delete_sticker_from_set(sticker_set.stickers[0].file_id)
            return False
        except Exception as exc:
            logger.warning(f"Placeholder cleanup failed for {sticker_set_name}: {exc}")
            return True

    async def add_pending_sticker_to_pack(
        self, context: ContextTypes.DEFAULT_TYPE, pending_data: dict, pack
    ):
        image_data, sticker_format = await self._process_pending_media(
            context, pending_data
        )
        await self.add_sticker_to_pack(
            context=context,
            owner_user_id=pack.owner_user_id,
            sticker_set_name=pack.telegram_name,
            image_data=image_data,
            emoji=pending_data.get("emoji", "😀"),
            format=sticker_format,
        )

    async def add_sticker_to_pack(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        owner_user_id: int,
        sticker_set_name: str,
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
            await context.bot.add_sticker_to_set(
                user_id=owner_user_id,
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
        # run_webhook registers the webhook with Telegram; Bot.set_webhook is async
        # and must not be called without awaiting.
        self.application.run_webhook(
            listen=Config.API_HOST, port=Config.API_PORT, webhook_url=Config.WEBHOOK_URL
        )


# Global bot instance
bot = StickerBot()
