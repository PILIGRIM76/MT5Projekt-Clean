# src/gui/settings_window.py

import os
import subprocess
import sys
from dataclasses import Field

from dotenv import dotenv_values, set_key
from pathlib import Path
import logging


import MetaTrader5 as mt5
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QPushButton, QLabel, QLineEdit, QFrame,
                               QDialogButtonBox, QTabWidget, QWidget, QFileDialog,
                               QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QCheckBox,
                               QDoubleSpinBox, QSpinBox, QGroupBox, QTimeEdit, QComboBox)

from PySide6.QtGui import QColor
from PySide6.QtCore import Qt, QThread, Signal, QTime

from core.config_models import Settings
from pydantic import BaseModel

from .api_tester import ApiTester
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
                self.result_ready.emit(True, f"Успех! Счет #{account_info.login}")
            mt5.shutdown()
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
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
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
        self.setMinimumWidth(800)
        self.setModal(True)

        self.env_path = self._find_env_file()
        self.connection_tester = None
        self.api_testers = {}
        self.scheduler_manager = scheduler_manager

        self.full_config = config

        main_layout = QVBoxLayout(self)
        tab_widget = QTabWidget()
        main_layout.addWidget(tab_widget)

        mt5_tab = self._create_mt5_tab()
        api_tab = self._create_api_tab()
        trading_tab = self._create_trading_tab()
        paths_tab = self._create_paths_tab()
        scheduler_tab = self._create_scheduler_tab()
        gp_tab = self._create_gp_tab()
        tab_widget.addTab(gp_tab, "R&D (AI)")

        tab_widget.addTab(mt5_tab, "Подключение MT5")
        tab_widget.addTab(api_tab, "API Ключи")
        tab_widget.addTab(trading_tab, "Торговля")
        tab_widget.addTab(paths_tab, "Пути к данным")
        tab_widget.addTab(scheduler_tab, "Планировщик")

        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

        self.load_settings()

    def _create_gp_tab(self):
        widget = QWidget()
        layout = QGridLayout(widget)
        layout.setAlignment(Qt.AlignTop)

        layout.addWidget(QLabel("<b>Настройки Генетического Программирования (R&D)</b>"), 0, 0, 1, 2)

        layout.addWidget(QLabel("Размер популяции (GP_POPULATION_SIZE):"), 1, 0)
        self.gp_pop_spin = QSpinBox()
        self.gp_pop_spin.setRange(10, 1000)
        self.gp_pop_spin.setToolTip("Количество стратегий в одном поколении.")
        layout.addWidget(self.gp_pop_spin, 1, 1)

        layout.addWidget(QLabel("Количество поколений (GP_GENERATIONS):"), 2, 0)
        self.gp_gen_spin = QSpinBox()
        self.gp_gen_spin.setRange(1, 500)
        layout.addWidget(self.gp_gen_spin, 2, 1)

        return widget


    def _create_trading_tab(self):
        """Создает вкладку с настройками торговли и управления рисками."""
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setAlignment(Qt.AlignTop)

        # --- Группа Управления Рисками ---
        risk_group = QGroupBox("Управление Рисками")
        risk_layout = QGridLayout(risk_group)

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

        main_layout.addWidget(risk_group)

        # --- Группа Управления Позициями ---
        positions_group = QGroupBox("Управление Позициями")
        positions_layout = QGridLayout(positions_group)

        positions_layout.addWidget(QLabel("Макс. кол-во открытых позиций:"), 0, 0)
        self.max_open_positions_spinbox = QSpinBox()
        self.max_open_positions_spinbox.setRange(1, 100)
        self.max_open_positions_spinbox.setToolTip(
            "Максимальное количество одновременно открытых позиций по всем инструментам.")
        positions_layout.addWidget(self.max_open_positions_spinbox, 0, 1)

        self.allow_weekend_trading_checkbox = QCheckBox("Разрешить торговлю на выходных (для отладки)")
        self.allow_weekend_trading_checkbox.setToolTip(
            "Если включено, система будет игнорировать проверку на субботу и воскресенье.\nИспользовать только для тестирования и отладки, не на реальных счетах!"
        )
        positions_layout.addWidget(self.allow_weekend_trading_checkbox, 1, 0, 1, 2)

        main_layout.addWidget(positions_group)

        # --- Группа Управления Символами ---
        symbols_group = QGroupBox("Управление Торговыми Символами (Whitelist)")
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
        return widget

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
        api_keys = {k: v for k, v in config_values.items() if
                    k.endswith(('_KEY', '_TOKEN', '_ID', '_HASH')) and not k.startswith('MT5')}
        for key, value in api_keys.items():
            self._add_row_to_api_table(key, value)

        self.web_enabled_checkbox.setChecked(self.full_config.web_dashboard.enabled)
        self.web_host_edit.setText(self.full_config.web_dashboard.host)
        self.web_port_spinbox.setValue(self.full_config.web_dashboard.port)

        self.hf_cache_edit.setText(self.full_config.HF_MODELS_CACHE_DIR or "")
        self.risk_percentage_spinbox.setValue(self.full_config.RISK_PERCENTAGE)
        self.risk_reward_ratio_spinbox.setValue(self.full_config.RISK_REWARD_RATIO)
        self.max_daily_drawdown_spinbox.setValue(self.full_config.MAX_DAILY_DRAWDOWN_PERCENT)
        self.max_open_positions_spinbox.setValue(self.full_config.MAX_OPEN_POSITIONS)
        self.allow_weekend_trading_checkbox.setChecked(self.full_config.ALLOW_WEEKEND_TRADING)
        self.gp_pop_spin.setValue(self.full_config.GP_POPULATION_SIZE)
        self.gp_gen_spin.setValue(self.full_config.GP_GENERATIONS)

        self.symbols_table.setRowCount(0)
        for symbol in self.full_config.SYMBOLS_WHITELIST:
            row_position = self.symbols_table.rowCount()
            self.symbols_table.insertRow(row_position)
            self.symbols_table.setItem(row_position, 0, QTableWidgetItem(symbol))

        self.db_folder_edit.setText(self.full_config.DATABASE_FOLDER)
        self._update_scheduler_status()
        
        # Загрузка настроек автообучения
        if hasattr(self.full_config, 'auto_retraining'):
            self.auto_retrain_checkbox.setChecked(self.full_config.auto_retraining.enabled)
            time_parts = self.full_config.auto_retraining.schedule_time.split(':')
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
        self.profit_target_mode_combo.setCurrentText(getattr(self.full_config, 'PROFIT_TARGET_MODE', 'auto'))
        self.profit_target_manual_spin.setValue(getattr(self.full_config, 'PROFIT_TARGET_MANUAL_PERCENT', 5.0))
        self.reentry_profit_spin.setValue(getattr(self.full_config, 'REENTRY_COOLDOWN_AFTER_PROFIT', 60))
        self.reentry_loss_spin.setValue(getattr(self.full_config, 'REENTRY_COOLDOWN_AFTER_LOSS', 30))

        # Загрузка новых настроек контроля прибыли и интенсивности
        self.max_profit_close_spin.setValue(getattr(self.full_config, 'MAX_PROFIT_PER_TRADE_PERCENT', 5.0))
        self.profit_mode_combo.setCurrentText(getattr(self.full_config, 'PROFIT_MODE', 'auto'))
        self.trade_intensity_combo.setCurrentText(getattr(self.full_config, 'TRADE_INTENSITY', 'medium'))
        self.trade_interval_spin.setValue(getattr(self.full_config, 'TRADE_INTERVAL_SECONDS', 15))
        self.reentry_same_pair_combo.setCurrentText(getattr(self.full_config, 'REENTRY_SAME_PAIR_MODE', 'cooldown'))
        self.reentry_same_pair_cooldown_spin.setValue(getattr(self.full_config, 'REENTRY_SAME_PAIR_COOLDOWN_MINUTES', 30))

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
                "HF_MODELS_CACHE_DIR": self.hf_cache_edit.text() or None,  # <-- Исправлено

                "GP_POPULATION_SIZE": self.gp_pop_spin.value(),
                "GP_GENERATIONS": self.gp_gen_spin.value(),

                "web_dashboard": {
                    "enabled": self.web_enabled_checkbox.isChecked(),
                    "host": self.web_host_edit.text(),
                    "port": self.web_port_spinbox.value()

                },
                
                "auto_retraining": {
                    "enabled": self.auto_retrain_checkbox.isChecked(),
                    "schedule_time": self.auto_retrain_time_edit.time().toString("hh:mm"),
                    "interval_hours": self.auto_retrain_interval_spin.value(),
                    "max_symbols": self.auto_retrain_max_symbols_spin.value(),
                    "max_workers": self.auto_retrain_max_workers_spin.value()
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
                QMessageBox.critical(self, "Ошибка", "Не удалось сохранить настройки в settings.json.")

        except Exception as e:
            logger.error(f"Критическая ошибка при сохранении settings.json: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить настройки: {e}")

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
            QMessageBox.critical(self, "Ошибка сохранения", f"Не удалось сохранить API ключи: {e}")

        self._handle_scheduler_tasks()

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

        layout.addWidget(QLabel("<b>Управление фоновыми задачами</b>"), 0, 0, 1, 3)

        self.autostart_checkbox = QCheckBox("Автозапуск системы при старте Windows")
        self.autostart_status_label = QLabel("Статус: Неизвестно")
        layout.addWidget(self.autostart_checkbox, 1, 0)
        layout.addWidget(self.autostart_status_label, 1, 2)

        # Задача ежедневного обслуживания (с выбором времени)
        self.maintenance_checkbox = QCheckBox("Ежедневное обслуживание")
        self.maintenance_time_edit = QTimeEdit()
        self.maintenance_time_edit.setDisplayFormat("hh:mm")
        self.maintenance_status_label = QLabel("Статус: Неизвестно")
        layout.addWidget(self.maintenance_checkbox, 2, 0)
        layout.addWidget(self.maintenance_time_edit, 2, 1)  # Добавляем виджет времени
        layout.addWidget(self.maintenance_status_label, 2, 2)

        # Задача еженедельной оптимизации (с выбором времени)
        self.optimization_checkbox = QCheckBox("Еженедельная оптимизация (Сб)")
        self.optimization_time_edit = QTimeEdit()
        self.optimization_time_edit.setDisplayFormat("hh:mm")
        self.optimization_status_label = QLabel("Статус: Неизвестно")
        layout.addWidget(self.optimization_checkbox, 3, 0)
        layout.addWidget(self.optimization_time_edit, 3, 1)  # Добавляем виджет времени
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
        self.manual_retrain_button.setToolTip("Запустить переобучение моделей вручную")
        self.manual_retrain_button.clicked.connect(self._trigger_manual_retraining)
        layout.addWidget(self.manual_retrain_button, 10, 0, 1, 2)
        
        self.auto_retrain_status_label = QLabel("Статус: не запланировано")
        layout.addWidget(self.auto_retrain_status_label, 10, 2)

        info_label = QLabel(
            "\n<b>Внимание:</b> Для управления задачами программу необходимо запустить <b>от имени Администратора</b>."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label, 11, 0, 1, 3)

        # --- НОВАЯ СЕКЦИЯ: Целевая прибыль ---
        layout.addWidget(QLabel("\n<b>Контроль прибыли сделок</b>"), 12, 0, 1, 3)

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
            "Минимальный интервал между открытием новых сделок.\n"
            "Защищает от чрезмерной торговли."
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
        self.reentry_same_pair_cooldown_spin.setToolTip(
            "Сколько минут ждать перед повторным входом на ту же валютную пару."
        )
        layout.addWidget(self.reentry_same_pair_cooldown_spin, 23, 1)

        return widget

    def _create_paths_tab(self):
        widget = QWidget()
        layout = QGridLayout(widget)
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
            lambda: self._browse_folder(self.db_folder_edit, "Выберите папку для хранения данных")
        )
        db_layout.addWidget(db_label, 0, 0)
        db_layout.addWidget(self.db_folder_edit, 0, 1)
        db_layout.addWidget(db_browse_button, 0, 2)

        hf_label = QLabel("Папка для кэша AI-моделей (Hugging Face):")
        hf_label.setToolTip(
            "Здесь будут храниться большие языковые модели (несколько ГБ), скачанные из интернета.\n"
            "ВНИМАНИЕ: Изменение этого пути требует перезапуска программы!"
        )
        self.hf_cache_edit = QLineEdit()
        hf_browse_button = QPushButton("Обзор...")
        hf_browse_button.clicked.connect(
            lambda: self._browse_folder(self.hf_cache_edit, "Выберите папку для кэша AI-моделей")
        )
        db_layout.addWidget(hf_label, 1, 0)
        db_layout.addWidget(self.hf_cache_edit, 1, 1)
        db_layout.addWidget(hf_browse_button, 1, 2)

        layout.addWidget(db_group, 0, 0, 1, 3)

        # --- НОВАЯ ГРУППА: Настройки Web-Dashboard ---
        web_group = QGroupBox("Настройки Web-Dashboard")
        web_layout = QGridLayout(web_group)

        self.web_enabled_checkbox = QCheckBox("Включить Web-Dashboard")
        self.web_enabled_checkbox.setToolTip("Включает/отключает запуск веб-сервера для удаленного мониторинга.")
        web_layout.addWidget(self.web_enabled_checkbox, 0, 0, 1, 3)

        web_layout.addWidget(QLabel("Хост (IP адрес):"), 1, 0)
        self.web_host_edit = QLineEdit()
        self.web_host_edit.setToolTip("IP адрес, на котором будет слушать сервер (0.0.0.0 для всех).")
        web_layout.addWidget(self.web_host_edit, 1, 1)

        web_layout.addWidget(QLabel("Порт:"), 2, 0)
        self.web_port_spinbox = QSpinBox()
        self.web_port_spinbox.setRange(1024, 65535)
        self.web_port_spinbox.setToolTip("Порт, на котором будет доступен дашборд (по умолчанию 8000).")
        web_layout.addWidget(self.web_port_spinbox, 2, 1)

        layout.addWidget(web_group, 1, 0, 1, 3)


        layout.setRowStretch(2, 1)
        return widget

    def _browse_folder(self, line_edit_widget, title):
        dir_path = QFileDialog.getExistingDirectory(self, title)
        if dir_path:
            line_edit_widget.setText(dir_path)

    def _find_env_file(self):
        project_root = Path(__file__).parent.parent.parent
        configs_dir = project_root / 'configs'
        configs_dir.mkdir(exist_ok=True)
        env_path = configs_dir / '.env'
        if not env_path.exists():
            env_path.touch()
        return str(env_path)

    def _create_mt5_tab(self):
        widget = QWidget()
        layout = QGridLayout(widget)
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
        return widget

    def _create_api_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
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
        return widget

    def _update_scheduler_status(self):
        tasks = [
            ("GenesisTraderAutostart", self.autostart_checkbox, self.autostart_status_label, None),
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
            task_exists = self.scheduler_manager.task_exists(task_info["task_name"])

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
        if not service_name_item or not api_key_item: return
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
        if button: button.setEnabled(True)
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
                        self.auto_retrain_status_label.setText("Статус: завершено ✓")
                        self.auto_retrain_status_label.setStyleSheet("color: #50fa7b;")
                        self.manual_retrain_button.setEnabled(True)
                    except Exception as e:
                        logger.error(f"Ошибка при ручном переобучении: {e}", exc_info=True)
                        self.auto_retrain_status_label.setText(f"Статус: ошибка ❌")
                        self.auto_retrain_status_label.setStyleSheet("color: #ff5555;")
                        self.manual_retrain_button.setEnabled(True)
                
                training_thread = threading.Thread(target=run_training, daemon=True)
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
                QMessageBox.critical(self, "Ошибка", f"Не удалось запустить обучение:\n{e}")