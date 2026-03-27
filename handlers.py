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

        if config.CHANNEL_ID != 0 and chat_id != config.CHANNEL_ID:
            return

        msg_id = event.message.body.mid if event.message.body else None
        if not msg_id:
            logger.warning("Пост без body.mid, пропускаем")
            return

        # Сохраняем существующие вложения (фото, видео и т.д.),
        # убираем старую клавиатуру, если она уже есть
        existing = event.message.body.attachments or []
        non_keyboard = [a for a in existing if not isinstance(a, AttachmentButton)]

        kb = InlineKeyboardBuilder()
        kb.row(LinkButton(text=config.BUTTON_TEXT, url=config.CHAT_URL))

        new_attachments = non_keyboard + [kb.as_markup()]

        try:
            await event.message.edit(attachments=new_attachments)
            logger.info("Кнопка добавлена к посту %s в канале %s", msg_id, chat_id)
        except Exception:
            logger.exception("Не удалось добавить кнопку к посту %s", msg_id)
