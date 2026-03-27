import logging

from maxapi.enums.chat_type import ChatType
from maxapi.enums.message_link_type import MessageLinkType
from maxapi.filters.channel_post import ChannelPostFilter
from maxapi.filters.filter import BaseFilter
from maxapi.types import MessageCreated
from maxapi.types import Command
from maxapi.types.attachments.buttons.attachment_button import AttachmentButton
from maxapi.types.attachments.buttons.link_button import LinkButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

import config
import storage

logger = logging.getLogger(__name__)

# In-memory FSM: {user_id: {"step": "waiting_forward"|"waiting_url", "channel_id": int}}
_pending: dict[int, dict] = {}


class PendingStateFilter(BaseFilter):
    """Фильтр: сообщение из DM от пользователя с активным шагом диалога."""

    def __init__(self, step: str) -> None:
        self.step = step

    async def __call__(self, event) -> bool:
        if not isinstance(event, MessageCreated):
            return False
        if event.message.recipient.chat_type != ChatType.DIALOG:
            return False
        sender = event.message.sender
        if sender is None:
            return False
        return _pending.get(sender.user_id, {}).get("step") == self.step


def _is_admin(event: MessageCreated) -> bool:
    if not config.ADMIN_USER_IDS:
        return True
    sender = event.message.sender
    return sender is not None and sender.user_id in config.ADMIN_USER_IDS


def _get_chat_url(channel_id: int) -> str | None:
    channels = storage.get_channels()
    return (
        channels.get(channel_id)
        or channels.get(0)
        or config.CHANNELS.get(channel_id)
        or config.CHANNELS.get(0)
    )


def register(dp) -> None:
    """Регистрирует все обработчики. Порядок важен."""

    # ── /cancel ────────────────────────────────────────────────────────────

    @dp.message_created(Command("cancel"))
    async def cmd_cancel(event: MessageCreated):
        sender = event.message.sender
        if sender and _pending.pop(sender.user_id, None):
            await event.message.answer("Отменено.")
        else:
            await event.message.answer("Нет активного действия.")

    # ── /addchannel ────────────────────────────────────────────────────────

    @dp.message_created(Command("addchannel"))
    async def cmd_add_channel(event: MessageCreated):
        if not _is_admin(event):
            await event.message.answer("⛔ Недостаточно прав.")
            return

        parts = (event.message.body.text or "").split()

        if len(parts) == 1:
            # Без аргументов — запускаем диалог
            sender = event.message.sender
            if sender:
                _pending[sender.user_id] = {"step": "waiting_forward"}
            await event.message.answer(
                "Перешлите любой пост из канала — я определю его ID.\n\n"
                "⚠️ Убедитесь, что бот добавлен администратором в этот канал, "
                "иначе кнопки добавляться не будут.\n\n"
                "/cancel для отмены."
            )
            return

        if len(parts) == 3:
            # Прямое добавление: /addchannel <id> <url>
            try:
                channel_id = int(parts[1])
            except ValueError:
                await event.message.answer("❌ channel_id должен быть числом.")
                return
            chat_url = parts[2]
            storage.add_channel(channel_id, chat_url)
            logger.info("Добавлен канал %s → %s", channel_id, chat_url)
            await event.message.answer(
                f"✅ Канал <b>{channel_id}</b> добавлен.\nЧат: {chat_url}",
                format="html",
            )
            return

        await event.message.answer(
            "Использование:\n"
            "/addchannel — запустить диалог (переслать пост)\n"
            "/addchannel <channel_id> <chat_url> — прямое добавление"
        )

    # ── /removechannel ─────────────────────────────────────────────────────

    @dp.message_created(Command("removechannel"))
    async def cmd_remove_channel(event: MessageCreated):
        if not _is_admin(event):
            await event.message.answer("⛔ Недостаточно прав.")
            return

        parts = (event.message.body.text or "").split()
        if len(parts) != 2:
            await event.message.answer("Использование:\n/removechannel <channel_id>")
            return

        try:
            channel_id = int(parts[1])
        except ValueError:
            await event.message.answer("❌ channel_id должен быть числом.")
            return

        if storage.remove_channel(channel_id):
            logger.info("Удалён канал %s", channel_id)
            await event.message.answer(f"✅ Канал {channel_id} удалён.")
        else:
            await event.message.answer(f"⚠️ Канал {channel_id} не найден в базе.")

    # ── /channels ──────────────────────────────────────────────────────────

    @dp.message_created(Command("channels"))
    async def cmd_list_channels(event: MessageCreated):
        if not _is_admin(event):
            await event.message.answer("⛔ Недостаточно прав.")
            return

        db_channels = storage.get_channels()
        all_channels = {**config.CHANNELS, **db_channels}

        if not all_channels:
            await event.message.answer("Каналы не настроены.")
            return

        lines = []
        for ch_id, url in all_channels.items():
            label = "все каналы" if ch_id == 0 else str(ch_id)
            src = " (env)" if ch_id in config.CHANNELS and ch_id not in db_channels else " (БД)"
            lines.append(f"• {label}{src} → {url}")

        await event.message.answer("📋 Настроенные каналы:\n" + "\n".join(lines))

    # ── Диалог: шаг 1 — ждём пересланный пост ─────────────────────────────

    @dp.message_created(PendingStateFilter("waiting_forward"))
    async def on_forwarded_post(event: MessageCreated):
        msg = event.message
        link = msg.link

        if not link or link.type != MessageLinkType.FORWARD or not link.chat_id:
            await msg.answer(
                "Это не пересланный пост из канала. "
                "Перешлите пост или /cancel для отмены."
            )
            return

        channel_id = link.chat_id
        sender = msg.sender
        if sender:
            _pending[sender.user_id] = {"step": "waiting_url", "channel_id": channel_id}

        await msg.answer(
            f"Канал найден: <b>{channel_id}</b>\n\n"
            "Теперь отправьте ссылку на чат для обсуждений\n"
            "(или /cancel для отмены):",
            format="html",
        )

    # ── Диалог: шаг 2 — ждём ссылку на чат ───────────────────────────────

    @dp.message_created(PendingStateFilter("waiting_url"))
    async def on_chat_url(event: MessageCreated):
        msg = event.message
        url = (msg.body.text or "").strip() if msg.body else ""

        if not url.startswith("http"):
            await msg.answer(
                "Отправьте корректную ссылку (должна начинаться с https://).\n"
                "/cancel для отмены."
            )
            return

        sender = msg.sender
        if sender is None:
            return

        state = _pending.pop(sender.user_id, {})
        channel_id = state.get("channel_id")
        if channel_id is None:
            await msg.answer("Что-то пошло не так. Начните заново: /addchannel")
            return

        storage.add_channel(channel_id, url)
        logger.info("Добавлен канал %s → %s", channel_id, url)
        await msg.answer(
            f"✅ Готово!\nКанал: <b>{channel_id}</b>\nЧат: {url}",
            format="html",
        )

    # ── Обработчик постов канала (последним) ───────────────────────────────

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
