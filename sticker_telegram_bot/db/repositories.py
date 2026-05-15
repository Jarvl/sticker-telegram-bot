from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sticker_telegram_bot.db.models import StickerPack


class StickerPackRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_pack_record(
        self,
        *,
        telegram_name: str,
        title: str,
        owner_user_id: int,
        chat_id: int,
        created_by_user_id: int,
        is_visible: bool = True,
    ) -> StickerPack:
        pack = StickerPack(
            telegram_name=telegram_name,
            title=title,
            owner_user_id=owner_user_id,
            chat_id=chat_id,
            created_by_user_id=created_by_user_id,
            is_visible=is_visible,
        )
        self.session.add(pack)
        await self.session.flush()
        await self.session.refresh(pack)
        return pack

    async def get_group_pack(self, *, pack_id: int, chat_id: int) -> StickerPack | None:
        result = await self.session.execute(
            select(StickerPack).where(
                StickerPack.id == pack_id,
                StickerPack.chat_id == chat_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_telegram_name(self, telegram_name: str) -> StickerPack | None:
        result = await self.session.execute(
            select(StickerPack).where(StickerPack.telegram_name == telegram_name)
        )
        return result.scalar_one_or_none()

    async def get_group_pack_by_telegram_name(
        self, *, telegram_name: str, chat_id: int
    ) -> StickerPack | None:
        result = await self.session.execute(
            select(StickerPack).where(
                StickerPack.telegram_name == telegram_name,
                StickerPack.chat_id == chat_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_group_packs(self, chat_id: int) -> list[StickerPack]:
        result = await self.session.execute(
            select(StickerPack)
            .where(StickerPack.chat_id == chat_id)
            .order_by(StickerPack.is_visible.desc(), func.lower(StickerPack.title))
        )
        return list(result.scalars().all())

    async def list_visible_group_packs(self, chat_id: int) -> list[StickerPack]:
        result = await self.session.execute(
            select(StickerPack)
            .where(
                StickerPack.chat_id == chat_id,
                StickerPack.is_visible.is_(True),
            )
            .order_by(func.lower(StickerPack.title))
        )
        return list(result.scalars().all())

    async def set_pack_visibility(
        self, *, pack_id: int, chat_id: int, is_visible: bool
    ) -> StickerPack | None:
        pack = await self.get_group_pack(pack_id=pack_id, chat_id=chat_id)
        if pack is None:
            return None
        pack.is_visible = is_visible
        await self.session.flush()
        await self.session.refresh(pack)
        return pack
