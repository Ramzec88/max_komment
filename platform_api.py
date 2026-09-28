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
