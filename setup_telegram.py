import os
import asyncio
from telethon import TelegramClient
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv(os.path.join("configs", ".env"))

# Получаем данные
API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
PHONE = os.getenv("TELEGRAM_PHONE")

# Имя сессии должно совпадать с тем, что в коде бота (genesis_telegram_session)
SESSION_NAME = 'genesis_telegram_session'


async def main():
    if not API_ID or not API_HASH:
        print("ОШИБКА: Не заполнены TELEGRAM_API_ID или TELEGRAM_API_HASH в configs/.env")
        return

    print(f"Подключение к Telegram (ID: {API_ID})...")

    client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)

    # Эта команда запустит интерактивный процесс входа
    # Если файла сессии нет, она попросит ввести номер и код
    await client.start(phone=PHONE)

    print("------------------------------------------------")
    print("УСПЕХ! Сессия создана.")
    print(f"Файл '{SESSION_NAME}.session' должен появиться в папке.")
    print("Теперь вы можете запускать основного бота.")
    print("------------------------------------------------")

    await client.disconnect()


if __name__ == '__main__':
    asyncio.run(main())