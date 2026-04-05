#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Автоматическая настройка Email уведомлений.

Этот скрипт:
1. Спрашивает ваши email данные
2. Сохраняет в .env и settings.json
3. Тестирует отправку
4. Показывает результат
"""

import os
import sys
from pathlib import Path


def main():
    print("\n" + "=" * 60)
    print("📧 НАСТРОЙКА EMAIL УВЕДОМЛЕНИЙ")
    print("=" * 60)
    print()

    env_path = Path(__file__).parent / ".env"

    if not env_path.exists():
        print("❌ Файл .env не найден!")
        return

    # Загружаем текущие значения
    from dotenv import dotenv_values

    current = dotenv_values(str(env_path))

    print("Введите данные для Email уведомлений:")
    print("(нажмите Enter чтобы оставить текущее значение)")
    print()

    # Спрашиваем данные
    email = input("📧 Ваш Email (отправитель): ").strip()
    if not email:
        email = current.get("ALERT_EMAIL_FROM", "")
        if email:
            print(f"   Оставлено: {email}")

    if not email:
        print("\n❌ Email обязателен! Запустите скрипт снова.")
        sys.exit(1)

    password = input("🔑 Пароль приложения (16 символов): ").strip()
    if not password:
        print("\n❌ Пароль обязателен! Запустите скрипт снова.")
        print("   Как создать: https://myaccount.google.com/apppasswords")
        sys.exit(1)

    # Убираем пробелы из пароля
    password = password.replace(" ", "")

    recipient = input(f"📬 Email получателя [{email}]: ").strip()
    if not recipient:
        recipient = email
        print(f"   Установлен: {recipient}")

    # SMTP сервер
    domain = email.split("@")[-1].lower()
    if "gmail" in domain or "google" in domain:
        default_smtp = "smtp.gmail.com"
    elif "yandex" in domain or "ya.ru" in domain:
        default_smtp = "smtp.yandex.ru"
    elif "mail.ru" in domain:
        default_smtp = "smtp.mail.ru"
    elif "outlook" in domain or "hotmail" in domain:
        default_smtp = "smtp.office365.com"
    else:
        default_smtp = "smtp.gmail.com"

    smtp = input(f"🌐 SMTP сервер [{default_smtp}]: ").strip()
    if not smtp:
        smtp = default_smtp

    print()
    print("💾 Сохранение настроек...")

    # Сохраняем в .env
    from dotenv import set_key

    set_key(str(env_path), "ALERT_EMAIL_FROM", email)
    set_key(str(env_path), "ALERT_EMAIL_PASSWORD", password)
    set_key(str(env_path), "ALERT_EMAIL_RECIPIENTS", recipient)

    print("✅ .env файл обновлён")

    # Обновляем settings.json
    settings_path = Path(__file__).parent / "configs" / "settings.json"
    import json

    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            content = "\n".join(line for line in f if not line.strip().startswith("//"))
            settings = json.loads(content)

        if "alerting" not in settings:
            settings["alerting"] = {"enabled": True, "channels": {}}

        settings["alerting"]["enabled"] = True
        settings["alerting"]["channels"]["email"] = {
            "enabled": True,
            "smtp_server": smtp,
            "smtp_port": 587,
            "use_tls": True,
            "from_email_env": "ALERT_EMAIL_FROM",
            "password_env": "ALERT_EMAIL_PASSWORD",
            "recipients_env": "ALERT_EMAIL_RECIPIENTS",
        }

        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)

        print("✅ settings.json обновлён")

    except Exception as e:
        print(f"⚠️ Ошибка обновления settings.json: {e}")

    # Тестируем
    print()
    print("🧪 Тестирование отправки...")
    print()

    try:
        import smtplib
        from datetime import datetime
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart()
        msg["From"] = email
        msg["To"] = recipient
        msg["Subject"] = "[Genesis Trading] ✅ Email уведомления работают!"

        body = f"""
✅ УСПЕХ! Email уведомления Genesis Trading System работают!

Время: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Отправитель: {email}
Получатель: {recipient}
SMTP сервер: {smtp}

Теперь система будет отправлять вам:
- Торговые сигналы
- Предупреждения о рисках
- Ошибки системы
- Ежедневные дайджесты

---
Это автоматическое сообщение от Genesis Trading System.
"""
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(smtp, 587, timeout=15) as server:
            server.starttls()
            server.login(email, password)
            server.send_message(msg)

        print("🎉 УСПЕХ!")
        print()
        print(f"✅ Email отправлен на: {recipient}")
        print()
        print("💡 Проверьте папку 'Входящие' (и 'Спам')")
        print()
        print("Теперь:")
        print("1. Перезапустите Genesis Trading System")
        print("2. Email уведомления будут работать автоматически")
        print("3. В настройках можно включить/выключить уведомления")
        print()

    except smtplib.SMTPAuthenticationError as e:
        print("❌ ОШИБКА АУТЕНТИФИКАЦИИ!")
        print()
        print(f"Ошибка: {e}")
        print()
        print("Что делать:")
        print("1. Проверьте что использует ПАРОЛЬ ПРИЛОЖЕНИЯ (не обычный пароль)")
        print("2. Для Gmail: https://myaccount.google.com/apppasswords")
        print("3. Для Yandex: https://passport.yandex.ru/profile → Пароли приложений")
        print()
        print("Повторите скрипт с правильным паролем.")

    except smtplib.SMTPConnectError as e:
        print("❌ ОШИБКА ПОДКЛЮЧЕНИЯ!")
        print()
        print(f"Ошибка: {e}")
        print()
        print("Что делать:")
        print("1. Проверьте подключение к интернету")
        print("2. Попробуйте включить VPN")
        print("3. Проверьте что порт 587 не заблокирован фаерволом")
        print()
        print("SMTP сервер:", smtp)
        print("Попробуйте другие:")
        print("- smtp.yandex.ru")
        print("- smtp.mail.ru")
        print("- smtp.office365.com")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        print()
        print("Проверьте логи Genesis Trading System для деталей")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ Настройка отменена пользователем")
    except Exception as e:
        print(f"\n❌ Неожиданная ошибка: {e}")
        print("Запустите скрипт снова или обратитесь к документации")
