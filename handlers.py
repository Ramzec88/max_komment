import logging

from maxapi.filters.channel_post import ChannelPostFilter
from maxapi.types import MessageCreated
from maxapi.types.attachments.buttons.attachment_button import AttachmentButton
from maxapi.types.attachments.buttons.link_button import LinkButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

import config

logger = logging.getLogger(__name__)


def register(dp):
    """Регистрирует обработчик постов в канале."""

    @dp.message_created(ChannelPostFilter())
    async def on_channel_post(event: MessageCreated):
        chat_id = event.message.recipient.chat_id

        # Ищем chat_url для этого канала; ключ 0 = «все каналы»
        chat_url = config.CHANNELS.get(chat_id) or config.CHANNELS.get(0)
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
            # Берём существующую клавиатуру и проверяем, не добавляли ли мы уже кнопку
            rows = list(existing_keyboards[0].payload.buttons)
            already_added = any(
                getattr(btn, "url", None) == config.CHAT_URL
                for row in rows for btn in row
            )
            if already_added:
                logger.info("Кнопка уже есть в посте %s, пропускаем", msg_id)
                return
            # Добавляем нашу кнопку новым рядом к существующим
            rows.append([our_button])
        else:
            rows = [[our_button]]

        kb = InlineKeyboardBuilder()
        for row in rows:
            kb.row(*row)

        new_attachments = non_keyboard + [kb.as_markup()]

        try:
            await event.message.edit(attachments=new_attachments)
            logger.info("Кнопка добавлена к посту %s в канале %s", msg_id, chat_id)
        except Exception:
            logger.exception("Не удалось добавить кнопку к посту %s", msg_id)
