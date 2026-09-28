import asyncio
import logging
import os

from aiohttp import web
from maxapi import Bot, Dispatcher
from maxapi.webhook.aiohttp import AiohttpMaxWebhook

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

    port = int(os.getenv("PORT", 8080))

    if config.WEBHOOK_URL:
        webhook_endpoint = f"{config.WEBHOOK_URL}/webhook"

        # Снимаем старые подписки и ставим новую через Bot API
        await bot.delete_webhook()
        await bot.subscribe_webhook(url=webhook_endpoint)
        logger.info("Webhook Bot API зарегистрирован: %s", webhook_endpoint)

        # Регистрируем отдельную подписку на события комментариев через Platform API
        try:
            await platform_api.subscribe_webhooks(config.MAX_BOT_TOKEN, webhook_endpoint)
            logger.info("Webhook комментариев зарегистрирован")
        except Exception:
            logger.exception("Не удалось зарегистрировать webhook комментариев")

        # Запускаем HTTP-сервер (webhook-режим — без polling)
        maxapi_webhook = AiohttpMaxWebhook(dp=dp, bot=bot)
        app = create_app(bot, maxapi_webhook)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()

        logger.info("HTTP-сервер запущен на порту %s", port)
        logger.info("Бот запущен в webhook-режиме, каналы: %s", list(config.CHANNELS.keys()))

        await asyncio.Event().wait()  # работаем вечно

    else:
        # Fallback: polling (без уведомлений о комментариях)
        await bot.delete_webhook()
        logger.warning("WEBHOOK_URL не задан — запуск в режиме polling, комментарии недоступны")
        logger.info("Бот запущен, каналы: %s", list(config.CHANNELS.keys()))
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
