# src/gui/settings_window.py

import os
import subprocess
import sys

from dotenv import dotenv_values, set_key
from pathlib import Path
import logging


import MetaTrader5 as mt5
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QPushButton, QLabel, QLineEdit, QFrame,
                               QDialogButtonBox, QTabWidget, QWidget, QFileDialog,
                               QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QCheckBox,
                               QDoubleSpinBox, QSpinBox, QGroupBox, QTimeEdit, QComboBox, QScrollArea,
                               QSizePolicy)

from PySide6.QtGui import QColor
from PySide6.QtCore import Qt, QThread, Signal, QTime

from src.core.config_models import Settings
from pydantic import BaseModel

from .api_tester import ApiTester
from .trading_modes_widget import TradingModesWidget, TRADING_MODES
from src.core.config_loader import load_config
from src.core.config_writer import write_config
from src.utils.scheduler_manager import SchedulerManager

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
                self.result_ready.emit(
                    True, f"Успех! Счет #{account_info.login}")
            mt5.shutdown()
        except Exception as e:
            self.result_ready.emit(False, f"Ошибка: {str(e)}")


class TelegramTester(QThread):
    """Поток для тестирования Telegram подключения."""
    result_ready = Signal(bool, str)

    def __init__(self, token: str, chat_id: str):
        super().__init__()
        self.token = token
        self.chat_id = chat_id

    def run(self):
        try:
            import requests
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': '🧪 <b>Тест Genesis Trading System</b>\n\nУведомления Telegram работают корректно!',
                'parse_mode': 'HTML'
            }
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            result = response.json()
            if result.get('ok'):
                self.result_ready.emit(True, "Успех! Проверьте Telegram.")
            else:
                self.result_ready.emit(
                    False, f"Ошибка API: {result.get('description', 'Unknown error')}")
        except requests.exceptions.Timeout:
            self.result_ready.emit(False, "Превышено время ожидания (10 сек)")
        except requests.exceptions.ConnectionError:
            self.result_ready.emit(
                False, "Ошибка подключения. Проверьте интернет.")
        except Exception as e:
            self.result_ready.emit(False, f"Ошибка: {str(e)}")


class EmailTester(QThread):
    """Поток для тестирования Email подключения."""
    result_ready = Signal(bool, str)

    def __init__(self, smtp_server: str, smtp_port: int, email_from: str,
                 email_password: str, recipients: str):
        super().__init__()
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.email_from = email_from
        self.email_password = email_password
        self.recipients = recipients

    def run(self):
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            msg = MIMEMultipart()
            msg['From'] = self.email_from
            msg['To'] = self.recipients
            msg['Subject'] = "[Genesis Trading] Тест Email"

            body = """
🧪 Тест Genesis Trading System

Email уведомления работают корректно!

---
Это автоматическое тестовое сообщение.
"""
            msg.attach(MIMEText(body, 'plain', 'utf-8'))

            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.email_from, self.email_password)
            server.send_message(msg)
            server.quit()

            self.result_ready.emit(True, "Успех! Проверьте Email.")
        except smtplib.SMTPAuthenticationError:
            self.result_ready.emit(
                False, "Ошибка аутентификации. Проверьте логин/пароль.")
        except smtplib.SMTPConnectError:
            self.result_ready.emit(False, "Ошибка подключения к SMTP серверу.")
        except Exception as e:
            self.result_ready.emit(False, f"Ошибка: {str(e)}")


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
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, 2, 0, 1, 2)

    def get_data(self):
        return self.service_name_edit.text(), self.api_key_edit.text()


class SettingsWindow(QDialog):
    settings_saved = Signal()
    scheduler_status_updated = Signal(dict)

    def __init__(self, scheduler_manager: SchedulerManager, config: Settings, parent=None):

        super().__init__(parent)
        self.setWindowTitle("Настройки Системы")
        self.setMinimumSize(900, 750)  # Увеличенный размер (было 700x550)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setModal(True)

        self.env_path = self._find_env_file()
        self.connection_tester = None
        self.api_testers = {}
        self.scheduler_manager = scheduler_manager

        self.full_config = config

        main_layout = QVBoxLayout(self)
        self.tab_widget = QTabWidget()  # Сохраняем ссылку для переключения вкладок
        # Прокрутка вкладок при нехватке места
        self.tab_widget.setUsesScrollButtons(True)
        main_layout.addWidget(self.tab_widget)

        mt5_tab = self._create_mt5_tab()
        api_tab = self._create_api_tab()
        trading_tab = self._create_trading_tab()
        paths_tab = self._create_paths_tab()
        scheduler_tab = self._create_scheduler_tab()
        gp_tab = self._create_gp_tab()
        # P0: Notifications (Telegram/Email)
        notifications_tab = self._create_notifications_tab()
        self.tab_widget.addTab(gp_tab, "R&D (AI)")

        self.tab_widget.addTab(mt5_tab, "Подключение MT5")
        self.tab_widget.addTab(api_tab, "API Ключи")
        self.tab_widget.addTab(trading_tab, "Торговля")
        self.tab_widget.addTab(paths_tab, "Пути к данным")
        self.tab_widget.addTab(scheduler_tab, "Планировщик")
        self.tab_widget.addTab(notifications_tab, "Уведомления")

        button_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

        self.load_settings()

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

    def _create_gp_tab(self):
        content_widget = QWidget()
        layout = QGridLayout(content_widget)
        layout.setAlignment(Qt.AlignTop)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        layout.setColumnMinimumWidth(0, 250)  # Минимальная ширина для labels
        layout.setColumnStretch(1, 1)  # Растягиваем колонку со spinbox

        gp_title = QLabel(
            "<b>Настройки Генетического Программирования (R&D)</b>")
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
            "Рекомендуется: 50-100")
        layout.addWidget(self.gp_pop_spin, 1, 1)

        layout.addWidget(QLabel("Количество поколений:"), 2, 0)
        self.gp_gen_spin = QSpinBox()
        self.gp_gen_spin.setRange(1, 500)
        self.gp_gen_spin.setValue(20)  # Значение по умолчанию
        self.gp_gen_spin.setToolTip(
            "Количество поколений для эволюции стратегий.\n"
            "Больше = лучше оптимизация, но дольше обучение.\n"
            "Рекомендуется: 20-50")
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
        self.trading_modes_widget.mode_changed.connect(
            self._on_trading_mode_changed)
        self.trading_modes_widget.enabled_changed.connect(
            self._on_trading_modes_enabled_changed)
        self.trading_modes_widget.open_settings_requested.connect(
            self._scroll_to_risk_settings)

        # Подключаем чекбокс к виджету
        self.trading_modes_enable_checkbox.stateChanged.connect(
            self.trading_modes_widget.on_enabled_changed)

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
            "Процент от баланса счета, которым система готова рискнуть в одной сделке.\nНапример, 1% от $10000 = $100 риска.")
        risk_layout.addWidget(self.risk_percentage_spinbox, 0, 1)

        risk_layout.addWidget(QLabel("Соотношение Риск/Прибыль:"), 1, 0)
        self.risk_reward_ratio_spinbox = QDoubleSpinBox()
        self.risk_reward_ratio_spinbox.setRange(0.5, 10.0)
        self.risk_reward_ratio_spinbox.setSingleStep(0.1)
        self.risk_reward_ratio_spinbox.setToolTip(
            "Соотношение потенциальной прибыли к риску.\nЗначение 2.0 означает, что Take Profit будет в 2 раза дальше от цены входа, чем Stop Loss.")
        risk_layout.addWidget(self.risk_reward_ratio_spinbox, 1, 1)

        risk_layout.addWidget(QLabel("Макс. дневная просадка (%):"), 2, 0)
        self.max_daily_drawdown_spinbox = QDoubleSpinBox()
        self.max_daily_drawdown_spinbox.setRange(1.0, 50.0)
        self.max_daily_drawdown_spinbox.setSingleStep(1.0)
        self.max_daily_drawdown_spinbox.setToolTip(
            "Максимально допустимая дневная просадка в процентах от баланса.\nПри достижении этого лимита система прекратит открывать новые сделки до следующего дня.")
        risk_layout.addWidget(self.max_daily_drawdown_spinbox, 2, 1)

        main_layout.addWidget(self._risk_group)

        # --- Группа Управления Позициями ---
        positions_group = QGroupBox("Управление Позициями")
        positions_group.setToolTip(
            "Настройки управления количеством открытых позиций и торговлей в выходные дни."
        )
        positions_layout = QGridLayout(positions_group)

        positions_layout.addWidget(
            QLabel("Макс. кол-во открытых позиций:"), 0, 0)
        self.max_open_positions_spinbox = QSpinBox()
        self.max_open_positions_spinbox.setRange(1, 100)
        self.max_open_positions_spinbox.setToolTip(
            "Максимальное количество одновременно открытых позиций по всем инструментам.")
        positions_layout.addWidget(self.max_open_positions_spinbox, 0, 1)

        self.allow_weekend_trading_checkbox = QCheckBox(
            "Разрешить торговлю на выходных (для отладки)")
        self.allow_weekend_trading_checkbox.setToolTip(
            "Если включено, система будет игнорировать проверку на субботу и воскресенье.\nИспользовать только для тестирования и отладки, не на реальных счетах!"
        )
        positions_layout.addWidget(
            self.allow_weekend_trading_checkbox, 1, 0, 1, 2)

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
            "Список символов (whitelist), которыми разрешено торговать роботу.\nСистема будет анализировать и открывать сделки только по этим инструментам.")
        symbols_layout.addWidget(self.symbols_table)

        add_remove_layout = QHBoxLayout()
        self.symbol_input = QLineEdit()
        self.symbol_input.setPlaceholderText("Напр. EURUSD, GBPJPY, XAUUSD...")
        self.symbol_input.setToolTip(
            "Введите тикер символа в формате брокера (например, EURUSD, XAUUSD) и нажмите 'Добавить'.")
        self.add_symbol_button = QPushButton("Добавить")
        self.add_symbol_button.setToolTip(
            "Добавляет указанный символ в список разрешённых для торговли.")
        self.remove_symbol_button = QPushButton("Удалить выбранный")
        self.remove_symbol_button.setToolTip(
            "Удаляет выбранный в таблице символ из списка разрешенных.")
        add_remove_layout.addWidget(self.symbol_input)
        add_remove_layout.addWidget(self.add_symbol_button)
        add_remove_layout.addWidget(self.remove_symbol_button)
        symbols_layout.addLayout(add_remove_layout)

        self.add_symbol_button.clicked.connect(self._add_symbol_to_table)
        self.remove_symbol_button.clicked.connect(
            self._remove_symbol_from_table)

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
            self.symbols_table.setItem(
                row_position, 0, QTableWidgetItem(symbol))
            self.symbol_input.clear()
        else:
            QMessageBox.warning(
                self, "Дубликат", f"Символ '{symbol}' уже есть в списке.")

    def _remove_symbol_from_table(self):
        current_row = self.symbols_table.currentRow()
        if current_row >= 0:
            self.symbols_table.removeRow(current_row)
        else:
            QMessageBox.warning(
                self, "Внимание", "Пожалуйста, выберите символ для удаления.")

    def load_settings(self):
        config_values = dotenv_values(self.env_path)
        for key, widget in self.mt5_entries.items():
            widget.setText(config_values.get(key, ""))
        self.api_table.setRowCount(0)
        api_keys = {k: v for k, v in config_values.items() if
                    k.endswith(('_KEY', '_TOKEN', '_ID', '_HASH')) and not k.startswith('MT5')}
        for key, value in api_keys.items():
            self._add_row_to_api_table(key, value)

        self.web_enabled_checkbox.setChecked(
            self.full_config.web_dashboard.enabled)
        self.web_host_edit.setText(self.full_config.web_dashboard.host)
        self.web_port_spinbox.setValue(self.full_config.web_dashboard.port)

        self.hf_cache_edit.setText(self.full_config.HF_MODELS_CACHE_DIR or "")
        self.risk_percentage_spinbox.setValue(self.full_config.RISK_PERCENTAGE)
        self.risk_reward_ratio_spinbox.setValue(
            self.full_config.RISK_REWARD_RATIO)
        self.max_daily_drawdown_spinbox.setValue(
            self.full_config.MAX_DAILY_DRAWDOWN_PERCENT)
        self.max_open_positions_spinbox.setValue(
            self.full_config.MAX_OPEN_POSITIONS)
        self.allow_weekend_trading_checkbox.setChecked(
            self.full_config.ALLOW_WEEKEND_TRADING)
        self.gp_pop_spin.setValue(self.full_config.GP_POPULATION_SIZE)
        self.gp_gen_spin.setValue(self.full_config.GP_GENERATIONS)

        self.symbols_table.setRowCount(0)
        for symbol in self.full_config.SYMBOLS_WHITELIST:
            row_position = self.symbols_table.rowCount()
            self.symbols_table.insertRow(row_position)
            self.symbols_table.setItem(
                row_position, 0, QTableWidgetItem(symbol))

        self.db_folder_edit.setText(self.full_config.DATABASE_FOLDER)

        # Загрузка путей к векторной БД и логам
        vector_db_path = getattr(
            self.full_config.vector_db, 'path', 'vector_db')
        # Если путь относительный, добавляем к DATABASE_FOLDER
        if not os.path.isabs(vector_db_path):
            vector_db_full_path = os.path.join(
                self.full_config.DATABASE_FOLDER, vector_db_path)
        else:
            vector_db_full_path = vector_db_path
        self.vector_db_folder_edit.setText(vector_db_full_path)

        # Загрузка пути к логам (по умолчанию database/logs)
        logs_path = getattr(self.full_config, 'LOGS_FOLDER', os.path.join(
            self.full_config.DATABASE_FOLDER, 'logs'))
        self.logs_folder_edit.setText(logs_path)

        self._update_scheduler_status()

        # Загрузка настроек автообучения
        if hasattr(self.full_config, 'auto_retraining'):
            self.auto_retrain_checkbox.setChecked(
                self.full_config.auto_retraining.enabled)
            time_parts = self.full_config.auto_retraining.schedule_time.split(
                ':')
            self.auto_retrain_time_edit.setTime(
                QTime(int(time_parts[0]), int(time_parts[1])))
            self.auto_retrain_interval_spin.setValue(
                self.full_config.auto_retraining.interval_hours)
            self.auto_retrain_max_symbols_spin.setValue(
                self.full_config.auto_retraining.max_symbols)
            self.auto_retrain_max_workers_spin.setValue(
                self.full_config.auto_retraining.max_workers)
        else:
            # Значения по умолчанию
            self.auto_retrain_checkbox.setChecked(True)
            self.auto_retrain_time_edit.setTime(QTime(2, 0))
            self.auto_retrain_interval_spin.setValue(24)
            self.auto_retrain_max_symbols_spin.setValue(30)
            self.auto_retrain_max_workers_spin.setValue(3)

        # Загрузка настроек контроля прибыли
        self.profit_target_mode_combo.setCurrentText(
            getattr(self.full_config, 'PROFIT_TARGET_MODE', 'auto'))
        self.profit_target_manual_spin.setValue(
            getattr(self.full_config, 'PROFIT_TARGET_MANUAL_PERCENT', 5.0))
        self.reentry_profit_spin.setValue(
            getattr(self.full_config, 'REENTRY_COOLDOWN_AFTER_PROFIT', 60))
        self.reentry_loss_spin.setValue(
            getattr(self.full_config, 'REENTRY_COOLDOWN_AFTER_LOSS', 30))

        # Загрузка новых настроек контроля прибыли и интенсивности
        self.max_profit_close_spin.setValue(
            getattr(self.full_config, 'MAX_PROFIT_PER_TRADE_PERCENT', 5.0))
        self.profit_mode_combo.setCurrentText(
            getattr(self.full_config, 'PROFIT_MODE', 'auto'))
        self.trade_intensity_combo.setCurrentText(
            getattr(self.full_config, 'TRADE_INTENSITY', 'medium'))
        self.trade_interval_spin.setValue(
            getattr(self.full_config, 'TRADE_INTERVAL_SECONDS', 15))
        self.reentry_same_pair_combo.setCurrentText(
            getattr(self.full_config, 'REENTRY_SAME_PAIR_MODE', 'cooldown'))
        self.reentry_same_pair_cooldown_spin.setValue(
            getattr(self.full_config, 'REENTRY_SAME_PAIR_COOLDOWN_MINUTES', 30))

        maint_time_str = self.scheduler_manager.get_task_trigger_time(
            "GenesisMaintenance")
        if maint_time_str:
            self.maintenance_time_edit.setTime(
                QTime.fromString(maint_time_str, "HH:mm"))
        else:
            self.maintenance_time_edit.setTime(
                QTime(3, 0))  # Время по умолчанию

        # Загружаем время для задачи оптимизации
        opt_time_str = self.scheduler_manager.get_task_trigger_time(
            "GenesisWeeklyOptimization")
        if opt_time_str:
            self.optimization_time_edit.setTime(
                QTime.fromString(opt_time_str, "HH:mm"))
        else:
            self.optimization_time_edit.setTime(
                QTime(12, 0))  # Время по умолчанию

        # P0: Загрузка настроек уведомлений (Telegram/Email)
        config_values = dotenv_values(self.env_path)
        
        if hasattr(self.full_config, 'alerting'):
            alerting_config = self.full_config.alerting

            # Telegram
            telegram_config = alerting_config.channels.get('telegram', {})
            self.telegram_enabled_checkbox.setChecked(
                telegram_config.get('enabled', False))
            # Токен и chat_id загружаем из .env файла
            self.telegram_token_edit.setText(
                config_values.get('TELEGRAM_BOT_TOKEN', ''))
            self.telegram_chat_id_edit.setText(
                config_values.get('TELEGRAM_CHAT_ID', ''))

            # Email
            email_config = alerting_config.channels.get('email', {})
            self.email_enabled_checkbox.setChecked(
                email_config.get('enabled', False))
            self.email_smtp_edit.setText(
                email_config.get('smtp_server', 'smtp.gmail.com'))
            self.email_port_edit.setValue(email_config.get('smtp_port', 587))
            self.email_from_edit.setText(
                config_values.get('ALERT_EMAIL_FROM', ''))
            self.email_recipients_edit.setText(
                config_values.get('ALERT_EMAIL_RECIPIENTS', ''))
            # Пароль загружаем из .env
            self.email_password_edit.setText(
                config_values.get('ALERT_EMAIL_PASSWORD', ''))

            # Quiet Hours
            quiet_hours_config = alerting_config.get('quiet_hours', {})
            self.quiet_hours_enabled_checkbox.setChecked(
                quiet_hours_config.get('enabled', False))
            if quiet_hours_config.get('start'):
                self.quiet_hours_start_edit.setTime(
                    QTime.fromString(quiet_hours_config['start'], "HH:mm"))
            if quiet_hours_config.get('end'):
                self.quiet_hours_end_edit.setTime(
                    QTime.fromString(quiet_hours_config['end'], "HH:mm"))

            # Daily Digest
            digest_config = alerting_config.get('daily_digest', {})
            self.digest_enabled_checkbox.setChecked(
                digest_config.get('enabled', True))
            if digest_config.get('time'):
                self.digest_time_edit.setTime(
                    QTime.fromString(digest_config['time'], "HH:mm"))
        else:
            logger.warning("alerting конфигурация не найдена")

    def save_settings(self):
        # --- Сохранение .env (остается без изменений) ---
        for key, widget in self.mt5_entries.items():
            set_key(self.env_path, key, widget.text())

        # --- ИСПРАВЛЕННАЯ ЛОГИКА СОХРАНЕНИЯ settings.json ---
        try:
            # 1. Сначала загружаем текущую полную конфигурацию
            current_config = load_config().model_dump()

            # 2. Собираем новые значения из GUI
            symbols_list = []
            for row in range(self.symbols_table.rowCount()):
                item = self.symbols_table.item(row, 0)
                if item:
                    symbols_list.append(item.text())

            # 3. Создаем словарь только с теми настройками, которые мы меняем
            settings_to_update = {
                "RISK_PERCENTAGE": self.risk_percentage_spinbox.value(),
                "RISK_REWARD_RATIO": self.risk_reward_ratio_spinbox.value(),
                "MAX_DAILY_DRAWDOWN_PERCENT": self.max_daily_drawdown_spinbox.value(),
                "MAX_OPEN_POSITIONS": self.max_open_positions_spinbox.value(),
                "SYMBOLS_WHITELIST": symbols_list,
                "ALLOW_WEEKEND_TRADING": self.allow_weekend_trading_checkbox.isChecked(),
                "DATABASE_FOLDER": self.db_folder_edit.text(),
                "LOGS_FOLDER": self.logs_folder_edit.text(),
                "HF_MODELS_CACHE_DIR": self.hf_cache_edit.text() or None,

                "GP_POPULATION_SIZE": self.gp_pop_spin.value(),
                "GP_GENERATIONS": self.gp_gen_spin.value(),

                "web_dashboard": {
                    "enabled": self.web_enabled_checkbox.isChecked(),
                    "host": self.web_host_edit.text(),
                    "port": self.web_port_spinbox.value()

                },

                "vector_db": {
                    "enabled": self.full_config.vector_db.enabled,
                    "path": self._get_relative_vector_db_path(),
                    "collection_name": self.full_config.vector_db.collection_name,
                    "embedding_model": self.full_config.vector_db.embedding_model,
                    "cleanup_enabled": self.full_config.vector_db.cleanup_enabled,
                    "max_age_days": self.full_config.vector_db.max_age_days,
                    "cleanup_interval_hours": self.full_config.vector_db.cleanup_interval_hours
                },

                "auto_retraining": {
                    "enabled": self.auto_retrain_checkbox.isChecked(),
                    "schedule_time": self.auto_retrain_time_edit.time().toString("hh:mm"),
                    "interval_hours": self.auto_retrain_interval_spin.value(),
                    "max_symbols": self.auto_retrain_max_symbols_spin.value(),
                    "max_workers": self.auto_retrain_max_workers_spin.value()
                },

                "trading_mode": {
                    "current_mode": self.trading_mode_toggle.get_mode() if hasattr(self, 'trading_mode_toggle') else "paper",
                    "enabled": True  # Всегда включено с новым переключателем
                },

                "PROFIT_TARGET_MODE": self.profit_target_mode_combo.currentText(),
                "PROFIT_TARGET_MANUAL_PERCENT": self.profit_target_manual_spin.value(),
                "REENTRY_COOLDOWN_AFTER_PROFIT": self.reentry_profit_spin.value(),
                "REENTRY_COOLDOWN_AFTER_LOSS": self.reentry_loss_spin.value(),

                # Новые настройки контроля прибыли и интенсивности
                "MAX_PROFIT_PER_TRADE_PERCENT": self.max_profit_close_spin.value(),
                "PROFIT_MODE": self.profit_mode_combo.currentText(),
                "TRADE_INTENSITY": self.trade_intensity_combo.currentText(),
                "TRADE_INTERVAL_SECONDS": self.trade_interval_spin.value(),
                "REENTRY_SAME_PAIR_MODE": self.reentry_same_pair_combo.currentText(),
                "REENTRY_SAME_PAIR_COOLDOWN_MINUTES": self.reentry_same_pair_cooldown_spin.value()


            }

            # 4. Обновляем текущую конфигурацию новыми значениями
            # Это сохранит все остальные настройки, которые не были в GUI
            current_config.update(settings_to_update)

            # 5. Записываем полный, обновленный конфиг в файл
            if not write_config(current_config):
                QMessageBox.critical(
                    self, "Ошибка", "Не удалось сохранить настройки в settings.json.")

        except Exception as e:
            logger.error(
                f"Критическая ошибка при сохранении settings.json: {e}")
            QMessageBox.critical(
                self, "Ошибка", f"Не удалось сохранить настройки: {e}")

        # --- Сохранение API ключей (остается без изменений) ---
        try:
            initial_keys = {k for k, v in dotenv_values(self.env_path).items() if
                            k.endswith(('_KEY', '_TOKEN', '_ID', '_HASH')) and not k.startswith('MT5')}
            table_keys = set()
            for row in range(self.api_table.rowCount()):
                key_item = self.api_table.item(row, 0)
                value_item = self.api_table.item(row, 1)
                if key_item and value_item:
                    key = key_item.text()
                    value = value_item.text()
                    table_keys.add(key)
                    set_key(self.env_path, key, value)
            keys_to_delete = initial_keys - table_keys
            for key in keys_to_delete:
                set_key(self.env_path, key, "")
            logger.info("Настройки API ключей успешно сохранены в .env файл.")
        except Exception as e:
            logger.error(f"Произошла ошибка при сохранении API ключей: {e}")
            QMessageBox.critical(self, "Ошибка сохранения",
                                 f"Не удалось сохранить API ключи: {e}")

        self._handle_scheduler_tasks()

        # P0: Сохранение настроек уведомлений (Telegram/Email) — ДО записи settings.json
        try:
            # Сохраняем чувствительные данные в .env
            set_key(self.env_path, 'TELEGRAM_BOT_TOKEN',
                    self.telegram_token_edit.text())
            set_key(self.env_path, 'TELEGRAM_CHAT_ID',
                    self.telegram_chat_id_edit.text())
            set_key(self.env_path, 'ALERT_EMAIL_FROM',
                    self.email_from_edit.text())
            set_key(self.env_path, 'ALERT_EMAIL_RECIPIENTS',
                    self.email_recipients_edit.text())

            # Пароль сохраняем только если он был изменён
            if self.email_password_edit.text():
                set_key(self.env_path, 'ALERT_EMAIL_PASSWORD',
                        self.email_password_edit.text())

            # Обновляем current_config перед записью
            current_config['alerting'] = {
                'enabled': self.telegram_enabled_checkbox.isChecked() or self.email_enabled_checkbox.isChecked(),
                'channels': {
                    'telegram': {
                        'enabled': self.telegram_enabled_checkbox.isChecked(),
                        'bot_token_env': 'TELEGRAM_BOT_TOKEN',
                        'chat_id_env': 'TELEGRAM_CHAT_ID'
                    },
                    'email': {
                        'enabled': self.email_enabled_checkbox.isChecked(),
                        'smtp_server': self.email_smtp_edit.text(),
                        'smtp_port': self.email_port_edit.value(),
                        'use_tls': True,
                        'from_email_env': 'ALERT_EMAIL_FROM',
                        'password_env': 'ALERT_EMAIL_PASSWORD',
                        'recipients_env': 'ALERT_EMAIL_RECIPIENTS'
                    },
                    'push': {
                        'enabled': False,
                        'user_key_env': 'PUSHOVER_USER_KEY',
                        'api_token_env': 'PUSHOVER_API_TOKEN'
                    }
                },
                'rate_limit': {
                    'max_per_minute': 10,
                    'cooldown_seconds': 60
                },
                'quiet_hours': {
                    'enabled': self.quiet_hours_enabled_checkbox.isChecked(),
                    'start': self.quiet_hours_start_edit.time().toString("HH:mm"),
                    'end': self.quiet_hours_end_edit.time().toString("HH:mm"),
                    'timezone': 'UTC'
                },
                'daily_digest': {
                    'enabled': self.digest_enabled_checkbox.isChecked(),
                    'time': self.digest_time_edit.time().toString("HH:mm"),
                    'timezone': 'UTC'
                }
            }

            logger.info("Настройки уведомлений подготовлены к сохранению")

        except Exception as e:
            logger.error(f"Ошибка при подготовке настроек уведомлений: {e}")

        # Записываем обновлённый конфиг в файл
        try:
            if not write_config(current_config):
                QMessageBox.critical(
                    self, "Ошибка", "Не удалось сохранить настройки в settings.json.")
            else:
                logger.info("Настройки успешно сохранены в settings.json")

                # Обновляем конфигурацию в работающей системе
                self._update_running_system_config(current_config)

        except Exception as e:
            logger.error(f"Критическая ошибка при записи settings.json: {e}")
            QMessageBox.critical(
                self, "Ошибка", f"Не удалось сохранить настройки: {e}")

    def _update_running_system_config(self, new_config: dict):
        """
        Обновляет конфигурацию в работающей системе без перезапуска.

        Args:
            new_config: Новая конфигурация
        """
        try:
            if hasattr(self, 'full_config') and hasattr(self, 'scheduler_manager'):
                # Обновляем full_config
                from src.core.config_models import Settings
                try:
                    self.full_config = Settings(**new_config)
                    logger.info("Конфигурация обновлена в памяти")
                except Exception as e:
                    logger.warning(
                        f"Не удалось обновить конфигурацию в памяти: {e}")

                # Если есть ссылка на trading_system, обновляем настройки уведомлений
                if hasattr(self, 'trading_system') and self.trading_system:
                    try:
                        # Обновляем настройки alerting
                        if hasattr(self.trading_system, 'alert_manager'):
                            self.trading_system.alert_manager.config = self.full_config
                            logger.info("Alert Manager обновлён")
                    except Exception as e:
                        logger.warning(
                            f"Не удалось обновить trading_system: {e}")

        except Exception as e:
            logger.error(f"Ошибка обновления конфигурации: {e}")

    def accept(self):
        # Сначала сохраняем настройки, пока виджеты живы
        self.save_settings()

        # Уведомляем о сохранении
        self.settings_saved.emit()

        # Показываем сообщение (это блокирует выполнение, но виджеты еще существуют)
        QMessageBox.information(self, "Сохранено",
                                "Настройки успешно сохранены. Для их полного применения может потребоваться перезапуск системы.")

        # И только в самом конце закрываем окно
        super().accept()

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

        self.autostart_checkbox = QCheckBox(
            "Автозапуск системы при старте Windows")
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
            "Автоматическая ежедневная очистка и оптимизация базы данных.\n"
            "Рекомендуется запускать в нерабочее время рынка."
        )
        self.maintenance_time_edit = QTimeEdit()
        self.maintenance_time_edit.setDisplayFormat("hh:mm")
        self.maintenance_time_edit.setToolTip(
            "Время выполнения ежедневного обслуживания.")
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
        self.optimization_time_edit.setToolTip(
            "Время выполнения еженедельной оптимизации (суббота).")
        self.optimization_status_label = QLabel("Статус: Неизвестно")
        layout.addWidget(self.optimization_checkbox, 3, 0)
        layout.addWidget(self.optimization_time_edit, 3, 1)
        layout.addWidget(self.optimization_status_label, 3, 2)

        # --- НОВАЯ СЕКЦИЯ: Автоматическое переобучение моделей ---
        layout.addWidget(
            QLabel("\n<b>Автоматическое переобучение моделей</b>"), 4, 0, 1, 3)

        self.auto_retrain_checkbox = QCheckBox("Включить автообучение")
        self.auto_retrain_checkbox.setToolTip(
            "Автоматически переобучает AI-модели по расписанию.\n"
            "Система сама выбирает лучшие символы из всех доступных в MT5."
        )
        layout.addWidget(self.auto_retrain_checkbox, 5, 0)

        layout.addWidget(QLabel("Время запуска:"), 6, 0)
        self.auto_retrain_time_edit = QTimeEdit()
        self.auto_retrain_time_edit.setDisplayFormat("hh:mm")
        self.auto_retrain_time_edit.setToolTip(
            "Время суток для автоматического запуска обучения (рекомендуется ночью)")
        layout.addWidget(self.auto_retrain_time_edit, 6, 1)

        layout.addWidget(QLabel("Интервал (часов):"), 7, 0)
        self.auto_retrain_interval_spin = QSpinBox()
        self.auto_retrain_interval_spin.setRange(1, 168)  # От 1 часа до недели
        self.auto_retrain_interval_spin.setToolTip(
            "Интервал между запусками обучения (в часах)")
        layout.addWidget(self.auto_retrain_interval_spin, 7, 1)

        layout.addWidget(QLabel("Макс. символов:"), 8, 0)
        self.auto_retrain_max_symbols_spin = QSpinBox()
        self.auto_retrain_max_symbols_spin.setRange(5, 200)
        self.auto_retrain_max_symbols_spin.setToolTip(
            "Максимальное количество символов для обучения.\n"
            "Система автоматически отберёт лучшие из всех доступных."
        )
        layout.addWidget(self.auto_retrain_max_symbols_spin, 8, 1)

        layout.addWidget(QLabel("Параллельных потоков:"), 9, 0)
        self.auto_retrain_max_workers_spin = QSpinBox()
        self.auto_retrain_max_workers_spin.setRange(1, 10)
        self.auto_retrain_max_workers_spin.setToolTip(
            "Количество параллельных потоков для обучения.\n"
            "Рекомендуется: CPU/2 (например, 3-4 для 8-ядерного процессора)"
        )
        layout.addWidget(self.auto_retrain_max_workers_spin, 9, 1)

        # Кнопка для ручного запуска
        self.manual_retrain_button = QPushButton("▶ Запустить обучение сейчас")
        self.manual_retrain_button.setToolTip(
            "Запустить переобучение моделей вручную.\n"
            "Полезно для тестирования или внепланового обновления стратегий."
        )
        self.manual_retrain_button.clicked.connect(
            self._trigger_manual_retraining)
        layout.addWidget(self.manual_retrain_button, 10, 0, 1, 2)

        self.auto_retrain_status_label = QLabel("Статус: не запланировано")
        self.auto_retrain_status_label.setToolTip(
            "Текущий статус задачи автоматического переобучения.")
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
        layout.addWidget(
            QLabel("\n<b>Контроль прибыли сделок</b>"), 12, 0, 1, 3)

        self.profit_target_mode_combo = QComboBox()
        self.profit_target_mode_combo.addItems(["auto", "manual"])
        self.profit_target_mode_combo.setToolTip(
            "auto - система сама определяет оптимальную прибыль\n"
            "manual - использовать фиксированное значение"
        )
        layout.addWidget(QLabel("Режим:"), 13, 0)
        layout.addWidget(self.profit_target_mode_combo, 13, 1)

        self.profit_target_manual_spin = QDoubleSpinBox()
        self.profit_target_manual_spin.setRange(0.1, 100.0)
        self.profit_target_manual_spin.setSuffix(" %")
        self.profit_target_manual_spin.setToolTip(
            "Фиксированный процент прибыли для закрытия сделки")
        layout.addWidget(QLabel("Целевая прибыль (%):"), 14, 0)
        layout.addWidget(self.profit_target_manual_spin, 14, 1)

        self.reentry_profit_spin = QSpinBox()
        self.reentry_profit_spin.setRange(1, 480)
        self.reentry_profit_spin.setSuffix(" мин")
        self.reentry_profit_spin.setToolTip(
            "Пауза перед повторным входом после прибыльной сделки")
        layout.addWidget(QLabel("Повторный вход после прибыли:"), 15, 0)
        layout.addWidget(self.reentry_profit_spin, 15, 1)

        self.reentry_loss_spin = QSpinBox()
        self.reentry_loss_spin.setRange(1, 480)
        self.reentry_loss_spin.setSuffix(" мин")
        self.reentry_loss_spin.setToolTip(
            "Пауза перед повторным входом после убыточной сделки")
        layout.addWidget(QLabel("Повторный вход после убытка:"), 16, 0)
        layout.addWidget(self.reentry_loss_spin, 16, 1)

        # --- НОВАЯ СЕКЦИЯ: Контроль прибыли и интенсивность сделок ---
        layout.addWidget(
            QLabel("\n<b>Контроль прибыли и интенсивность сделок</b>"), 17, 0, 1, 3)

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
            "Минимальный интервал между открытием новых сделок.\n"
            "Защищает от чрезмерной торговли."
        )
        layout.addWidget(self.trade_interval_spin, 21, 1)

        # Повторный вход на ту же пару
        layout.addWidget(QLabel("Повторный вход на ту же пару:"), 22, 0)
        self.reentry_same_pair_combo = QComboBox()
        self.reentry_same_pair_combo.addItems(
            ["allowed", "cooldown", "blocked"])
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
        self.reentry_same_pair_cooldown_spin.setToolTip(
            "Сколько минут ждать перед повторным входом на ту же валютную пару."
        )
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

        db_label = QLabel("Папка для баз данных (модели, история):")
        db_label.setToolTip(
            "Здесь будут храниться все данные системы: база данных SQLite с историей сделок,\n"
            "обученные AI-модели, логи состояний и бэкапы."
        )
        self.db_folder_edit = QLineEdit()
        db_browse_button = QPushButton("Обзор...")
        db_browse_button.clicked.connect(
            lambda: self._browse_folder(
                self.db_folder_edit, "Выберите папку для хранения данных")
        )
        db_layout.addWidget(db_label, 0, 0)
        db_layout.addWidget(self.db_folder_edit, 0, 1)
        db_layout.addWidget(db_browse_button, 0, 2)

        hf_label = QLabel("<b>Папка для кэша AI-моделей (SentenceTransformer):</b>")
        hf_label.setToolTip(
            "<b>Модель:</b> all-MiniLM-L6-v2 (90 MB)\n\n"
            "<b>Для чего нужна:</b>\n"
            "• Анализ новостей и заголовков\n"
            "• Поиск похожих событий в истории\n"
            "• Понимание смысла текстов (NLP)\n"
            "• Работа с графом знаний (Knowledge Graph)\n\n"
            "<b>Как работает:</b>\n"
            "При первом запуске модель скачивается из интернета (~90 MB).\n"
            "Повторная загрузка не требуется — модель берётся из кэша.\n\n"
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
        self.hf_cache_edit.setPlaceholderText("Например: D:/AI_Models_Cache")
        self.hf_cache_edit.setToolTip(
            "Путь к папке где будут храниться AI модели.\n"
            "Оставьте пустым для использования пути по умолчанию."
        )
        hf_browse_button = QPushButton("📁 Обзор...")
        hf_browse_button.setCursor(Qt.PointingHandCursor)
        hf_browse_button.clicked.connect(
            lambda: self._browse_folder(
                self.hf_cache_edit, "Выберите папку для кэша AI-моделей")
        )
        db_layout.addWidget(hf_label, 1, 0)
        db_layout.addWidget(self.hf_cache_edit, 1, 1)
        db_layout.addWidget(hf_browse_button, 1, 2)

        # Папка для векторной БД
        vector_db_label = QLabel("Папка для векторной базы данных:")
        vector_db_label.setToolTip(
            "Здесь будет храниться векторная база данных FAISS для поиска по новостям и событиям.\n"
            "Рекомендуется размещать в той же папке, что и основная БД."
        )
        self.vector_db_folder_edit = QLineEdit()
        vector_db_browse_button = QPushButton("Обзор...")
        vector_db_browse_button.clicked.connect(
            lambda: self._browse_folder(
                self.vector_db_folder_edit, "Выберите папку для векторной БД")
        )
        db_layout.addWidget(vector_db_label, 2, 0)
        db_layout.addWidget(self.vector_db_folder_edit, 2, 1)
        db_layout.addWidget(vector_db_browse_button, 2, 2)

        # Папка для логов
        logs_label = QLabel("Папка для логов системы:")
        logs_label.setToolTip(
            "Здесь будут храниться файлы логов работы системы.\n"
            "Рекомендуется периодически очищать старые логи."
        )
        self.logs_folder_edit = QLineEdit()
        logs_browse_button = QPushButton("Обзор...")
        logs_browse_button.clicked.connect(
            lambda: self._browse_folder(
                self.logs_folder_edit, "Выберите папку для логов")
        )
        db_layout.addWidget(logs_label, 3, 0)
        db_layout.addWidget(self.logs_folder_edit, 3, 1)
        db_layout.addWidget(logs_browse_button, 3, 2)

        layout.addWidget(db_group, 0, 0, 1, 3)

        # --- НОВАЯ ГРУППА: Настройки Web-Dashboard ---
        web_group = QGroupBox("Настройки Web-Dashboard")
        web_layout = QGridLayout(web_group)

        self.web_enabled_checkbox = QCheckBox("Включить Web-Dashboard")
        self.web_enabled_checkbox.setToolTip(
            "Включает/отключает запуск веб-сервера для удаленного мониторинга.")
        web_layout.addWidget(self.web_enabled_checkbox, 0, 0, 1, 3)

        web_layout.addWidget(QLabel("Хост (IP адрес):"), 1, 0)
        self.web_host_edit = QLineEdit()
        self.web_host_edit.setToolTip(
            "IP адрес, на котором будет слушать сервер (0.0.0.0 для всех).")
        web_layout.addWidget(self.web_host_edit, 1, 1)

        web_layout.addWidget(QLabel("Порт:"), 2, 0)
        self.web_port_spinbox = QSpinBox()
        self.web_port_spinbox.setRange(1024, 65535)
        self.web_port_spinbox.setToolTip(
            "Порт, на котором будет доступен дашборд (по умолчанию 8000).")
        web_layout.addWidget(self.web_port_spinbox, 2, 1)

        layout.addWidget(web_group, 1, 0, 1, 3)

        layout.setRowStretch(2, 1)
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
        title.setToolTip(
            "Настройте каналы для получения торговых уведомлений и алертов системы.")
        layout.addWidget(title)

        # --- Группа: Telegram ---
        telegram_group = QGroupBox("Telegram уведомления")
        telegram_layout = QGridLayout(telegram_group)
        telegram_layout.setColumnStretch(1, 1)

        # Включить Telegram
        self.telegram_enabled_checkbox = QCheckBox(
            "Включить Telegram уведомления")
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
        self.telegram_token_toggle_btn.setToolTip(
            "Показать или скрыть токен бота")
        self.telegram_token_toggle_btn.clicked.connect(
            lambda: self._toggle_password_visibility(
                self.telegram_token_edit, self.telegram_token_toggle_btn)
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
        telegram_help.setStyleSheet(
            "background-color: #f0f0f0; padding: 10px; border-radius: 5px;")
        telegram_help.setToolTip(
            "Следуйте инструкции для быстрой настройки Telegram уведомлений")
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
            "Порт SMTP сервера.\n\n"
            "• 587 — TLS (рекомендуется)\n"
            "• 465 — SSL\n"
            "• 25 — без шифрования (не рекомендуется)"
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
            lambda: self._toggle_password_visibility(
                self.email_password_edit, self.email_password_toggle_btn)
        )
        email_layout.addWidget(self.email_password_toggle_btn, 4, 2)

        # Recipients
        email_layout.addWidget(QLabel("Получатели (через запятую):"), 5, 0)
        self.email_recipients_edit = QLineEdit()
        self.email_recipients_edit.setPlaceholderText(
            "recipient1@example.com, recipient2@example.com")
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
        email_help.setStyleSheet(
            "background-color: #f0f0f0; padding: 10px; border-radius: 5px;")
        email_help.setToolTip(
            "Следуйте инструкции для быстрой настройки Email уведомлений")
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
        quiet_hours_layout.addWidget(
            self.quiet_hours_enabled_checkbox, 0, 0, 1, 3)

        # Начало
        quiet_hours_layout.addWidget(QLabel("Начало:"), 1, 0)
        self.quiet_hours_start_edit = QTimeEdit()
        self.quiet_hours_start_edit.setTime(QTime(22, 0))
        self.quiet_hours_start_edit.setDisplayFormat("HH:mm")
        self.quiet_hours_start_edit.setToolTip(
            "Время начала тихих часов.\n\n"
            "Рекомендуется: 22:00"
        )
        quiet_hours_layout.addWidget(self.quiet_hours_start_edit, 1, 1)

        # Конец
        quiet_hours_layout.addWidget(QLabel("Конец:"), 2, 0)
        self.quiet_hours_end_edit = QTimeEdit()
        self.quiet_hours_end_edit.setTime(QTime(8, 0))
        self.quiet_hours_end_edit.setDisplayFormat("HH:mm")
        self.quiet_hours_end_edit.setToolTip(
            "Время окончания тихих часов.\n\n"
            "Рекомендуется: 08:00"
        )
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
            "Время отправки дневного дайджеста.\n\n"
            "Рекомендуется: 20:00 (после закрытия торгов)"
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
            QMessageBox.warning(
                self, "Ошибка", "Заполните Bot Token и Chat ID")
            return

        # Останавливаем предыдущий тест если он ещё идёт
        if hasattr(self, 'telegram_tester') and self.telegram_tester.isRunning():
            self.telegram_tester.quit()
            self.telegram_tester.wait(1000)  # Ждём до 1 сек

        # Создаём и запускаем тестер
        self.telegram_tester = TelegramTester(token, chat_id)
        self.telegram_tester.result_ready.connect(
            self._on_telegram_test_complete)
        self.telegram_tester.finished.connect(
            self._on_telegram_tester_finished)
        self.telegram_tester.start()

    def _on_telegram_test_complete(self, success: bool, message: str):
        """Обработка результата тестирования Telegram."""
        from PySide6.QtWidgets import QMessageBox
        if success:
            QMessageBox.information(self, "Успех", message)
        else:
            QMessageBox.critical(self, "Ошибка", message)

    def _on_telegram_tester_finished(self):
        """Очистка после завершения тестера."""
        if hasattr(self, 'telegram_tester'):
            self.telegram_tester.deleteLater()

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

        # Останавливаем предыдущий тест если он ещё идёт
        if hasattr(self, 'email_tester') and self.email_tester.isRunning():
            self.email_tester.quit()
            self.email_tester.wait(1000)

        # Создаём и запускаем тестер
        self.email_tester = EmailTester(smtp_server, smtp_port, email_from,
                                        email_password, recipients)
        self.email_tester.result_ready.connect(self._on_email_test_complete)
        self.email_tester.finished.connect(self._on_email_tester_finished)
        self.email_tester.start()

    def _on_email_test_complete(self, success: bool, message: str):
        """Обработка результата тестирования Email."""
        from PySide6.QtWidgets import QMessageBox
        if success:
            QMessageBox.information(self, "Успех", message)
        else:
            QMessageBox.critical(self, "Ошибка", message)

    def _on_email_tester_finished(self):
        """Очистка после завершения тестера."""
        if hasattr(self, 'email_tester'):
            self.email_tester.deleteLater()

    def _browse_folder(self, line_edit_widget, title):
        dir_path = QFileDialog.getExistingDirectory(self, title)
        if dir_path:
            line_edit_widget.setText(dir_path)

    def _get_relative_vector_db_path(self):
        """Получить относительный путь к векторной БД относительно DATABASE_FOLDER"""
        vector_db_path = self.vector_db_folder_edit.text()
        db_folder = self.db_folder_edit.text()

        # Если путь начинается с DATABASE_FOLDER, делаем его относительным
        if vector_db_path.startswith(db_folder):
            relative_path = os.path.relpath(vector_db_path, db_folder)
            return relative_path.replace('\\', '/')
        else:
            # Если путь вне DATABASE_FOLDER, сохраняем абсолютный
            return vector_db_path.replace('\\', '/')

    def _find_env_file(self):
        project_root = Path(__file__).parent.parent.parent
        configs_dir = project_root / 'configs'
        configs_dir.mkdir(exist_ok=True)
        env_path = configs_dir / '.env'
        if not env_path.exists():
            env_path.touch()
        return str(env_path)

    def _create_mt5_tab(self):
        content_widget = QWidget()
        layout = QGridLayout(content_widget)
        self.mt5_entries = {}
        self.mt5_entries["MT5_LOGIN"] = QLineEdit()
        self.mt5_entries["MT5_PASSWORD"] = QLineEdit(
            echoMode=QLineEdit.Password)
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
        self.api_table.setHorizontalHeaderLabels(
            ["Источник", "API Ключ", "Действие", "Статус"])
        self.api_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self.api_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.api_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents)
        self.api_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents)
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
            ("GenesisTraderAutostart", self.autostart_checkbox,
             self.autostart_status_label, None),
            (
                "GenesisMaintenance", self.maintenance_checkbox, self.maintenance_status_label,
                self.maintenance_time_edit),
            ("GenesisWeeklyOptimization", self.optimization_checkbox, self.optimization_status_label,
             self.optimization_time_edit)
        ]
        scheduler_summary = {}

        for task_name, checkbox, status_label, time_edit_widget in tasks:
            if self.scheduler_manager.task_exists(task_name):
                checkbox.setChecked(True)
                status_label.setText("Статус: АКТИВНА")
                status_label.setStyleSheet("color: #50fa7b;")

                # --- Добавляем время в сводку, если оно есть ---
                time_str = self.scheduler_manager.get_task_trigger_time(
                    task_name)
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
                "checkbox": self.autostart_checkbox, "task_name": "GenesisTraderAutostart",
                "script_name": "start_genesis.bat", "trigger": "ONSTART"
            },
            {
                "checkbox": self.maintenance_checkbox, "task_name": "GenesisMaintenance",
                "script_name": "maintenance.bat", "trigger": "DAILY", "time": maintenance_time_str
            },
            {
                "checkbox": self.optimization_checkbox, "task_name": "GenesisWeeklyOptimization",
                "script_name": "optimize_all.bat", "trigger": "WEEKLY", "time": optimization_time_str, "day": "SAT"
            }
        ]

        for task_info in tasks_to_manage:
            is_checked = task_info["checkbox"].isChecked()
            task_exists = self.scheduler_manager.task_exists(
                task_info["task_name"])

            if is_checked:
                # Если флажок установлен, всегда создаем/перезаписываем задачу с новым временем
                success, message = self.scheduler_manager.create_task(
                    task_name=task_info["task_name"],
                    script_name=task_info["script_name"],
                    trigger_type=task_info["trigger"],
                    trigger_time=task_info.get("time"),
                    trigger_day=task_info.get("day")
                )
                if not success:
                    QMessageBox.warning(
                        self, f"Ошибка создания/обновления задачи '{task_info['task_name']}'", message)
            elif not is_checked and task_exists:
                # Если флажок снят и задача существует, удаляем ее
                success, message = self.scheduler_manager.delete_task(
                    task_info["task_name"])
                if not success:
                    QMessageBox.warning(
                        self, f"Ошибка удаления задачи '{task_info['task_name']}'", message)

        self._update_scheduler_status()

    def _browse_mt5_path(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите terminal64.exe", "", "Executable files (*.exe)")
        if file_path:
            self.mt5_entries["MT5_PATH"].setText(file_path)

    def _test_mt5_connection(self):
        settings = {key: widget.text()
                    for key, widget in self.mt5_entries.items()}
        self.test_status_label.setText("Подключение...")
        self.test_status_label.setStyleSheet("color: orange;")
        self.connection_tester = ConnectionTester(settings)
        self.connection_tester.result_ready.connect(self._on_test_finished)
        self.connection_tester.start()

    def _on_test_finished(self, success, message):
        self.test_status_label.setText(message)
        self.test_status_label.setStyleSheet(
            "color: #50fa7b;" if success else "color: #ff5555;")

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
            status_label.setStyleSheet(
                "color: #50fa7b;" if success else "color: #ff5555;")
        if row in self.api_testers:
            del self.api_testers[row]

    def _add_row_to_api_table(self, key: str, value: str):
        row_position = self.api_table.rowCount()
        self.api_table.insertRow(row_position)
        self.api_table.setItem(row_position, 0, QTableWidgetItem(key))
        self.api_table.setItem(row_position, 1, QTableWidgetItem(value))
        check_button = QPushButton("Проверить")
        check_button.clicked.connect(
            lambda checked=False, row=row_position: self._test_api_key(row))
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
            QMessageBox.warning(
                self, "Внимание", "Пожалуйста, выберите ключ для удаления.")

    def _trigger_manual_retraining(self):
        """Запускает ручное переобучение моделей."""
        reply = QMessageBox.question(
            self,
            'Подтверждение',
            f"Запустить переобучение {self.auto_retrain_max_symbols_spin.value()} символов в {self.auto_retrain_max_workers_spin.value()} потоков?\n\n"
            f"Это может занять несколько минут. Продолжить?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
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
                            max_workers=self.auto_retrain_max_workers_spin.value()
                        )
                        # Обновляем статус в GUI потокобезопасным способом
                        self.auto_retrain_status_label.setText(
                            "Статус: завершено ✓")
                        self.auto_retrain_status_label.setStyleSheet(
                            "color: #50fa7b;")
                        self.manual_retrain_button.setEnabled(True)
                    except Exception as e:
                        logger.error(
                            f"Ошибка при ручном переобучении: {e}", exc_info=True)
                        self.auto_retrain_status_label.setText(
                            f"Статус: ошибка ❌")
                        self.auto_retrain_status_label.setStyleSheet(
                            "color: #ff5555;")
                        self.manual_retrain_button.setEnabled(True)

                training_thread = threading.Thread(
                    target=run_training, daemon=True)
                training_thread.start()

                QMessageBox.information(
                    self,
                    "Обучение запущено",
                    "Переобучение моделей запущено в фоновом режиме.\n"
                    "Процесс можно отслеживать в логах."
                )

            except Exception as e:
                logger.error(f"Ошибка запуска обучения: {e}", exc_info=True)
                self.auto_retrain_status_label.setText("Статус: ошибка ❌")
                self.auto_retrain_status_label.setStyleSheet("color: #ff5555;")
                self.manual_retrain_button.setEnabled(True)
                QMessageBox.critical(
                    self, "Ошибка", f"Не удалось запустить обучение:\n{e}")

    def _scroll_to_risk_settings(self):
        """Информирование пользователя о настройках риск-менеджмента."""
        # Вкладка уже активна, пользователь может прокрутить вниз самостоятельно
        logger.info(
            "📊 Выбран кастомный режим - настройки риск-менеджмента ниже")

    def _on_trading_mode_changed(self, mode_id: str, settings: dict):
        """Обработка изменения режима торговли."""
        logger.info(f"🎯 Режим торговли изменен на: {mode_id}")

        # Обработка отключения режимов
        if mode_id == "disabled":
            # Обновляем метку в TradingModesWidget
            if hasattr(self, 'trading_modes_widget'):
                self.trading_modes_widget.current_mode_label.setText(
                    "⚙️ Режимы торговли ОТКЛЮЧЕНЫ")
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
                if hasattr(self.parent(), 'trading_system'):
                    self.parent().trading_system.set_trading_mode("disabled", {})
                    logger.info(
                        "✅ Режимы торговли отключены - система использует базовые настройки")
            except Exception as e:
                logger.error(f"❌ Ошибка при отключении режимов: {e}")
            return

        # Обновляем метку в TradingModesWidget
        if hasattr(self, 'trading_modes_widget'):
            mode_data = TRADING_MODES.get(mode_id, {})
            mode_name = mode_data.get("name", "Кастомный")
            mode_icon = mode_data.get("icon", "🔧")

            self.trading_modes_widget.current_mode_label.setText(
                f"Текущий режим: {mode_icon} {mode_name}")

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
            if hasattr(self.parent(), 'trading_system'):
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
            current_mode = getattr(self.full_config, 'trading_mode', {}).get(
                'current_mode', 'standard')
            # Получаем состояние включения режимов
            modes_enabled = getattr(
                self.full_config, 'trading_mode', {}).get('enabled', False)

            # Устанавливаем режим в виджете
            if hasattr(self, 'trading_modes_widget'):
                # Блокируем/разблокируем контейнер в зависимости от состояния
                self.trading_modes_widget.modes_container.setEnabled(
                    modes_enabled)
                # Устанавливаем чекбокс в заголовке
                if hasattr(self, 'trading_modes_enable_checkbox'):
                    self.trading_modes_enable_checkbox.setChecked(
                        modes_enabled)

                self.trading_modes_widget.set_mode(current_mode)
                # Метка обновится автоматически в set_mode через on_mode_selected

        except Exception as e:
            logger.error(f"Ошибка загрузки текущего режима: {e}")
