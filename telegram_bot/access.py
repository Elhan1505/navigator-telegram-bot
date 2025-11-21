"""
Модуль управления доступом и лимитами пользователей.
"""
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from .models import User, ActivationCode

logger = logging.getLogger(__name__)

# Константы тарифа
PLAN_REQUESTS = 100  # Количество запросов в одном тарифе
PLAN_DAYS = 30       # Срок действия тарифа в днях
PLAN_PRICE = 1500    # Цена в рублях (для текстов)

# Пороги для уведомлений
REQUEST_WARNING_THRESHOLDS = [30, 10, 3]  # Предупреждения при оставшихся запросах
DAY_WARNING_THRESHOLDS = [7, 3, 1]        # Предупреждения при оставшихся днях

PAYMENT_LINK = os.getenv("PAYMENT_LINK", "")


def normalize_datetime_to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Приводит datetime к timezone-aware UTC.
    Если datetime уже имеет tzinfo, оставляет как есть.
    Если datetime naive (без tzinfo), добавляет UTC.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Naive datetime - считаем, что это UTC и добавляем tzinfo
        return dt.replace(tzinfo=timezone.utc)
    return dt


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

    # Нормализуем expires_at к timezone-aware UTC для корректного сравнения
    expires_at = normalize_datetime_to_utc(user.expires_at)

    # Логируем тип datetime для отладки
    if expires_at:
        logger.debug(
            f"check_access для {telegram_id}: expires_at={expires_at}, "
            f"tzinfo={'aware' if expires_at.tzinfo else 'naive'}"
        )

    # Проверяем, есть ли активный доступ
    remaining_requests = user.total_requests_in_plan - user.used_requests_in_plan

    # Проверка срока действия
    access_expired = False
    if expires_at:
        if now >= expires_at:
            access_expired = True
            logger.info(f"Доступ для {telegram_id} истёк: {expires_at.strftime('%d.%m.%Y %H:%M')} UTC")

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
            denial_reason = f"Срок действия вашего доступа истёк {expires_at.strftime('%d.%m.%Y')}. Продлите доступ."
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
        if expires_at and not warning_message:
            days_remaining = (expires_at - now).days
            for threshold in DAY_WARNING_THRESHOLDS:
                if days_remaining == threshold:
                    days_word = "день" if threshold == 1 else "дня" if threshold < 5 else "дней"
                    warning_message = f"⚠️ Ваш доступ истекает через {days_remaining} {days_word} ({expires_at.strftime('%d.%m.%Y')})."
                    break

    return AccessStatus(
        has_access=has_access,
        remaining_requests=remaining_requests,
        total_requests_in_plan=user.total_requests_in_plan,
        used_requests_in_plan=user.used_requests_in_plan,
        total_requests_all_time=user.total_requests_all_time,
        expires_at=expires_at,
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
    Обрабатывает случаи с активным и неактивным доступом.
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        user = get_or_create_user(db, telegram_id)
        status = check_access(db, telegram_id)

        # Защита от None значений (на случай битых данных в БД)
        total_in_plan = user.total_requests_in_plan if user.total_requests_in_plan is not None else 0
        used_in_plan = user.used_requests_in_plan if user.used_requests_in_plan is not None else 0
        total_all_time = user.total_requests_all_time if user.total_requests_all_time is not None else 0
        remaining = total_in_plan - used_in_plan

        # Проверяем, активировал ли пользователь хоть раз доступ
        has_ever_activated = total_in_plan > 0 or total_all_time > 0

        if not has_ever_activated:
            # Пользователь никогда не активировал доступ
            logger.info(f"Профиль для {telegram_id}: пользователь без активаций")
            profile_text = (
                f"👤 **Ваш профиль**\n\n"
                f"❌ **У вас пока нет активного доступа.**\n\n"
                f"Для активации доступа:\n"
                f"• Получите код активации\n"
                f"• Отправьте команду: `/start КОД`\n\n"
                f"💰 Тариф: {PLAN_REQUESTS} запросов / {PLAN_DAYS} дней — {PLAN_PRICE} ₽\n"
            )
            if PAYMENT_LINK:
                profile_text += f"\n🔗 Для покупки кода перейдите по ссылке:\n{PAYMENT_LINK}"
            else:
                profile_text += "\n💬 Для получения кода обратитесь к администратору."

            return profile_text

        # Пользователь имеет (или имел) активацию
        if status.has_access:
            status_emoji = "✅"
            status_text = "Активен"
        else:
            status_emoji = "❌"
            status_text = "Неактивен"

        profile_text = (
            f"👤 **Ваш профиль**\n\n"
            f"{status_emoji} Статус: **{status_text}**\n"
            f"📦 Запросов в пакете: {total_in_plan}\n"
            f"✅ Использовано: {used_in_plan}\n"
            f"📊 Осталось: {remaining}\n"
        )

        if user.expires_at:
            profile_text += f"📅 Действителен до: {user.expires_at.strftime('%d.%m.%Y %H:%M')} UTC\n"

        profile_text += f"📈 Всего запросов за всё время: {total_all_time}\n"

        # Добавляем информацию о продлении
        if not status.has_access or remaining < 20:
            profile_text += f"\n💰 Тариф: {PLAN_REQUESTS} запросов / {PLAN_DAYS} дней — {PLAN_PRICE} ₽\n"
            if PAYMENT_LINK:
                profile_text += f"\n🔗 Для активации/продления перейдите по ссылке:\n{PAYMENT_LINK}"

        # Логируем успешное формирование профиля
        logger.info(
            f"Профиль для {telegram_id}: статус={status_text}, "
            f"запросов={used_in_plan}/{total_in_plan}, всего={total_all_time}"
        )

        return profile_text

    except Exception as e:
        logger.error(f"Ошибка при формировании профиля для {telegram_id}: {e}", exc_info=True)
        # Возвращаем безопасное сообщение вместо падения
        return (
            f"👤 **Ваш профиль**\n\n"
            f"❌ Не удалось загрузить данные профиля.\n\n"
            f"Попробуйте активировать доступ командой: `/start КОД`\n\n"
            f"💰 Тариф: {PLAN_REQUESTS} запросов / {PLAN_DAYS} дней — {PLAN_PRICE} ₽\n"
        )


def create_paid_activation_code(
    db: Session,
    code: str,
    total_requests: int = PLAN_REQUESTS,
    days_valid: int = PLAN_DAYS,
    note: Optional[str] = None,
) -> ActivationCode:
    """
    Создаёт новый платный код активации.

    Args:
        db: Сессия базы данных
        code: Уникальный код активации
        total_requests: Количество запросов в тарифе (по умолчанию 100)
        days_valid: Срок действия в днях (по умолчанию 30)
        note: Необязательная пометка о происхождении кода

    Returns:
        ActivationCode: Созданный код активации

    Raises:
        ValueError: Если код уже существует в базе данных
    """
    # Проверяем, существует ли уже такой код
    existing_code = db.query(ActivationCode).filter(ActivationCode.code == code).first()
    if existing_code:
        raise ValueError(f"Код {code} уже существует в базе данных")

    # Создаём новый код (не привязанный к пользователю)
    activation_code = ActivationCode(
        code=code,
        telegram_id=None,  # Код ещё никому не принадлежит
        used_at=None,      # Код ещё не использован
    )

    db.add(activation_code)
    db.commit()
    db.refresh(activation_code)

    logger.info(
        f"✅ Создан платный код активации: {code} "
        f"(лимит: {total_requests} запросов, срок: {days_valid} дней)"
        f"{f', метка: {note}' if note else ''}"
    )

    return activation_code


def activate_paid_code_bh(db: Session, telegram_id: int, code: str) -> Tuple[bool, str]:
    """
    Активирует платный код доступа формата bh_<id> для пользователя.

    При первой активации:
    - total_requests_in_plan = 100
    - used_requests_in_plan = 0
    - expires_at = сейчас + 30 дней

    При продлении (если доступ уже есть):
    - total_requests_in_plan += 100
    - expires_at = max(текущий expires_at, сейчас) + 30 дней

    Args:
        db: Сессия базы данных
        telegram_id: Telegram ID пользователя
        code: Код активации формата "bh_<id>" (например "bh_95")

    Returns:
        Tuple[bool, str]: (успех, текстовое сообщение для пользователя)
    """
    # Разбираем код для получения ID
    try:
        if not code.startswith("bh_"):
            return False, "❌ Неверный формат платного кода."

        code_id = code[3:]  # Получаем часть после "bh_"
        # Проверяем, что это число
        int(code_id)
    except (ValueError, IndexError):
        logger.warning(f"Попытка активации некорректного bh-кода: {code} (telegram_id={telegram_id})")
        return False, "❌ Неверный формат платного кода. Код должен быть вида bh_<число>."

    user = get_or_create_user(db, telegram_id)
    now = datetime.now(timezone.utc)

    # Определяем, первая это активация или продление
    is_first_activation = user.total_requests_in_plan == 0

    if is_first_activation:
        # Первая активация - создаём новый пакет
        user.total_requests_in_plan = PLAN_REQUESTS
        user.used_requests_in_plan = 0
        user.expires_at = now + timedelta(days=PLAN_DAYS)
        user.last_activation_at = now
        user.updated_at = now

        db.commit()
        db.refresh(user)

        logger.info(
            f"✅ Первая активация платного кода {code} для пользователя {telegram_id}: "
            f"remaining_requests={user.total_requests_in_plan}, "
            f"expires_at={user.expires_at.strftime('%d.%m.%Y %H:%M')} UTC"
        )

        message = (
            f"✅ Платный доступ успешно активирован!\n\n"
            f"🎉 Вы получили полный доступ к боту NAVIGATOR / VOCALIS.\n\n"
            f"📦 Доступно запросов: {user.total_requests_in_plan}\n"
            f"📅 Действителен до: {user.expires_at.strftime('%d.%m.%Y %H:%M')} UTC\n\n"
            f"💬 Можете задавать вопросы — я готов помочь!"
        )

        return True, message

    else:
        # Продление - добавляем запросы и продлеваем срок
        old_total = user.total_requests_in_plan
        old_expires = normalize_datetime_to_utc(user.expires_at)

        # Добавляем запросы
        user.total_requests_in_plan += PLAN_REQUESTS

        # Продлеваем срок: считаем от более поздней даты (текущий expires_at или сейчас)
        if old_expires and old_expires > now:
            # Доступ ещё активен - продлеваем от текущей даты окончания
            user.expires_at = old_expires + timedelta(days=PLAN_DAYS)
        else:
            # Доступ истёк - продлеваем от текущего момента
            user.expires_at = now + timedelta(days=PLAN_DAYS)

        user.last_activation_at = now
        user.updated_at = now

        db.commit()
        db.refresh(user)

        remaining = user.total_requests_in_plan - user.used_requests_in_plan

        logger.info(
            f"✅ Продление доступа по коду {code} для пользователя {telegram_id}: "
            f"total_requests={old_total} → {user.total_requests_in_plan} (+{PLAN_REQUESTS}), "
            f"remaining_requests={remaining}, "
            f"expires_at={user.expires_at.strftime('%d.%m.%Y %H:%M')} UTC"
        )

        message = (
            f"✅ Доступ успешно продлён!\n\n"
            f"📦 Добавлено запросов: +{PLAN_REQUESTS}\n"
            f"📊 Доступно сейчас: {remaining} из {user.total_requests_in_plan}\n"
            f"📅 Новый срок действия: {user.expires_at.strftime('%d.%m.%Y %H:%M')} UTC\n"
            f"⏰ Продлено на: +{PLAN_DAYS} дней\n\n"
            f"🎉 Спасибо за продление! Можете продолжать работу."
        )

        return True, message


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
