import logging
import ssl
import aiohttp

PLATFORM_API = "https://platform-api2.max.ru"
COMMENT_UPDATE_TYPES = ["comment_created", "comment_edited", "comment_removed"]
# All event types needed: bot conversation events + channel comment events
ALL_WEBHOOK_UPDATE_TYPES = [
    "message_created", "message_edited", "message_removed",
    "message_callback",
    "bot_started", "bot_added", "bot_removed", "bot_stopped",
    "chat_title_changed",
    "user_added", "user_removed",
    "comment_created", "comment_edited", "comment_removed",
]
logger = logging.getLogger(__name__)

# platform-api2.max.ru использует сертификат Минцифры, которому не доверяют
# стандартные CA-хранилища на зарубежных серверах (Railway, Heroku и др.)
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE


def _session() -> aiohttp.ClientSession:
    connector = aiohttp.TCPConnector(ssl=_SSL)
    return aiohttp.ClientSession(connector=connector)


async def subscribe_webhooks(token: str, url: str) -> dict:
    """Регистрирует единый webhook для всех событий (бот + комментарии)."""
    endpoint = f"{PLATFORM_API}/subscriptions"
    headers = {"Authorization": token}
    payload = {"url": url, "update_types": ALL_WEBHOOK_UPDATE_TYPES}

    async with _session() as session:
        async with session.post(endpoint, headers=headers, json=payload) as resp:
            data = await resp.json()
            if resp.status not in (200, 201):
                raise RuntimeError(f"Не удалось подписаться на webhook: HTTP {resp.status} — {data}")
            return data


async def get_subscriptions(token: str) -> list[dict]:
    """Возвращает активные webhook-подписки."""
    endpoint = f"{PLATFORM_API}/subscriptions"
    headers = {"Authorization": token}

    async with _session() as session:
        async with session.get(endpoint, headers=headers) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data.get("subscriptions", [])


async def get_comments(token: str, message_id: str, count: int = 10) -> list[dict]:
    url = f"{PLATFORM_API}/messages/{message_id}/comments"
    headers = {"Authorization": token}
    params = {"count": count}

    try:
        async with _session() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 401:
                    raise PermissionError("Токен недействителен (401)")
                if resp.status == 403:
                    raise PermissionError(
                        "Нет доступа (403) — проверьте, что бот администратор канала "
                        "с правом read_all_messages"
                    )
                if resp.status != 200:
                    logger.warning("get_comments HTTP %s для поста %s", resp.status, message_id)
                    return []
                data = await resp.json()
                return data.get("messages", [])
    except PermissionError:
        raise
    except Exception as e:
        logger.exception("Ошибка при получении комментариев к посту %s", message_id)
        raise RuntimeError(str(e)) from e


async def delete_comment(token: str, message_id: str, comment_id: str) -> bool:
    url = f"{PLATFORM_API}/messages/{message_id}/comments"
    headers = {"Authorization": token}
    params = {"comment_id": comment_id}

    try:
        async with _session() as session:
            async with session.delete(url, headers=headers, params=params) as resp:
                if resp.status == 401:
                    raise PermissionError("Токен недействителен (401)")
                if resp.status == 403:
                    raise PermissionError(
                        "Нет доступа (403) — проверьте, что бот администратор канала "
                        "с правами read_all_messages и delete"
                    )
                data = await resp.json()
                if not data.get("success"):
                    msg = data.get("message", "неизвестная ошибка")
                    raise RuntimeError(f"Удаление не выполнено: {msg}")
                return True
    except PermissionError:
        raise
    except RuntimeError:
        raise
    except Exception as e:
        logger.exception("Ошибка при удалении комментария %s поста %s", comment_id, message_id)
        raise RuntimeError(str(e)) from e


async def edit_comment(token: str, message_id: str, comment_id: str, text: str) -> bool:
    url = f"{PLATFORM_API}/messages/{message_id}/comments"
    headers = {"Authorization": token}
    params = {"comment_id": comment_id}
    payload = {"text": text}

    try:
        async with _session() as session:
            async with session.put(url, headers=headers, params=params, json=payload) as resp:
                if resp.status == 401:
                    raise PermissionError("Токен недействителен (401)")
                if resp.status == 403:
                    raise PermissionError(
                        "Нет доступа (403) — можно редактировать только свои комментарии "
                        "или комментарии от имени канала (если есть право edit)"
                    )
                data = await resp.json()
                if not data.get("success"):
                    msg = data.get("message", "неизвестная ошибка")
                    raise RuntimeError(f"Редактирование не выполнено: {msg}")
                return True
    except PermissionError:
        raise
    except RuntimeError:
        raise
    except Exception as e:
        logger.exception("Ошибка при редактировании комментария %s поста %s", comment_id, message_id)
        raise RuntimeError(str(e)) from e


async def post_comment(token: str, message_id: str, text: str) -> dict:
    url = f"{PLATFORM_API}/messages/{message_id}/comments"
    headers = {"Authorization": token}
    payload = {"text": text}

    try:
        async with _session() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 401:
                    raise PermissionError("Токен недействителен (401)")
                if resp.status == 403:
                    raise PermissionError(
                        "Нет доступа (403) — проверьте, что бот администратор канала "
                        "с правами read_all_messages и write, "
                        "и что комментарии включены в настройках канала"
                    )
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("post_comment HTTP %s: %s", resp.status, body)
                    raise RuntimeError(f"HTTP {resp.status}: {body}")
                data = await resp.json()
                return data.get("message", {})
    except PermissionError:
        raise
    except RuntimeError:
        raise
    except Exception as e:
        logger.exception("Ошибка при отправке комментария к посту %s", message_id)
        raise RuntimeError(str(e)) from e
