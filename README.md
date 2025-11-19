# NAVIGATOR Telegram Bot

Минимальный рабочий Telegram-бот для интеграции с NAVIGATOR/VOCALIS сервером.

## Описание

Бот принимает текстовые сообщения от пользователей, отправляет их на NAVIGATOR/VOCALIS сервер и возвращает ответ (поле `output`) обратно в Telegram.

## Установка и настройка

### 1. Клонирование репозитория

```bash
git clone https://github.com/Elhan1505/navigator-telegram-bot.git
cd navigator-telegram-bot
```

### 2. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 3. Настройка переменных окружения

Создайте файл `.env` на основе `.env.example`:

```bash
cp .env.example .env
```

Откройте `.env` и заполните необходимые значения:

- **TELEGRAM_BOT_TOKEN**: Токен вашего бота (получить у [@BotFather](https://t.me/BotFather))
- **NAVIGATOR_SERVER_URL**: URL вашего NAVIGATOR/VOCALIS сервера (без `/process` в конце)
- **NAVIGATOR_FRAMEWORK_NAME**: Название фреймворка (по умолчанию: `navigator_vocalis`)

Пример:
```
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
NAVIGATOR_SERVER_URL=https://your-navigator-server.com
NAVIGATOR_FRAMEWORK_NAME=navigator_vocalis
```

### 4. Запуск бота

```bash
python telegram_bot.py
```

Бот запустится в режиме polling и будет готов к обработке сообщений.

## Деплой на Railway

### Настройка переменных окружения в Railway:

1. Откройте ваш проект в Railway
2. Перейдите в раздел **Variables**
3. Добавьте следующие переменные:
   - `TELEGRAM_BOT_TOKEN`
   - `NAVIGATOR_SERVER_URL`
   - `NAVIGATOR_FRAMEWORK_NAME` (опционально)

### Команда запуска:

В настройках Railway укажите команду старта:

```
python telegram_bot.py
```

## Использование

1. Найдите вашего бота в Telegram
2. Отправьте команду `/start` для приветствия
3. Отправьте любое текстовое сообщение
4. Бот перешлёт его на NAVIGATOR сервер и вернёт ответ

## Структура проекта

```
navigator-telegram-bot/
├── telegram_bot.py      # Основной файл бота
├── requirements.txt     # Зависимости Python
├── .env.example        # Пример переменных окружения
└── README.md           # Документация
```

## Технические детали

### Эндпоинт NAVIGATOR сервера

Бот отправляет POST запрос на `{NAVIGATOR_SERVER_URL}/process` с телом:

```json
{
  "framework": "navigator_vocalis",
  "input": "текст от пользователя"
}
```

### Ожидаемый формат ответа

```json
{
  "output": "ответ от сервера"
}
```

## Требования

- Python 3.8+
- python-telegram-bot >= 21.0
- httpx >= 0.27.0

## Лицензия

MIT
