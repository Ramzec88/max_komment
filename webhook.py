import logging
from datetime import datetime, timezone

from aiohttp import web

import config

logger = logging.getLogger(__name__)


async def handle_webhook(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="Bad JSON")

    update_type = data.get("update_type", "")

    if update_type == "comment_created":
        await _notify_admins(request.app["bot"], data, kind="новый")
    elif update_type == "comment_edited":
        await _notify_admins(request.app["bot"], data, kind="изменён")
    elif update_type == "comment_removed":
        await _notify_admins(request.app["bot"], data, kind="удалён")

    return web.Response(text="OK")


async def _notify_admins(bot, data: dict, kind: str) -> None:
    if not config.ADMIN_USER_IDS:
        return

    msg = data.get("message") or {}
    recipient = msg.get("recipient") or {}
    sender_info = msg.get("sender") or {}
    body = msg.get("body") or {}

    post_id = recipient.get("post_id", "")
    channel_id = recipient.get("chat_id", "")
    author_name = sender_info.get("first_name", "Аноним")
    username = sender_info.get("username")
    text = (body.get("text") or "").strip()

    ts = msg.get("timestamp")
    time_str = ""
    if ts:
        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        time_str = f" · {dt.strftime('%d.%m %H:%M')}"

    author = author_name + (f" (@{username})" if username else "")

    lines = [
        f"💬 Комментарий <b>{kind}</b>{time_str}",
        f"Канал: <code>{channel_id}</code>",
        f"Пост: <code>{post_id}</code>",
        f"Автор: {author}",
    ]
    if text:
        lines.append(f"\n{text}")

    notification = "\n".join(lines)

    for admin_id in config.ADMIN_USER_IDS:
        try:
            from maxapi.enums.parse_mode import ParseMode
            await bot.send_message(user_id=admin_id, text=notification, parse_mode=ParseMode.HTML)
        except Exception:
            logger.exception("Не удалось отправить уведомление пользователю %s", admin_id)


def create_app(bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/webhook", handle_webhook)
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    return app
