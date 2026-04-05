#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Диагностика Email уведомлений Genesis Trading System.

Проверяет:
1. Загрузку .env файла
2. Настройки alerting в settings.json
3. AlertManager инициализацию
4. SMTP подключение
"""

import logging
import os
import sys
from pathlib import Path

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("email_diagnostic")

# Убираем прокси
for var in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
    os.environ.pop(var, None)


def check_env_file():
    """Проверяет .env файл"""
    logger.info("=" * 60)
    logger.info("ШАГ 1: Проверка .env файла")
    logger.info("=" * 60)

    env_path = Path(__file__).parent / ".env"

    if not env_path.exists():
        logger.error("❌ Файл .env не найден!")
        logger.info(f"   Ожидаемый путь: {env_path}")
        return False

    logger.info(f"✅ .env найден: {env_path}")

    # Загружаем переменные
    from dotenv import load_dotenv

    load_dotenv(env_path)

    # Проверяем email настройки
    email_from = os.getenv("ALERT_EMAIL_FROM", "")
    email_password = os.getenv("ALERT_EMAIL_PASSWORD", "")
    email_recipients = os.getenv("ALERT_EMAIL_RECIPIENTS", "")

    checks = {
        "ALERT_EMAIL_FROM": email_from,
        "ALERT_EMAIL_PASSWORD": email_password,
        "ALERT_EMAIL_RECIPIENTS": email_recipients,
    }

    all_ok = True
    for key, value in checks.items():
        if value:
            if "PASSWORD" in key:
                display_value = f"{'*' * len(value)} (длина: {len(value)})"
            else:
                display_value = value
            logger.info(f"   ✅ {key} = {display_value}")
        else:
            logger.warning(f"   ❌ {key} = НЕ ЗАПОЛНЕН")
            all_ok = False

    return all_ok


def check_settings_json():
    """Проверяет settings.json"""
    logger.info("=" * 60)
    logger.info("ШАГ 2: Проверка settings.json")
    logger.info("=" * 60)

    import json

    settings_path = Path(__file__).parent / "configs" / "settings.json"

    if not settings_path.exists():
        logger.error("❌ settings.json не найден!")
        return None

    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            # Убираем комментарии
            content = "\n".join(line for line in f if not line.strip().startswith("//"))
            config = json.loads(content)

        logger.info("✅ settings.json загружен")

        # Проверяем alerting
        alerting = config.get("alerting", {})

        if not alerting:
            logger.warning("⚠️ Секция 'alerting' не найдена в settings.json")
            return config

        enabled = alerting.get("enabled", False)
        logger.info(f"   Alerting enabled: {enabled}")

        # Email канал
        email_cfg = alerting.get("email", {})
        if email_cfg:
            logger.info(f"   Email enabled: {email_cfg.get('enabled', False)}")
            logger.info(f"   SMTP server: {email_cfg.get('smtp_server', 'N/A')}")
            logger.info(f"   SMTP port: {email_cfg.get('smtp_port', 'N/A')}")
            logger.info(f"   Use TLS: {email_cfg.get('use_tls', True)}")
        else:
            logger.warning("⚠️ Конфигурация Email канала не найдена")

        return config

    except Exception as e:
        logger.error(f"❌ Ошибка чтения settings.json: {e}")
        return None


def check_alert_manager():
    """Проверяет инициализацию AlertManager"""
    logger.info("=" * 60)
    logger.info("ШАГ 3: Проверка AlertManager")
    logger.info("=" * 60)

    try:
        from src.core.config_loader import load_config
        from src.monitoring.alert_manager import AlertManager

        config = load_config()
        alert_manager = AlertManager(config)

        logger.info(f"   Email enabled: {alert_manager.email_enabled}")
        logger.info(f"   Email from: {alert_manager.email_from or 'НЕ НАСТРОЕН'}")
        logger.info(f"   SMTP: {alert_manager.smtp_server}:{alert_manager.smtp_port}")
        logger.info(f"   Recipients: {alert_manager.email_recipients}")

        if not alert_manager.email_enabled:
            logger.warning("⚠️ Email уведомления ОТКЛЮЧены в конфигурации!")
            return False

        if not alert_manager.email_from or not alert_manager.email_password:
            logger.warning("⚠️ Email credentials НЕ НАСТРОЕНЫ!")
            return False

        logger.info("✅ AlertManager инициализирован корректно")
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка инициализации AlertManager: {e}", exc_info=True)
        return False


def test_smtp_connection():
    """Тестирует SMTP подключение"""
    logger.info("=" * 60)
    logger.info("ШАГ 4: Тест SMTP подключения")
    logger.info("=" * 60)

    import smtplib
    from datetime import datetime
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    # Загружаем настройки
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent / ".env")

    email_from = os.getenv("ALERT_EMAIL_FROM", "")
    email_password = os.getenv("ALERT_EMAIL_PASSWORD", "")
    email_recipients = os.getenv("ALERT_EMAIL_RECIPIENTS", "")

    if not all([email_from, email_password, email_recipients]):
        logger.error("❌ Не заполнены email настройки в .env файле")
        logger.info("   Заполните:")
        logger.info("   - ALERT_EMAIL_FROM=your_email@gmail.com")
        logger.info("   - ALERT_EMAIL_PASSWORD=your_app_password")
        logger.info("   - ALERT_EMAIL_RECIPIENTS=recipient@example.com")
        return False

    recipients_list = [r.strip() for r in email_recipients.split(",")]

    # Создаём тестовое письмо
    msg = MIMEMultipart()
    msg["From"] = email_from
    msg["To"] = ", ".join(recipients_list)
    msg["Subject"] = "[Genesis Trading] Тест подключения"

    body = f"""
🧪 Тест Genesis Trading System
Время: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

Если вы видите это сообщение, Email уведомления работают корректно!

---
Это автоматическое тестовое сообщение.
"""
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # Пробуем разные SMTP серверы
    smtp_configs = [
        {"server": "smtp.gmail.com", "port": 587, "name": "Gmail"},
        {"server": "smtp.yandex.ru", "port": 587, "name": "Yandex"},
        {"server": "smtp.mail.ru", "port": 587, "name": "Mail.ru"},
    ]

    # Определяем сервер по email
    domain = email_from.split("@")[-1].lower()
    if "gmail" in domain:
        smtp_configs = [smtp_configs[0]] + smtp_configs
    elif "yandex" in domain or "ya.ru" in domain:
        smtp_configs = [smtp_configs[1]] + smtp_configs
    elif "mail.ru" in domain:
        smtp_configs = [smtp_configs[2]] + smtp_configs

    for smtp_cfg in smtp_configs:
        try:
            logger.info(f"   Попытка: {smtp_cfg['name']} ({smtp_cfg['server']}:{smtp_cfg['port']})")

            with smtplib.SMTP(smtp_cfg["server"], smtp_cfg["port"], timeout=10) as server:
                server.starttls()
                server.login(email_from, email_password)
                server.send_message(msg)

            logger.info(f"✅ Успех! Email отправлен через {smtp_cfg['name']}")
            logger.info(f"   Получатели: {recipients_list}")
            logger.info("   💡 Проверьте папку 'Входящие' и 'Спам'")
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"❌ Ошибка аутентификации {smtp_cfg['name']}: {e}")
            logger.info("   💡 Для Gmail: создайте 'Пароль приложения'")
            logger.info("      https://myaccount.google.com/apppasswords")
            logger.info("   💡 Для Yandex: создайте 'Пароль приложения'")
            logger.info("      https://passport.yandex.ru/profile")
            return False

        except smtplib.SMTPConnectError as e:
            logger.warning(f"⚠️ Не удалось подключиться к {smtp_cfg['name']}: {e}")
            continue

        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка: {e}")
            return False

    logger.error("❌ Все SMTP серверы недоступны")
    return False


def main():
    logger.info("🔍 Диагностика Email уведомлений Genesis Trading System")
    logger.info(f"Python: {sys.version}")
    logger.info(f"Рабочая директория: {Path.cwd()}")
    logger.info("")

    # Шаг 1
    env_ok = check_env_file()
    logger.info("")

    # Шаг 2
    settings = check_settings_json()
    logger.info("")

    # Шаг 3
    if env_ok and settings:
        alert_ok = check_alert_manager()
    else:
        alert_ok = False
        logger.warning("⏭️ Пропуск проверки AlertManager (не заполнены настройки)")
    logger.info("")

    # Шаг 4
    if env_ok:
        smtp_ok = test_smtp_connection()
    else:
        smtp_ok = False
        logger.warning("⏭️ Пропуск SMTP теста (не заполнены credentials)")
    logger.info("")

    # Итог
    logger.info("=" * 60)
    logger.info("ИТОГ:")
    logger.info("=" * 60)

    if env_ok and smtp_ok:
        logger.info("✅ Email уведомления должны работать!")
        logger.info("")
        logger.info("Если письма не приходят:")
        logger.info("1. Проверьте папку 'Спам'")
        logger.info("2. Убедитесь что email_recipients верный")
        logger.info("3. Проверьте логи Genesis Trading System")
    else:
        logger.error("❌ Email уведомления НЕ РАБОТАЮТ")
        logger.info("")
        logger.info("Что сделать:")
        logger.info("1. Заполните .env файл:")
        logger.info("   ALERT_EMAIL_FROM=your_email@gmail.com")
        logger.info("   ALERT_EMAIL_PASSWORD=app_password_here")
        logger.info("   ALERT_EMAIL_RECIPIENTS=recipient@example.com")
        logger.info("")
        logger.info("2. Для Gmail создайте 'Пароль приложения':")
        logger.info("   https://myaccount.google.com/apppasswords")
        logger.info("")
        logger.info("3. Включите email в settings.json:")
        logger.info('   "alerting": {"email": {"enabled": true}}')
        logger.info("")
        logger.info("4. Перезапустите Genesis Trading System")


if __name__ == "__main__":
    main()
