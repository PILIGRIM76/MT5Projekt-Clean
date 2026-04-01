# src/monitoring/alert_manager.py
"""
Alerting System — Многоканальная система уведомлений.

Каналы:
- Telegram Bot
- Email (SMTP)
- Push (Pushover)
- Webhook

Уровни алертов:
- INFO: Логирование
- WARNING: Telegram
- ERROR: Telegram + Email
- CRITICAL: Все каналы + Push
"""

import logging
import smtplib
import time
from collections import deque
from datetime import datetime
from datetime import time as dt_time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from threading import Lock
from typing import Any, Dict, List, Optional

import httpx

from src.core.config_models import Settings

logger = logging.getLogger(__name__)


class AlertLevel:
    """Уровни алертов."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AlertRecord:
    """Запись об отправленном алерте."""

    def __init__(self, level: str, message: str, channels: List[str], timestamp: Optional[datetime] = None):
        self.level = level
        self.message = message
        self.channels = channels
        self.timestamp = timestamp or datetime.now()
        self.success = True
        self.error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "message": self.message,
            "channels": self.channels,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "error_message": self.error_message,
        }


class AlertManager:
    """
    Менеджер оповещений для Genesis Trading System.

    Поддерживает:
    - Многоканальные уведомления
    - Rate limiting
    - Quiet hours
    - Дневной дайджест
    """

    # Конфигурация маршрутизации по уровням
    LEVEL_CHANNELS = {
        AlertLevel.INFO: ["log"],
        AlertLevel.WARNING: ["log", "telegram"],
        AlertLevel.ERROR: ["log", "telegram", "email"],
        AlertLevel.CRITICAL: ["log", "telegram", "email", "push"],
    }

    # Эмодзи для уровней
    LEVEL_EMOJI = {AlertLevel.INFO: "🔵", AlertLevel.WARNING: "🟡", AlertLevel.ERROR: "🟠", AlertLevel.CRITICAL: "🔴"}

    def __init__(self, config: Settings, trading_system_ref=None):
        """
        Инициализация Alert Manager.

        Args:
            config: Конфигурация системы
            trading_system_ref: Ссылка на TradingSystem
        """
        self.config = config
        self.trading_system = trading_system_ref

        # Конфигурация из settings
        alert_config = getattr(config, "alerting", None)

        # Преобразуем Pydantic модель в dict или используем dict по умолчанию
        if alert_config is None:
            alert_dict = {}
        elif isinstance(alert_config, dict):
            alert_dict = alert_config
        else:
            # Pydantic модель - преобразуем в dict
            try:
                alert_dict = alert_config.model_dump() if hasattr(alert_config, "model_dump") else dict(alert_config)
            except Exception:
                alert_dict = {}

        self.enabled = alert_dict.get("enabled", True)

        # Telegram конфигурация
        telegram_config = alert_dict.get("telegram", {})
        self.telegram_enabled = telegram_config.get("enabled", False)
        self.telegram_bot_token = self._get_secret(telegram_config.get("bot_token_env", "TELEGRAM_BOT_TOKEN"))
        self.telegram_chat_id = self._get_secret(telegram_config.get("chat_id_env", "TELEGRAM_CHAT_ID"))

        # Email конфигурация
        email_config = alert_dict.get("email", {})
        self.email_enabled = email_config.get("enabled", False)
        self.smtp_server = email_config.get("smtp_server", "smtp.gmail.com")
        self.smtp_port = email_config.get("smtp_port", 587)
        self.use_tls = email_config.get("use_tls", True)
        self.email_from = self._get_secret(email_config.get("from_email_env", "ALERT_EMAIL_FROM"))
        self.email_password = self._get_secret(email_config.get("password_env", "ALERT_EMAIL_PASSWORD"))
        self.email_recipients = self._get_secret(email_config.get("recipients_env", "ALERT_EMAIL_RECIPIENTS")).split(",")

        # Push конфигурация
        push_config = alert_dict.get("push", {})
        self.push_enabled = push_config.get("enabled", False)
        self.pushover_user_key = self._get_secret(push_config.get("user_key_env", "PUSHOVER_USER_KEY"))
        self.pushover_api_token = self._get_secret(push_config.get("api_token_env", "PUSHOVER_API_TOKEN"))

        # Rate limiting
        rate_limit_config = alert_dict.get("rate_limit", {})
        self.max_alerts_per_minute = rate_limit_config.get("max_per_minute", 10)
        self.cooldown_seconds = rate_limit_config.get("cooldown_seconds", 60)

        # Quiet hours
        quiet_hours_config = alert_dict.get("quiet_hours", {})
        self.quiet_hours_enabled = quiet_hours_config.get("enabled", False)
        self.quiet_hours_start = dt_time.fromisoformat(quiet_hours_config.get("start", "22:00"))
        self.quiet_hours_end = dt_time.fromisoformat(quiet_hours_config.get("end", "08:00"))
        self.quiet_hours_timezone = quiet_hours_config.get("timezone", "UTC")

        # Daily digest
        digest_config = alert_dict.get("daily_digest", {})
        self.daily_digest_enabled = digest_config.get("enabled", True)
        self.daily_digest_time = dt_time.fromisoformat(digest_config.get("time", "20:00"))

        # Состояние
        self._lock = Lock()
        self._alert_history: deque = deque(maxlen=1000)
        self._alerts_this_minute = 0
        self._last_alert_time: Optional[datetime] = None
        self._last_minute_reset = datetime.now()

        # Статистика
        self.stats = {"total_sent": 0, "telegram_sent": 0, "email_sent": 0, "push_sent": 0, "failed": 0}

        logger.info("Alert Manager инициализирован")
        logger.info(f"  - Telegram: {'✓' if self.telegram_enabled else '✗'}")
        logger.info(f"  - Email: {'✓' if self.email_enabled else '✗'}")
        logger.info(f"  - Push: {'✓' if self.push_enabled else '✗'}")
        logger.info(f"  - Rate Limit: {self.max_alerts_per_minute}/мин")
        logger.info(f"  - Quiet Hours: {'✓' if self.quiet_hours_enabled else '✗'}")

    def _get_secret(self, env_name: str) -> str:
        """Получает секрет из переменных окружения."""
        import os

        return os.environ.get(env_name, "")

    def send_alert(self, level: str, message: str, context: Optional[Dict[str, Any]] = None) -> bool:
        """
        Отправляет оповещение по всем нужным каналам.

        Args:
            level: Уровень алерта (INFO, WARNING, ERROR, CRITICAL)
            message: Текст сообщения
            context: Дополнительный контекст

        Returns:
            True если отправлено успешно
        """
        if not self.enabled:
            return False

        # Проверяем rate limiting
        if not self._check_rate_limit():
            logger.warning(f"Rate limit превышен. Алерт отклонен: {message}")
            return False

        # Проверяем quiet hours (кроме CRITICAL)
        if level != AlertLevel.CRITICAL and self._is_quiet_hours():
            logger.debug(f"Quiet hours активны. Алерт отложен: {message}")
            return False

        # Определяем каналы для уровня
        channels = self.LEVEL_CHANNELS.get(level, ["log"])

        # Формируем сообщение с эмодзи
        emoji = self.LEVEL_EMOJI.get(level, "⚪")
        formatted_message = f"{emoji} {message}"

        # Добавляем контекст если есть
        if context:
            context_str = "\n".join(f"{k}: {v}" for k, v in context.items())
            formatted_message += f"\n\n{context_str}"

        # Создаём запись
        record = AlertRecord(level, formatted_message, channels)

        success = True

        # Отправляем по каналам
        for channel in channels:
            try:
                if channel == "log":
                    self._log_alert(level, formatted_message)
                elif channel == "telegram" and self.telegram_enabled:
                    self._send_telegram(formatted_message)
                    record.channels.append("telegram_sent")
                elif channel == "email" and self.email_enabled:
                    self._send_email(level, formatted_message)
                    record.channels.append("email_sent")
                elif channel == "push" and self.push_enabled:
                    self._send_push(formatted_message, priority="high" if level == AlertLevel.CRITICAL else "normal")
                    record.channels.append("push_sent")
            except Exception as e:
                logger.error(f"Ошибка отправки алерта в {channel}: {e}")
                record.success = False
                record.error_message = str(e)
                success = False
                self.stats["failed"] += 1

        # Сохраняем в историю
        with self._lock:
            self._alert_history.append(record)
            self.stats["total_sent"] += 1

        return success

    def _log_alert(self, level: str, message: str) -> None:
        """Логирует алерт."""
        log_func = {
            AlertLevel.INFO: logger.info,
            AlertLevel.WARNING: logger.warning,
            AlertLevel.ERROR: logger.error,
            AlertLevel.CRITICAL: logger.critical,
        }.get(level, logger.info)

        log_func(f"ALERT [{level}]: {message}")

    def _send_telegram(self, message: str) -> None:
        """Отправляет уведомление в Telegram."""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.warning("Telegram credentials не настроены")
            return

        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"

        payload = {"chat_id": self.telegram_chat_id, "text": message, "parse_mode": "Markdown"}

        # Экранируем специальные символы Markdown
        message_escaped = message.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
        payload["text"] = message_escaped

        # ИСПРАВЛЕНИЕ: отключаем прокси
        with httpx.Client(timeout=10.0, proxy=None) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()

        self.stats["telegram_sent"] += 1
        logger.debug(f"Telegram алерт отправлен: {message[:50]}...")

    def _send_email(self, subject: str, body: str) -> None:
        """Отправляет email уведомление."""
        if not self.email_from or not self.email_password:
            logger.warning("Email credentials не настроены")
            return

        msg = MIMEMultipart()
        msg["From"] = self.email_from
        msg["To"] = ", ".join(self.email_recipients)
        msg["Subject"] = f"[Genesis Trading] {subject}"

        # Добавляем timestamp и информацию о системе
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        full_body = f"""
Время: {timestamp}
Система: Genesis Trading System

{body}

---
Это автоматическое уведомление от Genesis Trading System.
"""

        msg.attach(MIMEText(full_body, "plain", "utf-8"))

        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            if self.use_tls:
                server.starttls()
            server.login(self.email_from, self.email_password)
            server.send_message(msg)

        self.stats["email_sent"] += 1
        logger.debug(f"Email алерт отправлен: {subject}")

    def _send_push(self, message: str, priority: str = "normal") -> None:
        """Отправляет push уведомление через Pushover."""
        if not self.pushover_user_key or not self.pushover_api_token:
            logger.warning("Pushover credentials не настроены")
            return

        url = "https://api.pushover.net/1/messages.json"

        payload = {
            "token": self.pushover_api_token,
            "user": self.pushover_user_key,
            "message": message,
            "priority": 0 if priority == "normal" else 1,
            "title": "Genesis Trading Alert",
        }

        if priority == "high":
            payload["priority"] = 2
            payload["retry"] = 300  # Повтор каждые 5 минут
            payload["expire"] = 3600  # Истекает через 1 час

        # ИСПРАВЛЕНИЕ: отключаем прокси
        with httpx.Client(timeout=10.0, proxy=None) as client:
            response = client.post(url, data=payload)
            response.raise_for_status()

        self.stats["push_sent"] += 1
        logger.debug(f"Push алерт отправлен: {message[:50]}...")

    def _check_rate_limit(self) -> bool:
        """Проверяет rate limiting."""
        now = datetime.now()

        with self._lock:
            # Сбрасываем счётчик каждую минуту
            if (now - self._last_minute_reset).total_seconds() >= 60:
                self._alerts_this_minute = 0
                self._last_minute_reset = now

            # Проверяем лимит
            if self._alerts_this_minute >= self.max_alerts_per_minute:
                # Проверяем cooldown
                if self._last_alert_time:
                    time_since_last = (now - self._last_alert_time).total_seconds()
                    if time_since_last < self.cooldown_seconds:
                        return False

                # Сбрасываем после cooldown
                self._alerts_this_minute = 0

            self._alerts_this_minute += 1
            self._last_alert_time = now
            return True

    def _is_quiet_hours(self) -> bool:
        """Проверяет, активны ли quiet hours."""
        if not self.quiet_hours_enabled:
            return False

        now = datetime.now().time()

        # Обработка overnight quiet hours (например, 22:00 - 08:00)
        if self.quiet_hours_start > self.quiet_hours_end:
            # Overnight период
            return now >= self.quiet_hours_start or now <= self.quiet_hours_end
        else:
            # Дневной период
            return self.quiet_hours_start <= now <= self.quiet_hours_end

    def test_channels(self) -> Dict[str, bool]:
        """
        Тестирует все каналы связи.

        Returns:
            Словарь с результатами тестов {канал: успех}
        """
        results = {}
        test_message = "🧪 Тестовый алерт Genesis Trading System"

        # Тест логов
        try:
            self._log_alert(AlertLevel.INFO, test_message)
            results["log"] = True
        except Exception as e:
            results["log"] = False
            logger.error(f"Тест log failed: {e}")

        # Тест Telegram
        if self.telegram_enabled:
            try:
                self._send_telegram(test_message)
                results["telegram"] = True
            except Exception as e:
                results["telegram"] = False
                logger.error(f"Тест Telegram failed: {e}")

        # Тест Email
        if self.email_enabled:
            try:
                self._send_email("TEST", test_message)
                results["email"] = True
            except Exception as e:
                results["email"] = False
                logger.error(f"Тест Email failed: {e}")

        # Тест Push
        if self.push_enabled:
            try:
                self._send_push(test_message)
                results["push"] = True
            except Exception as e:
                results["push"] = False
                logger.error(f"Тест Push failed: {e}")

        return results

    def get_alert_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Возвращает историю оповещений.

        Args:
            limit: Максимальное количество записей

        Returns:
            Список записей об алертах
        """
        with self._lock:
            history = list(self._alert_history)[-limit:]
            return [record.to_dict() for record in history]

    def get_statistics(self) -> Dict[str, Any]:
        """Возвращает статистику оповещений."""
        return {
            **self.stats,
            "history_size": len(self._alert_history),
            "rate_limit_remaining": self.max_alerts_per_minute - self._alerts_this_minute,
            "quiet_hours_active": self._is_quiet_hours(),
        }

    def send_daily_digest(self) -> bool:
        """
        Отправляет дневной дайджест.

        Returns:
            True если отправлено успешно
        """
        if not self.daily_digest_enabled or not self.email_enabled:
            return False

        # Собираем статистику за день
        today = datetime.now().date()
        today_alerts = [record for record in self._alert_history if record.timestamp.date() == today]

        # Группируем по уровням
        by_level = {}
        for alert in today_alerts:
            by_level[alert.level] = by_level.get(alert.level, 0) + 1

        # Формируем сообщение
        subject = f"Daily Digest — {today.strftime('%Y-%m-%d')}"
        body = f"""
Дневной дайджест Genesis Trading System

Дата: {today.strftime('%Y-%m-%d')}
Всего алертов: {len(today_alerts)}

По уровням:
- CRITICAL: {by_level.get(AlertLevel.CRITICAL, 0)}
- ERROR: {by_level.get(AlertLevel.ERROR, 0)}
- WARNING: {by_level.get(AlertLevel.WARNING, 0)}
- INFO: {by_level.get(AlertLevel.INFO, 0)}

Статистика системы:
- Всего отправлено: {self.stats['total_sent']}
- Telegram: {self.stats['telegram_sent']}
- Email: {self.stats['email_sent']}
- Push: {self.stats['push_sent']}
- Ошибок: {self.stats['failed']}

---
Это автоматическая сводка от Genesis Trading System.
"""

        return self._send_email(subject, body)
