import importlib
import io
import sys
from types import SimpleNamespace

import pytest
from PIL import Image
from telegram.ext import ConversationHandler

from sticker_telegram_bot.db.repositories import StickerPackRepository


def load_bot_module(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "dummybot")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/db"
    )
    for module_name in [
        "sticker_telegram_bot.bot",
        "sticker_telegram_bot.db.session",
        "sticker_telegram_bot.config",
    ]:
        sys.modules.pop(module_name, None)
    return importlib.import_module("sticker_telegram_bot.bot")


def test_group_sticker_set_name_is_telegram_safe(monkeypatch):
    bot_module = load_bot_module(monkeypatch)
    sticker_bot = bot_module.StickerBot()

    name = sticker_bot._make_group_sticker_set_name(
        title="Group Memes!!!",
        username="dummybot",
        chat_id=-100123456789,
    )

    assert name == "Group_Memes_100123456789_by_dummybot"
    assert len(name) <= 64


def test_empty_pack_placeholder_is_white_square(monkeypatch):
    bot_module = load_bot_module(monkeypatch)
    sticker_bot = bot_module.StickerBot()

    image = Image.open(io.BytesIO(sticker_bot._make_placeholder_sticker()))

    assert image.size == (512, 512)
    assert image.getpixel((0, 0)) == (255, 255, 255, 255)


@pytest.mark.asyncio
async def test_process_image_for_sticker_returns_optimized_png(monkeypatch):
    bot_module = load_bot_module(monkeypatch)
    sticker_bot = bot_module.StickerBot()
    source = Image.new("RGB", (2048, 1024), "navy")
    source.paste("gold", (100, 100, 900, 500))
    input_file = io.BytesIO()
    source.save(input_file, format="PNG")

    sticker_data = await sticker_bot.process_image_for_sticker(input_file.getvalue())
    sticker = Image.open(io.BytesIO(sticker_data))

    assert len(sticker_data) <= sticker_bot.MAX_STATIC_STICKER_BYTES
    assert sticker.format == "PNG"
    assert sticker.size == (512, 512)


def test_bot_managed_pack_name_requires_bot_suffix(monkeypatch):
    bot_module = load_bot_module(monkeypatch)
    sticker_bot = bot_module.StickerBot()

    assert sticker_bot._is_bot_managed_pack_name("Group_Memes_by_dummybot", "dummybot")
    assert not sticker_bot._is_bot_managed_pack_name(
        "Group_Memes_by_otherbot", "dummybot"
    )


def test_normalize_single_emoji_allows_variation_selector_noise(monkeypatch):
    bot_module = load_bot_module(monkeypatch)
    sticker_bot = bot_module.StickerBot()

    assert sticker_bot._normalize_single_emoji("🌭️️️️️️") == "🌭"
    assert sticker_bot._normalize_single_emoji("👁️️️️️️") == "👁️"
    assert sticker_bot._normalize_single_emoji("🧑‍💻️️") == "🧑‍💻"
    assert sticker_bot._normalize_single_emoji("👍🏽") == "👍🏽"
    assert sticker_bot._normalize_single_emoji("🌭👁️") is None
    assert sticker_bot._normalize_single_emoji("🌭x") is None


def test_manage_home_keyboard_places_import_and_create_on_same_row(monkeypatch):
    bot_module = load_bot_module(monkeypatch)
    sticker_bot = bot_module.StickerBot()

    rows = [
        [(button.text, button.callback_data) for button in row]
        for row in sticker_bot._manage_home_keyboard().inline_keyboard
    ]

    assert [
        ("📥 Import Sticker Set", "mg:import"),
        ("✨ Create Sticker Set", "mg:create"),
    ] in rows


class DummySession:
    def __init__(self):
        self.added = None
        self.flushed = False
        self.refreshed = None

    def add(self, value):
        self.added = value

    async def flush(self):
        self.flushed = True

    async def refresh(self, value):
        self.refreshed = value


class DummyMessage:
    def __init__(self, *, text=None, message_id=10, chat_id=-100, sticker=None):
        self.text = text
        self.message_id = message_id
        self.chat_id = chat_id
        self.sticker = sticker
        self.reply_to_message = None
        self.replies = []

    async def reply_text(self, text, **kwargs):
        reply = DummyMessage(message_id=kwargs.pop("message_id", self.message_id + 1))
        self.replies.append((text, kwargs, reply))
        return reply


class DummyQuery:
    def __init__(self, data, message):
        self.data = data
        self.message = message
        self.edits = []
        self.answered = False

    async def answer(self):
        self.answered = True

    async def edit_message_text(self, text, **kwargs):
        self.edits.append((text, kwargs))


def make_update(message=None, query=None, chat_id=-100):
    return SimpleNamespace(
        message=message,
        callback_query=query,
        effective_chat=SimpleNamespace(id=chat_id, type="supergroup"),
        effective_user=SimpleNamespace(id=123),
    )


def make_context():
    return SimpleNamespace(
        user_data={},
        bot=SimpleNamespace(username="dummybot"),
    )


@pytest.mark.asyncio
async def test_repository_creates_denormalized_group_pack_record():
    session = DummySession()
    repo = StickerPackRepository(session)

    pack = await repo.create_pack_record(
        telegram_name="Group_Memes_100123456789_by_dummybot",
        title="Group Memes",
        owner_user_id=111,
        chat_id=-100123456789,
        created_by_user_id=222,
    )

    assert session.added is pack
    assert session.flushed is True
    assert session.refreshed is pack
    assert pack.telegram_name == "Group_Memes_100123456789_by_dummybot"
    assert pack.chat_id == -100123456789
    assert pack.is_visible is True


@pytest.mark.asyncio
async def test_sticker_pack_selection_includes_import_option(monkeypatch):
    bot_module = load_bot_module(monkeypatch)
    sticker_bot = bot_module.StickerBot()

    async def load_visible_group_packs(chat_id):
        return []

    monkeypatch.setattr(
        sticker_bot, "_load_visible_group_packs", load_visible_group_packs
    )
    context = make_context()
    message = DummyMessage(text="🗿")
    message.reply_to_message = SimpleNamespace(message_id=99)
    update = make_update(message=message)
    flow = sticker_bot._flow_data(update, context)
    flow["pending_sticker"] = {"chat_id": -100, "file_id": "file-id"}
    flow["emoji_prompt_message_id"] = 99

    state = await sticker_bot.handle_sticker_emoji(update, context)

    assert state == sticker_bot.STICKER_PACK_SELECT
    reply_markup = message.replies[-1][1]["reply_markup"]
    callback_data = [
        button.callback_data for row in reply_markup.inline_keyboard for button in row
    ]
    rows = [
        [(button.text, button.callback_data) for button in row]
        for row in reply_markup.inline_keyboard
    ]
    assert "st:create" in callback_data
    assert "st:import" in callback_data
    assert [
        ("📥 Import Sticker Set", "st:import"),
        ("✨ Create Sticker Set", "st:create"),
    ] in rows


@pytest.mark.asyncio
async def test_sticker_import_callback_prompts_for_pack_sticker(monkeypatch):
    bot_module = load_bot_module(monkeypatch)
    sticker_bot = bot_module.StickerBot()
    context = make_context()
    callback_message = DummyMessage(message_id=20)
    query = DummyQuery("st:import", callback_message)
    update = make_update(query=query)
    flow = sticker_bot._flow_data(update, context)
    flow["pending_sticker"] = {"chat_id": -100, "file_id": "file-id"}

    state = await sticker_bot.handle_sticker_callback(update, context)

    assert state == sticker_bot.STICKER_PACK_SELECT
    assert query.answered is True
    assert flow["sticker_action"] == "import_pack"
    assert flow["action_message_id"] == 20
    assert flow["pack_import_prompt_message_id"] == 21
    assert "Import an existing bot-managed sticker pack" in query.edits[-1][0]


@pytest.mark.asyncio
async def test_sticker_import_adds_pending_sticker_to_imported_pack(monkeypatch):
    bot_module = load_bot_module(monkeypatch)
    sticker_bot = bot_module.StickerBot()
    context = make_context()
    prompt = SimpleNamespace(message_id=21)
    sticker = SimpleNamespace(set_name="Group_Memes_by_dummybot")
    message = DummyMessage(message_id=30, sticker=sticker)
    message.reply_to_message = prompt
    update = make_update(message=message)
    pending_sticker = {"chat_id": -100, "file_id": "file-id", "emoji": "🗿"}
    flow = sticker_bot._flow_data(update, context)
    flow["sticker_action"] = "import_pack"
    flow["pending_sticker"] = pending_sticker
    flow["pack_import_prompt_message_id"] = 21
    pack = SimpleNamespace(
        id=1,
        title="Group Memes",
        telegram_name="Group_Memes_by_dummybot",
        owner_user_id=123,
        is_visible=True,
    )
    added = {}

    async def import_group_pack_from_sticker(update_arg, context_arg, sticker_arg):
        return pack, False

    async def add_pending_sticker_to_pack(context_arg, pending_arg, pack_arg):
        added["context"] = context_arg
        added["pending"] = pending_arg
        added["pack"] = pack_arg

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(
        sticker_bot,
        "_import_group_pack_from_sticker",
        import_group_pack_from_sticker,
    )
    monkeypatch.setattr(
        sticker_bot, "add_pending_sticker_to_pack", add_pending_sticker_to_pack
    )
    monkeypatch.setattr(sticker_bot, "_replace_action_message", noop)
    monkeypatch.setattr(sticker_bot, "_cleanup_reply_prompts", noop)

    state = await sticker_bot.handle_sticker_import_sticker(update, context)

    assert state == ConversationHandler.END
    assert added == {"context": context, "pending": pending_sticker, "pack": pack}
    assert "Sticker added" in message.replies[-1][0]
