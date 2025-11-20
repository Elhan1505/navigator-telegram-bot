"""
Модуль управления доступом и лимитами пользователей.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from .models import User, ActivationCode

# Константы тарифа
PLAN_REQUESTS = 100  # Количество запросов в одном тарифе
PLAN_DAYS = 30       # Срок действия тарифа в днях
PLAN_PRICE = 1500    # Цена в рублях (для текстов)

# Пороги для уведомлений
REQUEST_WARNING_THRESHOLDS = [30, 10, 3]  # Предупреждения при оставшихся запросах
DAY_WARNING_THRESHOLDS = [7, 3, 1]        # Предупреждения при оставшихся днях

PAYMENT_LINK = os.getenv("PAYMENT_LINK", "")


class AccessStatus:
    """Статус доступа пользователя."""
    def __init__(
        self,
        has_access: bool,
        remaining_requests: int,
        total_requests_in_plan: int,
        used_requests_in_plan: int,
        total_requests_all_time: int,
        expires_at: Optional[datetime],
        warning_message: Optional[str] = None,
        denial_reason: Optional[str] = None,
    ):
        self.has_access = has_access
        self.remaining_requests = remaining_requests
        self.total_requests_in_plan = total_requests_in_plan
        self.used_requests_in_plan = used_requests_in_plan
        self.total_requests_all_time = total_requests_all_time
        self.expires_at = expires_at
        self.warning_message = warning_message
        self.denial_reason = denial_reason


def get_or_create_user(db: Session, telegram_id: int) -> User:
    """
    Получает пользователя по telegram_id или создаёт нового.
    """
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        user = User(telegram_id=telegram_id)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def check_access(db: Session, telegram_id: int) -> AccessStatus:
    """
    Проверяет, может ли пользователь сделать запрос.
    Возвращает AccessStatus с информацией о доступе.
    """
    user = get_or_create_user(db, telegram_id)

    now = datetime.now(timezone.utc)

    # Проверяем, есть ли активный доступ
    remaining_requests = user.total_requests_in_plan - user.used_requests_in_plan

    # Проверка срока действия
    access_expired = False
    if user.expires_at:
        if now >= user.expires_at:
            access_expired = True

    # Проверка лимита запросов
    requests_exhausted = remaining_requests <= 0

    # Определяем, есть ли доступ
    has_access = not access_expired and not requests_exhausted and user.total_requests_in_plan > 0

    # Формируем причину отказа
    denial_reason = None
    if not has_access:
        if user.total_requests_in_plan == 0:
            denial_reason = "У вас нет активного пакета. Активируйте доступ с помощью кода или оплатите тариф."
        elif access_expired:
            denial_reason = f"Срок действия вашего доступа истёк {user.expires_at.strftime('%d.%m.%Y')}. Продлите доступ."
        elif requests_exhausted:
            denial_reason = "Вы исчерпали все запросы из текущего пакета. Продлите доступ для получения новых запросов."

    # Формируем предупреждение
    warning_message = None
    if has_access:
        # Предупреждение по запросам
        for threshold in REQUEST_WARNING_THRESHOLDS:
            if remaining_requests == threshold:
                warning_message = f"⚠️ У вас осталось {remaining_requests} запросов из {user.total_requests_in_plan}."
                break

        # Предупреждение по сроку
        if user.expires_at and not warning_message:
            days_remaining = (user.expires_at - now).days
            for threshold in DAY_WARNING_THRESHOLDS:
                if days_remaining == threshold:
                    days_word = "день" if threshold == 1 else "дня" if threshold < 5 else "дней"
                    warning_message = f"⚠️ Ваш доступ истекает через {days_remaining} {days_word} ({user.expires_at.strftime('%d.%m.%Y')})."
                    break

    return AccessStatus(
        has_access=has_access,
        remaining_requests=remaining_requests,
        total_requests_in_plan=user.total_requests_in_plan,
        used_requests_in_plan=user.used_requests_in_plan,
        total_requests_all_time=user.total_requests_all_time,
        expires_at=user.expires_at,
        warning_message=warning_message,
        denial_reason=denial_reason,
    )


def consume_request(db: Session, telegram_id: int) -> AccessStatus:
    """
    Списывает один запрос у пользователя.
    Возвращает обновлённый статус доступа.
    """
    user = get_or_create_user(db, telegram_id)

    # Увеличиваем счётчики
    user.used_requests_in_plan += 1
    user.total_requests_all_time += 1
    user.last_request_at = datetime.now(timezone.utc)
    user.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(user)

    return check_access(db, telegram_id)


def activate_or_extend_plan(db: Session, telegram_id: int) -> Tuple[bool, str]:
    """
    Активирует или продлевает тариф для пользователя.

    При первой активации:
    - total_requests_in_plan = 100
    - expires_at = сейчас + 30 дней

    При продлении:
    - total_requests_in_plan += 100
    - expires_at = сейчас + 30 дней (обновляется от текущей даты)

    Возвращает (успех, сообщение).
    """
    user = get_or_create_user(db, telegram_id)

    now = datetime.now(timezone.utc)

    # Добавляем запросы к текущему пакету
    user.total_requests_in_plan += PLAN_REQUESTS

    # Обновляем срок действия (от текущей даты)
    user.expires_at = now + timedelta(days=PLAN_DAYS)
    user.last_activation_at = now
    user.updated_at = now

    db.commit()
    db.refresh(user)

    remaining = user.total_requests_in_plan - user.used_requests_in_plan
    message = (
        f"✅ Доступ успешно активирован!\n\n"
        f"📦 Доступно запросов: {remaining} из {user.total_requests_in_plan}\n"
        f"📅 Действителен до: {user.expires_at.strftime('%d.%m.%Y %H:%M')} UTC"
    )

    return True, message


def activate_code(db: Session, telegram_id: int, code: str) -> Tuple[bool, str]:
    """
    Активирует код доступа для пользователя.

    Возвращает (успех, сообщение).
    """
    # Проверяем, существует ли код
    activation_code = db.query(ActivationCode).filter(ActivationCode.code == code).first()

    if not activation_code:
        # Код не найден - создаём новый и активируем
        activation_code = ActivationCode(
            code=code,
            telegram_id=telegram_id,
            used_at=datetime.now(timezone.utc),
        )
        db.add(activation_code)
        db.commit()

        # Активируем тариф
        success, message = activate_or_extend_plan(db, telegram_id)
        return success, message

    # Код существует - проверяем его статус
    # Если код ещё не использован (telegram_id is None) - можно активировать
    if activation_code.telegram_id is None:
        # Код доступен для активации - активируем
        activation_code.telegram_id = telegram_id
        activation_code.used_at = datetime.now(timezone.utc)
        db.commit()

        # Активируем тариф
        success, message = activate_or_extend_plan(db, telegram_id)
        return success, message

    # Код уже использован - проверяем, кто его активировал
    if activation_code.telegram_id == telegram_id:
        return False, "⚠️ Вы уже активировали этот код ранее."
    else:
        return False, "❌ Этот код недействителен или уже использован другим пользователем."


def format_profile(db: Session, telegram_id: int) -> str:
    """
    Формирует текст профиля пользователя.
    """
    user = get_or_create_user(db, telegram_id)
    status = check_access(db, telegram_id)

    if status.has_access:
        status_emoji = "✅"
        status_text = "Активен"
    else:
        status_emoji = "❌"
        status_text = "Неактивен"

    remaining = user.total_requests_in_plan - user.used_requests_in_plan

    profile_text = (
        f"👤 **Ваш профиль**\n\n"
        f"{status_emoji} Статус: **{status_text}**\n"
        f"📦 Запросов в пакете: {user.total_requests_in_plan}\n"
        f"✅ Использовано: {user.used_requests_in_plan}\n"
        f"📊 Осталось: {remaining}\n"
    )

    if user.expires_at:
        profile_text += f"📅 Действителен до: {user.expires_at.strftime('%d.%m.%Y %H:%M')} UTC\n"

    profile_text += f"📈 Всего запросов за всё время: {user.total_requests_all_time}\n"

    # Добавляем информацию о продлении
    if not status.has_access or remaining < 20:
        profile_text += f"\n💰 Тариф: {PLAN_REQUESTS} запросов / {PLAN_DAYS} дней — {PLAN_PRICE} ₽\n"
        if PAYMENT_LINK:
            profile_text += f"\n🔗 Для активации/продления перейдите по ссылке:\n{PAYMENT_LINK}"

    return profile_text


def format_denial_message(status: AccessStatus) -> str:
    """
    Формирует сообщение об отказе в доступе.
    """
    message = f"❌ {status.denial_reason}\n\n"
    message += f"💰 Тариф: {PLAN_REQUESTS} запросов / {PLAN_DAYS} дней — {PLAN_PRICE} ₽\n"

    if PAYMENT_LINK:
        message += f"\n🔗 Для активации/продления перейдите по ссылке:\n{PAYMENT_LINK}"
    else:
        message += "\n💬 Для получения кода активации обратитесь к администратору."

    return message
