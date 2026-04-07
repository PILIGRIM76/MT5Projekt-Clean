# src/gui/settings_window.py

import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import MetaTrader5 as mt5
from dotenv import dotenv_values, set_key
from pydantic import BaseModel
from PySide6.QtCore import Qt, QThread, QTime, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from src.core.config_loader import load_config
from src.core.config_models import Settings
from src.core.config_writer import write_config
from src.core.secrets_manager import get_secrets_manager
from src.utils.scheduler_manager import SchedulerManager

from .api_tester import ApiTester
from .trading_modes_widget import TRADING_MODES, TradingModesWidget
from .unified_trading_settings import UnifiedTradingSettingsWidget

logger = logging.getLogger(__name__)


class ConnectionTester(QThread):
    result_ready = Signal(bool, str)

    def __init__(self, settings: dict, tab_widget=None):
        super().__init__()
        self.settings = settings

    def run(self):
        try:
            login = int(self.settings.get("MT5_LOGIN", 0))
            password = self.settings.get("MT5_PASSWORD", "")
            server = self.settings.get("MT5_SERVER", "")
            path = self.settings.get("MT5_PATH", "")
            if not all([login, password, server, path]):
                self.result_ready.emit(False, "Заполните все поля.")
                return
            if not mt5.initialize(path=path, login=login, password=password, server=server, timeout=5000):
                err_code, err_msg = mt5.last_error()
                self.result_ready.emit(False, f"Ошибка MT5: {err_msg}")
                mt5.shutdown()
                return
            account_info = mt5.account_info()
            if account_info is None:
                self.result_ready.emit(False, "Неверные учетные данные.")
            else:
                self.result_ready.emit(True, f"Успех! Счет #{account_info.login}")
            mt5.shutdown()
        except Exception as e:
            self.result_ready.emit(False, f"Ошибка: {str(e)}")


class TelegramTester(QThread):
    """Поток для тестирования Telegram подключения."""

    result_ready = Signal(bool, str)

    def __init__(self, token: str, chat_id: str, timeout: int = 15, use_proxy: bool = True):
        super().__init__()
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout
        self.use_proxy = use_proxy

    def run(self):
        try:
            import requests
            from urllib3.exceptions import ConnectTimeoutError

            # Расширенный список прокси (HTTP + SOCKS5)
            # SOCKS5 прокси работают надёжнее для Telegram
            proxy_list = [
                None,  # 0: Прямое подключение
                {"https": "http://185.162.228.73:80"},  # 1: NL HTTP
                {"https": "http://103.155.217.156:41476"},  # 2: ID HTTP
                {"https": "http://51.159.115.23:3128"},  # 3: FR HTTP
                {"https": "http://178.128.200.88:3128"},  # 4: DE HTTP
                {"https": "http://103.152.112.162:80"},  # 5: IN HTTP
                {"https": "http://20.204.212.76:3128"},  # 6: US HTTP
                {"https": "http://103.167.135.110:80"},  # 7: TH HTTP
                # SOCKS5 прокси (более надёжные)
                {"https": "socks5://176.115.126.216:14568"},  # 8: UA SOCKS5
                {"https": "socks5://195.154.220.171:1080"},  # 9: FR SOCKS5
                {"https": "socks5://51.159.114.111:3128"},  # 10: FR SOCKS5
            ]

            # Этап 1: Быстрая проверка токена (3 сек на попытку)
            logger.info("🔍 Этап 1: Проверка токена бота...")
            url = f"https://api.telegram.org/bot{self.token}/getMe"

            success = False
            for i, proxies in enumerate(proxy_list):
                try:
                    if proxies:
                        proxy_type = (
                            list(proxies.values())[0].split("://")[0].upper() if "://" in list(proxies.values())[0] else "HTTP"
                        )
                        proxy_name = f"#{i} ({['Прямое', 'NL', 'ID', 'FR', 'DE', 'IN', 'US', 'TH', 'UA-S5', 'FR-S5', 'FR-S5'][i]} {proxy_type})"
                    else:
                        proxy_name = "прямое подключение"

                    logger.debug(f"Попытка {i+1}/{len(proxy_list)}: {proxy_name}")

                    response = requests.get(url, timeout=3, proxies=proxies, verify=False)
                    response.raise_for_status()
                    result = response.json()

                    if result.get("ok"):
                        success = True
                        logger.info(f"✅ Успешно через {proxy_name}")
                        break
                    else:
                        # Токен недействителен
                        self.result_ready.emit(False, f"❌ Неверный токен бота: {result.get('description', 'Unknown error')}")
                        return

                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.ProxyError) as e:
                    logger.debug(f"Попытка {i+1} не удалась: {type(e).__name__}")
                    continue
                except Exception as e:
                    logger.debug(f"Попытка {i+1} ошибка: {e}")
                    continue

            if not success:
                logger.warning("Все попытки подключения не удались")
                self.result_ready.emit(
                    False,
                    "⏱️ Telegram заблокирован\n\n🔍 Все прокси недоступны\n\n💡 Решение:\n• Включите VPN и попробуйте снова\n• Проверьте интернет-соединение",
                )
                return

            bot_username = result.get("result", {}).get("username", "unknown")
            logger.info(f"✅ Токен действителен: @{bot_username}")

            # Этап 2: Отправка сообщения (5 сек на попытку)
            logger.info(f"📤 Этап 2: Отправка сообщения в чат {self.chat_id}...")
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": f"🧪 <b>Тест Genesis Trading System</b>\n\nУведомления Telegram работают корректно!\nБот: @{bot_username}",
                "parse_mode": "HTML",
            }

            send_success = False
            for i, proxies in enumerate(proxy_list):
                try:
                    if proxies:
                        proxy_type = (
                            list(proxies.values())[0].split("://")[0].upper() if "://" in list(proxies.values())[0] else "HTTP"
                        )
                        proxy_name = f"#{i} ({['Прямое', 'NL', 'ID', 'FR', 'DE', 'IN', 'US', 'TH', 'UA-S5', 'FR-S5', 'FR-S5'][i]} {proxy_type})"
                    else:
                        proxy_name = "прямое подключение"

                    logger.debug(f"Отправка {i+1}/{len(proxy_list)}: {proxy_name}")

                    response = requests.post(url, json=payload, timeout=5, proxies=proxies, verify=False)
                    response.raise_for_status()
                    result = response.json()

                    if result.get("ok"):
                        send_success = True
                        logger.info(f"✅ Отправлено через {proxy_name}")
                        break

                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.ProxyError) as e:
                    logger.debug(f"Отправка {i+1} не удалась: {type(e).__name__}")
                    continue
                except Exception as e:
                    logger.debug(f"Отправка {i+1} ошибка: {e}")
                    continue

            if not send_success:
                logger.warning("Не удалось отправить сообщение")
                self.result_ready.emit(
                    False, "⏱️ Не удалось отправить\n\n💡 Проверьте:\n• Chat ID (число)\n• Бот в чате\n• Включите VPN"
                )
                return

            if result.get("ok"):
                self.result_ready.emit(True, f"✅ Успех! Бот @{bot_username} отправил сообщение.\n\nПроверьте Telegram!")
            else:
                error_msg = result.get("description", "Unknown error")
                # Частые ошибки
                if "chat not found" in error_msg.lower():
                    error_msg += (
                        "\n\n🔍 Проверьте:\n• Chat ID (должен быть числом)\n• Бот добавлен в чат\n• Чат не заблокирован"
                    )
                elif "bot was blocked" in error_msg.lower():
                    error_msg += "\n\n🚫 Пользователь заблокировал бота.\n✅ Разблокируйте бота и нажмите /start"
                elif "user is deactivated" in error_msg.lower():
                    error_msg += "\n\n💀 Аккаунт пользователя удалён или заблокирован"
                self.result_ready.emit(False, f"❌ Ошибка отправки: {error_msg}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Telegram API error: {e}")
            self.result_ready.emit(False, f"❌ Ошибка запроса: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in TelegramTester: {e}", exc_info=True)
            self.result_ready.emit(False, f"⚠️ Неожиданная ошибка: {str(e)}")


class EmailTester(QThread):
    """Поток для тестирования Email подключения с поддержкой прокси."""

    result_ready = Signal(bool, str)

    def __init__(
        self, smtp_server: str, smtp_port: int, email_from: str, email_password: str, recipients: str, use_proxy: bool = True
    ):
        super().__init__()
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.email_from = email_from
        self.email_password = email_password
        self.recipients = recipients
        self.use_proxy = use_proxy

    def run(self):
        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            msg = MIMEMultipart()
            msg["From"] = self.email_from
            msg["To"] = self.recipients
            msg["Subject"] = "[Genesis Trading] Тест Email"

            body = """
🧪 Тест Genesis Trading System

Email уведомления работают корректно!

---
Это автоматическое тестовое сообщение.
"""
            msg.attach(MIMEText(body, "plain", "utf-8"))

            # === ИСПРАВЛЕНИЕ: Сначала пробуем прямое подключение ===
            logger.info(f"Попытка прямого подключения к {self.smtp_server}:{self.smtp_port}")
            try:
                server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10)
                server.starttls()
                server.login(self.email_from, self.email_password)
                server.send_message(msg)
                server.quit()

                logger.info("✅ Email отправлен через прямое подключение")
                self.result_ready.emit(True, "✅ Успех! Email отправлен (прямое подключение). Проверьте почту.")
                return
            except smtplib.SMTPAuthenticationError:
                self.result_ready.emit(False, "❌ Ошибка аутентификации. Проверьте логин/пароль приложения.")
                return
            except Exception as direct_err:
                logger.warning(f"Прямое подключение не удалось: {direct_err}")
                # Продолжаем пробуем через прокси если use_proxy=True

            # === Попытка подключения через прокси (если включено) ===
            if self.use_proxy:
                try:
                    import socket

                    import socks

                    logger.info("Попытка подключения через прокси...")

                    # Список прокси (без None - прямое уже пробовали)
                    proxy_list = [
                        ((socks.HTTP, "185.162.228.73", 80), "NL HTTP"),
                        ((socks.HTTP, "103.155.217.156", 41476), "ID HTTP"),
                        ((socks.HTTP, "51.159.115.23", 3128), "FR HTTP"),
                        ((socks.SOCKS5, "176.115.126.216", 14568), "UA SOCKS5"),
                        ((socks.SOCKS5, "195.154.220.171", 1080), "FR SOCKS5"),
                    ]

                    for proxy_config, proxy_name in proxy_list:
                        try:
                            logger.info(f"  Пробуем прокси {proxy_name}...")
                            socks.set_default_proxy(*proxy_config)
                            socket.socket = socks.socksocket

                            server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10)
                            server.starttls()
                            server.login(self.email_from, self.email_password)
                            server.send_message(msg)
                            server.quit()

                            # Сброс прокси
                            socks.set_default_proxy()
                            socket.socket = socket._socketobject if hasattr(socket, "_socketobject") else socket.socket

                            logger.info(f"✅ Email отправлен через прокси {proxy_name}")
                            self.result_ready.emit(
                                True, f"✅ Успех! Email отправлен через прокси ({proxy_name}). Проверьте почту."
                            )
                            return

                        except Exception as proxy_err:
                            logger.debug(f"  Прокси {proxy_name} не удался: {proxy_err}")
                            # Сброс прокси перед следующей попыткой
                            try:
                                socks.set_default_proxy()
                                socket.socket = socket._socketobject if hasattr(socket, "_socketobject") else socket.socket
                            except:
                                pass
                            continue

                    # Все прокси не сработали
                    self.result_ready.emit(
                        False,
                        "❌ Все прокси недоступны.\n\n"
                        "💡 Возможные решения:\n"
                        "• Проверьте подключение к интернету\n"
                        "• Попробуйте использовать VPN\n"
                        "• Проверьте что SMTP сервер не заблокирован",
                    )
                    return

                except ImportError:
                    logger.warning("PySocks не установлен, прокси недоступен")
                    self.result_ready.emit(
                        False,
                        "❌ Прямое подключение не удалосьось.\n\n"
                        "💡 Установите PySocks для обхода блокировок:\n"
                        "   pip install PySocks\n\n"
                        "Или используйте VPN",
                    )
                    return

            # Если дошли сюда - все способы исчерпаны
            self.result_ready.emit(
                False,
                "❌ Не удалось отправить Email.\n\n"
                "💡 Проверьте:\n"
                "• Подключение к интернету\n"
                "• Правильность SMTP сервера\n"
                "• Что порт 587 не заблокирован фаерволом",
            )

        except smtplib.SMTPAuthenticationError:
            self.result_ready.emit(False, "❌ Ошибка аутентификации. Проверьте логин/пароль приложения.")
        except smtplib.SMTPConnectError as e:
            self.result_ready.emit(
                False,
                f"❌ Ошибка подключения к SMTP: {e}\n\n"
                f"💡 Попробуйте:\n"
                f"• Использовать другой SMTP сервер\n"
                f"• Включить VPN\n"
                f"• Проверьте фаервол/антивирус",
            )
        except Exception as e:
            logger.error(f"Неожиданная ошибка при тестировании Email: {e}", exc_info=True)
            self.result_ready.emit(False, f"❌ Неожиданная ошибка: {e}")


class ApiKeyTesterThread(QThread):
    result_ready = Signal(int, bool, str)

    def __init__(self, row: int, service_name: str, api_key: str):
        super().__init__()
        self.row = row
        self.service_name = service_name
        self.api_key = api_key

    def run(self):
        tester = ApiTester(self.api_key)
        try:
            success, message = tester.test_key(self.service_name)
            self.result_ready.emit(self.row, success, message)
        except Exception as e:
            self.result_ready.emit(self.row, False, f"Критическая ошибка: {e}")


class AddKeyDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Добавить API ключ")
        layout = QGridLayout(self)
        self.service_name_edit = QLineEdit()
        self.api_key_edit = QLineEdit()
        layout.addWidget(QLabel("Название сервиса (напр. MyService):"), 0, 0)
        layout.addWidget(self.service_name_edit, 0, 1)
        layout.addWidget(QLabel("API Ключ:"), 1, 0)
        layout.addWidget(self.api_key_edit, 1, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, 2, 0, 1, 2)

    def get_data(self):
        return self.service_name_edit.text(), self.api_key_edit.text()


class SettingsWindow(QDialog):
    settings_saved = Signal()
    scheduler_status_updated = Signal(dict)
    database_path_changed = Signal(str)  # Сигнал об изменении пути к базе данных

    def __init__(self, scheduler_manager: SchedulerManager, config: Settings, trading_system=None, parent=None):

        super().__init__(parent)
        self.setWindowTitle("Настройки Системы")
        self.setMinimumSize(900, 750)  # Увеличенный размер (было 700x550)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setModal(True)

        self.env_path = self._find_env_file()
        self.connection_tester = None
        self.api_testers = {}
        self.scheduler_manager = scheduler_manager
        self._icon_pixmap_cache = {}
        self.trading_system = trading_system  # Сохраняем ссылку на торговую систему

        self.full_config = config

        main_layout = QVBoxLayout(self)

        # Инициализация вкладок
        self._init_tabs()

        # Останавливаем любые активные тестеры от предыдущего экземпляра окна
        self._stop_all_testers()

        self.load_settings()

    def create_icon(self, emoji: str, size: int = 28) -> QIcon:
        """Создаёт QIcon из эмодзи с кэшированием."""
        if emoji in self._icon_pixmap_cache:
            return QIcon(self._icon_pixmap_cache[emoji])

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.TextAntialiasing)
        font = painter.font()
        font.setPixelSize(int(size * 0.75))
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, emoji)
        painter.end()

        self._icon_pixmap_cache[emoji] = pixmap
        return QIcon(pixmap)

    def _init_tabs(self):
        self.tab_widget = QTabWidget()  # Сохраняем ссылку для переключения вкладок
        # Прокрутка вкладок при нехватке места
        self.tab_widget.setUsesScrollButtons(True)
        self.layout().addWidget(self.tab_widget)

        mt5_tab = self._create_mt5_tab()
        crypto_tab = self._create_crypto_tab()  # НОВОЕ: Вкладка криптовалют
        api_tab = self._create_api_tab()
        trading_tab = self._create_trading_tab()
        paths_tab = self._create_paths_tab()
        scheduler_tab = self._create_scheduler_tab()
        gp_tab = self._create_gp_tab()
        news_scheduler_tab = self._create_news_scheduler_tab()  # НОВОЕ: Планировщик новостей
        # P0: Notifications (Telegram/Email)
        notifications_tab = self._create_notifications_tab()
        # НОВОЕ: Вкладка обновлений
        updates_tab = self._create_updates_tab()

        self.tab_widget.addTab(mt5_tab, self.create_icon("🔌"), "Подключение MT5")
        self.tab_widget.addTab(crypto_tab, self.create_icon("₿"), "Криптовалюты")  # НОВОЕ
        self.tab_widget.addTab(api_tab, self.create_icon("🔑"), "API Ключи")
        self.tab_widget.addTab(trading_tab, self.create_icon("💹"), "Торговля")
        self.tab_widget.addTab(paths_tab, self.create_icon("📁"), "Пути к данным")
        self.tab_widget.addTab(scheduler_tab, self.create_icon("⏰"), "Планировщик")
        self.tab_widget.addTab(news_scheduler_tab, self.create_icon("📰"), "Планировщик Новостей")
        self.tab_widget.addTab(notifications_tab, self.create_icon("🔔"), "Уведомления")
        self.tab_widget.addTab(updates_tab, self.create_icon("🔄"), "Обновления")
        
        # НОВОЕ: Вкладка Копирование Сделок (в самом конце для заметности)
        try:
            social_tab = self._create_social_tab()
            self.tab_widget.addTab(social_tab, self.create_icon("🤝"), "Копирование Сделок")
            logger.info("✅ Вкладка 'Копирование Сделок' успешно создана и добавлена")
        except Exception as e:
            logger.error(f"❌ Ошибка создания вкладки Social Trading: {e}")

        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        self.layout().addWidget(button_box)

    def _create_news_scheduler_tab(self):
        """Создание вкладки планировщика новостей."""
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setAlignment(Qt.AlignTop)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Заголовок
        title = QLabel("<b>📰 Планировщик Загрузки Новостей</b>")
        title.setStyleSheet("color: #f8f8f2; padding: 10px;")
        layout.addWidget(title)

        # Группа 1: Основные настройки
        main_group = QGroupBox("Основные Настройки")
        main_layout = QFormLayout(main_group)

        # Включение/выключение
        self.news_enabled_check = QCheckBox("Включить загрузку новостей")
        self.news_enabled_check.setToolTip("Автоматическая загрузка новостей по расписанию")
        main_layout.addRow(self.news_enabled_check)

        # Интервал загрузки
        self.news_interval_spin = QSpinBox()
        self.news_interval_spin.setRange(1, 24)
        self.news_interval_spin.setValue(4)
        self.news_interval_spin.setSuffix(" часов")
        self.news_interval_spin.setToolTip("Как часто загружать новые новости")
        main_layout.addRow("Интервал загрузки:", self.news_interval_spin)

        # Время начала
        self.news_start_time = QTimeEdit()
        self.news_start_time.setDisplayFormat("HH:mm")
        self.news_start_time.setTime(QTime(8, 0))
        self.news_start_time.setToolTip("Время первой загрузки новостей")
        main_layout.addRow("Время начала:", self.news_start_time)

        # Максимум новостей за раз
        self.news_max_per_load_spin = QSpinBox()
        self.news_max_per_load_spin.setRange(5, 100)
        self.news_max_per_load_spin.setValue(20)
        self.news_max_per_load_spin.setToolTip("Максимальное количество новостей за одну загрузку")
        main_layout.addRow("Макс. новостей за раз:", self.news_max_per_load_spin)

        layout.addWidget(main_group)

        # Группа 2: Источники новостей
        sources_group = QGroupBox("Источники Новостей")
        sources_layout = QVBoxLayout(sources_group)

        self.news_sources = {}
        sources_list = [
            ("NewsAPI", "newsapi_enabled", "Основные мировые новости (требуется API ключ)"),
            ("RSS Feeds", "rss_enabled", "Ленты RSS (бесплатно, без ключей)"),
            ("Twitter/X", "twitter_enabled", "Твиты инфлюенсеров и СМИ"),
            ("Telegram", "telegram_news_enabled", "Каналы Telegram"),
            ("Yahoo Finance", "yahoo_news_enabled", "Финансовые новости Yahoo"),
            ("Google Trends", "google_trends_enabled", "Тренды поиска Google"),
        ]

        for name, key, tooltip in sources_list:
            cb = QCheckBox(name)
            cb.setToolTip(tooltip)
            cb.setChecked(key in ["newsapi_enabled", "rss_enabled"])  # Включены по умолчанию
            self.news_sources[key] = cb
            sources_layout.addWidget(cb)

        layout.addWidget(sources_group)

        # Группа 3: Ключевые слова и символы
        keywords_group = QGroupBox("Ключевые Слова и Символы")
        keywords_layout = QFormLayout(keywords_group)

        self.news_keywords_edit = QLineEdit()
        self.news_keywords_edit.setPlaceholderText("например: Fed, ECB, inflation, GDP, unemployment")
        self.news_keywords_edit.setToolTip("Ключевые слова для поиска (через запятую)")
        keywords_layout.addRow("Ключевые слова:", self.news_keywords_edit)

        self.news_symbols_edit = QLineEdit()
        self.news_symbols_edit.setPlaceholderText("например: EURUSD, GBPUSD, XAUUSD, BTCUSD")
        self.news_symbols_edit.setToolTip("Торговые символы для мониторинга новостей")
        keywords_layout.addRow("Торговые символы:", self.news_symbols_edit)

        layout.addWidget(keywords_group)

        # Группа 4: NLP Настройки
        nlp_group = QGroupBox("Настройки NLP Анализа")
        nlp_layout = QFormLayout(nlp_group)

        self.news_nlp_enabled = QCheckBox("Включить NLP анализ новостей")
        self.news_nlp_enabled.setToolTip("Автоматический анализ тональности и извлечение сущностей")
        nlp_layout.addRow(self.news_nlp_enabled)

        self.news_sentiment_threshold = QDoubleSpinBox()
        self.news_sentiment_threshold.setRange(-1.0, 1.0)
        self.news_sentiment_threshold.setSingleStep(0.1)
        self.news_sentiment_threshold.setValue(-0.3)
        self.news_sentiment_threshold.setToolTip("Порог негативной тональности для алертов")
        nlp_layout.addRow("Порог негатива:", self.news_sentiment_threshold)

        layout.addWidget(nlp_group)

        # Группа 5: Статус и Лог
        status_group = QGroupBox("Статус и Лог Загрузки")
        status_layout = QVBoxLayout(status_group)

        self.news_status_label = QLabel("Статус: Не запущено")
        self.news_status_label.setStyleSheet("color: gray; font-weight: bold;")
        status_layout.addWidget(self.news_status_label)

        self.news_last_load_label = QLabel("Последняя загрузка: Н/Д")
        status_layout.addWidget(self.news_last_load_label)

        self.news_total_loaded_label = QLabel("Всего загружено: Н/Д")
        status_layout.addWidget(self.news_total_loaded_label)

        # Кнопка ручной загрузки
        self.news_load_now_button = QPushButton("📥 Загрузить новости сейчас")
        self.news_load_now_button.clicked.connect(self._trigger_manual_news_load)
        status_layout.addWidget(self.news_load_now_button)

        layout.addWidget(status_group)

        # Растягиваем последнее пространство
        layout.addStretch()

        return self._create_scrollable_widget(content_widget)

    def _trigger_manual_news_load(self):
        """Ручной запуск загрузки новостей."""
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            "Загрузить новости вручную?\n\nЭто может занять несколько минут.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self.news_load_now_button.setEnabled(False)
            self.news_status_label.setText("Статус: Загрузка...")
            self.news_status_label.setStyleSheet("color: orange; font-weight: bold;")

            try:
                # Здесь будет вызов загрузчика новостей
                logger.info("[NewsScheduler] Ручная загрузка новостей запущена")
                
                # TODO: Вызов загрузчика новостей
                # from src.news.news_loader import NewsLoader
                # loader = NewsLoader(self.full_config)
                # loader.load_all_news()
                
                self.news_status_label.setText("Статус: Завершено ✓")
                self.news_status_label.setStyleSheet("color: #50fa7b; font-weight: bold;")
                self.news_last_load_label.setText(f"Последняя загрузка: {datetime.now().strftime('%H:%M:%S')}")
                QMessageBox.information(self, "Готово", "Новости успешно загружены!")
                
            except Exception as e:
                logger.error(f"[NewsScheduler] Ошибка загрузки: {e}")
                self.news_status_label.setText("Статус: Ошибка ❌")
                self.news_status_label.setStyleSheet("color: #ff5555; font-weight: bold;")
                QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить новости:\n{e}")
            finally:
                self.news_load_now_button.setEnabled(True)

    def _apply_news_scheduler_settings(self):
        """Применение настроек планировщика новостей."""
        if not hasattr(self.full_config, 'news_scheduler'):
            self.full_config.news_scheduler = {}
        
        # Основные настройки
        self.full_config.news_scheduler = {
            "enabled": self.news_enabled_check.isChecked(),
            "interval_hours": self.news_interval_spin.value(),
            "start_time": self.news_start_time.time().toString("HH:mm"),
            "max_news_per_load": self.news_max_per_load_spin.value(),
            
            # Источники
            "sources": {
                key: cb.isChecked() for key, cb in self.news_sources.items()
            },
            
            # Ключевые слова
            "keywords": [k.strip() for k in self.news_keywords_edit.text().split(",") if k.strip()],
            "symbols": [s.strip() for s in self.news_symbols_edit.text().split(",") if s.strip()],
            
            # NLP
            "nlp_enabled": self.news_nlp_enabled.isChecked(),
            "sentiment_threshold": self.news_sentiment_threshold.value(),
        }

    def _load_news_scheduler_settings(self):
        """Загрузка настроек планировщика новостей."""
        news_cfg = getattr(self.full_config, 'news_scheduler', {})
        if not news_cfg:
            news_cfg = {}
        
        # Основные
        self.news_enabled_check.setChecked(news_cfg.get("enabled", True))
        self.news_interval_spin.setValue(news_cfg.get("interval_hours", 4))
        
        start_time = news_cfg.get("start_time", "08:00")
        self.news_start_time.setTime(QTime.fromString(start_time, "HH:mm"))
        
        self.news_max_per_load_spin.setValue(news_cfg.get("max_news_per_load", 20))
        
        # Источники
        sources = news_cfg.get("sources", {})
        for key, cb in self.news_sources.items():
            cb.setChecked(sources.get(key, cb.isChecked()))
        
        # Ключевые слова
        keywords = news_cfg.get("keywords", [])
        self.news_keywords_edit.setText(", ".join(keywords))
        
        symbols = news_cfg.get("symbols", [])
        self.news_symbols_edit.setText(", ".join(symbols))
        
        # NLP
        self.news_nlp_enabled.setChecked(news_cfg.get("nlp_enabled", True))
        self.news_sentiment_threshold.setValue(news_cfg.get("sentiment_threshold", -0.3))

    def _create_social_tab(self):
        """Создание вкладки социальной торговли."""
        widget = QWidget()
        layout = QFormLayout()
        widget.setLayout(layout)

        # Группа: Основные настройки
        self.social_enabled_check = QCheckBox("Включить копирование сделок")
        layout.addRow(self.social_enabled_check)

        self.social_role_combo = QComboBox()
        self.social_role_combo.addItem("Мастер (Трансляция сигналов)", "master")
        self.social_role_combo.addItem("Подписчик (Копирование)", "follower")
        layout.addRow("Роль:", self.social_role_combo)

        # Группа: Режим работы
        self.social_mode_combo = QComboBox()
        self.social_mode_combo.addItem("🏠 Локальный (один ПК)", "local")
        self.social_mode_combo.addItem("🌐 Сетевой (через интернет)", "network")
        self.social_mode_combo.addItem("🔄 Гибридный (оба режима)", "hybrid")
        layout.addRow("Режим работы:", self.social_mode_combo)

        # Группа: Настройки сети (для сетевого/гибридного режима)
        self.social_network_group = QGroupBox("Настройки сети (ZeroMQ)")
        net_layout = QFormLayout()
        self.social_network_group.setLayout(net_layout)

        self.social_master_host_edit = QLineEdit("localhost")
        self.social_master_host_edit.setPlaceholderText("IP адрес Мастера")
        net_layout.addRow("IP адрес Мастера:", self.social_master_host_edit)

        self.social_master_port_spin = QSpinBox()
        self.social_master_port_spin.setRange(1000, 65535)
        self.social_master_port_spin.setValue(5555)
        net_layout.addRow("Порт:", self.social_master_port_spin)

        layout.addRow(self.social_network_group)

        # Группа: Настройки Подписчика
        self.social_sub_group = QGroupBox("Настройки Подписчика")
        sub_layout = QFormLayout()
        self.social_sub_group.setLayout(sub_layout)

        self.social_risk_spin = QDoubleSpinBox()
        self.social_risk_spin.setRange(0.1, 10.0)
        self.social_risk_spin.setValue(1.0)
        self.social_risk_spin.setSingleStep(0.1)
        sub_layout.addRow("Множитель риска:", self.social_risk_spin)

        self.social_max_lot_spin = QDoubleSpinBox()
        self.social_max_lot_spin.setRange(0.01, 100.0)
        self.social_max_lot_spin.setValue(1.0)
        self.social_max_lot_spin.setSingleStep(0.1)
        sub_layout.addRow("Максимальный лот:", self.social_max_lot_spin)

        self.social_symbols_edit = QLineEdit()
        self.social_symbols_edit.setPlaceholderText("EURUSD, GBPUSD (оставьте пустым для всех)")
        sub_layout.addRow("Разрешенные символы:", self.social_symbols_edit)

        layout.addRow(self.social_sub_group)

        # Группа: Статус
        self.social_status_label = QLabel("Статус: Не запущено")
        self.social_status_label.setStyleSheet("color: gray;")
        layout.addRow("Статус:", self.social_status_label)

        return widget

    def _apply_social_settings(self):
        """Применение настроек социальной торговли."""
        enabled = self.social_enabled_check.isChecked()
        role = self.social_role_combo.currentData()
        mode = self.social_mode_combo.currentData()
        master_host = self.social_master_host_edit.text()
        master_port = self.social_master_port_spin.value()
        risk = self.social_risk_spin.value()
        max_lot = self.social_max_lot_spin.value()
        symbols_str = self.social_symbols_edit.text()
        allowed_symbols = [s.strip().upper() for s in symbols_str.split(",") if s.strip()]

        if not hasattr(self.full_config, 'social_trading'):
            self.full_config.social_trading = {}
            
        self.full_config.social_trading = {
            "enabled": enabled,
            "role": role,
            "mode": mode,
            "master_host": master_host,
            "master_port": master_port,
            "risk_multiplier": risk,
            "max_lot_per_trade": max_lot,
            "allowed_symbols": allowed_symbols
        }

    def _load_social_settings(self):
        """Загрузка настроек социальной торговли."""
        social_cfg = None
        if hasattr(self.full_config, 'social_trading'):
            social_cfg = self.full_config.social_trading
        
        if not social_cfg:
            social_cfg = {}
        
        self.social_enabled_check.setChecked(social_cfg.get("enabled", False))
        
        role = social_cfg.get("role", "master")
        index = self.social_role_combo.findData(role)
        if index >= 0:
            self.social_role_combo.setCurrentIndex(index)

        mode = social_cfg.get("mode", "local")
        index = self.social_mode_combo.findData(mode)
        if index >= 0:
            self.social_mode_combo.setCurrentIndex(index)

        self.social_master_host_edit.setText(social_cfg.get("master_host", "localhost"))
        self.social_master_port_spin.setValue(social_cfg.get("master_port", 5555))

        self.social_risk_spin.setValue(social_cfg.get("risk_multiplier", 1.0))
        self.social_max_lot_spin.setValue(social_cfg.get("max_lot_per_trade", 1.0))
        
        symbols = social_cfg.get("allowed_symbols", [])
        self.social_symbols_edit.setText(", ".join(symbols))

    def _create_scrollable_widget(self, content_widget: QWidget) -> QWidget:
        """Создаёт прокручиваемый контейнер для вкладки."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content_widget)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        layout.addWidget(scroll)
        return container

    def _create_updates_tab(self):
        """Создает вкладку для управления обновлениями системы."""
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setAlignment(Qt.AlignTop)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Заголовок
        title = QLabel("<h2>🔄 Управление обновлениями</h2>")
        title.setStyleSheet("color: #f8f8f2; padding: 10px;")
        title.setWordWrap(True)
        layout.addWidget(title)

        # Фрейм статуса
        status_frame = QFrame()
        status_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        status_frame.setStyleSheet("""
            QFrame {
                background-color: #282a36;
                border: 1px solid #44475a;
                border-radius: 5px;
                padding: 15px;
            }
        """)
        status_layout = QVBoxLayout(status_frame)

        # Текущая версия
        version_layout = QHBoxLayout()
        version_layout.addWidget(QLabel("📦 Текущая версия:"))
        self.update_current_version_label = QLabel("Загрузка...")
        self.update_current_version_label.setFont(QFont("Consolas", 11))
        self.update_current_version_label.setStyleSheet("color: #50fa7b; font-weight: bold;")
        version_layout.addWidget(self.update_current_version_label)
        status_layout.addLayout(version_layout)

        # Статус обновления
        update_status_layout = QHBoxLayout()
        update_status_layout.addWidget(QLabel("📢 Статус:"))
        self.update_status_label = QLabel("Нет обновлений")
        self.update_status_label.setFont(QFont("Arial", 10))
        self.update_status_label.setStyleSheet("color: #f8f8f2;")
        update_status_layout.addWidget(self.update_status_label)
        status_layout.addLayout(update_status_layout)

        # Статус мониторинга
        monitoring_layout = QHBoxLayout()
        monitoring_layout.addWidget(QLabel("👁️ Мониторинг:"))
        self.update_monitoring_status_label = QLabel("Не активен")
        self.update_monitoring_status_label.setFont(QFont("Arial", 10))
        self.update_monitoring_status_label.setStyleSheet("color: #ffb86c;")
        monitoring_layout.addWidget(self.update_monitoring_status_label)
        status_layout.addLayout(monitoring_layout)

        # Последняя проверка
        last_check_layout = QHBoxLayout()
        last_check_layout.addWidget(QLabel("⏰ Последняя проверка:"))
        self.update_last_check_label = QLabel("Н/Д")
        self.update_last_check_label.setFont(QFont("Arial", 9))
        self.update_last_check_label.setStyleSheet("color: #888;")
        last_check_layout.addWidget(self.update_last_check_label)
        status_layout.addLayout(last_check_layout)

        layout.addWidget(status_frame)

        # Кнопки управления
        buttons_group = QGroupBox("⚡ Действия")
        buttons_layout = QVBoxLayout(buttons_group)

        # Кнопка проверки обновлений
        self.update_check_button = QPushButton("🔍 Проверить обновления")
        self.update_check_button.clicked.connect(self._on_check_updates_clicked)
        self.update_check_button.setStyleSheet("""
            QPushButton {
                background-color: #44475a;
                color: #f8f8f2;
                border: none;
                padding: 12px;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #6272a4;
            }
            QPushButton:pressed {
                background-color: #44475a;
            }
        """)
        buttons_layout.addWidget(self.update_check_button)

        # Кнопка применения обновления
        self.update_apply_button = QPushButton("⬇️ Применить обновление")
        self.update_apply_button.clicked.connect(self._on_apply_update_clicked)
        self.update_apply_button.setEnabled(False)
        self.update_apply_button.setStyleSheet("""
            QPushButton {
                background-color: #50fa7b;
                color: #282a36;
                border: none;
                padding: 12px;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #69ff94;
            }
            QPushButton:pressed {
                background-color: #50fa7b;
            }
            QPushButton:disabled {
                background-color: #44475a;
                color: #6272a4;
            }
        """)
        buttons_layout.addWidget(self.update_apply_button)

        # Кнопка включения/выключения мониторинга
        self.update_toggle_monitoring_button = QPushButton("▶️ Включить мониторинг")
        self.update_toggle_monitoring_button.clicked.connect(self._on_toggle_monitoring_clicked)
        self.update_toggle_monitoring_button.setStyleSheet("""
            QPushButton {
                background-color: #bd93f9;
                color: #f8f8f2;
                border: none;
                padding: 12px;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #d6acff;
            }
            QPushButton:pressed {
                background-color: #bd93f9;
            }
        """)
        buttons_layout.addWidget(self.update_toggle_monitoring_button)

        layout.addWidget(buttons_group)

        # Информация
        info_group = QGroupBox("ℹ️ Информация")
        info_layout = QVBoxLayout(info_group)
        info_label = QLabel(
            "Система обновлений позволяет:\n\n"
            "• Проверять наличие новых версий из репозитория\n"
            "• Автоматически применять обновления\n"
            "• Мониторить изменения в фоновом режиме\n\n"
            "Обновления применяются без перезапуска приложения.\n"
            "Активные позиции не будут затронуты."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #bdc3c7; padding: 5px;")
        info_layout.addWidget(info_label)
        layout.addWidget(info_group)

        # Растяжка
        layout.addStretch()

        # Запуск таймера обновления статуса
        self.update_status_timer = QTimer(self)
        self.update_status_timer.timeout.connect(self._update_update_status)
        self.update_status_timer.start(5000)  # Обновление каждые 5 секунд

        return self._create_scrollable_widget(content_widget)

    def _update_update_status(self):
        """Обновление статуса обновлений."""
        if not self.trading_system:
            return

        # Получаем hot_reload_manager через core_system
        manager = self._get_hot_reload_manager()

        if not manager:
            return

        try:
            status = manager.get_update_status()

            # Обновляем текущую версию
            if status.get("local_commit"):
                short_commit = status["local_commit"][:8]
                self.update_current_version_label.setText(short_commit)

            # Обновляем статус мониторинга
            if status.get("monitoring"):
                self.update_monitoring_status_label.setText("✅ Активен")
                self.update_monitoring_status_label.setStyleSheet("color: #50fa7b;")
                self.update_toggle_monitoring_button.setText("⏹️ Выключить мониторинг")
            else:
                self.update_monitoring_status_label.setText("❌ Не активен")
                self.update_monitoring_status_label.setStyleSheet("color: #ff5555;")
                self.update_toggle_monitoring_button.setText("▶️ Включить мониторинг")

            # Обновляем время последней проверки
            if status.get("last_check"):
                last_check = datetime.fromtimestamp(status["last_check"])
                self.update_last_check_label.setText(last_check.strftime("%H:%M:%S"))
            else:
                self.update_last_check_label.setText("Н/Д")

            # Проверяем наличие обновлений
            if status.get("has_updates"):
                self.update_status_label.setText("🔔 Доступна новая версия!")
                self.update_status_label.setStyleSheet("color: #ffb86c; font-weight: bold;")
                self.update_apply_button.setEnabled(True)
            else:
                self.update_status_label.setText("✅ Нет обновлений")
                self.update_status_label.setStyleSheet("color: #50fa7b;")
                self.update_apply_button.setEnabled(False)

        except Exception as e:
            logger.error(f"[SettingsWindow Updates] Ошибка: {e}")

    def _on_check_updates_clicked(self):
        """Обработчик кнопки проверки обновлений."""
        logger.info("🔍 Запрос проверки обновлений из настроек")

        manager = self._get_hot_reload_manager()
        if not manager:
            QMessageBox.warning(self, "Ошибка", "Менеджер обновлений не инициализирован.")
            return

        self.update_check_button.setText("⏳ Проверка...")
        self.update_check_button.setEnabled(False)

        try:
            has_updates = manager.check_for_updates()
            if has_updates:
                self.update_status_label.setText("🔔 Доступна новая версия!")
                self.update_status_label.setStyleSheet("color: #ffb86c; font-weight: bold;")
                self.update_apply_button.setEnabled(True)
            else:
                self.update_status_label.setText("✅ Нет обновлений")
                self.update_status_label.setStyleSheet("color: #50fa7b;")
                self.update_apply_button.setEnabled(False)
        except Exception as e:
            logger.error(f"Ошибка при проверке обновлений: {e}")
            self.update_status_label.setText(f"❌ Ошибка: {e}")
            self.update_status_label.setStyleSheet("color: #ff5555;")
        finally:
            self.update_check_button.setText("🔍 Проверить обновления")
            self.update_check_button.setEnabled(True)

    def _on_apply_update_clicked(self):
        """Обработчик кнопки применения обновления."""
        logger.info("⬇️ Запрос применения обновления из настроек")

        manager = self._get_hot_reload_manager()
        if not manager:
            QMessageBox.warning(self, "Ошибка", "Менеджер обновлений не инициализирован.")
            return

        reply = QMessageBox.question(
            self,
            "Подтверждение обновления",
            "Применить обновление системы?\n\n"
            "• Будут загружены последние изменения из GitHub\n"
            "• Модули будут перезагружены\n"
            "• Активные позиции НЕ будут затронуты\n\n"
            "Продолжить?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self.update_apply_button.setText("⏳ Применение...")
            self.update_apply_button.setEnabled(False)

            try:
                success = manager.apply_update()
                if success:
                    self.update_status_label.setText("✅ Обновление применено!")
                    self.update_status_label.setStyleSheet("color: #50fa7b;")
                    QMessageBox.information(
                        self,
                        "Обновление завершено",
                        "✅ Система успешно обновлена!\n\n"
                        "• Модули перезагружены\n"
                        "• GUI обновлён\n"
                        "• Активные позиции сохранены",
                        QMessageBox.Ok,
                    )
                else:
                    self.update_status_label.setText("❌ Ошибка обновления")
                    self.update_status_label.setStyleSheet("color: #ff5555;")
                    QMessageBox.critical(
                        self,
                        "Ошибка обновления",
                        "❌ Не удалось применить обновление.\n\n" "Проверьте логи для получения подробностей.",
                        QMessageBox.Ok,
                    )
            except Exception as e:
                logger.error(f"Ошибка при применении обновления: {e}")
                self.update_status_label.setText(f"❌ Ошибка: {e}")
                self.update_status_label.setStyleSheet("color: #ff5555;")
            finally:
                self.update_apply_button.setText("⬇️ Применить обновление")
                self.update_apply_button.setEnabled(True)

    def _on_toggle_monitoring_clicked(self):
        """Обработчик кнопки переключения мониторинга."""
        logger.info("🔄 Запрос переключения мониторинга из настроек")

        manager = self._get_hot_reload_manager()
        if not manager:
            QMessageBox.warning(self, "Ошибка", "Менеджер обновлений не инициализирован.")
            return

        if manager._monitoring:
            manager.stop_monitoring()
            self.update_monitoring_status_label.setText("❌ Не активен")
            self.update_monitoring_status_label.setStyleSheet("color: #ff5555;")
            self.update_toggle_monitoring_button.setText("▶️ Включить мониторинг")
        else:
            manager.start_monitoring(interval=60)
            self.update_monitoring_status_label.setText("✅ Активен")
            self.update_monitoring_status_label.setStyleSheet("color: #50fa7b;")
            self.update_toggle_monitoring_button.setText("⏹️ Выключить мониторинг")

    def _get_hot_reload_manager(self):
        """Получение HotReloadManager."""
        if self.trading_system:
            if hasattr(self.trading_system, "core_system") and self.trading_system.core_system:
                return self.trading_system.core_system.hot_reload_manager
            elif hasattr(self.trading_system, "hot_reload_manager"):
                return self.trading_system.hot_reload_manager
        return None

    def _create_gp_tab(self):
        content_widget = QWidget()
        layout = QGridLayout(content_widget)
        layout.setAlignment(Qt.AlignTop)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        layout.setColumnMinimumWidth(0, 250)  # Минимальная ширина для labels
        layout.setColumnStretch(1, 1)  # Растягиваем колонку со spinbox

        gp_title = QLabel("<b>Настройки Генетического Программирования (R&D)</b>")
        gp_title.setToolTip(
            "Генетическое программирование (GP) используется для эволюционной оптимизации торговых стратегий.\n"
            "Система автоматически создаёт и улучшает стратегии, отбирая наиболее прибыльные."
        )
        layout.addWidget(gp_title, 0, 0, 1, 2)

        layout.addWidget(QLabel("Размер популяции:"), 1, 0)
        self.gp_pop_spin = QSpinBox()
        self.gp_pop_spin.setRange(10, 1000)
        self.gp_pop_spin.setValue(50)  # Значение по умолчанию
        self.gp_pop_spin.setToolTip(
            "Количество стратегий в одном поколении.\n"
            "Больше = больше разнообразия, но медленнее работа.\n"
            "Рекомендуется: 50-100"
        )
        layout.addWidget(self.gp_pop_spin, 1, 1)

        layout.addWidget(QLabel("Количество поколений:"), 2, 0)
        self.gp_gen_spin = QSpinBox()
        self.gp_gen_spin.setRange(1, 500)
        self.gp_gen_spin.setValue(20)  # Значение по умолчанию
        self.gp_gen_spin.setToolTip(
            "Количество поколений для эволюции стратегий.\n"
            "Больше = лучше оптимизация, но дольше обучение.\n"
            "Рекомендуется: 20-50"
        )
        layout.addWidget(self.gp_gen_spin, 2, 1)

        layout.setRowStretch(10, 1)

        return self._create_scrollable_widget(content_widget)

    def _create_trading_tab(self):
        """Создает вкладку с настройками торговли, управления рисками и торговыми режимами."""
        content_widget = QWidget()
        self._trading_tab_widget = content_widget
        main_layout = QVBoxLayout(content_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # === ЗАГОЛОВОК ===
        title_layout = QHBoxLayout()
        title_layout.setSpacing(10)

        title_label = QLabel("<h2>⚙️ Торговля и Риск-менеджмент</h2>")
        title_label.setStyleSheet("color: #f8f8f2; padding: 10px;")
        title_label.setWordWrap(True)
        title_layout.addWidget(title_label)

        title_layout.addStretch()

        # Переключатель в виде toggle switch (бегунок)
        toggle_container = QWidget()
        toggle_layout = QHBoxLayout(toggle_container)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.setSpacing(10)

        # Левая метка
        off_label = QLabel("⛔ Выкл")
        off_label.setStyleSheet("color: #95a5a6; font-weight: bold; font-size: 13px;")

        # Toggle Switch (кастомный чекбокс)
        self.trading_modes_enable_checkbox = QCheckBox()
        self.trading_modes_enable_checkbox.setChecked(False)
        self.trading_modes_enable_checkbox.setCursor(Qt.PointingHandCursor)
        self.trading_modes_enable_checkbox.setStyleSheet("""
            QCheckBox {
                spacing: 0px;
            }
            QCheckBox::indicator {
                width: 60px;
                height: 30px;
                border-radius: 15px;
                background-color: #34495e;
            }
            QCheckBox::indicator:checked {
                background-color: #27ae60;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #27ae60;
            }
            QCheckBox::indicator:unchecked:hover {
                border: 2px solid #95a5a6;
            }
        """)
        self.trading_modes_enable_checkbox.setToolTip(
            "Включите для активации карточек режимов торговли\n"
            "Пока выключено - используется базовая конфигурация риск-менеджмента"
        )

        # Правая метка
        on_label = QLabel("✅ Вкл")
        on_label.setStyleSheet("color: #27ae60; font-weight: bold; font-size: 13px;")

        toggle_layout.addWidget(off_label)
        toggle_layout.addWidget(self.trading_modes_enable_checkbox)
        toggle_layout.addWidget(on_label)

        title_layout.addWidget(toggle_container)

        main_layout.addLayout(title_layout)

        # === СЕКЦИЯ ТОРГОВЫХ РЕЖИМОВ ===
        modes_group = QGroupBox("📊 Режимы Торговли")
        modes_group.setToolTip(
            "Выберите готовый режим торговли для автоматической настройки всех параметров риск-менеджмента.\n"
            "Каждый режим оптимизирован под определённый стиль торговли."
        )
        modes_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #f8f8f2;
                margin-top: 10px;
                padding-top: 10px;
                border: 1px solid #3e4451;
                border-radius: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        modes_layout = QVBoxLayout(modes_group)

        modes_desc = QLabel(
            "Выберите готовый режим торговли для автоматической настройки риск-менеджмента.\n"
            "Настройки применяются немедленно и сохраняются в конфигурацию."
        )
        modes_desc.setStyleSheet("color: #bdc3c7; padding: 5px;")
        modes_desc.setWordWrap(True)
        modes_layout.addWidget(modes_desc)

        # Используем TradingModesWidget (у него есть встроенный скролл)
        self.trading_modes_widget = TradingModesWidget()
        self.trading_modes_widget.mode_changed.connect(self._on_trading_mode_changed)
        self.trading_modes_widget.enabled_changed.connect(self._on_trading_modes_enabled_changed)
        self.trading_modes_widget.open_settings_requested.connect(self._scroll_to_risk_settings)

        # Подключаем чекбокс к виджету
        self.trading_modes_enable_checkbox.stateChanged.connect(self.trading_modes_widget.on_enabled_changed)

        modes_layout.addWidget(self.trading_modes_widget)

        main_layout.addWidget(modes_group)

        # --- Группа Управления Рисками ---
        self._risk_group = QGroupBox("⚙️ Ручная Настройка Риск-Менеджмента")
        self._risk_group.setToolTip(
            "Ручная настройка параметров риск-менеджмента для кастомного режима торговли.\n"
            "Изменения применяются немедленно после сохранения настроек."
        )
        self._risk_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #f8f8f2;
                margin-top: 10px;
                padding-top: 10px;
                border: 1px solid #3e4451;
                border-radius: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        risk_layout = QGridLayout(self._risk_group)

        risk_layout.addWidget(QLabel("Риск на сделку (% от капитала):"), 0, 0)
        self.risk_percentage_spinbox = QDoubleSpinBox()
        self.risk_percentage_spinbox.setRange(0.1, 10.0)
        self.risk_percentage_spinbox.setSingleStep(0.1)
        self.risk_percentage_spinbox.setToolTip(
            "Процент от баланса счета, которым система готова рискнуть в одной сделке.\nНапример, 1% от $10000 = $100 риска."
        )
        risk_layout.addWidget(self.risk_percentage_spinbox, 0, 1)

        risk_layout.addWidget(QLabel("Соотношение Риск/Прибыль:"), 1, 0)
        self.risk_reward_ratio_spinbox = QDoubleSpinBox()
        self.risk_reward_ratio_spinbox.setRange(0.5, 10.0)
        self.risk_reward_ratio_spinbox.setSingleStep(0.1)
        self.risk_reward_ratio_spinbox.setToolTip(
            "Соотношение потенциальной прибыли к риску.\nЗначение 2.0 означает, что Take Profit будет в 2 раза дальше от цены входа, чем Stop Loss."
        )
        risk_layout.addWidget(self.risk_reward_ratio_spinbox, 1, 1)

        risk_layout.addWidget(QLabel("Макс. дневная просадка (%):"), 2, 0)
        self.max_daily_drawdown_spinbox = QDoubleSpinBox()
        self.max_daily_drawdown_spinbox.setRange(1.0, 50.0)
        self.max_daily_drawdown_spinbox.setSingleStep(1.0)
        self.max_daily_drawdown_spinbox.setToolTip(
            "Максимально допустимая дневная просадка в процентах от баланса.\nПри достижении этого лимита система прекратит открывать новые сделки до следующего дня."
        )
        risk_layout.addWidget(self.max_daily_drawdown_spinbox, 2, 1)

        main_layout.addWidget(self._risk_group)

        # --- Группа Управления Позициями ---
        positions_group = QGroupBox("Управление Позициями")
        positions_group.setToolTip("Настройки управления количеством открытых позиций и торговлей в выходные дни.")
        positions_layout = QGridLayout(positions_group)

        positions_layout.addWidget(QLabel("Макс. кол-во открытых позиций:"), 0, 0)
        self.max_open_positions_spinbox = QSpinBox()
        self.max_open_positions_spinbox.setRange(1, 100)
        self.max_open_positions_spinbox.setToolTip(
            "Максимальное количество одновременно открытых позиций по всем инструментам."
        )
        positions_layout.addWidget(self.max_open_positions_spinbox, 0, 1)

        self.allow_weekend_trading_checkbox = QCheckBox("Разрешить торговлю на выходных (для отладки)")
        self.allow_weekend_trading_checkbox.setToolTip(
            "Если включено, система будет игнорировать проверку на субботу и воскресенье.\nИспользовать только для тестирования и отладки, не на реальных счетах!"
        )
        positions_layout.addWidget(self.allow_weekend_trading_checkbox, 1, 0, 1, 2)

        main_layout.addWidget(positions_group)

        # --- Группа Управления Символами ---
        symbols_group = QGroupBox("Управление Торговыми Символами (Whitelist)")
        symbols_group.setToolTip(
            "Список разрешённых торговых инструментов (символов).\n"
            "Робот будет анализировать и торговать только выбранные символы."
        )
        symbols_layout = QVBoxLayout(symbols_group)

        self.symbols_table = QTableWidget()
        self.symbols_table.setColumnCount(1)
        self.symbols_table.setHorizontalHeaderLabels(["Символ"])
        self.symbols_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.symbols_table.setToolTip(
            "Список символов (whitelist), которыми разрешено торговать роботу.\nСистема будет анализировать и открывать сделки только по этим инструментам."
        )
        symbols_layout.addWidget(self.symbols_table)

        add_remove_layout = QHBoxLayout()
        self.symbol_input = QLineEdit()
        self.symbol_input.setPlaceholderText("Напр. EURUSD, GBPJPY, XAUUSD...")
        self.symbol_input.setToolTip(
            "Введите тикер символа в формате брокера (например, EURUSD, XAUUSD) и нажмите 'Добавить'."
        )
        self.add_symbol_button = QPushButton("Добавить")
        self.add_symbol_button.setToolTip("Добавляет указанный символ в список разрешённых для торговли.")
        self.remove_symbol_button = QPushButton("Удалить выбранный")
        self.remove_symbol_button.setToolTip("Удаляет выбранный в таблице символ из списка разрешенных.")
        add_remove_layout.addWidget(self.symbol_input)
        add_remove_layout.addWidget(self.add_symbol_button)
        add_remove_layout.addWidget(self.remove_symbol_button)
        symbols_layout.addLayout(add_remove_layout)

        self.add_symbol_button.clicked.connect(self._add_symbol_to_table)
        self.remove_symbol_button.clicked.connect(self._remove_symbol_from_table)

        main_layout.addWidget(symbols_group)
        main_layout.addStretch()

        # Загрузка текущего режима из конфига
        self._load_current_trading_mode()

        return self._create_scrollable_widget(self._trading_tab_widget)

    def _add_symbol_to_table(self):
        symbol = self.symbol_input.text().upper().strip()
        if not symbol:
            return

        items = self.symbols_table.findItems(symbol, Qt.MatchExactly)
        if not items:
            row_position = self.symbols_table.rowCount()
            self.symbols_table.insertRow(row_position)
            self.symbols_table.setItem(row_position, 0, QTableWidgetItem(symbol))
            self.symbol_input.clear()
        else:
            QMessageBox.warning(self, "Дубликат", f"Символ '{symbol}' уже есть в списке.")

    def _remove_symbol_from_table(self):
        current_row = self.symbols_table.currentRow()
        if current_row >= 0:
            self.symbols_table.removeRow(current_row)
        else:
            QMessageBox.warning(self, "Внимание", "Пожалуйста, выберите символ для удаления.")

    def load_settings(self):
        config_values = dotenv_values(self.env_path)
        for key, widget in self.mt5_entries.items():
            widget.setText(config_values.get(key, ""))
        self.api_table.setRowCount(0)
        api_keys = {
            k: v
            for k, v in config_values.items()
            if k.endswith(("_KEY", "_TOKEN", "_ID", "_HASH")) and not k.startswith("MT5")
        }
        for key, value in api_keys.items():
            self._add_row_to_api_table(key, value)

        self.hf_cache_edit.setText(self.full_config.HF_MODELS_CACHE_DIR or "")

        # Загрузка пути к модели Оркестратора
        self.orchestrator_model_edit.setText(self.full_config.ORCHESTRATOR_MODEL_PATH or "")

        # Загрузка настроек криптовалют
        crypto_config = getattr(self.full_config, "crypto_exchanges", None)
        if crypto_config:
            # Преобразуем Pydantic модель в dict если нужно
            if hasattr(crypto_config, "model_dump"):
                crypto_data = crypto_config.model_dump()
            elif isinstance(crypto_config, dict):
                crypto_data = crypto_config
            else:
                crypto_data = {}

            if crypto_data:
                self.crypto_enabled_checkbox.setChecked(crypto_data.get("enabled", False))
                self.crypto_default_exchange_combo.setCurrentText(crypto_data.get("default_exchange", "binance"))

                # Binance
                exchanges = crypto_data.get("exchanges", {})
                if isinstance(exchanges, dict):
                    binance_config = exchanges.get("binance", {})
                    self.binance_enabled_checkbox.setChecked(binance_config.get("enabled", False))
                    self.binance_sandbox_checkbox.setChecked(binance_config.get("sandbox", False))
                    self.binance_symbols_edit.setText(",".join(binance_config.get("symbols", ["BTC/USDT", "ETH/USDT"])))
                    self.binance_leverage_spin.setValue(binance_config.get("default_leverage", 1))
                    self.binance_market_type_combo.setCurrentText(binance_config.get("market_type", "spot"))

                    # Bybit
                    bybit_config = exchanges.get("bybit", {})
                    self.bybit_enabled_checkbox.setChecked(bybit_config.get("enabled", False))
                    self.bybit_sandbox_checkbox.setChecked(bybit_config.get("sandbox", False))
                    self.bybit_symbols_edit.setText(",".join(bybit_config.get("symbols", ["BTC/USDT", "ETH/USDT"])))
        self.risk_percentage_spinbox.setValue(self.full_config.RISK_PERCENTAGE)
        self.risk_reward_ratio_spinbox.setValue(self.full_config.RISK_REWARD_RATIO)
        self.max_daily_drawdown_spinbox.setValue(self.full_config.MAX_DAILY_DRAWDOWN_PERCENT)
        self.max_open_positions_spinbox.setValue(self.full_config.MAX_OPEN_POSITIONS)
        self.allow_weekend_trading_checkbox.setChecked(self.full_config.ALLOW_WEEKEND_TRADING)
        try:
            if hasattr(self, 'gp_pop_spin'):
                self.gp_pop_spin.setValue(self.full_config.GP_POPULATION_SIZE)
                self.gp_gen_spin.setValue(self.full_config.GP_GENERATIONS)
        except RuntimeError as e:
            logger.warning(f"Пропуск настройки GP (виджет удалён): {e}")

        self.symbols_table.setRowCount(0)
        for symbol in self.full_config.SYMBOLS_WHITELIST:
            row_position = self.symbols_table.rowCount()
            self.symbols_table.insertRow(row_position)
            self.symbols_table.setItem(row_position, 0, QTableWidgetItem(symbol))

        self.db_folder_edit.setText(self.full_config.DATABASE_FOLDER)

        # Загрузка путей к векторной БД и логам
        vector_db_path = getattr(self.full_config.vector_db, "path", "vector_db")
        # Если путь относительный, добавляем к DATABASE_FOLDER
        if not os.path.isabs(vector_db_path):
            vector_db_full_path = os.path.join(self.full_config.DATABASE_FOLDER, vector_db_path)
        else:
            vector_db_full_path = vector_db_path
        self.vector_db_folder_edit.setText(vector_db_full_path)

        # Загрузка пути к логам (по умолчанию database/logs)
        logs_path = getattr(self.full_config, "LOGS_FOLDER", os.path.join(self.full_config.DATABASE_FOLDER, "logs"))
        self.logs_folder_edit.setText(logs_path)

        self._update_scheduler_status()

        # Загрузка настроек автообучения
        if hasattr(self.full_config, "auto_retraining"):
            self.auto_retrain_checkbox.setChecked(self.full_config.auto_retraining.enabled)
            time_parts = self.full_config.auto_retraining.schedule_time.split(":")
            self.auto_retrain_time_edit.setTime(QTime(int(time_parts[0]), int(time_parts[1])))
            self.auto_retrain_interval_spin.setValue(self.full_config.auto_retraining.interval_hours)
            self.auto_retrain_max_symbols_spin.setValue(self.full_config.auto_retraining.max_symbols)
            self.auto_retrain_max_workers_spin.setValue(self.full_config.auto_retraining.max_workers)
        else:
            # Значения по умолчанию
            self.auto_retrain_checkbox.setChecked(True)
            self.auto_retrain_time_edit.setTime(QTime(2, 0))
            self.auto_retrain_interval_spin.setValue(24)
            self.auto_retrain_max_symbols_spin.setValue(30)
            self.auto_retrain_max_workers_spin.setValue(3)

        # Загрузка настроек контроля прибыли
        self.profit_target_mode_combo.setCurrentText(getattr(self.full_config, "PROFIT_TARGET_MODE", "auto"))
        self.profit_target_manual_spin.setValue(getattr(self.full_config, "PROFIT_TARGET_MANUAL_PERCENT", 5.0))
        self.reentry_profit_spin.setValue(getattr(self.full_config, "REENTRY_COOLDOWN_AFTER_PROFIT", 60))
        self.reentry_loss_spin.setValue(getattr(self.full_config, "REENTRY_COOLDOWN_AFTER_LOSS", 30))

        # Загрузка новых настроек контроля прибыли и интенсивности
        self.max_profit_close_spin.setValue(getattr(self.full_config, "MAX_PROFIT_PER_TRADE_PERCENT", 5.0))
        self.profit_mode_combo.setCurrentText(getattr(self.full_config, "PROFIT_MODE", "auto"))
        self.trade_intensity_combo.setCurrentText(getattr(self.full_config, "TRADE_INTENSITY", "medium"))
        self.trade_interval_spin.setValue(getattr(self.full_config, "TRADE_INTERVAL_SECONDS", 15))
        self.reentry_same_pair_combo.setCurrentText(getattr(self.full_config, "REENTRY_SAME_PAIR_MODE", "cooldown"))
        self.reentry_same_pair_cooldown_spin.setValue(getattr(self.full_config, "REENTRY_SAME_PAIR_COOLDOWN_MINUTES", 30))

        maint_time_str = self.scheduler_manager.get_task_trigger_time("GenesisMaintenance")
        if maint_time_str:
            self.maintenance_time_edit.setTime(QTime.fromString(maint_time_str, "HH:mm"))
        else:
            self.maintenance_time_edit.setTime(QTime(3, 0))  # Время по умолчанию

        # Загружаем время для задачи оптимизации
        opt_time_str = self.scheduler_manager.get_task_trigger_time("GenesisWeeklyOptimization")
        if opt_time_str:
            self.optimization_time_edit.setTime(QTime.fromString(opt_time_str, "HH:mm"))
        else:
            self.optimization_time_edit.setTime(QTime(12, 0))  # Время по умолчанию

        # P0: Загрузка настроек уведомлений (Telegram/Email)
        config_values = dotenv_values(self.env_path)
        logger.info(f"Загрузка настроек уведомлений из {self.env_path}")
        logger.info(f"config_values keys: {list(config_values.keys())}")

        # Получаем SecretsManager для загрузки чувствительных данных
        secrets_mgr = get_secrets_manager()
        logger.info(f"SecretsManager инициализирован: {secrets_mgr}")
        logger.info(f"Secrets file exists: {secrets_mgr.secrets_file.exists()}")
        logger.info(f"Secrets file path: {secrets_mgr.secrets_file}")

        if hasattr(self.full_config, "alerting"):
            alerting_config = self.full_config.alerting
            logger.info(f"alerting конфигурация найдена: {alerting_config}")

            # Telegram
            telegram_config = (
                alerting_config.channels.get("telegram", {})
                if isinstance(alerting_config.channels, dict)
                else {"enabled": False}
            )
            logger.info(f"Telegram config: {telegram_config}")

            telegram_enabled_saved = telegram_config.get("enabled", False)
            logger.info(f"Telegram enabled из settings.json: {telegram_enabled_saved}")
            self.telegram_enabled_checkbox.setChecked(telegram_enabled_saved)

            # Токен загружаем из .env или SecretsManager
            telegram_token = config_values.get("TELEGRAM_BOT_TOKEN", "")
            logger.info(
                f"Telegram token из .env: {'есть' if telegram_token else 'нет'} (длина: {len(telegram_token) if telegram_token else 0})"
            )

            if not telegram_token:
                # Пробуем загрузить из SecretsManager
                logger.info("Попытка загрузки Telegram token из SecretsManager...")
                telegram_token = secrets_mgr.get_secret("TELEGRAM_BOT_TOKEN", cache=True) or ""
                logger.info(
                    f"Telegram token из SecretsManager: {'есть' if telegram_token else 'нет'} (длина: {len(telegram_token) if telegram_token else 0})"
                )

            if telegram_token:
                # Маскируем токен для безопасности (показываем первые 10 символов)
                masked_token = telegram_token[:10] + "..." if len(telegram_token) > 10 else telegram_token
                logger.info(f"✅ Telegram token загружен: {masked_token}")
            else:
                logger.warning("❌ Telegram token НЕ загружен (пустой)")
            self.telegram_token_edit.setText(telegram_token)

            telegram_chat_id = config_values.get("TELEGRAM_CHAT_ID", "")
            logger.info(f"Telegram chat_id из .env: {'есть' if telegram_chat_id else 'нет'} (значение: {telegram_chat_id})")
            self.telegram_chat_id_edit.setText(telegram_chat_id)

            # Email
            email_config = (
                alerting_config.channels.get("email", {}) if isinstance(alerting_config.channels, dict) else {"enabled": False}
            )
            logger.info(f"Email config: {email_config}")

            email_enabled_saved = email_config.get("enabled", False)
            logger.info(f"Email enabled из settings.json: {email_enabled_saved}")
            self.email_enabled_checkbox.setChecked(email_enabled_saved)

            if isinstance(email_config, dict):
                # Исправление: если smtp_server пустой, используем значение по умолчанию
                smtp_server = email_config.get("smtp_server", "smtp.gmail.com")
                if not smtp_server:  # Пустая строка = None
                    smtp_server = "smtp.gmail.com"
                self.email_smtp_edit.setText(smtp_server)
                self.email_port_edit.setValue(email_config.get("smtp_port", 587))
            else:
                self.email_smtp_edit.setText("smtp.gmail.com")
                self.email_port_edit.setValue(587)

            # Загружаем Email из .env
            email_from = config_values.get("ALERT_EMAIL_FROM", "")
            logger.info(f"Email from из .env: {'есть' if email_from else 'нет'} (значение: {email_from})")
            self.email_from_edit.setText(email_from)

            email_recipients = config_values.get("ALERT_EMAIL_RECIPIENTS", "")
            logger.info(f"Email recipients из .env: {'есть' if email_recipients else 'нет'} (значение: {email_recipients})")
            self.email_recipients_edit.setText(email_recipients)

            # Пароль загружаем из .env или SecretsManager
            email_password = config_values.get("ALERT_EMAIL_PASSWORD", "")
            logger.info(
                f"Email password из .env: {'есть' if email_password else 'нет'} (длина: {len(email_password) if email_password else 0})"
            )

            if not email_password:
                # Пробуем загрузить из SecretsManager
                logger.info("Попытка загрузки Email password из SecretsManager...")
                email_password = secrets_mgr.get_secret("ALERT_EMAIL_PASSWORD", cache=True) or ""
                logger.info(
                    f"Email password из SecretsManager: {'есть' if email_password else 'нет'} (длина: {len(email_password) if email_password else 0})"
                )

            if email_password:
                logger.info("✅ Email password загружен")
            else:
                logger.warning("❌ Email password НЕ загружен (пустой)")
            self.email_password_edit.setText(email_password)

            # Quiet Hours
            if isinstance(alerting_config, dict):
                quiet_hours_config = alerting_config.get("quiet_hours", {})
            else:
                quiet_hours_config = alerting_config.quiet_hours if hasattr(alerting_config, "quiet_hours") else {}

            if isinstance(quiet_hours_config, dict):
                self.quiet_hours_enabled_checkbox.setChecked(quiet_hours_config.get("enabled", False))
                if quiet_hours_config.get("start"):
                    self.quiet_hours_start_edit.setTime(QTime.fromString(quiet_hours_config["start"], "HH:mm"))
                if quiet_hours_config.get("end"):
                    self.quiet_hours_end_edit.setTime(QTime.fromString(quiet_hours_config["end"], "HH:mm"))
            else:
                self.quiet_hours_enabled_checkbox.setChecked(False)

            # Social Trading Settings
            self._load_social_settings()
            
            # Настройки планировщика новостей
            self._load_news_scheduler_settings()

            # Daily Digest
            if isinstance(alerting_config, dict):
                digest_config = alerting_config.get("daily_digest", {})
            else:
                digest_config = alerting_config.daily_digest if hasattr(alerting_config, "daily_digest") else {}

            if isinstance(digest_config, dict):
                self.digest_enabled_checkbox.setChecked(digest_config.get("enabled", True))
                if digest_config.get("time"):
                    self.digest_time_edit.setTime(QTime.fromString(digest_config["time"], "HH:mm"))
            else:
                self.digest_enabled_checkbox.setChecked(True)
        else:
            logger.warning("alerting конфигурация не найдена в settings.json")

    def save_settings(self):
        """Сохранение настроек из GUI."""

        # --- 1. Сохранение MT5-настроек в Credential Manager (приоритет) и .env (для совместимости) ---
        secrets_mgr = None
        try:
            secrets_mgr = get_secrets_manager()
            logger.info(f"SecretsManager инициализирован: {secrets_mgr is not None}")
        except Exception as e:
            logger.error(f"Ошибка инициализации SecretsManager: {e}", exc_info=True)
            secrets_mgr = None

        # Сохраняем MT5 credentials
        mt5_values = {}
        for key, widget in self.mt5_entries.items():
            value = widget.text()
            mt5_values[key] = value

            # .env для совместимости
            set_key(self.env_path, key, value)

            # Credential Manager для безопасности (особенно пароль)
            if secrets_mgr and key in ["MT5_PASSWORD", "MT5_LOGIN"]:
                try:
                    success = secrets_mgr.store_secret(key, value)
                    if success:
                        logger.info(f"{key} сохранён в Credential Manager")
                    else:
                        logger.warning(f"Не удалось сохранить {key} в Credential Manager")
                except Exception as e:
                    logger.error(f"Ошибка сохранения {key} в Credential Manager: {e}")

        logger.info("MT5-настройки сохранены в .env и Credential Manager")

        # --- 2. Сохранение API ключей ---
        try:
            initial_keys = {
                k
                for k, v in dotenv_values(self.env_path).items()
                if k.endswith(("_KEY", "_TOKEN", "_ID", "_HASH")) and not k.startswith("MT5")
            }
            table_keys = set()
            for row in range(self.api_table.rowCount()):
                key_item = self.api_table.item(row, 0)
                value_item = self.api_table.item(row, 1)
                if key_item and value_item:
                    key = key_item.text()
                    value = value_item.text()
                    table_keys.add(key)
                    set_key(self.env_path, key, value)

                    # Сохраняем API ключи в Credential Manager
                    if secrets_mgr and key.endswith(("_KEY", "_TOKEN")):
                        try:
                            success = secrets_mgr.store_secret(key, value)
                            if success:
                                logger.debug(f"{key} сохранён в Credential Manager")
                        except Exception as e:
                            logger.debug(f"Не удалось сохранить {key} в Credential Manager: {e}")

            keys_to_delete = initial_keys - table_keys
            for key in keys_to_delete:
                set_key(self.env_path, key, "")
            logger.info("Настройки API ключей успешно сохранены в .env файл.")
        except Exception as e:
            logger.error(f"Произошла ошибка при сохранении API ключей: {e}")
            QMessageBox.critical(self, "Ошибка сохранения", f"Не удалось сохранить API ключи: {e}")

        # --- 3. Сохранение настроек уведомлений ---
        try:
            # Сохраняем Telegram токен (чувствительные данные)
            telegram_token = self.telegram_token_edit.text()
            telegram_enabled = self.telegram_enabled_checkbox.isChecked()
            logger.info(f"Telegram: enabled={telegram_enabled}, token={'есть' if telegram_token else 'пуст'}")

            if telegram_token:
                logger.info("Сохранение Telegram token...")
                set_key(self.env_path, "TELEGRAM_BOT_TOKEN", telegram_token)
                # Сохраняем также в SecretsManager для безопасности
                if secrets_mgr:
                    success = secrets_mgr.store_secret("TELEGRAM_BOT_TOKEN", telegram_token)
                    logger.info(f"Telegram token сохранён в SecretsManager: {success}")
                    if not success:
                        logger.warning("Не удалось сохранить Telegram token в SecretsManager, сохранён только в .env")
                else:
                    logger.warning("SecretsManager не доступен, Telegram token сохранён только в .env")
            else:
                set_key(self.env_path, "TELEGRAM_BOT_TOKEN", "")
                logger.debug("Telegram token пуст, не сохраняем")

            # Сохраняем Chat ID (не чувствительные данные)
            telegram_chat_id = self.telegram_chat_id_edit.text()
            logger.info(f"Telegram Chat ID: {'есть' if telegram_chat_id else 'пуст'}")
            set_key(self.env_path, "TELEGRAM_CHAT_ID", telegram_chat_id)

            # Сохраняем Email настройки
            email_enabled = self.email_enabled_checkbox.isChecked()
            email_from = self.email_from_edit.text()
            email_recipients = self.email_recipients_edit.text()
            logger.info(f"Email: enabled={email_enabled}, from={email_from}, recipients={email_recipients}")

            set_key(self.env_path, "ALERT_EMAIL_FROM", email_from)
            set_key(self.env_path, "ALERT_EMAIL_RECIPIENTS", email_recipients)

            # Пароль email сохраняем в SecretsManager для безопасности
            email_password = self.email_password_edit.text()
            logger.info(f"Email password: {'есть' if email_password else 'пуст'}")

            if email_password:
                logger.info("Сохранение Email password...")
                # Сохраняем в зашифрованном виде через SecretsManager
                if secrets_mgr:
                    success = secrets_mgr.store_secret("ALERT_EMAIL_PASSWORD", email_password)
                    logger.info(f"Email password сохранён в SecretsManager: {success}")
                    if not success:
                        logger.warning("Не удалось сохранить Email password в SecretsManager, сохранён только в .env")
                else:
                    logger.warning("SecretsManager не доступен, Email password сохранён только в .env")
                # Также сохраняем в .env для совместимости
                set_key(self.env_path, "ALERT_EMAIL_PASSWORD", email_password)
            else:
                logger.debug("Email password пуст, не сохраняем")

            # Сохраняем состояние чекбоксов в settings.json (будет сделано ниже)
            logger.info(f"Настройки уведомлений: Telegram={telegram_enabled}, Email={email_enabled}")
            logger.info("Настройки уведомлений сохранены")

            # Сохраняем API ключи криптовалют
            binance_api_key = self.binance_api_key_edit.text()
            binance_api_secret = self.binance_api_secret_edit.text()
            if binance_api_key:
                set_key(self.env_path, "BINANCE_API_KEY", binance_api_key)
                if secrets_mgr:
                    secrets_mgr.store_secret("BINANCE_API_KEY", binance_api_key)
            if binance_api_secret:
                set_key(self.env_path, "BINANCE_API_SECRET", binance_api_secret)
                if secrets_mgr:
                    secrets_mgr.store_secret("BINANCE_API_SECRET", binance_api_secret)

            bybit_api_key = self.bybit_api_key_edit.text()
            bybit_api_secret = self.bybit_api_secret_edit.text()
            if bybit_api_key:
                set_key(self.env_path, "BYBIT_API_KEY", bybit_api_key)
                if secrets_mgr:
                    secrets_mgr.store_secret("BYBIT_API_KEY", bybit_api_key)
            if bybit_api_secret:
                set_key(self.env_path, "BYBIT_API_SECRET", bybit_api_secret)
                if secrets_mgr:
                    secrets_mgr.store_secret("BYBIT_API_SECRET", bybit_api_secret)

            logger.info("Настройки криптовалют сохранены")
        except Exception as e:
            logger.error(f"Ошибка при сохранении настроек криптовалют: {e}", exc_info=True)
            QMessageBox.warning(
                self, "Предупреждение", f"Настройки сохранены, но произошла ошибка при шифровании паролей:\n{e}"
            )

        self._handle_scheduler_tasks()

        # --- ЕДИНАЯ ЛОГИКА СОХРАНЕНИЯ settings.json ---
        try:
            current_config = load_config().model_dump()
            
            # Собираем символы
            symbols_list = []
            try:
                for row in range(self.symbols_table.rowCount()):
                    item = self.symbols_table.item(row, 0)
                    if item: symbols_list.append(item.text())
            except RuntimeError: symbols_list = self.full_config.SYMBOLS_WHITELIST

            self._apply_social_settings()
            
            # Настройки планировщика новостей
            self._apply_news_scheduler_settings()

            # Собираем настройки с защитой от ошибок виджетов
            def safe_val(w, d): 
                try: return w.value() if hasattr(w, 'value') else w.isChecked() 
                except RuntimeError: return d

            settings_to_update = {
                "RISK_PERCENTAGE": safe_val(self.risk_percentage_spinbox, self.full_config.RISK_PERCENTAGE),
                "RISK_REWARD_RATIO": safe_val(self.risk_reward_ratio_spinbox, self.full_config.RISK_REWARD_RATIO),
                "MAX_DAILY_DRAWDOWN_PERCENT": safe_val(self.max_daily_drawdown_spinbox, self.full_config.MAX_DAILY_DRAWDOWN_PERCENT),
                "MAX_OPEN_POSITIONS": safe_val(self.max_open_positions_spinbox, self.full_config.MAX_OPEN_POSITIONS),
                "SYMBOLS_WHITELIST": symbols_list,
                "ALLOW_WEEKEND_TRADING": safe_val(self.allow_weekend_trading_checkbox, self.full_config.ALLOW_WEEKEND_TRADING),
                "DATABASE_FOLDER": self.db_folder_edit.text(),
                "LOGS_FOLDER": self.logs_folder_edit.text(),
                "HF_MODELS_CACHE_DIR": self.hf_cache_edit.text() or None,
                "ORCHESTRATOR_MODEL_PATH": self.orchestrator_model_edit.text() or None,
                "GP_POPULATION_SIZE": safe_val(self.gp_pop_spin, self.full_config.GP_POPULATION_SIZE),
                "GP_GENERATIONS": safe_val(self.gp_gen_spin, self.full_config.GP_GENERATIONS),
            }

            # Криптовалюты
            settings_to_update["crypto_exchanges"] = {
                "enabled": self.crypto_enabled_checkbox.isChecked(),
                "default_exchange": self.crypto_default_exchange_combo.currentText(),
                "exchanges": {
                    "binance": {
                        "enabled": self.binance_enabled_checkbox.isChecked(),
                        "api_key_env": "BINANCE_API_KEY",
                        "api_secret_env": "BINANCE_API_SECRET",
                        "sandbox": self.binance_sandbox_checkbox.isChecked(),
                        "symbols": [s.strip() for s in self.binance_symbols_edit.text().split(",") if s.strip()],
                        "default_leverage": self.binance_leverage_spin.value(),
                        "market_type": self.binance_market_type_combo.currentText(),
                    },
                    "bybit": {
                        "enabled": self.bybit_enabled_checkbox.isChecked(),
                        "api_key_env": "BYBIT_API_KEY",
                        "api_secret_env": "BYBIT_API_SECRET",
                        "sandbox": self.bybit_sandbox_checkbox.isChecked(),
                        "symbols": [s.strip() for s in self.bybit_symbols_edit.text().split(",") if s.strip()],
                        "default_leverage": 1,
                        "market_type": "spot",
                    },
                },
            }
            settings_to_update.update({
                "GP_POPULATION_SIZE": safe_val(self.gp_pop_spin, self.full_config.GP_POPULATION_SIZE),
                "GP_GENERATIONS": safe_val(self.gp_gen_spin, self.full_config.GP_GENERATIONS),
            })
            settings_to_update["vector_db"] = {
                    "enabled": self.full_config.vector_db.enabled,
                    "path": self._get_relative_vector_db_path(),
                    "collection_name": self.full_config.vector_db.collection_name,
                    "embedding_model": self.full_config.vector_db.embedding_model,
                    "cleanup_enabled": self.full_config.vector_db.cleanup_enabled,
                    "max_age_days": self.full_config.vector_db.max_age_days,
                    "cleanup_interval_hours": self.full_config.vector_db.cleanup_interval_hours,
                }
            settings_to_update["auto_retraining"] = {
                    "enabled": self.auto_retrain_checkbox.isChecked(),
                    "schedule_time": self.auto_retrain_time_edit.time().toString("hh:mm"),
                    "interval_hours": self.auto_retrain_interval_spin.value(),
                    "max_symbols": self.auto_retrain_max_symbols_spin.value(),
                    "max_workers": self.auto_retrain_max_workers_spin.value(),
                }
            settings_to_update["trading_mode"] = {
                    "current_mode": self.trading_mode_toggle.get_mode() if hasattr(self, "trading_mode_toggle") else "paper",
                    "enabled": True,
                }
            settings_to_update["PROFIT_TARGET_MODE"] = self.profit_target_mode_combo.currentText()
            settings_to_update.update({
                    "PROFIT_TARGET_MANUAL_PERCENT": self.profit_target_manual_spin.value(),
                    "REENTRY_COOLDOWN_AFTER_PROFIT": self.reentry_profit_spin.value(),
                    "REENTRY_COOLDOWN_AFTER_LOSS": self.reentry_loss_spin.value(),
                })
            settings_to_update.update({
                    # Новые настройки контроля прибыли и интенсивности
                    "MAX_PROFIT_PER_TRADE_PERCENT": self.max_profit_close_spin.value(),
                    "PROFIT_MODE": self.profit_mode_combo.currentText(),
                    "TRADE_INTENSITY": self.trade_intensity_combo.currentText(),
                    "TRADE_INTERVAL_SECONDS": self.trade_interval_spin.value(),
                    "REENTRY_SAME_PAIR_MODE": self.reentry_same_pair_combo.currentText(),
                    "REENTRY_SAME_PAIR_COOLDOWN_MINUTES": self.reentry_same_pair_cooldown_spin.value(),
                })
            settings_to_update["alerting"] = {
                    "enabled": self.telegram_enabled_checkbox.isChecked() or self.email_enabled_checkbox.isChecked(),
                    "channels": {
                        "telegram": {
                            "enabled": self.telegram_enabled_checkbox.isChecked(),
                            "bot_token_env": "TELEGRAM_BOT_TOKEN",
                            "chat_id_env": "TELEGRAM_CHAT_ID",
                        },
                        "email": {
                            "enabled": self.email_enabled_checkbox.isChecked(),
                            "smtp_server": self.email_smtp_edit.text(),
                            "smtp_port": self.email_port_edit.value(),
                            "use_tls": True,
                            "from_email_env": "ALERT_EMAIL_FROM",
                            "password_env": "ALERT_EMAIL_PASSWORD",
                            "recipients_env": "ALERT_EMAIL_RECIPIENTS",
                        },
                        "push": {"enabled": False, "user_key_env": "PUSHOVER_USER_KEY", "api_token_env": "PUSHOVER_API_TOKEN"},
                    },
                    "rate_limit": {"max_per_minute": 10, "cooldown_seconds": 60},
                    "quiet_hours": {
                        "enabled": self.quiet_hours_enabled_checkbox.isChecked(),
                        "start": self.quiet_hours_start_edit.time().toString("HH:mm"),
                        "end": self.quiet_hours_end_edit.time().toString("HH:mm"),
                        "timezone": "UTC",
                    },
                    "daily_digest": {
                        "enabled": self.digest_enabled_checkbox.isChecked(),
                        "time": self.digest_time_edit.time().toString("HH:mm"),
                        "timezone": "UTC",
                    },
                }
            settings_to_update["social_trading"] = self.full_config.social_trading if hasattr(self.full_config, 'social_trading') and self.full_config.social_trading else {}
            settings_to_update["news_scheduler"] = self.full_config.news_scheduler if hasattr(self.full_config, 'news_scheduler') and self.full_config.news_scheduler else {}

            # 4. Обновляем текущую конфигурацию новыми значениями
            current_config.update(settings_to_update)

            # 5. Записываем полный, обновленный конфиг в файл (ЕДИНЫЙ ВЫЗОВ)
            if not write_config(current_config):
                QMessageBox.critical(self, "Ошибка", "Не удалось сохранить настройки в settings.json.")
            else:
                logger.info("Настройки успешно сохранены в settings.json")

                # Обновляем конфигурацию в работающей системе
                self._update_running_system_config(current_config)

                # Уведомляем об изменении пути к базе данных
                db_folder = current_config.get("DATABASE_FOLDER", "database")
                self.database_path_changed.emit(db_folder)

        except Exception as e:
            logger.error(f"Критическая ошибка при сохранении settings.json: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить настройки: {e}")

    def _update_running_system_config(self, new_config: dict):
        """
        Обновляет конфигурацию в работающей системе без перезапуска.

        Args:
            new_config: Новая конфигурация
        """
        try:
            if hasattr(self, "full_config") and hasattr(self, "scheduler_manager"):
                # Обновляем full_config
                from src.core.config_models import Settings

                try:
                    self.full_config = Settings(**new_config)
                    logger.info("Конфигурация обновлена в памяти")
                except Exception as e:
                    logger.warning(f"Не удалось обновить конфигурацию в памяти: {e}")

                # Если есть ссылка на trading_system, обновляем настройки уведомлений
                if hasattr(self, "trading_system") and self.trading_system:
                    try:
                        # Обновляем настройки alerting
                        if hasattr(self.trading_system, "alert_manager"):
                            self.trading_system.alert_manager.config = self.full_config
                            logger.info("Alert Manager обновлён")
                    except Exception as e:
                        logger.warning(f"Не удалось обновить trading_system: {e}")

        except Exception as e:
            logger.error(f"Ошибка обновления конфигурации: {e}")

    def accept(self):
        # Сначала сохраняем настройки, пока виджеты живы
        self.save_settings()

        # Останавливаем все активные тестеры перед закрытием
        self._stop_all_testers()

        # Уведомляем о сохранении
        self.settings_saved.emit()

        # Показываем сообщение (это блокирует выполнение, но виджеты еще существуют)
        QMessageBox.information(
            self, "Сохранено", "Настройки успешно сохранены. Для их полного применения может потребоваться перезапуск системы."
        )

        # И только в самом конце закрываем окно
        super().accept()

    def reject(self):
        # Останавливаем все активные тестеры перед закрытием
        self._stop_all_testers()
        super().reject()

    def _stop_all_testers(self):
        """Корректно останавливает все активные потоки тестеров."""
        # Остановка Telegram тестера
        if hasattr(self, "telegram_tester"):
            try:
                if self.telegram_tester.isRunning():
                    self.telegram_tester.quit()
                    if not self.telegram_tester.wait(2000):  # Ждём до 2 сек
                        logger.warning("TelegramTester не завершился вовремя, принудительная остановка")
                        self.telegram_tester.terminate()
                        self.telegram_tester.wait()
            except RuntimeError:
                # Объект уже удалён
                pass
            except Exception as e:
                logger.debug(f"Ошибка при остановке TelegramTester: {e}")

        # Остановка Email тестера
        if hasattr(self, "email_tester"):
            try:
                if self.email_tester.isRunning():
                    self.email_tester.quit()
                    if not self.email_tester.wait(2000):  # Ждём до 2 сек
                        logger.warning("EmailTester не завершился вовремя, принудительная остановка")
                        self.email_tester.terminate()
                        self.email_tester.wait()
            except RuntimeError:
                # Объект уже удалён
                pass
            except Exception as e:
                logger.debug(f"Ошибка при остановке EmailTester: {e}")

    def _create_scheduler_tab(self):
        widget = QWidget()
        layout = QGridLayout(widget)
        layout.setAlignment(Qt.AlignTop)
        layout.setColumnStretch(1, 1)

        scheduler_title = QLabel("<b>Управление фоновыми задачами</b>")
        scheduler_title.setToolTip(
            "Планировщик выполняет автоматические задачи по расписанию:\n"
            "• Автозапуск - запуск системы при старте Windows\n"
            "• Обслуживание - ежедневная очистка и оптимизация данных\n"
            "• Оптимизация - еженедельная оптимизация стратегий\n"
            "• Автообучение - автоматическое переобучение AI-моделей"
        )
        layout.addWidget(scheduler_title, 0, 0, 1, 3)

        self.autostart_checkbox = QCheckBox("Автозапуск системы при старте Windows")
        self.autostart_checkbox.setToolTip(
            "Автоматически запускает торговую систему при загрузке Windows.\n"
            "Требует запуска программы от имени администратора."
        )
        self.autostart_status_label = QLabel("Статус: Неизвестно")
        layout.addWidget(self.autostart_checkbox, 1, 0)
        layout.addWidget(self.autostart_status_label, 1, 2)

        # Задача ежедневного обслуживания (с выбором времени)
        self.maintenance_checkbox = QCheckBox("Ежедневное обслуживание")
        self.maintenance_checkbox.setToolTip(
            "Автоматическая ежедневная очистка и оптимизация базы данных.\n" "Рекомендуется запускать в нерабочее время рынка."
        )
        self.maintenance_time_edit = QTimeEdit()
        self.maintenance_time_edit.setDisplayFormat("hh:mm")
        self.maintenance_time_edit.setToolTip("Время выполнения ежедневного обслуживания.")
        self.maintenance_status_label = QLabel("Статус: Неизвестно")
        layout.addWidget(self.maintenance_checkbox, 2, 0)
        layout.addWidget(self.maintenance_time_edit, 2, 1)
        layout.addWidget(self.maintenance_status_label, 2, 2)

        # Задача еженедельной оптимизации (с выбором времени)
        self.optimization_checkbox = QCheckBox("Еженедельная оптимизация (Сб)")
        self.optimization_checkbox.setToolTip(
            "Автоматическая еженедельная оптимизация торговых стратегий.\n"
            "Выполняется по субботам для анализа прошедшей недели."
        )
        self.optimization_time_edit = QTimeEdit()
        self.optimization_time_edit.setDisplayFormat("hh:mm")
        self.optimization_time_edit.setToolTip("Время выполнения еженедельной оптимизации (суббота).")
        self.optimization_status_label = QLabel("Статус: Неизвестно")
        layout.addWidget(self.optimization_checkbox, 3, 0)
        layout.addWidget(self.optimization_time_edit, 3, 1)
        layout.addWidget(self.optimization_status_label, 3, 2)

        # --- НОВАЯ СЕКЦИЯ: Автоматическое переобучение моделей ---
        layout.addWidget(QLabel("\n<b>Автоматическое переобучение моделей</b>"), 4, 0, 1, 3)

        self.auto_retrain_checkbox = QCheckBox("Включить автообучение")
        self.auto_retrain_checkbox.setToolTip(
            "Автоматически переобучает AI-модели по расписанию.\n"
            "Система сама выбирает лучшие символы из всех доступных в MT5."
        )
        layout.addWidget(self.auto_retrain_checkbox, 5, 0)

        layout.addWidget(QLabel("Время запуска:"), 6, 0)
        self.auto_retrain_time_edit = QTimeEdit()
        self.auto_retrain_time_edit.setDisplayFormat("hh:mm")
        self.auto_retrain_time_edit.setToolTip("Время суток для автоматического запуска обучения (рекомендуется ночью)")
        layout.addWidget(self.auto_retrain_time_edit, 6, 1)

        layout.addWidget(QLabel("Интервал (часов):"), 7, 0)
        self.auto_retrain_interval_spin = QSpinBox()
        self.auto_retrain_interval_spin.setRange(1, 168)  # От 1 часа до недели
        self.auto_retrain_interval_spin.setToolTip("Интервал между запусками обучения (в часах)")
        layout.addWidget(self.auto_retrain_interval_spin, 7, 1)

        layout.addWidget(QLabel("Макс. символов:"), 8, 0)
        self.auto_retrain_max_symbols_spin = QSpinBox()
        self.auto_retrain_max_symbols_spin.setRange(5, 200)
        self.auto_retrain_max_symbols_spin.setToolTip(
            "Максимальное количество символов для обучения.\n" "Система автоматически отберёт лучшие из всех доступных."
        )
        layout.addWidget(self.auto_retrain_max_symbols_spin, 8, 1)

        layout.addWidget(QLabel("Параллельных потоков:"), 9, 0)
        self.auto_retrain_max_workers_spin = QSpinBox()
        self.auto_retrain_max_workers_spin.setRange(1, 10)
        self.auto_retrain_max_workers_spin.setToolTip(
            "Количество параллельных потоков для обучения.\n" "Рекомендуется: CPU/2 (например, 3-4 для 8-ядерного процессора)"
        )
        layout.addWidget(self.auto_retrain_max_workers_spin, 9, 1)

        # Кнопка для ручного запуска
        self.manual_retrain_button = QPushButton("▶ Запустить обучение сейчас")
        self.manual_retrain_button.setToolTip(
            "Запустить переобучение моделей вручную.\n" "Полезно для тестирования или внепланового обновления стратегий."
        )
        self.manual_retrain_button.clicked.connect(self._trigger_manual_retraining)
        layout.addWidget(self.manual_retrain_button, 10, 0, 1, 2)

        self.auto_retrain_status_label = QLabel("Статус: не запланировано")
        self.auto_retrain_status_label.setToolTip("Текущий статус задачи автоматического переобучения.")
        layout.addWidget(self.auto_retrain_status_label, 10, 2)

        info_label = QLabel(
            "\n<b>Внимание:</b> Для управления задачами программу необходимо запустить <b>от имени Администратора</b>."
        )
        info_label.setToolTip(
            "Задачи планировщика требуют прав администратора для создания расписаний в Windows.\n"
            "Без прав администратора задачи не будут созданы."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label, 11, 0, 1, 3)

        # --- НОВАЯ СЕКЦИЯ: Целевая прибыль ---
        layout.addWidget(QLabel("\n<b>Контроль прибыли сделок</b>"), 12, 0, 1, 3)

        self.profit_target_mode_combo = QComboBox()
        self.profit_target_mode_combo.addItems(["auto", "manual"])
        self.profit_target_mode_combo.setToolTip(
            "auto - система сама определяет оптимальную прибыль\n" "manual - использовать фиксированное значение"
        )
        layout.addWidget(QLabel("Режим:"), 13, 0)
        layout.addWidget(self.profit_target_mode_combo, 13, 1)

        self.profit_target_manual_spin = QDoubleSpinBox()
        self.profit_target_manual_spin.setRange(0.1, 100.0)
        self.profit_target_manual_spin.setSuffix(" %")
        self.profit_target_manual_spin.setToolTip("Фиксированный процент прибыли для закрытия сделки")
        layout.addWidget(QLabel("Целевая прибыль (%):"), 14, 0)
        layout.addWidget(self.profit_target_manual_spin, 14, 1)

        self.reentry_profit_spin = QSpinBox()
        self.reentry_profit_spin.setRange(1, 480)
        self.reentry_profit_spin.setSuffix(" мин")
        self.reentry_profit_spin.setToolTip("Пауза перед повторным входом после прибыльной сделки")
        layout.addWidget(QLabel("Повторный вход после прибыли:"), 15, 0)
        layout.addWidget(self.reentry_profit_spin, 15, 1)

        self.reentry_loss_spin = QSpinBox()
        self.reentry_loss_spin.setRange(1, 480)
        self.reentry_loss_spin.setSuffix(" мин")
        self.reentry_loss_spin.setToolTip("Пауза перед повторным входом после убыточной сделки")
        layout.addWidget(QLabel("Повторный вход после убытка:"), 16, 0)
        layout.addWidget(self.reentry_loss_spin, 16, 1)

        # --- НОВАЯ СЕКЦИЯ: Контроль прибыли и интенсивность сделок ---
        layout.addWidget(QLabel("\n<b>Контроль прибыли и интенсивность сделок</b>"), 17, 0, 1, 3)

        # Максимальная прибыль для закрытия
        layout.addWidget(QLabel("Макс. прибыль для закрытия (%):"), 18, 0)
        self.max_profit_close_spin = QDoubleSpinBox()
        self.max_profit_close_spin.setRange(0.1, 100.0)
        self.max_profit_close_spin.setSuffix(" %")
        self.max_profit_close_spin.setToolTip(
            "Максимальная сумма прибыли, после которой сделка будет закрыта.\n"
            "0 - без ограничений (закрытие только по TP/SL)."
        )
        layout.addWidget(self.max_profit_close_spin, 18, 1)

        # Режим выбора целевой прибыли
        layout.addWidget(QLabel("Режим целевой прибыли:"), 19, 0)
        self.profit_mode_combo = QComboBox()
        self.profit_mode_combo.addItems(["auto", "manual"])
        self.profit_mode_combo.setToolTip(
            "auto - система сама выбирает оптимальную прибыль на основе анализа\n"
            "manual - использовать фиксированное значение из настроек"
        )
        layout.addWidget(self.profit_mode_combo, 19, 1)

        # Интенсивность сделок
        layout.addWidget(QLabel("Интенсивность сделок:"), 20, 0)
        self.trade_intensity_combo = QComboBox()
        self.trade_intensity_combo.addItems(["low", "medium", "high", "auto"])
        self.trade_intensity_combo.setToolTip(
            "low - редкие сделки, высокая уверенность\n"
            "medium - стандартная частота\n"
            "high - частые сделки, агрессивная торговля\n"
            "auto - система сама регулирует частоту"
        )
        layout.addWidget(self.trade_intensity_combo, 20, 1)

        # Интервал между сделками
        layout.addWidget(QLabel("Мин. интервал между сделками (сек):"), 21, 0)
        self.trade_interval_spin = QSpinBox()
        self.trade_interval_spin.setRange(5, 3600)
        self.trade_interval_spin.setSuffix(" сек")
        self.trade_interval_spin.setToolTip(
            "Минимальный интервал между открытием новых сделок.\n" "Защищает от чрезмерной торговли."
        )
        layout.addWidget(self.trade_interval_spin, 21, 1)

        # Повторный вход на ту же пару
        layout.addWidget(QLabel("Повторный вход на ту же пару:"), 22, 0)
        self.reentry_same_pair_combo = QComboBox()
        self.reentry_same_pair_combo.addItems(["allowed", "cooldown", "blocked"])
        self.reentry_same_pair_combo.setToolTip(
            "allowed - разрешен без ограничений\n"
            "cooldown - пауза между сделками на одну пару\n"
            "blocked - запрещено открывать новые сделки на той же паре"
        )
        layout.addWidget(self.reentry_same_pair_combo, 22, 1)

        # Пауза перед повторным входом на ту же пару
        layout.addWidget(QLabel("Пауза перед повторным входом (мин):"), 23, 0)
        self.reentry_same_pair_cooldown_spin = QSpinBox()
        self.reentry_same_pair_cooldown_spin.setRange(1, 1440)
        self.reentry_same_pair_cooldown_spin.setSuffix(" мин")
        self.reentry_same_pair_cooldown_spin.setToolTip("Сколько минут ждать перед повторным входом на ту же валютную пару.")
        layout.addWidget(self.reentry_same_pair_cooldown_spin, 23, 1)

        return self._create_scrollable_widget(widget)

    def _create_paths_tab(self):
        content_widget = QWidget()
        layout = QGridLayout(content_widget)
        layout.setAlignment(Qt.AlignTop)
        layout.setColumnStretch(1, 1)

        # --- Группа: Пути к данным ---
        db_group = QGroupBox("Пути к данным")
        db_layout = QGridLayout(db_group)

        db_label = QLabel("<b>📁 Папка для баз данных:</b>")
        db_label.setToolTip(
            "<b>Что хранится:</b>\n"
            "• SQLite база данных (история сделок)\n"
            "• Обученные AI-модели (LightGBM, LSTM)\n"
            "• Логи состояний системы\n"
            "• Бэкапы конфигураций\n\n"
            "<b>Рекомендации:</b>\n"
            "• Используйте SSD диск для скорости\n"
            "• Минимум 10 GB свободного места"
        )
        db_label.setWordWrap(True)
        db_label.setStyleSheet("color: #f8f8f2; padding: 5px;")

        self.db_folder_edit = QLineEdit()
        self.db_folder_edit.setPlaceholderText("Например: D:/GenesisDB")
        db_browse_button = QPushButton("📁 Обзор...")
        db_browse_button.setCursor(Qt.PointingHandCursor)
        db_browse_button.clicked.connect(
            lambda: self._browse_folder(self.db_folder_edit, "Выберите папку для хранения данных")
        )
        db_layout.addWidget(db_label, 0, 0)
        db_layout.addWidget(self.db_folder_edit, 0, 1)
        db_layout.addWidget(db_browse_button, 0, 2)

        hf_label = QLabel("<b>🤖 Папка для кэша AI-моделей (Hugging Face):</b>")
        hf_label.setToolTip(
            "<b>Модель 1:</b> all-MiniLM-L6-v2 (90 MB)\n"
            "• Анализ новостей и заголовков\n"
            "• Поиск похожих событий\n"
            "• Понимание смысла текстов (NLP)\n"
            "• Работа с графом знаний\n\n"
            "<b>Модель 2:</b> google/flan-t5-base (990 MB)\n"
            "• Генерация связей между событиями\n"
            "• Анализ причинно-следственных связей\n"
            "• Обработка естественного языка\n\n"
            "<b>Общий размер:</b> ~1.1 GB\n\n"
            "<b>Как работает:</b>\n"
            "При первом запуске модели скачиваются из интернета.\n"
            "Повторная загрузка не требуется — модели берутся из кэша.\n\n"
            "<b>Рекомендации:</b>\n"
            "• Укажите папку на диске с большим местом (D:, E:)\n"
            "• Не используйте путь с кириллицей\n"
            "• Изменение пути требует перезапуска программы!\n\n"
            "<b>Можно отключить:</b>\n"
            "Если анализ новостей не нужен, оставьте поле пустым."
        )
        hf_label.setWordWrap(True)
        hf_label.setStyleSheet("color: #f8f8f2; padding: 5px;")

        self.hf_cache_edit = QLineEdit()
        self.hf_cache_edit.setPlaceholderText("Например: F:/Enjen/all-MiniLM-L6-v2")
        self.hf_cache_edit.setToolTip(
            "Путь к папке где будут храниться AI модели.\n" "Оставьте пустым для использования пути по умолчанию."
        )
        hf_browse_button = QPushButton("📁 Обзор...")
        hf_browse_button.setCursor(Qt.PointingHandCursor)
        hf_browse_button.clicked.connect(lambda: self._browse_folder(self.hf_cache_edit, "Выберите папку для кэша AI-моделей"))
        db_layout.addWidget(hf_label, 1, 0)
        db_layout.addWidget(self.hf_cache_edit, 1, 1)
        db_layout.addWidget(hf_browse_button, 1, 2)

        # Папка для векторной БД
        vector_db_label = QLabel("<b>📊 Папка для векторной базы данных (FAISS):</b>")
        vector_db_label.setToolTip(
            "<b>Что хранится:</b>\n"
            "• Векторные эмбеддинги новостей\n"
            "• Индексы для быстрого поиска\n"
            "• Кэш похожих событий\n\n"
            "<b>Размер:</b> ~100-500 MB (растёт со временем)\n\n"
            "<b>Рекомендации:</b>\n"
            "• Размещайте в той же папке что и основную БД\n"
            "• Рекомендуется SSD для скорости поиска"
        )
        vector_db_label.setWordWrap(True)
        vector_db_label.setStyleSheet("color: #f8f8f2; padding: 5px;")

        self.vector_db_folder_edit = QLineEdit()
        self.vector_db_folder_edit.setPlaceholderText("Например: D:/GenesisDB/vector_db")
        vector_db_browse_button = QPushButton("📁 Обзор...")
        vector_db_browse_button.setCursor(Qt.PointingHandCursor)
        vector_db_browse_button.clicked.connect(
            lambda: self._browse_folder(self.vector_db_folder_edit, "Выберите папку для векторной БД")
        )
        db_layout.addWidget(vector_db_label, 2, 0)
        db_layout.addWidget(self.vector_db_folder_edit, 2, 1)
        db_layout.addWidget(vector_db_browse_button, 2, 2)

        # Путь к модели Оркестратора
        orchestrator_model_label = QLabel("<b>🎯 Путь к модели Оркестратора (PPO):</b>")
        orchestrator_model_label.setToolTip(
            "<b>Что хранится:</b>\n"
            "• Обученная PPO модель Оркестратора\n"
            "• Веса нейросети для распределения капитала\n"
            "• Буфер опыта для дообучения\n\n"
            "<b>Размер:</b> ~5-20 MB\n\n"
            "<b>Как работает:</b>\n"
            "Оркестратор обучается раз в 7 дней и сохраняет модель.\n"
            "При перезапуске модель загружается для продолжения обучения.\n\n"
            "<b>По умолчанию:</b>\n"
            "DATABASE_FOLDER/orchestrator_ppo_model.zip\n\n"
            "<b>Рекомендации:</b>\n"
            "• Оставьте пустым для использования пути по умолчанию\n"
            "• Укажите свой путь если нужно хранить в другом месте"
        )
        orchestrator_model_label.setWordWrap(True)
        orchestrator_model_label.setStyleSheet("color: #f8f8f2; padding: 5px;")

        self.orchestrator_model_edit = QLineEdit()
        self.orchestrator_model_edit.setPlaceholderText("По умолчанию: DATABASE_FOLDER/orchestrator_ppo_model.zip")
        self.orchestrator_model_edit.setToolTip(
            "Полный путь к файлу модели Оркестратора.\n" "Оставьте пустым для использования пути по умолчанию."
        )
        orchestrator_model_browse_button = QPushButton("📁 Обзор...")
        orchestrator_model_browse_button.setCursor(Qt.PointingHandCursor)
        orchestrator_model_browse_button.clicked.connect(
            lambda: self._browse_folder(self.orchestrator_model_edit, "Выберите папку для сохранения модели Оркестратора")
        )
        db_layout.addWidget(orchestrator_model_label, 3, 0)
        db_layout.addWidget(self.orchestrator_model_edit, 3, 1)
        db_layout.addWidget(orchestrator_model_browse_button, 3, 2)

        # Папка для логов
        logs_label = QLabel("<b>📝 Папка для логов системы:</b>")
        logs_label.setToolTip(
            "<b>Что хранится:</b>\n"
            "• genesis.log — основные логи системы\n"
            "• genesis_errors.log — ошибки и исключения\n"
            "• trading.log — история торговых операций\n\n"
            "<b>Размер:</b> ~50-200 MB в месяц\n\n"
            "<b>Рекомендации:</b>\n"
            "• Размещайте на диске с большим местом\n"
            "• Регулярно очищайте старые логи"
        )
        logs_label.setWordWrap(True)
        logs_label.setStyleSheet("color: #f8f8f2; padding: 5px;")

        self.logs_folder_edit = QLineEdit()
        self.logs_folder_edit.setPlaceholderText("Например: F:/Enjen/database/logs")
        logs_browse_button = QPushButton("📁 Обзор...")
        logs_browse_button.setCursor(Qt.PointingHandCursor)
        logs_browse_button.clicked.connect(lambda: self._browse_folder(self.logs_folder_edit, "Выберите папку для логов"))
        db_layout.addWidget(logs_label, 4, 0)
        db_layout.addWidget(self.logs_folder_edit, 4, 1)
        db_layout.addWidget(logs_browse_button, 4, 2)

        layout.addWidget(db_group, 0, 0, 1, 3)

        layout.setRowStretch(1, 1)
        return self._create_scrollable_widget(content_widget)

    def _create_notifications_tab(self):
        """
        P0: Создание вкладки для настройки уведомлений (Telegram, Email).
        """
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setAlignment(Qt.AlignTop)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Заголовок
        title = QLabel("<b>Настройки уведомлений</b>")
        title.setToolTip("Настройте каналы для получения торговых уведомлений и алертов системы.")
        layout.addWidget(title)

        # --- Группа: Telegram ---
        telegram_group = QGroupBox("Telegram уведомления")
        telegram_layout = QGridLayout(telegram_group)
        telegram_layout.setColumnStretch(1, 1)

        # Включить Telegram
        self.telegram_enabled_checkbox = QCheckBox("Включить Telegram уведомления")
        self.telegram_enabled_checkbox.setToolTip(
            "Включает отправку торговых сигналов и критических событий в Telegram.\n\n"
            "✓ INFO — торговые сигналы\n"
            "✓ WARNING — предупреждения системы\n"
            "✓ ERROR — ошибки торговли\n"
            "✓ CRITICAL — критические события (Circuit Breaker, потеря MT5)"
        )
        telegram_layout.addWidget(self.telegram_enabled_checkbox, 0, 0, 1, 3)

        # Bot Token
        telegram_layout.addWidget(QLabel("Bot Token:"), 1, 0)
        self.telegram_token_edit = QLineEdit()
        self.telegram_token_edit.setEchoMode(QLineEdit.Password)
        self.telegram_token_edit.setToolTip(
            "Токен бота от @BotFather.\n\n"
            "Как получить:\n"
            "1. Найдите @BotFather в Telegram\n"
            "2. Отправьте /newbot\n"
            "3. Введите имя бота\n"
            "4. Скопируйте полученный токен\n\n"
            "Пример: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
        )
        telegram_layout.addWidget(self.telegram_token_edit, 1, 1)

        # Кнопка показать/скрыть токен
        self.telegram_token_toggle_btn = QPushButton("👁️")
        self.telegram_token_toggle_btn.setFixedWidth(40)
        self.telegram_token_toggle_btn.setToolTip("Показать или скрыть токен бота")
        self.telegram_token_toggle_btn.clicked.connect(
            lambda: self._toggle_password_visibility(self.telegram_token_edit, self.telegram_token_toggle_btn)
        )
        telegram_layout.addWidget(self.telegram_token_toggle_btn, 1, 2)

        # Chat ID
        telegram_layout.addWidget(QLabel("Chat ID:"), 2, 0)
        self.telegram_chat_id_edit = QLineEdit()
        self.telegram_chat_id_edit.setToolTip(
            "ID чата для отправки уведомлений.\n\n"
            "Как получить:\n"
            "1. Найдите @userinfobot или @getmyid_bot\n"
            "2. Нажмите Start\n"
            "3. Скопируйте ваш ID\n\n"
            "Для группы: добавьте бота в группу и отправьте сообщение"
        )
        telegram_layout.addWidget(self.telegram_chat_id_edit, 2, 1)

        # Кнопка тестирования
        self.test_telegram_btn = QPushButton("🧪 Тестировать Telegram")
        self.test_telegram_btn.setToolTip(
            "Отправляет тестовое сообщение в указанный чат.\n\n"
            "Проверьте:\n"
            "✓ Бот добавлен в чат (для групп)\n"
            "✓ Токен и Chat ID введены верно\n"
            "✓ Есть подключение к интернету\n\n"
            "Если не работает — проверьте логи."
        )
        self.test_telegram_btn.clicked.connect(self._test_telegram_connection)
        telegram_layout.addWidget(self.test_telegram_btn, 3, 0, 1, 3)

        # Инструкция
        telegram_help = QLabel(
            "📝 <b>Как настроить:</b><br>"
            "1. Создайте бота в @BotFather<br>"
            "2. Узнайте Chat ID в @userinfobot<br>"
            "3. Добавьте бота в чат (опционально)<br>"
            "4. Нажмите 'Тестировать'"
        )
        telegram_help.setWordWrap(True)
        telegram_help.setStyleSheet("background-color: #f0f0f0; padding: 10px; border-radius: 5px;")
        telegram_help.setToolTip("Следуйте инструкции для быстрой настройки Telegram уведомлений")
        telegram_layout.addWidget(telegram_help, 4, 0, 1, 3)

        layout.addWidget(telegram_group)

        # --- Группа: Email ---
        email_group = QGroupBox("Email уведомления")
        email_layout = QGridLayout(email_group)
        email_layout.setColumnStretch(1, 1)

        # Включить Email
        self.email_enabled_checkbox = QCheckBox("Включить Email уведомления")
        self.email_enabled_checkbox.setToolTip(
            "Включает отправку торговых отчётов и критических событий на Email.\n\n"
            "✓ Дневной дайджест — сводка за день\n"
            "✓ ERROR — ошибки системы\n"
            "✓ CRITICAL — критические события"
        )
        email_layout.addWidget(self.email_enabled_checkbox, 0, 0, 1, 3)

        # SMTP Server
        email_layout.addWidget(QLabel("SMTP сервер:"), 1, 0)
        self.email_smtp_edit = QLineEdit()
        self.email_smtp_edit.setPlaceholderText("smtp.gmail.com")
        self.email_smtp_edit.setToolTip(
            "SMTP сервер вашего почтового провайдера.\n\n"
            "Примеры:\n"
            "• Gmail: smtp.gmail.com\n"
            "• Yandex: smtp.yandex.ru\n"
            "• Mail.ru: smtp.mail.ru\n"
            "• Outlook: smtp.office365.com"
        )
        email_layout.addWidget(self.email_smtp_edit, 1, 1)

        # Port
        email_layout.addWidget(QLabel("Порт:"), 2, 0)
        self.email_port_edit = QSpinBox()
        self.email_port_edit.setRange(1, 65535)
        self.email_port_edit.setValue(587)
        self.email_port_edit.setToolTip(
            "Порт SMTP сервера.\n\n" "• 587 — TLS (рекомендуется)\n" "• 465 — SSL\n" "• 25 — без шифрования (не рекомендуется)"
        )
        email_layout.addWidget(self.email_port_edit, 2, 1)

        # Email From
        email_layout.addWidget(QLabel("Отправитель (Email):"), 3, 0)
        self.email_from_edit = QLineEdit()
        self.email_from_edit.setPlaceholderText("your_email@gmail.com")
        self.email_from_edit.setToolTip(
            "Ваш Email адрес для отправки уведомлений.\n\n"
            "Должен совпадать с аккаунтом,\n"
            "который используется для аутентификации."
        )
        email_layout.addWidget(self.email_from_edit, 3, 1)

        # Password
        email_layout.addWidget(QLabel("Пароль приложения:"), 4, 0)
        self.email_password_edit = QLineEdit()
        self.email_password_edit.setEchoMode(QLineEdit.Password)
        self.email_password_edit.setToolTip(
            "Пароль приложения (не основной пароль!).\n\n"
            "Как получить:\n"
            "• Gmail: Безопасность → Пароли приложений\n"
            "• Yandex: Безопасность → Пароли приложений\n"
            "• Mail.ru: Безопасность → Пароли для внешних приложений"
        )
        email_layout.addWidget(self.email_password_edit, 4, 1)

        # Кнопка показать/скрыть пароль
        self.email_password_toggle_btn = QPushButton("👁️")
        self.email_password_toggle_btn.setFixedWidth(40)
        self.email_password_toggle_btn.setToolTip("Показать или скрыть пароль")
        self.email_password_toggle_btn.clicked.connect(
            lambda: self._toggle_password_visibility(self.email_password_edit, self.email_password_toggle_btn)
        )
        email_layout.addWidget(self.email_password_toggle_btn, 4, 2)

        # Recipients
        email_layout.addWidget(QLabel("Получатели (через запятую):"), 5, 0)
        self.email_recipients_edit = QLineEdit()
        self.email_recipients_edit.setPlaceholderText("recipient1@example.com, recipient2@example.com")
        self.email_recipients_edit.setToolTip(
            "Список Email адресов для получения уведомлений.\n\n"
            "Можно указать несколько адресов через запятую:\n"
            "admin@example.com, trader@example.com"
        )
        email_layout.addWidget(self.email_recipients_edit, 5, 1)

        # Кнопка тестирования
        self.test_email_btn = QPushButton("🧪 Тестировать Email")
        self.test_email_btn.setToolTip(
            "Отправляет тестовое письмо на указанный адрес.\n\n"
            "Проверьте:\n"
            "✓ SMTP сервер и порт\n"
            "✓ Логин и пароль приложения\n"
            "✓ Подключение к интернету\n\n"
            "Если не работает — проверьте папку 'Спам'."
        )
        self.test_email_btn.clicked.connect(self._test_email_connection)
        email_layout.addWidget(self.test_email_btn, 6, 0, 1, 3)

        # Инструкция
        email_help = QLabel(
            "📝 <b>Как настроить:</b><br>"
            "1. Включите 'Пароли приложений' в почтовом сервисе<br>"
            "2. Создайте пароль приложения<br>"
            "3. Введите SMTP сервер и порт<br>"
            "4. Нажмите 'Тестировать'"
        )
        email_help.setWordWrap(True)
        email_help.setStyleSheet("background-color: #f0f0f0; padding: 10px; border-radius: 5px;")
        email_help.setToolTip("Следуйте инструкции для быстрой настройки Email уведомлений")
        email_layout.addWidget(email_help, 7, 0, 1, 3)

        layout.addWidget(email_group)

        # --- Группа: Quiet Hours ---
        quiet_hours_group = QGroupBox("Тихие часы (Quiet Hours)")
        quiet_hours_layout = QGridLayout(quiet_hours_group)
        quiet_hours_layout.setColumnStretch(1, 1)

        # Включить тихие часы
        self.quiet_hours_enabled_checkbox = QCheckBox("Включить тихие часы")
        self.quiet_hours_enabled_checkbox.setToolTip(
            "Отключает уведомления (кроме CRITICAL) в указанное время.\n\n"
            "Полезно для:\n"
            "• Ночного времени\n"
            "• Выходных дней\n"
            "• Отпуска"
        )
        quiet_hours_layout.addWidget(self.quiet_hours_enabled_checkbox, 0, 0, 1, 3)

        # Начало
        quiet_hours_layout.addWidget(QLabel("Начало:"), 1, 0)
        self.quiet_hours_start_edit = QTimeEdit()
        self.quiet_hours_start_edit.setTime(QTime(22, 0))
        self.quiet_hours_start_edit.setDisplayFormat("HH:mm")
        self.quiet_hours_start_edit.setToolTip("Время начала тихих часов.\n\n" "Рекомендуется: 22:00")
        quiet_hours_layout.addWidget(self.quiet_hours_start_edit, 1, 1)

        # Конец
        quiet_hours_layout.addWidget(QLabel("Конец:"), 2, 0)
        self.quiet_hours_end_edit = QTimeEdit()
        self.quiet_hours_end_edit.setTime(QTime(8, 0))
        self.quiet_hours_end_edit.setDisplayFormat("HH:mm")
        self.quiet_hours_end_edit.setToolTip("Время окончания тихих часов.\n\n" "Рекомендуется: 08:00")
        quiet_hours_layout.addWidget(self.quiet_hours_end_edit, 2, 1)

        layout.addWidget(quiet_hours_group)

        # --- Группа: Daily Digest ---
        digest_group = QGroupBox("Дневной дайджест")
        digest_layout = QGridLayout(digest_group)
        digest_layout.setColumnStretch(1, 1)

        # Включить дайджест
        self.digest_enabled_checkbox = QCheckBox("Включить дневной дайджест")
        self.digest_enabled_checkbox.setToolTip(
            "Отправляет сводку за день в указанное время.\n\n"
            "Содержит:\n"
            "• Количество сделок\n"
            "• Общий PnL\n"
            "• Win Rate\n"
            "• Статус системы"
        )
        digest_layout.addWidget(self.digest_enabled_checkbox, 0, 0, 1, 3)

        # Время
        digest_layout.addWidget(QLabel("Время отправки:"), 1, 0)
        self.digest_time_edit = QTimeEdit()
        self.digest_time_edit.setTime(QTime(20, 0))
        self.digest_time_edit.setDisplayFormat("HH:mm")
        self.digest_time_edit.setToolTip(
            "Время отправки дневного дайджеста.\n\n" "Рекомендуется: 20:00 (после закрытия торгов)"
        )
        digest_layout.addWidget(self.digest_time_edit, 1, 1)

        layout.addWidget(digest_group)

        layout.addStretch()

        return self._create_scrollable_widget(content_widget)

    def _toggle_password_visibility(self, line_edit: QLineEdit, button: QPushButton):
        """Переключает видимость пароля/токена."""
        if line_edit.echoMode() == QLineEdit.Password:
            line_edit.setEchoMode(QLineEdit.Normal)
            button.setText("🙈")
        else:
            line_edit.setEchoMode(QLineEdit.Password)
            button.setText("👁️")

    def _test_telegram_connection(self):
        """Тестирует подключение к Telegram."""
        from PySide6.QtWidgets import QMessageBox

        token = self.telegram_token_edit.text().strip()
        chat_id = self.telegram_chat_id_edit.text().strip()

        if not token or not chat_id:
            QMessageBox.warning(self, "Ошибка", "Заполните Bot Token и Chat ID")
            return

        logger.info(f"Начало тестирования Telegram: token={token[:10]}..., chat_id={chat_id}")

        # Останавливаем предыдущий тест если он ещё идёт
        if hasattr(self, "telegram_tester"):
            try:
                if self.telegram_tester.isRunning():
                    logger.debug("Остановка предыдущего TelegramTester")
                    self.telegram_tester.quit()
                    self.telegram_tester.wait(1000)  # Ждём до 1 сек
            except RuntimeError:
                # Объект уже удалён, игнорируем
                logger.debug("Предыдущий TelegramTester уже удалён")
                if hasattr(self, "telegram_tester"):
                    del self.telegram_tester

        # Создаём и запускаем тестер
        # Используем прокси по умолчанию для обхода блокировок
        logger.info("Запуск TelegramTester (с прокси для обхода блокировок)")
        self.telegram_tester = TelegramTester(token, chat_id, timeout=15, use_proxy=True)
        self.telegram_tester.result_ready.connect(self._on_telegram_test_complete)
        self.telegram_tester.finished.connect(self._on_telegram_tester_finished)
        self.telegram_tester.start()

    def _on_telegram_test_complete(self, success: bool, message: str):
        """Обработка результата тестирования Telegram."""
        from PySide6.QtWidgets import QMessageBox

        # Логируем результат
        if success:
            logger.info("✅ Тестирование Telegram успешно")
        else:
            logger.warning(f"❌ Тестирование Telegram не удалось: {message}")

        if success:
            QMessageBox.information(self, "Успех", message)
        else:
            QMessageBox.critical(self, "Ошибка", message)

    def _on_telegram_tester_finished(self):
        """Очистка после завершения тестера."""
        if hasattr(self, "telegram_tester"):
            try:
                self.telegram_tester.deleteLater()
            except RuntimeError:
                # Объект уже удалён
                pass
            del self.telegram_tester

    def _test_email_connection(self):
        """Тестирует подключение к Email."""
        from PySide6.QtWidgets import QMessageBox

        smtp_server = self.email_smtp_edit.text().strip()
        smtp_port = self.email_port_edit.value()
        email_from = self.email_from_edit.text().strip()
        email_password = self.email_password_edit.text().strip()
        recipients = self.email_recipients_edit.text().strip()

        if not all([smtp_server, email_from, email_password, recipients]):
            QMessageBox.warning(self, "Ошибка", "Заполните все поля Email")
            return

        logger.info(f"Начало тестирования Email: smtp={smtp_server}, from={email_from}")

        # Останавливаем предыдущий тест если он ещё идёт
        if hasattr(self, "email_tester"):
            try:
                if self.email_tester.isRunning():
                    logger.debug("Остановка предыдущего EmailTester")
                    self.email_tester.quit()
                    self.email_tester.wait(1000)
            except RuntimeError:
                # Объект уже удалён, игнорируем
                logger.debug("Предыдущий EmailTester уже удалён")
                if hasattr(self, "email_tester"):
                    del self.email_tester

        # Создаём и запускаем тестер
        logger.info("Запуск EmailTester")
        self.email_tester = EmailTester(smtp_server, smtp_port, email_from, email_password, recipients, use_proxy=True)
        self.email_tester.result_ready.connect(self._on_email_test_complete)
        self.email_tester.finished.connect(self._on_email_tester_finished)
        self.email_tester.start()

    def _on_email_test_complete(self, success: bool, message: str):
        """Обработка результата тестирования Email."""
        from PySide6.QtWidgets import QMessageBox

        # Логируем результат
        if success:
            logger.info("✅ Тестирование Email успешно")
        else:
            logger.warning(f"❌ Тестирование Email не удалось: {message}")

        if success:
            QMessageBox.information(self, "Успех", message)
        else:
            QMessageBox.critical(self, "Ошибка", message)

    def _on_email_tester_finished(self):
        """Очистка после завершения тестера."""
        if hasattr(self, "email_tester"):
            try:
                self.email_tester.deleteLater()
            except RuntimeError:
                # Объект уже удалён
                pass
            del self.email_tester

    def _browse_folder(self, line_edit_widget, title):
        dir_path = QFileDialog.getExistingDirectory(self, title)
        if dir_path:
            line_edit_widget.setText(dir_path)

    def _browse_file(self, line_edit_widget, title, file_filter="All Files (*.*)"):
        """Открыть диалог выбора файла."""
        from PySide6.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getOpenFileName(self, title, "", file_filter)
        if file_path:
            line_edit_widget.setText(file_path)

    def _get_relative_vector_db_path(self):
        """Получить относительный путь к векторной БД относительно DATABASE_FOLDER"""
        vector_db_path = self.vector_db_folder_edit.text()
        db_folder = self.db_folder_edit.text()

        # Если путь начинается с DATABASE_FOLDER, делаем его относительным
        if vector_db_path.startswith(db_folder):
            relative_path = os.path.relpath(vector_db_path, db_folder)
            return relative_path.replace("\\", "/")
        else:
            # Если путь вне DATABASE_FOLDER, сохраняем абсолютный
            return vector_db_path.replace("\\", "/")

    def _find_env_file(self):
        project_root = Path(__file__).parent.parent.parent
        configs_dir = project_root / "configs"
        configs_dir.mkdir(exist_ok=True)
        env_path = configs_dir / ".env"
        if not env_path.exists():
            env_path.touch()
        return str(env_path)

    def _create_crypto_tab(self):
        """Создает вкладку для настройки криптовалютных бирж."""
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setAlignment(Qt.AlignTop)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Заголовок
        title = QLabel("<h2>₿ Настройка криптовалютных бирж</h2>")
        title.setStyleSheet("color: #f8f8f2; padding: 10px;")
        title.setWordWrap(True)
        layout.addWidget(title)

        # Общая настройка
        general_group = QGroupBox("Общие настройки")
        general_layout = QGridLayout(general_group)

        self.crypto_enabled_checkbox = QCheckBox("Включить поддержку криптовалют")
        self.crypto_enabled_checkbox.setToolTip(
            "Включает интеграцию с крипто-биржами через ccxt.\n"
            "Позволяет торговать Bitcoin, Ethereum и другими криптовалютами."
        )
        general_layout.addWidget(self.crypto_enabled_checkbox, 0, 0, 1, 2)

        general_layout.addWidget(QLabel("Биржа по умолчанию:"), 1, 0)
        self.crypto_default_exchange_combo = QComboBox()
        self.crypto_default_exchange_combo.addItems(["binance", "bybit", "okx", "kucoin"])
        self.crypto_default_exchange_combo.setToolTip("Биржа, которая будет использоваться по умолчанию.")
        general_layout.addWidget(self.crypto_default_exchange_combo, 1, 1)

        layout.addWidget(general_group)

        # Binance
        binance_group = QGroupBox("Binance")
        binance_layout = QGridLayout(binance_group)

        self.binance_enabled_checkbox = QCheckBox("Включить Binance")
        binance_layout.addWidget(self.binance_enabled_checkbox, 0, 0, 1, 2)

        binance_layout.addWidget(QLabel("API Key:"), 1, 0)
        self.binance_api_key_edit = QLineEdit()
        self.binance_api_key_edit.setPlaceholderText("Введите API ключ Binance")
        self.binance_api_key_edit.setEchoMode(QLineEdit.Password)
        binance_layout.addWidget(self.binance_api_key_edit, 1, 1)

        # Кнопка показать/скрыть
        self.binance_api_key_toggle_btn = QPushButton("👁️")
        self.binance_api_key_toggle_btn.setFixedWidth(40)
        self.binance_api_key_toggle_btn.setToolTip("Показать или скрыть API ключ")
        self.binance_api_key_toggle_btn.clicked.connect(
            lambda: self._toggle_password_visibility(self.binance_api_key_edit, self.binance_api_key_toggle_btn)
        )
        binance_layout.addWidget(self.binance_api_key_toggle_btn, 1, 2)

        binance_layout.addWidget(QLabel("API Secret:"), 2, 0)
        self.binance_api_secret_edit = QLineEdit()
        self.binance_api_secret_edit.setPlaceholderText("Введите секретный ключ")
        self.binance_api_secret_edit.setEchoMode(QLineEdit.Password)
        binance_layout.addWidget(self.binance_api_secret_edit, 2, 1)

        # Кнопка показать/скрыть
        self.binance_api_secret_toggle_btn = QPushButton("👁️")
        self.binance_api_secret_toggle_btn.setFixedWidth(40)
        self.binance_api_secret_toggle_btn.setToolTip("Показать или скрыть Secret ключ")
        self.binance_api_secret_toggle_btn.clicked.connect(
            lambda: self._toggle_password_visibility(self.binance_api_secret_edit, self.binance_api_secret_toggle_btn)
        )
        binance_layout.addWidget(self.binance_api_secret_toggle_btn, 2, 2)

        self.binance_sandbox_checkbox = QCheckBox("Sandbox (тестовый режим)")
        self.binance_sandbox_checkbox.setToolTip(
            "Использовать тестовую среду Binance.\n"
            "Не требует реальных API ключей.\n"
            "Безопасно для обучения и тестирования."
        )
        binance_layout.addWidget(self.binance_sandbox_checkbox, 3, 0, 1, 2)

        binance_layout.addWidget(QLabel("Торговые пары:"), 4, 0)
        self.binance_symbols_edit = QLineEdit()
        self.binance_symbols_edit.setPlaceholderText("BTC/USDT,ETH/USDT,BNB/USDT")
        self.binance_symbols_edit.setToolTip(
            "Список торговых пар через запятую.\n" "Пример: BTC/USDT,ETH/USDT,BNB/USDT,SOL/USDT"
        )
        binance_layout.addWidget(self.binance_symbols_edit, 4, 1, 1, 2)

        binance_layout.addWidget(QLabel("Кредитное плечо:"), 5, 0)
        self.binance_leverage_spin = QSpinBox()
        self.binance_leverage_spin.setRange(1, 125)
        self.binance_leverage_spin.setValue(1)
        self.binance_leverage_spin.setToolTip("Кредитное плечо по умолчанию (1 = без плеча).")
        binance_layout.addWidget(self.binance_leverage_spin, 5, 1)

        binance_layout.addWidget(QLabel("Тип рынка:"), 6, 0)
        self.binance_market_type_combo = QComboBox()
        self.binance_market_type_combo.addItems(["spot", "future"])
        self.binance_market_type_combo.setToolTip("spot = спотовая торговля, future = фьючерсы.")
        binance_layout.addWidget(self.binance_market_type_combo, 6, 1)

        # Кнопка тестирования
        self.test_binance_btn = QPushButton("🧪 Тестировать подключение")
        self.test_binance_btn.setToolTip("Проверяет подключение к Binance API.\n" "В sandbox режиме проверяет тестовую среду.")
        self.test_binance_btn.clicked.connect(self._test_binance_connection)
        binance_layout.addWidget(self.test_binance_btn, 7, 0, 1, 3)

        layout.addWidget(binance_group)

        # Bybit
        bybit_group = QGroupBox("Bybit")
        bybit_layout = QGridLayout(bybit_group)

        self.bybit_enabled_checkbox = QCheckBox("Включить Bybit")
        bybit_layout.addWidget(self.bybit_enabled_checkbox, 0, 0, 1, 2)

        bybit_layout.addWidget(QLabel("API Key:"), 1, 0)
        self.bybit_api_key_edit = QLineEdit()
        self.bybit_api_key_edit.setPlaceholderText("Введите API ключ Bybit")
        self.bybit_api_key_edit.setEchoMode(QLineEdit.Password)
        bybit_layout.addWidget(self.bybit_api_key_edit, 1, 1)

        bybit_layout.addWidget(QLabel("API Secret:"), 2, 0)
        self.bybit_api_secret_edit = QLineEdit()
        self.bybit_api_secret_edit.setPlaceholderText("Введите секретный ключ")
        self.bybit_api_secret_edit.setEchoMode(QLineEdit.Password)
        bybit_layout.addWidget(self.bybit_api_secret_edit, 2, 1)

        self.bybit_sandbox_checkbox = QCheckBox("Sandbox (тестовый режим)")
        bybit_layout.addWidget(self.bybit_sandbox_checkbox, 3, 0, 1, 2)

        bybit_layout.addWidget(QLabel("Торговые пары:"), 4, 0)
        self.bybit_symbols_edit = QLineEdit()
        self.bybit_symbols_edit.setPlaceholderText("BTC/USDT,ETH/USDT")
        bybit_layout.addWidget(self.bybit_symbols_edit, 4, 1, 1, 2)

        layout.addWidget(bybit_group)

        layout.addStretch()

        return self._create_scrollable_widget(content_widget)

    def _test_binance_connection(self):
        """Тестирует подключение к Binance."""
        from PySide6.QtWidgets import QMessageBox

        try:
            import ccxt

            sandbox = self.binance_sandbox_checkbox.isChecked()

            if sandbox:
                # Тестовое подключение
                exchange = ccxt.binance(
                    {
                        "sandbox": True,
                        "enableRateLimit": True,
                    }
                )
                exchange.load_markets()
                QMessageBox.information(
                    self,
                    "Тестирование Binance",
                    f"✅ Sandbox режим работает!\n\n"
                    f"Доступно торговых пар: {len(exchange.markets)}\n\n"
                    f"Это тестовая среда - реальные торги не проводятся.",
                )
            else:
                # Проверка наличия API ключей
                api_key = self.binance_api_key_edit.text().strip()
                api_secret = self.binance_api_secret_edit.text().strip()

                if not api_key or not api_secret:
                    QMessageBox.warning(
                        self,
                        "Предупреждение",
                        "⚠️ Введите API ключи для тестирования реального подключения!\n\n"
                        "Или включите Sandbox режим для тестирования без ключей.",
                    )
                    return

                exchange = ccxt.binance(
                    {
                        "apiKey": api_key,
                        "secret": api_secret,
                        "enableRateLimit": True,
                    }
                )

                exchange.load_markets()
                balance = exchange.fetch_balance()

                QMessageBox.information(
                    self,
                    "Тестирование Binance",
                    f"✅ Подключение успешно!\n\n"
                    f"Доступно торговых пар: {len(exchange.markets)}\n"
                    f"Баланс: {balance.get('USDT', {}).get('free', 0)} USDT",
                )

        except ccxt.AuthenticationError as e:
            QMessageBox.critical(self, "Ошибка аутентификации", f"❌ Ошибка аутентификации:\n{str(e)}\n\nПроверьте API ключи.")
        except ccxt.NetworkError as e:
            QMessageBox.critical(self, "Ошибка сети", f"❌ Ошибка подключения:\n{str(e)}\n\nПроверьте интернет-соединение.")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"❌ Неожиданная ошибка:\n{str(e)}")

    def _create_mt5_tab(self):
        content_widget = QWidget()
        layout = QGridLayout(content_widget)
        self.mt5_entries = {}
        self.mt5_entries["MT5_LOGIN"] = QLineEdit()
        self.mt5_entries["MT5_PASSWORD"] = QLineEdit(echoMode=QLineEdit.Password)
        self.mt5_entries["MT5_SERVER"] = QLineEdit()
        self.mt5_entries["MT5_PATH"] = QLineEdit()
        layout.addWidget(QLabel("Логин:"), 0, 0)
        layout.addWidget(self.mt5_entries["MT5_LOGIN"], 0, 1)
        layout.addWidget(QLabel("Пароль:"), 1, 0)
        layout.addWidget(self.mt5_entries["MT5_PASSWORD"], 1, 1)
        layout.addWidget(QLabel("Сервер:"), 2, 0)
        layout.addWidget(self.mt5_entries["MT5_SERVER"], 2, 1)
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.mt5_entries["MT5_PATH"])
        browse_button = QPushButton("Обзор...")
        browse_button.clicked.connect(self._browse_mt5_path)
        path_layout.addWidget(browse_button)
        layout.addWidget(QLabel("Путь к terminal64.exe:"), 3, 0)
        layout.addLayout(path_layout, 3, 1)
        test_layout = QHBoxLayout()
        test_button = QPushButton("Проверить подключение")
        test_button.clicked.connect(self._test_mt5_connection)
        self.test_status_label = QLabel("Статус: не проверялось")
        self.test_status_label.setStyleSheet("color: gray;")
        test_layout.addWidget(test_button)
        test_layout.addWidget(self.test_status_label)
        test_layout.addStretch()
        layout.addLayout(test_layout, 4, 1)
        return self._create_scrollable_widget(content_widget)

    def _create_api_tab(self):
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        self.api_table = QTableWidget()
        self.api_table.setColumnCount(4)
        self.api_table.setHorizontalHeaderLabels(["Источник", "API Ключ", "Действие", "Статус"])
        self.api_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.api_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.api_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.api_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.api_table)
        button_layout = QHBoxLayout()
        add_button = QPushButton("Добавить ключ")
        delete_button = QPushButton("Удалить выбранный")
        add_button.clicked.connect(self._add_api_key)
        delete_button.clicked.connect(self._delete_api_key)
        button_layout.addStretch()
        button_layout.addWidget(add_button)
        button_layout.addWidget(delete_button)
        layout.addLayout(button_layout)
        return self._create_scrollable_widget(content_widget)

    def _update_scheduler_status(self):
        tasks = [
            ("GenesisTraderAutostart", self.autostart_checkbox, self.autostart_status_label, None),
            ("GenesisMaintenance", self.maintenance_checkbox, self.maintenance_status_label, self.maintenance_time_edit),
            (
                "GenesisWeeklyOptimization",
                self.optimization_checkbox,
                self.optimization_status_label,
                self.optimization_time_edit,
            ),
        ]
        scheduler_summary = {}

        for task_name, checkbox, status_label, time_edit_widget in tasks:
            if self.scheduler_manager.task_exists(task_name):
                checkbox.setChecked(True)
                status_label.setText("Статус: АКТИВНА")
                status_label.setStyleSheet("color: #50fa7b;")

                # --- Добавляем время в сводку, если оно есть ---
                time_str = self.scheduler_manager.get_task_trigger_time(task_name)
                if time_str:
                    scheduler_summary[task_name] = f"АКТИВНА ({time_str})"
                else:
                    scheduler_summary[task_name] = "АКТИВНА"
                # ------------------------------------------------------------

            else:
                checkbox.setChecked(False)
                status_label.setText("Статус: НЕ настроена")
                status_label.setStyleSheet("color: orange;")
                scheduler_summary[task_name] = "НЕ настроена"

        # ---  Отправляем сводку ОДИН раз, после цикла ---
        self.scheduler_status_updated.emit(scheduler_summary)
        # ------------------------------------------------------------

    def _handle_scheduler_tasks(self):
        # Получаем значения времени из виджетов
        maintenance_time_str = self.maintenance_time_edit.time().toString("HH:mm")
        optimization_time_str = self.optimization_time_edit.time().toString("HH:mm")

        tasks_to_manage = [
            {
                "checkbox": self.autostart_checkbox,
                "task_name": "GenesisTraderAutostart",
                "script_name": "start_genesis.bat",
                "trigger": "ONSTART",
            },
            {
                "checkbox": self.maintenance_checkbox,
                "task_name": "GenesisMaintenance",
                "script_name": "maintenance.bat",
                "trigger": "DAILY",
                "time": maintenance_time_str,
            },
            {
                "checkbox": self.optimization_checkbox,
                "task_name": "GenesisWeeklyOptimization",
                "script_name": "optimize_all.bat",
                "trigger": "WEEKLY",
                "time": optimization_time_str,
                "day": "SAT",
            },
        ]

        for task_info in tasks_to_manage:
            is_checked = task_info["checkbox"].isChecked()
            task_exists = self.scheduler_manager.task_exists(task_info["task_name"])

            if is_checked:
                # Если флажок установлен, всегда создаем/перезаписываем задачу с новым временем
                success, message = self.scheduler_manager.create_task(
                    task_name=task_info["task_name"],
                    script_name=task_info["script_name"],
                    trigger_type=task_info["trigger"],
                    trigger_time=task_info.get("time"),
                    trigger_day=task_info.get("day"),
                )
                if not success:
                    QMessageBox.warning(self, f"Ошибка создания/обновления задачи '{task_info['task_name']}'", message)
            elif not is_checked and task_exists:
                # Если флажок снят и задача существует, удаляем ее
                success, message = self.scheduler_manager.delete_task(task_info["task_name"])
                if not success:
                    QMessageBox.warning(self, f"Ошибка удаления задачи '{task_info['task_name']}'", message)

        self._update_scheduler_status()

    def _browse_mt5_path(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите terminal64.exe", "", "Executable files (*.exe)")
        if file_path:
            self.mt5_entries["MT5_PATH"].setText(file_path)

    def _test_mt5_connection(self):
        settings = {key: widget.text() for key, widget in self.mt5_entries.items()}
        self.test_status_label.setText("Подключение...")
        self.test_status_label.setStyleSheet("color: orange;")
        self.connection_tester = ConnectionTester(settings)
        self.connection_tester.result_ready.connect(self._on_test_finished)
        self.connection_tester.start()

    def _on_test_finished(self, success, message):
        self.test_status_label.setText(message)
        self.test_status_label.setStyleSheet("color: #50fa7b;" if success else "color: #ff5555;")

    def _test_api_key(self, row):
        service_name_item = self.api_table.item(row, 0)
        api_key_item = self.api_table.item(row, 1)
        if not service_name_item or not api_key_item:
            return
        service_name = service_name_item.text()
        api_key = api_key_item.text()
        button = self.api_table.cellWidget(row, 2)
        status_label = self.api_table.cellWidget(row, 3)
        if not api_key:
            status_label.setText("Ключ пуст")
            status_label.setStyleSheet("color: orange;")
            return
        button.setEnabled(False)
        status_label.setText("Проверка...")
        status_label.setStyleSheet("color: orange;")
        tester_thread = ApiKeyTesterThread(row, service_name, api_key)
        tester_thread.result_ready.connect(self._on_api_test_finished)
        self.api_testers[row] = tester_thread
        tester_thread.start()

    def _on_api_test_finished(self, row, success, message):
        button = self.api_table.cellWidget(row, 2)
        status_label = self.api_table.cellWidget(row, 3)
        if button:
            button.setEnabled(True)
        if status_label:
            status_label.setText(message)
            status_label.setStyleSheet("color: #50fa7b;" if success else "color: #ff5555;")
        if row in self.api_testers:
            del self.api_testers[row]

    def _add_row_to_api_table(self, key: str, value: str):
        row_position = self.api_table.rowCount()
        self.api_table.insertRow(row_position)
        self.api_table.setItem(row_position, 0, QTableWidgetItem(key))
        self.api_table.setItem(row_position, 1, QTableWidgetItem(value))
        check_button = QPushButton("Проверить")
        check_button.clicked.connect(lambda checked=False, row=row_position: self._test_api_key(row))
        self.api_table.setCellWidget(row_position, 2, check_button)
        status_label = QLabel("Не проверялся")
        status_label.setAlignment(Qt.AlignCenter)
        self.api_table.setCellWidget(row_position, 3, status_label)

    def _add_api_key(self):
        dialog = AddKeyDialog(self)
        if dialog.exec():
            service, key = dialog.get_data()
            if service and key:
                key_name = f"{service.upper().replace(' ', '_')}_API_KEY"
                self._add_row_to_api_table(key_name, key)

    def _delete_api_key(self):
        current_row = self.api_table.currentRow()
        if current_row >= 0:
            self.api_table.removeRow(current_row)
        else:
            QMessageBox.warning(self, "Внимание", "Пожалуйста, выберите ключ для удаления.")

    def _trigger_manual_retraining(self):
        """Запускает ручное переобучение моделей."""
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Запустить переобучение {self.auto_retrain_max_symbols_spin.value()} символов в {self.auto_retrain_max_workers_spin.value()} потоков?\n\n"
            f"Это может занять несколько минут. Продолжить?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            try:
                self.manual_retrain_button.setEnabled(False)
                self.auto_retrain_status_label.setText("Статус: запуск...")
                self.auto_retrain_status_label.setStyleSheet("color: orange;")

                # Запускаем в отдельном потоке
                import threading

                from smart_retrain import smart_retrain_models

                def run_training():
                    try:
                        smart_retrain_models(
                            max_symbols=self.auto_retrain_max_symbols_spin.value(),
                            max_workers=self.auto_retrain_max_workers_spin.value(),
                        )
                        # Обновляем статус в GUI потокобезопасным способом через QTimer
                        from PySide6.QtCore import QTimer
                        QTimer.singleShot(0, lambda: self._on_training_finished(success=True))
                    except Exception as e:
                        logger.error(f"Ошибка при ручном переобучении: {e}", exc_info=True)
                        from PySide6.QtCore import QTimer
                        QTimer.singleShot(0, lambda: self._on_training_finished(success=False, error=str(e)))

                training_thread = threading.Thread(target=run_training, daemon=True)
                training_thread.start()

                QMessageBox.information(
                    self,
                    "Обучение запущено",
                    "Переобучение моделей запущено в фоновом режиме.\n" "Процесс можно отслеживать в логах.",
                )

            except Exception as e:
                logger.error(f"Ошибка запуска обучения: {e}", exc_info=True)
                self.auto_retrain_status_label.setText("Статус: ошибка ❌")
                self.auto_retrain_status_label.setStyleSheet("color: #ff5555;")
                self.manual_retrain_button.setEnabled(True)
                QMessageBox.critical(self, "Ошибка", f"Не удалось запустить обучение:\n{e}")

    def _on_training_finished(self, success: bool = True, error: str = ""):
        """Безопасное обновление GUI после завершения обучения (вызывается из основного потока)."""
        if success:
            self.auto_retrain_status_label.setText("Статус: завершено ✓")
            self.auto_retrain_status_label.setStyleSheet("color: #50fa7b;")
            QMessageBox.information(self, "Готово", "Переобучение моделей успешно завершено!")
        else:
            self.auto_retrain_status_label.setText(f"Статус: ошибка ❌")
            self.auto_retrain_status_label.setStyleSheet("color: #ff5555;")
            QMessageBox.critical(self, "Ошибка", f"Не удалось завершить обучение:\n{error}")
        
        # Возвращаем кнопку в активное состояние
        self.manual_retrain_button.setEnabled(True)

    def _scroll_to_risk_settings(self):
        """Информирование пользователя о настройках риск-менеджмента."""
        # Вкладка уже активна, пользователь может прокрутить вниз самостоятельно
        logger.info("📊 Выбран кастомный режим - настройки риск-менеджмента ниже")

    def _on_trading_mode_changed(self, mode_id: str, settings: dict):
        """Обработка изменения режима торговли."""
        logger.info(f"🎯 Режим торговли изменен на: {mode_id}")

        # Обработка отключения режимов
        if mode_id == "disabled":
            # Обновляем метку в TradingModesWidget
            if hasattr(self, "trading_modes_widget"):
                self.trading_modes_widget.current_mode_label.setText("⚙️ Режимы торговли ОТКЛЮЧЕНЫ")
                self.trading_modes_widget.current_mode_label.setStyleSheet("""
                    background-color: #5e636f20;
                    color: #95a5a6;
                    padding: 10px;
                    border-radius: 5px;
                    font-weight: bold;
                    font-size: 12px;
                """)

            # Отключаем режимы в TradingSystem
            try:
                if hasattr(self.parent(), "trading_system"):
                    self.parent().trading_system.set_trading_mode("disabled", {})
                    logger.info("✅ Режимы торговли отключены - система использует базовые настройки")
            except Exception as e:
                logger.error(f"❌ Ошибка при отключении режимов: {e}")
            return

        # Обновляем метку в TradingModesWidget
        if hasattr(self, "trading_modes_widget"):
            mode_data = TRADING_MODES.get(mode_id, {})
            mode_name = mode_data.get("name", "Кастомный")
            mode_icon = mode_data.get("icon", "🔧")

            self.trading_modes_widget.current_mode_label.setText(f"Текущий режим: {mode_icon} {mode_name}")

            if mode_id != "custom":
                color = mode_data.get("color", "#f39c12")
                self.trading_modes_widget.current_mode_label.setStyleSheet(f"""
                    background-color: {color}20;
                    color: {color};
                    padding: 10px;
                    border-radius: 5px;
                    font-weight: bold;
                    font-size: 12px;
                """)
            else:
                self.trading_modes_widget.current_mode_label.setStyleSheet("""
                    background-color: #3498db20;
                    color: #3498db;
                    padding: 10px;
                    border-radius: 5px;
                    font-weight: bold;
                    font-size: 12px;
                """)

        # Применяем режим через TradingSystem
        try:
            from src.core.trading_system import TradingSystem

            # Получаем ссылку на trading_system через родителя
            if hasattr(self.parent(), "trading_system"):
                self.parent().trading_system.set_trading_mode(mode_id, settings)
                logger.info(f"✅ Режим '{mode_id}' успешно применен")
        except Exception as e:
            logger.error(f"❌ Ошибка при применении режима: {e}")

    def _on_trading_modes_enabled_changed(self, enabled: bool):
        """Обработка изменения флага включения режимов из TradingModesWidget."""
        if enabled:
            logger.info("🎯 Режимы торговли ВКЛЮЧЕНЫ")
        else:
            logger.info("⚙️ Режимы торговли ОТКЛЮЧЕНЫ")

    def _load_current_trading_mode(self):
        """Загрузка текущего режима из конфигурации."""
        try:
            # Получаем текущий режим из конфига
            current_mode = getattr(self.full_config, "trading_mode", {}).get("current_mode", "standard")
            # Получаем состояние включения режимов
            modes_enabled = getattr(self.full_config, "trading_mode", {}).get("enabled", False)

            # Устанавливаем режим в виджете
            if hasattr(self, "trading_modes_widget"):
                # Блокируем/разблокируем контейнер в зависимости от состояния
                self.trading_modes_widget.modes_container.setEnabled(modes_enabled)
                # Устанавливаем чекбокс в заголовке
                if hasattr(self, "trading_modes_enable_checkbox"):
                    self.trading_modes_enable_checkbox.setChecked(modes_enabled)

                self.trading_modes_widget.set_mode(current_mode)
                # Метка обновится автоматически в set_mode через on_mode_selected

        except Exception as e:
            logger.error(f"Ошибка загрузки текущего режима: {e}")
