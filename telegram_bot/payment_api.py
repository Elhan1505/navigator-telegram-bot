"""
Модуль HTTP API для выдачи платных кодов активации.

Этот API предназначен для интеграции с внешними платёжными системами (BotHelp),
которые после успешной оплаты вызывают эндпоинт для генерации кода активации.
"""
import os
import secrets
import logging
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

from .models import SessionLocal
from .access import create_paid_activation_code, PLAN_REQUESTS, PLAN_DAYS

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Navigator Telegram Bot – Payment API",
    description="API для автоматической выдачи платных кодов доступа после успешной оплаты",
    version="1.0.0",
)


class IssuePaidCodeRequest(BaseModel):
    """Запрос на выдачу платного кода активации."""
    secret: str  # Shared secret для авторизации внешних сервисов
    note: str | None = None  # Необязательная метка источника платежа


class IssuePaidCodeResponse(BaseModel):
    """Ответ с выданным платным кодом активации."""
    code: str
    limit_requests: int
    days_valid: int


def generate_activation_code(length: int = 10) -> str:
    """
    Генерирует человекочитаемый код активации.

    Использует только заглавные буквы (без I, O) и цифры (без 0, 1),
    чтобы избежать путаницы при ручном вводе.

    Args:
        length: Длина кода (по умолчанию 10 символов)

    Returns:
        str: Сгенерированный код активации
    """
    # Алфавит без похожих символов: без I, O, 0, 1
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


@app.post(
    "/issue_paid_code",
    response_model=IssuePaidCodeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Выдать платный код активации",
    description="Создаёт новый платный код активации после успешной оплаты. Требует авторизации через shared secret.",
)
def issue_paid_code(payload: IssuePaidCodeRequest):
    """
    Эндпоинт для выдачи платного кода активации.

    Вызывается внешними платёжными системами (например, BotHelp) после успешной оплаты.
    Генерирует уникальный код активации и сохраняет его в базе данных.

    Args:
        payload: Данные запроса с секретом и необязательной меткой

    Returns:
        IssuePaidCodeResponse: Информация о выданном коде

    Raises:
        HTTPException 401: Неверный секрет авторизации
        HTTPException 500: Ошибка при создании кода (например, коллизия)
    """
    # Проверка авторизации
    expected_secret = os.getenv("PAYMENT_API_SECRET")
    if not expected_secret:
        logger.error("❌ PAYMENT_API_SECRET не задан в переменных окружения!")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment API не настроен корректно. Обратитесь к администратору.",
        )

    if payload.secret != expected_secret:
        logger.warning(f"⚠️ Попытка доступа к /issue_paid_code с неверным секретом")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid secret",
        )

    # Параметры тарифа
    limit_requests = PLAN_REQUESTS  # 70 запросов
    days_valid = PLAN_DAYS          # 30 дней

    # Генерация уникального кода (с защитой от коллизий)
    max_attempts = 10
    activation_code = None

    for attempt in range(max_attempts):
        try:
            raw_code = generate_activation_code(length=10)

            db = SessionLocal()
            try:
                activation_code = create_paid_activation_code(
                    db=db,
                    code=raw_code,
                    total_requests=limit_requests,
                    days_valid=days_valid,
                    note=payload.note or "paid_bothelp",
                )
                break  # Успешно создали код
            finally:
                db.close()

        except ValueError as e:
            # Код уже существует - пробуем ещё раз
            logger.warning(f"Коллизия кода активации (попытка {attempt + 1}/{max_attempts}): {e}")
            if attempt == max_attempts - 1:
                # Исчерпали все попытки
                logger.error("❌ Не удалось сгенерировать уникальный код активации")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Не удалось создать уникальный код. Попробуйте ещё раз.",
                )

    # Логируем успешную выдачу кода
    logger.info(
        f"✅ Выдан платный код активации: {activation_code.code} "
        f"(лимит: {limit_requests} запросов, срок: {days_valid} дней)"
        f"{f', метка: {payload.note}' if payload.note else ''}"
    )

    return IssuePaidCodeResponse(
        code=activation_code.code,
        limit_requests=limit_requests,
        days_valid=days_valid,
    )


@app.get("/health", summary="Проверка работоспособности API")
def health_check():
    """
    Эндпоинт для проверки работоспособности Payment API.

    Returns:
        dict: Статус сервиса
    """
    return {"status": "ok", "service": "navigator-telegram-bot-payment-api"}
