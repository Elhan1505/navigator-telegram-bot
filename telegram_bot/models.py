"""
Модели базы данных для хранения информации о пользователях и кодах активации.
"""
import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, DateTime, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Получаем URL базы данных из окружения или используем SQLite по умолчанию
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./navigator_bot.db")

# Для совместимости с некоторыми провайдерами, которые используют postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Создаём движок базы данных
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)

# Создаём фабрику сессий
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Базовый класс для моделей
Base = declarative_base()


class User(Base):
    """
    Модель пользователя бота с информацией о его доступе и лимитах.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)

    # Лимиты текущего пакета
    total_requests_in_plan = Column(Integer, default=0)  # Всего запросов в пакете
    used_requests_in_plan = Column(Integer, default=0)   # Использовано из пакета

    # Общая статистика
    total_requests_all_time = Column(Integer, default=0)  # Всего запросов за всё время

    # Даты
    expires_at = Column(DateTime(timezone=True), nullable=True)  # Дата истечения доступа
    last_activation_at = Column(DateTime(timezone=True), nullable=True)  # Последняя активация
    last_request_at = Column(DateTime(timezone=True), nullable=True)  # Последний запрос
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<User(telegram_id={self.telegram_id}, requests={self.used_requests_in_plan}/{self.total_requests_in_plan})>"


class ActivationCode(Base):
    """
    Модель кода активации для предоставления доступа пользователям.
    """
    __tablename__ = "activation_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)
    telegram_id = Column(BigInteger, nullable=True)  # ID пользователя, который активировал код
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    used_at = Column(DateTime(timezone=True), nullable=True)  # Когда код был использован

    def __repr__(self):
        return f"<ActivationCode(code={self.code}, telegram_id={self.telegram_id})>"


def init_db():
    """
    Инициализирует базу данных, создавая все таблицы.
    """
    Base.metadata.create_all(bind=engine)


def get_db():
    """
    Создаёт и возвращает сессию базы данных.
    Использовать с context manager или вручную закрывать.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_demo_code():
    """
    Создаёт демо-код активации для тестирования, если таблица активационных кодов пуста.

    Демо-код:
    - Код: DEMO100
    - Даёт 100 запросов на 30 дней (как обычный тариф)
    - Можно использовать только один раз
    - Привязывается к telegram_id пользователя при активации

    ВНИМАНИЕ: Это демо-функция для тестирования.
    Код создаётся автоматически только если в таблице activation_codes нет ни одной записи.
    При необходимости эту функцию можно удалить из кода.
    """
    db = SessionLocal()
    try:
        # Проверяем, есть ли хоть один код в таблице
        existing_codes_count = db.query(ActivationCode).count()

        if existing_codes_count == 0:
            # Таблица пуста - создаём демо-код
            demo_code = ActivationCode(
                code="DEMO100",
                telegram_id=None,  # Не привязан к пользователю до активации
                used_at=None,      # Не использован
            )
            db.add(demo_code)
            db.commit()

            print("✅ Демо-код DEMO100 успешно создан для тестирования")
            print("   Для активации используйте: /start DEMO100")
        else:
            # В таблице уже есть коды - ничего не делаем
            print(f"ℹ️  В таблице activation_codes уже есть {existing_codes_count} код(ов), пропускаем создание демо-кода")

    except Exception as e:
        print(f"❌ Ошибка при создании демо-кода: {e}")
        db.rollback()
    finally:
        db.close()
