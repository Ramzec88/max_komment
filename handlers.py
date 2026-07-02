import logging

from maxapi.enums.chat_type import ChatType
from maxapi.enums.message_link_type import MessageLinkType
from maxapi.enums.parse_mode import ParseMode
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

# In-memory FSM: {user_id: {"step": str, ...}}
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


def _is_discuss_row(row: list) -> bool:
    return any(getattr(btn, "text", None) == config.BUTTON_TEXT for btn in row)


def _split_rows(rows: list[list]) -> tuple[list[list], list[list]]:
    custom = [r for r in rows if not _is_discuss_row(r)]
    discuss = [r for r in rows if _is_discuss_row(r)]
    return custom, discuss


def register(dp, bot) -> None:
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
                format=ParseMode.HTML,
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

    # ── /whoowns ───────────────────────────────────────────────────────────

    @dp.message_created(Command("whoowns"))
    async def cmd_whoowns(event: MessageCreated):
        if not _is_admin(event):
            await event.message.answer("⛔ Недостаточно прав.")
            return

        sender = event.message.sender
        if sender:
            _pending[sender.user_id] = {"step": "whoowns_input"}
        await event.message.answer(
            "Перешлите пост из канала или отправьте ссылку на канал "
            "(например: https://max.ru/имя_канала или просто @имя_канала).\n"
            "/cancel для отмены."
        )

    # ── whoowns: ждём пост или ссылку ─────────────────────────────────────

    @dp.message_created(PendingStateFilter("whoowns_input"))
    async def on_whoowns_input(event: MessageCreated):
        msg = event.message
        sender = msg.sender
        if sender is None:
            return

        _pending.pop(sender.user_id, None)

        link = msg.link
        text = (msg.body.text or "").strip() if msg.body else ""

        chat = None
        chat_id = None

        # Пересланный пост — берём chat_id напрямую
        if link and link.type == MessageLinkType.FORWARD and link.chat_id:
            chat_id = link.chat_id
            try:
                chat = await bot.get_chat_by_id(id=chat_id)
            except Exception:
                logger.exception("Не удалось получить чат %s", chat_id)
                await msg.answer("❌ Не удалось получить информацию о канале.")
                return

        # Текстовая ссылка или @alias
        elif text:
            try:
                chat = await bot.get_chat_by_link(text)
                chat_id = chat.chat_id
            except Exception:
                logger.exception("Не удалось найти канал по ссылке: %s", text)
                await msg.answer(
                    "❌ Не удалось найти канал. Проверьте ссылку и попробуйте снова."
                )
                return
        else:
            await msg.answer(
                "Перешлите пост из канала или отправьте ссылку на канал.\n"
                "/cancel для отмены."
            )
            _pending[sender.user_id] = {"step": "whoowns_input"}
            return

        if chat is None or chat.owner_id is None:
            await msg.answer("⚠️ Не удалось определить владельца канала.")
            return

        owner_id = chat.owner_id
        channel_title = chat.title or str(chat_id)

        # Пробуем получить имя/ник владельца
        owner_name = None
        owner_username = None
        if chat_id is not None:
            try:
                member = await bot.get_chat_member(chat_id, owner_id)
                if member:
                    owner_name = member.full_name
                    owner_username = member.username
            except Exception:
                pass  # Бот не в канале — покажем только ID

        lines = [f"📢 Канал: <b>{channel_title}</b>", f"👤 Владелец ID: <code>{owner_id}</code>"]
        if owner_name:
            lines.append(f"Имя: {owner_name}")
        if owner_username:
            lines.append(f"Ник: @{owner_username}")

        await msg.answer("\n".join(lines), format=ParseMode.HTML)

    # ── /addbutton ─────────────────────────────────────────────────────────

    @dp.message_created(Command("addbutton"))
    async def cmd_add_button(event: MessageCreated):
        if not _is_admin(event):
            await event.message.answer("⛔ Недостаточно прав.")
            return

        sender = event.message.sender
        if sender:
            _pending[sender.user_id] = {"step": "add_btn_forward"}
        await event.message.answer(
            "Перешлите пост из канала, к которому нужно добавить кнопку.\n"
            "/cancel для отмены."
        )

    # ── /removebutton ──────────────────────────────────────────────────────

    @dp.message_created(Command("removebutton"))
    async def cmd_remove_button(event: MessageCreated):
        if not _is_admin(event):
            await event.message.answer("⛔ Недостаточно прав.")
            return

        sender = event.message.sender
        if sender:
            _pending[sender.user_id] = {"step": "rm_btn_forward"}
        await event.message.answer(
            "Перешлите пост из канала, с которого нужно удалить кнопку.\n"
            "/cancel для отмены."
        )

    # ── Диалог: шаг 1 — ждём пересланный пост (addchannel) ────────────────

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
            format=ParseMode.HTML,
        )

    # ── Диалог: шаг 2 — ждём ссылку на чат (addchannel) ──────────────────

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
            format=ParseMode.HTML,
        )

    # ── addbutton: шаг 1 — ждём пересланный пост ──────────────────────────

    @dp.message_created(PendingStateFilter("add_btn_forward"))
    async def on_add_btn_forward(event: MessageCreated):
        msg = event.message
        link = msg.link

        if not link or link.type != MessageLinkType.FORWARD or not link.message:
            await msg.answer(
                "Это не пересланный пост из канала. "
                "Перешлите пост или /cancel для отмены."
            )
            return

        message_id = link.message.mid
        channel_id = link.chat_id
        sender = msg.sender
        if sender:
            _pending[sender.user_id] = {
                "step": "add_btn_text",
                "message_id": message_id,
                "channel_id": channel_id,
            }

        await msg.answer(
            "Введите текст кнопки (например: «Купить»):\n"
            "/cancel для отмены."
        )

    # ── addbutton: шаг 2 — ждём текст кнопки ─────────────────────────────

    @dp.message_created(PendingStateFilter("add_btn_text"))
    async def on_add_btn_text(event: MessageCreated):
        msg = event.message
        btn_text = (msg.body.text or "").strip() if msg.body else ""

        if not btn_text:
            await msg.answer("Текст не может быть пустым. Введите текст кнопки:")
            return

        sender = msg.sender
        if sender is None:
            return

        _pending[sender.user_id]["step"] = "add_btn_url"
        _pending[sender.user_id]["btn_text"] = btn_text

        await msg.answer(
            f"Текст кнопки: «{btn_text}»\n\n"
            "Теперь введите URL для кнопки:\n"
            "/cancel для отмены."
        )

    # ── addbutton: шаг 3 — ждём URL ───────────────────────────────────────

    @dp.message_created(PendingStateFilter("add_btn_url"))
    async def on_add_btn_url(event: MessageCreated):
        msg = event.message
        btn_url = (msg.body.text or "").strip() if msg.body else ""

        if not btn_url.startswith("http"):
            await msg.answer(
                "Отправьте корректную ссылку (должна начинаться с https://).\n"
                "/cancel для отмены."
            )
            return

        sender = msg.sender
        if sender is None:
            return

        state = _pending.pop(sender.user_id, {})
        mid = state.get("message_id")
        btn_text = state.get("btn_text", "")

        if not mid:
            await msg.answer("Что-то пошло не так. Начните заново: /addbutton")
            return

        try:
            post = await bot.get_message(message_id=mid)
        except Exception:
            logger.exception("Не удалось получить пост %s", mid)
            await msg.answer("❌ Не удалось получить пост. Попробуйте снова.")
            return

        existing = (post.body.attachments or []) if post.body else []
        non_keyboard = [a for a in existing if not isinstance(a, AttachmentButton)]
        existing_keyboards = [a for a in existing if isinstance(a, AttachmentButton)]

        rows = list(existing_keyboards[0].payload.buttons) if existing_keyboards else []
        custom_rows, discuss_rows = _split_rows(rows)

        new_row = [LinkButton(text=btn_text, url=btn_url)]
        new_rows = custom_rows + [new_row] + discuss_rows

        kb = InlineKeyboardBuilder()
        for row in new_rows:
            kb.row(*row)

        try:
            await bot.edit_message(message_id=mid, attachments=non_keyboard + [kb.as_markup()])
            logger.info("Кнопка «%s» добавлена к посту %s", btn_text, mid)
            await msg.answer(f"✅ Кнопка «{btn_text}» добавлена к посту!")
        except Exception:
            logger.exception("Не удалось изменить пост %s", mid)
            await msg.answer(
                "❌ Не удалось изменить пост. "
                "Проверьте, что бот — администратор канала."
            )

    # ── removebutton: шаг 1 — ждём пересланный пост ───────────────────────

    @dp.message_created(PendingStateFilter("rm_btn_forward"))
    async def on_rm_btn_forward(event: MessageCreated):
        msg = event.message
        link = msg.link

        if not link or link.type != MessageLinkType.FORWARD or not link.message:
            await msg.answer(
                "Это не пересланный пост из канала. "
                "Перешлите пост или /cancel для отмены."
            )
            return

        message_id = link.message.mid
        sender = msg.sender
        if sender is None:
            return

        try:
            post = await bot.get_message(message_id=message_id)
        except Exception:
            logger.exception("Не удалось получить пост %s", message_id)
            await msg.answer("❌ Не удалось получить пост. Попробуйте снова.")
            return

        existing = (post.body.attachments or []) if post.body else []
        existing_keyboards = [a for a in existing if isinstance(a, AttachmentButton)]

        if not existing_keyboards:
            await msg.answer("В этом посте нет кнопок.")
            _pending.pop(sender.user_id, None)
            return

        rows = list(existing_keyboards[0].payload.buttons)
        custom_rows, _ = _split_rows(rows)

        if not custom_rows:
            await msg.answer(
                "В этом посте нет пользовательских кнопок "
                "(только «" + config.BUTTON_TEXT + "»)."
            )
            _pending.pop(sender.user_id, None)
            return

        _pending[sender.user_id] = {
            "step": "rm_btn_select",
            "message_id": message_id,
        }

        lines = []
        for i, row in enumerate(custom_rows, 1):
            btn_labels = ", ".join(getattr(btn, "text", "?") for btn in row)
            lines.append(f"{i}. {btn_labels}")

        await msg.answer(
            "Выберите кнопку для удаления (введите номер):\n"
            + "\n".join(lines)
            + "\n\n/cancel для отмены."
        )

    # ── removebutton: шаг 2 — ждём выбор номера ───────────────────────────

    @dp.message_created(PendingStateFilter("rm_btn_select"))
    async def on_rm_btn_select(event: MessageCreated):
        msg = event.message
        text = (msg.body.text or "").strip() if msg.body else ""

        sender = msg.sender
        if sender is None:
            return

        state = _pending.pop(sender.user_id, {})
        mid = state.get("message_id")

        if not mid:
            await msg.answer("Что-то пошло не так. Начните заново: /removebutton")
            return

        try:
            choice = int(text)
        except ValueError:
            await msg.answer(
                "Введите номер кнопки из списка. Начните заново: /removebutton"
            )
            return

        try:
            post = await bot.get_message(message_id=mid)
        except Exception:
            logger.exception("Не удалось получить пост %s", mid)
            await msg.answer("❌ Не удалось получить пост. Попробуйте снова.")
            return

        existing = (post.body.attachments or []) if post.body else []
        non_keyboard = [a for a in existing if not isinstance(a, AttachmentButton)]
        existing_keyboards = [a for a in existing if isinstance(a, AttachmentButton)]

        rows = list(existing_keyboards[0].payload.buttons) if existing_keyboards else []
        custom_rows, discuss_rows = _split_rows(rows)

        if choice < 1 or choice > len(custom_rows):
            await msg.answer(
                f"Номер должен быть от 1 до {len(custom_rows)}. "
                "Начните заново: /removebutton"
            )
            return

        removed_row = custom_rows.pop(choice - 1)
        removed_label = ", ".join(getattr(btn, "text", "?") for btn in removed_row)

        new_rows = custom_rows + discuss_rows

        if not new_rows:
            try:
                await bot.edit_message(message_id=mid, attachments=non_keyboard)
                await msg.answer(
                    f"✅ Кнопка «{removed_label}» удалена. Клавиатура поста очищена."
                )
            except Exception:
                logger.exception("Не удалось изменить пост %s", mid)
                await msg.answer("❌ Не удалось изменить пост.")
            return

        kb = InlineKeyboardBuilder()
        for row in new_rows:
            kb.row(*row)

        try:
            await bot.edit_message(message_id=mid, attachments=non_keyboard + [kb.as_markup()])
            logger.info("Кнопка «%s» удалена из поста %s", removed_label, mid)
            await msg.answer(f"✅ Кнопка «{removed_label}» удалена.")
        except Exception:
            logger.exception("Не удалось изменить пост %s", mid)
            await msg.answer(
                "❌ Не удалось изменить пост. "
                "Проверьте, что бот — администратор канала."
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
