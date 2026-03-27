import os
from dotenv import load_dotenv

load_dotenv()

MAX_BOT_TOKEN: str = os.environ["MAX_BOT_TOKEN"]
BUTTON_TEXT: str = os.getenv("BUTTON_TEXT", "💬 Обсудить в чате")

# user_id через запятую; если пусто — команды доступны всем
ADMIN_USER_IDS: set[int] = {
    int(x.strip()) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()
}


def _parse_channels() -> dict[int, str]:
    """
    Парсит маппинг channel_id -> chat_url.

    Поддерживает два формата:
    1. CHANNELS=-111|https://max.ru/join/aaa;-222|https://max.ru/join/bbb
       (несколько каналов, разделитель между парами «;», между id и url «|»)
    2. CHANNEL_ID=-111 + CHAT_URL=https://... (старый формат, один канал)
    """
    raw = os.getenv("CHANNELS", "").strip()
    if raw:
        result: dict[int, str] = {}
        for pair in raw.split(";"):
            pair = pair.strip()
            if "|" not in pair:
                continue
            channel_id_str, chat_url = pair.split("|", 1)
            result[int(channel_id_str.strip())] = chat_url.strip()
        return result

    # Обратная совместимость: старые переменные CHANNEL_ID + CHAT_URL
    channel_id = int(os.getenv("CHANNEL_ID", "0"))
    chat_url = os.getenv("CHAT_URL", "")
    if chat_url:
        return {channel_id: chat_url}  # 0 = все каналы
    return {}


# dict[channel_id, chat_url]; ключ 0 означает «любой канал»
CHANNELS: dict[int, str] = _parse_channels()
