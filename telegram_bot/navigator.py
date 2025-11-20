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

    # Подготавливаем данные запроса
    request_data = {
        "framework": NAVIGATOR_FRAMEWORK_NAME,
        "input": {
            "message": message,
            "user_id": str(user_id),
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
