import logging
from datetime import datetime, timezone

from aiohttp import web

import config

logger = logging.getLogger(__name__)

COMMENT_TYPES = {"comment_created", "comment_edited", "comment_removed"}
COMMENT_KIND = {
    "comment_created": "новый",
    "comment_edited": "изменён",
    "comment_removed": "удалён",
}


def create_app(bot, maxapi_webhook) -> web.Application:
    """
    Создаёт aiohttp-приложение.
    - Все bot-события (message_created, channel_post и т.д.) → maxapi dispatcher
    - comment_* события → наш обработчик уведомлений
    """
    app = web.Application()
    app["bot"] = bot
    app.on_startup.append(maxapi_webhook.on_startup)

    async def _webhook_handler(request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return web.Response(status=400, text="Bad JSON")

        update_type = data.get("update_type", "")
        logger.info("WEBHOOK EVENT: %s | keys: %s", update_type, list(data.keys()))
        if update_type in COMMENT_TYPES:
            logger.info("COMMENT DATA: %s", data)

        if update_type in COMMENT_TYPES:
            await _notify_admins(bot, data, kind=COMMENT_KIND[update_type])
        else:
            await maxapi_webhook._dispatch(data)

        return web.Response(text="OK")

    app.router.add_post("/webhook", _webhook_handler)
    app.router.add_get("/webhook", lambda r: web.Response(text="OK"))
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    return app


async def _notify_admins(bot, data: dict, kind: str) -> None:
    if not config.ADMIN_USER_IDS:
        return

    update_type = data.get("update_type", "")

    # comment_removed has a flat structure (no nested message object)
    if update_type == "comment_removed":
        channel_id = data.get("chat_id", "")
        post_id = data.get("post_id", "")
        post_url = ""
        user_id = data.get("user_id")
        ts = data.get("timestamp")
        author = f"ID {user_id}" if user_id else "неизвестен"
        text = ""
    else:
        # comment_created / comment_edited have nested message object
        msg = data.get("message") or {}
        recipient = msg.get("recipient") or {}
        sender_info = msg.get("sender") or {}
        body = msg.get("body") or {}

        channel_id = recipient.get("chat_id", "")
        post_id = recipient.get("post_id", "")
        post_url = msg.get("url", "")
        ts = msg.get("timestamp")

        author_name = sender_info.get("first_name") or "от имени канала"
        username = sender_info.get("username")
        author = author_name + (f" (@{username})" if username else "")
        text = (body.get("text") or "").strip()

    time_str = ""
    if ts:
        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        time_str = f" · {dt.strftime('%d.%m %H:%M')}"

    # Try to get channel title via Bot API
    channel_label = str(channel_id) if channel_id else "—"
    if channel_id:
        try:
            chat = await bot.get_chat_by_id(id=int(channel_id))
            if chat and chat.title:
                channel_label = f"{chat.title} (<code>{channel_id}</code>)"
            else:
                channel_label = f"<code>{channel_id}</code>"
        except Exception:
            channel_label = f"<code>{channel_id}</code>"

    if post_url:
        post_line = f'Пост: <a href="{post_url}">{post_url}</a>'
    elif post_id:
        post_line = f"Пост: <code>{post_id}</code>"
    else:
        post_line = "Пост: —"

    lines = [
        f"💬 Комментарий <b>{kind}</b>{time_str}",
        f"Канал: {channel_label}",
        post_line,
        f"Автор: {author}",
    ]
    if text:
        lines.append(f"\n{text}")

    notification = "\n".join(lines)

    from maxapi.enums.parse_mode import ParseMode
    for admin_id in config.ADMIN_USER_IDS:
        try:
            await bot.send_message(user_id=admin_id, text=notification, parse_mode=ParseMode.HTML)
        except Exception:
            logger.exception("Не удалось отправить уведомление пользователю %s", admin_id)
