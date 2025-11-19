import os
import logging
import asyncio

import httpx
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NAVIGATOR_SERVER_URL = os.getenv("NAVIGATOR_SERVER_URL")  # без /process в конце
NAVIGATOR_FRAMEWORK_NAME = os.getenv("NAVIGATOR_FRAMEWORK_NAME", "navigator_vocalis")


async def call_navigator(input_text: str) -> str:
    """
    Отправляет текст на NAVIGATOR / VOCALIS сервер и возвращает поле `output`.
    """
    if not NAVIGATOR_SERVER_URL:
        return "Ошибка: переменная окружения NAVIGATOR_SERVER_URL не настроена."

    url = NAVIGATOR_SERVER_URL.rstrip("/") + "/process"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                json={
                    "framework": NAVIGATOR_FRAMEWORK_NAME,
                    "input": input_text,
                },
            )
    except Exception as e:
        logger.exception("Ошибка при запросе к NAVIGATOR серверу")
        return f"Техническая ошибка при обращении к NAVIGATOR серверу: {e}"

    if response.status_code != 200:
        return f"Ошибка сервера NAVIGATOR: статус {response.status_code}"

    try:
        data = response.json()
    except Exception as e:
        logger.exception("Не удалось разобрать JSON-ответ от NAVIGATOR сервера")
        return f"Ошибка: не удалось прочитать ответ сервера ({e})"

    output = data.get("output")
    if not output:
        return "Ответ от NAVIGATOR сервера получен, но поле `output` пустое."

    return str(output)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик команды /start.
    """
    text = (
        "Привет! Я бот NAVIGATOR / VOCALIS.\n\n"
        "Напиши мне любой запрос — я отправлю его в NAVIGATOR сервер и верну ответ."
    )
    await update.message.reply_text(text)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик любого текстового сообщения.
    """
    user_text = update.message.text or ""
    chat_id = update.message.chat_id

    # Черновое сообщение, чтобы пользователь видел, что что-то происходит
    waiting_message = await update.message.reply_text("Думаю над ответом...")

    reply_text = await call_navigator(user_text)

    try:
        await waiting_message.edit_text(reply_text)
    except Exception:
        # Если не удалось отредактировать (например, сообщение слишком старое) — просто отправим новое
        await context.bot.send_message(chat_id=chat_id, text=reply_text)


def main() -> None:
    """
    Точка входа для Railway: запускает Telegram-бота в режиме polling.
    """
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "Переменная окружения TELEGRAM_BOT_TOKEN не установлена. "
            "Задай её в настройках Railway."
        )

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("NAVIGATOR Telegram bot started (polling mode).")
    application.run_polling()


if __name__ == "__main__":
    main()
