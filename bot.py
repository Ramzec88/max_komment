import asyncio
import logging
import os

from aiohttp import web

from maxapi import Bot, Dispatcher

import config
import handlers
import platform_api
import storage
from webhook import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    storage.init_db()
    bot = Bot(token=config.MAX_BOT_TOKEN)
    dp = Dispatcher()
    handlers.register(dp, bot)

    await bot.delete_webhook()

    # Запускаем HTTP-сервер для приёма webhook-событий
    app = create_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("HTTP-сервер запущен на порту %s", port)

    # Регистрируем подписку на комментарии, если задан WEBHOOK_URL
    if config.WEBHOOK_URL:
        webhook_endpoint = f"{config.WEBHOOK_URL}/webhook"
        try:
            await platform_api.subscribe_webhooks(config.MAX_BOT_TOKEN, webhook_endpoint)
            logger.info("Webhook зарегистрирован: %s", webhook_endpoint)
        except Exception:
            logger.exception("Не удалось зарегистрировать webhook — комментарии не будут приходить")
    else:
        logger.warning("WEBHOOK_URL не задан — уведомления о комментариях отключены")

    logger.info("Бот запущен, каналы: %s", list(config.CHANNELS.keys()))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
