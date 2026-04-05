#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Быстрая настройка Email уведомлений Genesis Trading System.

Этот скрипт поможет вам заполнить .env и settings.json для работы Email.
"""

import os
import sys
from pathlib import Path

print("=" * 60)
print("⚙️  Настройка Email уведомлений")
print("=" * 60)
print()

# Пути
env_path = Path(__file__).parent / ".env"
settings_path = Path(__file__).parent / "configs" / "settings.json"

# Проверяем .env
if not env_path.exists():
    print("❌ Файл .env не найден!")
    sys.exit(1)

print("📝 Заполните данные (нажмите Enter для пропуска):")
print()

# Читаем текущие значения
from dotenv import dotenv_values

current = dotenv_values(env_path)

email_from = input(f"Email отправителя [{current.get('ALERT_EMAIL_FROM', '')}]: ").strip()
if not email_from:
    email_from = current.get("ALERT_EMAIL_FROM", "")

email_recipients = input(f"Email получателя [{current.get('ALERT_EMAIL_RECIPIENTS', '')}]: ").strip()
if not email_recipients:
    email_recipients = current.get("ALERT_EMAIL_RECIPIENTS", "")

email_password = input("Пароль приложения (16 символов от Google/Yandex): ").strip()

smtp_server = input(f"SMTP сервер [{current.get('SMTP_SERVER', 'smtp.gmail.com')}]: ").strip()
if not smtp_server:
    smtp_server = "smtp.gmail.com"

if not email_from or not email_password or not email_recipients:
    print()
    print("❌ Не заполнены обязательные поля!")
    print()
    print("Нужно заполнить:")
    print("  - Email отправителя")
    print("  - Email получателя")
    print("  - Пароль приложения")
    print()
    print("💡 Как создать пароль приложения:")
    print("   Gmail:  https://myaccount.google.com/apppasswords")
    print("   Yandex: https://passport.yandex.ru/profile → Пароли приложений")
    sys.exit(1)

# Сохраняем в .env
from dotenv import set_key

print()
print("💾 Сохранение настроек...")

set_key(str(env_path), "ALERT_EMAIL_FROM", email_from)
set_key(str(env_path), "ALERT_EMAIL_RECIPIENTS", email_recipients)
set_key(str(env_path), "ALERT_EMAIL_PASSWORD", email_password)

print("✅ Настройки сохранены в .env файл")

# Проверяем settings.json
import json

try:
    with open(settings_path, "r", encoding="utf-8") as f:
        content = "\n".join(line for line in f if not line.strip().startswith("//"))
        settings = json.loads(content)

    # Обновляем alerting
    if "alerting" not in settings:
        settings["alerting"] = {"enabled": True, "channels": {}}

    if "channels" not in settings["alerting"]:
        settings["alerting"]["channels"] = {}

    settings["alerting"]["channels"]["email"] = {
        "enabled": True,
        "smtp_server": smtp_server,
        "smtp_port": 587,
        "use_tls": True,
        "from_email_env": "ALERT_EMAIL_FROM",
        "password_env": "ALERT_EMAIL_PASSWORD",
        "recipients_env": "ALERT_EMAIL_RECIPIENTS",
    }
    settings["alerting"]["enabled"] = True

    # Сохраняем
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)

    print("✅ settings.json обновлён")

except Exception as e:
    print(f"⚠️ Ошибка обновления settings.json: {e}")

# Тестируем
print()
print("🧪 Тестирование подключения...")

try:
    import smtplib
    from datetime import datetime
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart()
    msg["From"] = email_from
    msg["To"] = email_recipients
    msg["Subject"] = "[Genesis Trading] Тест подключения"

    body = f"""
✅ Тест успешен!

Время: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

Email уведомления Genesis Trading System работают корректно!

---
Это автоматическое тестовое сообщение.
"""
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(smtp_server, 587, timeout=10) as server:
        server.starttls()
        server.login(email_from, email_password)
        server.send_message(msg)

    print("✅ УСПЕХ! Email отправлен!")
    print(f"   Получатель: {email_recipients}")
    print()
    print("💡 Проверьте папку 'Входящие' (и 'Спам')")
    print()
    print("🎉 Email уведомления настроены и работают!")
    print()
    print("Теперь запустите Genesis Trading System:")
    print("  python main_pyside.py")
    print()
    print("И система будет отправлять уведомления на указанный Email.")

except smtplib.SMTPAuthenticationError as e:
    print(f"❌ Ошибка аутентификации: {e}")
    print()
    print("💡 Проверьте:")
    print("   1. Правильность email адреса")
    print("   2. Что пароль приложения (не обычный пароль!)")
    print("   3. Для Gmail: https://myaccount.google.com/apppasswords")
    print("   4. Для Yandex: https://passport.yandex.ru/profile")

except smtplib.SMTPConnectError as e:
    print(f"❌ Ошибка подключения: {e}")
    print()
    print("💡 Попробуйте:")
    print("   1. Включить VPN")
    print("   2. Проверить что SMTP сервер доступен")
    print("   3. Установить PySocks: pip install PySocks")

except Exception as e:
    print(f"❌ Ошибка: {e}")
    print()
    print("💡 Проверьте логи Genesis Trading System для деталей")
