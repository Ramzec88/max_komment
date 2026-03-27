import asyncio
import logging

from maxapi import Bot, Dispatcher

import config
import handlers
import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    storage.init_db()
    bot = Bot(token=config.MAX_BOT_TOKEN)
    dp = Dispatcher()

    handlers.register(dp)

    # Удаляем вебхук перед запуском polling, если он был установлен
    await bot.delete_webhook()
    logger.info("Бот запущен, каналы: %s", list(config.CHANNELS.keys()))

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
