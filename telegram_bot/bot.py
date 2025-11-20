"""
Модуль Telegram-бота NAVIGATOR с системой платного доступа.
"""
import os
import sys
import signal
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import Conflict, NetworkError, TimedOut

from .models import SessionLocal, init_db, ensure_demo_code
from .access import (
    check_access,
    consume_request,
    activate_code,
    format_profile,
    format_denial_message,
)
from .navigator import call_navigator

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Клавиатура для удобного доступа к функциям
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("👤 Мой профиль"), KeyboardButton("🔄 Новый диалог")],
    ],
    resize_keyboard=True,
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик команды /start [код].
    Если передан код — пытается активировать доступ.
    """
    telegram_id = update.effective_user.id
    username = update.effective_user.username or "unknown"
    args = context.args

    logger.info(f"Команда /start от пользователя {telegram_id} (@{username}), args: {args}")

    # Инициализируем БД при первом запуске
    init_db()

    with SessionLocal() as db:
        # Если передан код активации
        if args and len(args) > 0:
            code = args[0]
            success, message = activate_code(db, telegram_id, code)

            await update.message.reply_text(message, reply_markup=MAIN_KEYBOARD)

            if success:
                # После активации показываем краткую справку
                welcome_text = (
                    "🤖 **NAVIGATOR / VOCALIS Bot**\n\n"
                    "Я помогу вам с самыми разными задачами, используя возможности фреймворков NAVIGATOR и VOCALIS.\n\n"
                    "📝 Просто напишите мне свой вопрос или задачу, и я постараюсь помочь!\n\n"
                    "Используйте кнопки ниже для быстрого доступа к функциям."
                )
                await update.message.reply_text(welcome_text, parse_mode="Markdown")
            return

        # Если код не передан — показываем приветствие и статус
        status = check_access(db, telegram_id)

        welcome_text = (
            "🤖 **Добро пожаловать в NAVIGATOR / VOCALIS Bot!**\n\n"
            "Я — ваш помощник на базе фреймворков NAVIGATOR и VOCALIS.\n\n"
        )

        if status.has_access:
            welcome_text += (
                f"✅ Ваш доступ активен!\n"
                f"📊 Доступно запросов: {status.remaining_requests} из {status.total_requests_in_plan}\n"
            )
            if status.expires_at:
                welcome_text += f"📅 Действителен до: {status.expires_at.strftime('%d.%m.%Y %H:%M')} UTC\n"
            welcome_text += "\n📝 Напишите мне любой вопрос, и я постараюсь помочь!"
        else:
            welcome_text += (
                "❌ У вас пока нет активного доступа.\n\n"
                "Для активации:\n"
                "1. Получите код активации\n"
                "2. Перейдите по ссылке вида: `t.me/your_bot?start=КОД`\n"
                "   или отправьте команду: `/start КОД`\n\n"
            )
            payment_link = os.getenv("PAYMENT_LINK", "")
            if payment_link:
                welcome_text += f"🔗 Или оплатите доступ:\n{payment_link}"

        await update.message.reply_text(
            welcome_text,
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик команды /profile.
    Показывает профиль пользователя с информацией о доступе.
    """
    telegram_id = update.effective_user.id
    username = update.effective_user.username or "unknown"
    logger.info(f"Команда /profile от пользователя {telegram_id} (@{username})")

    try:
        with SessionLocal() as db:
            profile_text = format_profile(db, telegram_id)

        await update.message.reply_text(
            profile_text,
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )
        logger.info(f"Профиль успешно отправлен пользователю {telegram_id}")
    except Exception as e:
        logger.error(
            f"Критическая ошибка при обработке /profile для {telegram_id}: {e}",
            exc_info=True
        )
        await update.message.reply_text(
            "❌ Произошла ошибка при получении профиля. Попробуйте позже или обратитесь к администратору.",
            reply_markup=MAIN_KEYBOARD,
        )


async def new_dialog_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик команды /new_dialog.
    Объясняет, что начинается новый диалог.
    """
    text = (
        "🔄 **Новый диалог**\n\n"
        "Начинается новый диалог. История предыдущих сообщений используется на стороне "
        "NAVIGATOR сервера для поддержания контекста разговора.\n\n"
        "Если вы хотите начать с чистого листа по новой теме, просто напишите свой первый вопрос!"
    )

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик текстовых сообщений.
    Проверяет доступ и отправляет запрос в NAVIGATOR, если доступ есть.
    """
    user_text = update.message.text or ""
    telegram_id = update.effective_user.id

    logger.debug(f"Получено сообщение от {telegram_id}: {user_text[:50]}...")

    # Обработка кнопок клавиатуры
    if user_text == "👤 Мой профиль":
        logger.info(f"Пользователь {telegram_id} нажал кнопку 'Мой профиль'")
        await profile_command(update, context)
        return
    elif user_text == "🔄 Новый диалог":
        logger.info(f"Пользователь {telegram_id} нажал кнопку 'Новый диалог'")
        await new_dialog_command(update, context)
        return

    with SessionLocal() as db:
        # Проверяем доступ
        status = check_access(db, telegram_id)

        if not status.has_access:
            # Доступа нет — показываем сообщение
            denial_message = format_denial_message(status)
            await update.message.reply_text(
                denial_message,
                parse_mode="Markdown",
                reply_markup=MAIN_KEYBOARD,
            )
            return

        # Доступ есть — отправляем запрос
        # Показываем индикатор ожидания
        waiting_message = await update.message.reply_text("⏳ Обрабатываю ваш запрос...")

        # Вызываем NAVIGATOR
        try:
            response_text = await call_navigator(user_text, telegram_id)
        except Exception as e:
            logger.exception(f"Ошибка при вызове NAVIGATOR: {e}")
            response_text = "❌ Произошла ошибка при обработке вашего запроса. Попробуйте позже."

        # Списываем запрос
        updated_status = consume_request(db, telegram_id)

        # Добавляем предупреждение, если нужно
        if updated_status.warning_message:
            response_text += f"\n\n{updated_status.warning_message}"

        # Отправляем ответ
        try:
            await waiting_message.edit_text(response_text)
        except Exception:
            # Если не удалось отредактировать (например, сообщение слишком старое)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=response_text,
            )


def run_bot():
    """
    Запускает Telegram-бот в режиме polling с обработкой ошибок Conflict.
    """
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "Переменная окружения TELEGRAM_BOT_TOKEN не установлена. "
            "Задайте её в настройках Railway или в файле .env"
        )

    # Инициализируем базу данных
    try:
        init_db()
        logger.info("База данных инициализирована")

        # Гарантируем наличие демо-кода DEMO100 для тестирования
        # ВНИМАНИЕ: Это ТЕСТОВАЯ функция! В продакшене удалите этот вызов,
        # чтобы избежать бесплатного доступа к боту
        ensure_demo_code()
    except Exception as e:
        logger.error(f"Ошибка инициализации базы данных: {e}")
        sys.exit(1)

    # Создаём приложение бота
    try:
        application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    except Exception as e:
        logger.error(f"Ошибка создания приложения бота: {e}")
        sys.exit(1)

    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("new_dialog", new_dialog_command))

    # Добавляем обработчик текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("=" * 60)
    logger.info("NAVIGATOR Telegram bot starting...")
    logger.info("Polling mode enabled")
    logger.info(f"Bot token: ...{TELEGRAM_BOT_TOKEN[-10:] if TELEGRAM_BOT_TOKEN else 'NOT SET'}")
    logger.info("Доступные команды: /start, /profile, /new_dialog")
    logger.info("=" * 60)

    # Настройка graceful shutdown
    def signal_handler(sig, frame):
        logger.info("Получен сигнал завершения. Останавливаю бот...")
        application.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Запускаем бота с обработкой ошибок
    try:
        logger.info("Запуск polling...")
        # drop_pending_updates=True помогает избежать конфликтов при рестарте
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
    except Conflict as e:
        logger.error("=" * 60)
        logger.error("ОШИБКА: Получен Conflict от Telegram API")
        logger.error("Возможные причины:")
        logger.error("  1. Бот уже запущен в другом месте (другой сервис/локально)")
        logger.error("  2. Несколько экземпляров бота на Railway")
        logger.error("  3. Старый процесс не завершился корректно")
        logger.error("Решение:")
        logger.error("  - Убедитесь, что бот не запущен где-то ещё")
        logger.error("  - Проверьте количество реплик на Railway (должна быть 1)")
        logger.error("  - Используйте /revoke в @BotFather, если проблема не уходит")
        logger.error(f"Детали ошибки: {e}")
        logger.error("=" * 60)
        # Корректно завершаем работу без бесконечных рестартов
        sys.exit(1)
    except NetworkError as e:
        logger.error(f"Ошибка сети при работе с Telegram API: {e}")
        logger.error("Проверьте подключение к интернету и попробуйте снова")
        sys.exit(1)
    except TimedOut as e:
        logger.error(f"Таймаут при работе с Telegram API: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Неожиданная ошибка при запуске бота: {e}")
        sys.exit(1)
