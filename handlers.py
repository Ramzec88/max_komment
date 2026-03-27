import logging

from maxapi.filters.channel_post import ChannelPostFilter
from maxapi.types import MessageCreated
from maxapi.types import Command
from maxapi.types.attachments.buttons.attachment_button import AttachmentButton
from maxapi.types.attachments.buttons.link_button import LinkButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

import config
import storage

logger = logging.getLogger(__name__)


def _is_admin(event: MessageCreated) -> bool:
    """Проверяет, является ли отправитель сообщения администратором бота."""
    if not config.ADMIN_USER_IDS:
        return True  # если список не задан — разрешаем всем
    sender = event.message.sender
    return sender is not None and sender.user_id in config.ADMIN_USER_IDS


def _get_chat_url(channel_id: int) -> str | None:
    """Возвращает chat_url для канала: сначала из БД, потом из env-конфига."""
    channels = storage.get_channels()
    return (
        channels.get(channel_id)
        or channels.get(0)
        or config.CHANNELS.get(channel_id)
        or config.CHANNELS.get(0)
    )


def register(dp) -> None:
    """Регистрирует все обработчики."""

    # ── Команды управления ─────────────────────────────────────────────────

    @dp.message_created(Command("addchannel"))
    async def cmd_add_channel(event: MessageCreated):
        if not _is_admin(event):
            await event.message.answer("⛔ Недостаточно прав.")
            return

        parts = (event.message.body.text or "").split()
        if len(parts) != 3:
            await event.message.answer(
                "Использование:\n/addchannel <channel_id> <chat_url>\n\n"
                "Пример:\n/addchannel -72594321794397 https://max.ru/join/abc"
            )
            return

        try:
            channel_id = int(parts[1])
        except ValueError:
            await event.message.answer("❌ channel_id должен быть числом.")
            return

        chat_url = parts[2]
        storage.add_channel(channel_id, chat_url)
        logger.info("Добавлен канал %s → %s", channel_id, chat_url)
        await event.message.answer(
            f"✅ Канал <b>{channel_id}</b> добавлен.\n"
            f"Чат: {chat_url}",
            format="html",
        )

    @dp.message_created(Command("removechannel"))
    async def cmd_remove_channel(event: MessageCreated):
        if not _is_admin(event):
            await event.message.answer("⛔ Недостаточно прав.")
            return

        parts = (event.message.body.text or "").split()
        if len(parts) != 2:
            await event.message.answer(
                "Использование:\n/removechannel <channel_id>"
            )
            return

        try:
            channel_id = int(parts[1])
        except ValueError:
            await event.message.answer("❌ channel_id должен быть числом.")
            return

        removed = storage.remove_channel(channel_id)
        if removed:
            logger.info("Удалён канал %s", channel_id)
            await event.message.answer(f"✅ Канал {channel_id} удалён.")
        else:
            await event.message.answer(f"⚠️ Канал {channel_id} не найден в базе.")

    @dp.message_created(Command("channels"))
    async def cmd_list_channels(event: MessageCreated):
        if not _is_admin(event):
            await event.message.answer("⛔ Недостаточно прав.")
            return

        db_channels = storage.get_channels()
        all_channels = {**config.CHANNELS, **db_channels}  # БД перекрывает env

        if not all_channels:
            await event.message.answer("Каналы не настроены.")
            return

        lines = []
        for ch_id, url in all_channels.items():
            label = "все каналы" if ch_id == 0 else str(ch_id)
            src = " (env)" if ch_id in config.CHANNELS and ch_id not in db_channels else " (БД)"
            lines.append(f"• {label}{src} → {url}")

        await event.message.answer("📋 Настроенные каналы:\n" + "\n".join(lines))

    # ── Обработчик постов канала ───────────────────────────────────────────

    @dp.message_created(ChannelPostFilter())
    async def on_channel_post(event: MessageCreated):
        chat_id = event.message.recipient.chat_id
        chat_url = _get_chat_url(chat_id)
        if not chat_url:
            return

        msg_id = event.message.body.mid if event.message.body else None
        if not msg_id:
            logger.warning("Пост без body.mid, пропускаем")
            return

        existing = event.message.body.attachments or []
        non_keyboard = [a for a in existing if not isinstance(a, AttachmentButton)]
        existing_keyboards = [a for a in existing if isinstance(a, AttachmentButton)]

        our_button = LinkButton(text=config.BUTTON_TEXT, url=chat_url)

        if existing_keyboards:
            rows = list(existing_keyboards[0].payload.buttons)
            already_added = any(
                getattr(btn, "url", None) == chat_url
                for row in rows for btn in row
            )
            if already_added:
                logger.info("Кнопка уже есть в посте %s, пропускаем", msg_id)
                return
            rows.append([our_button])
        else:
            rows = [[our_button]]

        kb = InlineKeyboardBuilder()
        for row in rows:
            kb.row(*row)

        try:
            await event.message.edit(attachments=non_keyboard + [kb.as_markup()])
            logger.info("Кнопка добавлена к посту %s в канале %s", msg_id, chat_id)
        except Exception:
            logger.exception("Не удалось добавить кнопку к посту %s", msg_id)
