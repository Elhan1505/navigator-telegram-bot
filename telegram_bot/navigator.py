"""
Модуль интеграции с MCP-сервером NAVIGATOR/VOCALIS.
"""
import os
import logging
import httpx

logger = logging.getLogger(__name__)

NAVIGATOR_SERVER_URL = os.getenv("NAVIGATOR_SERVER_URL")
NAVIGATOR_FRAMEWORK_NAME = os.getenv("NAVIGATOR_FRAMEWORK_NAME", "navigator_vocalis")


async def call_navigator(message: str, user_id: int) -> str:
    """
    Отправляет запрос на MCP-сервер NAVIGATOR и возвращает ответ.

    Args:
        message: Текст сообщения от пользователя
        user_id: Telegram ID пользователя

    Returns:
        Текст ответа от сервера или сообщение об ошибке
    """
    if not NAVIGATOR_SERVER_URL:
        logger.error("NAVIGATOR_SERVER_URL не настроен")
        return "❌ Ошибка конфигурации: переменная окружения NAVIGATOR_SERVER_URL не настроена."

    # Формируем URL эндпоинта
    url = NAVIGATOR_SERVER_URL.rstrip("/") + "/process"

    # Детектируем запрос финального отчёта по ключевым словам
    FINAL_REPORT_KEYWORDS = [
        "финальный отчёт",
        "итоговый отчёт",
        "подведи итоги",
        "сформируй отчёт",
        "мои рекомендации",
        "финальные рекомендации",
        "что ты можешь посоветовать",
        "подведём итоги",
    ]

    is_final_report = any(
        keyword in message.lower()
        for keyword in FINAL_REPORT_KEYWORDS
    )

    if is_final_report:
        logger.info(f"Детектирован запрос финального отчёта от user_id={user_id}")

    # Подготавливаем данные запроса
    request_data = {
        "framework": NAVIGATOR_FRAMEWORK_NAME,
        "input": message,
        "user_id": str(user_id),
        "is_final_report": is_final_report,  # ← ДОБАВИЛИ ФЛАГ
        "state": {
            "telegram_id": str(user_id)
        }
    }

    try:
        logger.info(f"Отправка запроса к NAVIGATOR серверу: {url}")
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=request_data)

        # Проверяем статус ответа
        if response.status_code != 200:
            logger.error(f"NAVIGATOR сервер вернул статус {response.status_code}: {response.text}")
            return f"❌ Ошибка сервера NAVIGATOR: статус {response.status_code}. Попробуйте позже."

        # Парсим JSON-ответ
        try:
            data = response.json()
        except Exception as e:
            logger.exception("Не удалось распарсить JSON-ответ от NAVIGATOR сервера")
            return f"❌ Ошибка: не удалось прочитать ответ сервера. Попробуйте позже."

        # Извлекаем поле output
        output = data.get("output")
        if not output:
            logger.warning(f"NAVIGATOR сервер вернул пустой output: {data}")
            return "❌ Ответ от NAVIGATOR сервера получен, но он пустой. Попробуйте переформулировать запрос."

        return str(output)

    except httpx.TimeoutException:
        logger.exception("Таймаут при запросе к NAVIGATOR серверу")
        return "❌ Превышено время ожидания ответа от сервера. Попробуйте позже или упростите запрос."

    except httpx.RequestError as e:
        logger.exception(f"Ошибка сети при запросе к NAVIGATOR серверу: {e}")
        return "❌ Ошибка связи с сервером NAVIGATOR. Проверьте подключение к интернету или попробуйте позже."

    except Exception as e:
        logger.exception(f"Неожиданная ошибка при обращении к NAVIGATOR серверу: {e}")
        return f"❌ Техническая ошибка при обращении к NAVIGATOR серверу. Попробуйте позже."


async def reset_dialog(user_id: int) -> bool:
    """
    Сбрасывает историю диалога на MCP-сервере.

    Args:
        user_id: Telegram ID пользователя

    Returns:
        True если успешно, False если ошибка
    """
    if not NAVIGATOR_SERVER_URL:
        logger.error("NAVIGATOR_SERVER_URL не настроен")
        return False

    # Формируем URL эндпоинта
    url = NAVIGATOR_SERVER_URL.rstrip("/") + "/reset_dialog"

    # Подготавливаем данные запроса
    request_data = {
        "framework": NAVIGATOR_FRAMEWORK_NAME,
        "user_id": str(user_id),
    }

    try:
        logger.info(f"Сброс истории диалога для user_id={user_id}: {url}")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=request_data)

        # Проверяем статус ответа
        if response.status_code != 200:
            logger.error(f"NAVIGATOR сервер вернул статус {response.status_code}: {response.text}")
            return False

        # Парсим JSON-ответ
        try:
            data = response.json()
            if data.get("status") == "ok":
                logger.info(f"История диалога успешно сброшена для user_id={user_id}")
                return True
            else:
                logger.warning(f"Неожиданный ответ от сервера: {data}")
                return False
        except Exception as e:
            logger.exception("Не удалось распарсить JSON-ответ от NAVIGATOR сервера")
            return False

    except httpx.TimeoutException:
        logger.exception("Таймаут при запросе сброса истории к NAVIGATOR серверу")
        return False

    except httpx.RequestError as e:
        logger.exception(f"Ошибка сети при запросе к NAVIGATOR серверу: {e}")
        return False

    except Exception as e:
        logger.exception(f"Неожиданная ошибка при сбросе истории: {e}")
        return False
