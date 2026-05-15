import importlib
import io
import sys

import pytest
from PIL import Image

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
