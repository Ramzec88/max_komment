import os
from dotenv import load_dotenv

load_dotenv()

MAX_BOT_TOKEN: str = os.environ["MAX_BOT_TOKEN"]
CHANNEL_ID: int = int(os.environ["CHANNEL_ID"])
CHAT_URL: str = os.environ["CHAT_URL"]
BUTTON_TEXT: str = os.getenv("BUTTON_TEXT", "💬 Обсудить в чате")
