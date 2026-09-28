import logging
import aiohttp

PLATFORM_API = "https://platform-api2.max.ru"
logger = logging.getLogger(__name__)


async def get_comments(token: str, message_id: str, count: int = 10) -> list[dict]:
    url = f"{PLATFORM_API}/messages/{message_id}/comments"
    headers = {"Authorization": token}
    params = {"count": count}

    try:
        async with aiohttp.ClientSession() as session:
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
        async with aiohttp.ClientSession() as session:
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


async def post_comment(token: str, message_id: str, text: str) -> dict:
    url = f"{PLATFORM_API}/messages/{message_id}/comments"
    headers = {"Authorization": token}
    payload = {"text": text}

    try:
        async with aiohttp.ClientSession() as session:
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
