# src/gui/control_center_widget.py
import logging
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QTableWidget, QTableWidgetItem, QTextEdit, QHeaderView,
                               QTabWidget, QGroupBox, QGridLayout, QSlider, QDoubleSpinBox,
                               QComboBox, QPushButton, QMessageBox, QRadioButton)
from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtGui import QColor

logger = logging.getLogger(__name__)


class ControlCenterWidget(QWidget):
    """
    Объединенный виджет: Дашборд (Сканер + Логи) и Панель Управления (Риски).
    """
    settings_changed = Signal(object)

    def __init__(self, bridge, config=None, trading_system_adapter=None):
        super().__init__()
        self.bridge = bridge
        self.config = config
        self.trading_system = trading_system_adapter

        # --- ИСПРАВЛЕНИЕ: Правильный доступ к стратегиям через core_system ---
        if self.trading_system and hasattr(self.trading_system, 'core_system'):
            self.strategies = self.trading_system.core_system.strategies
        else:
            self.strategies = {}
        # ---------------------------------------------------------------------

        # 1. Сначала строим интерфейс
        self.init_ui()

        # 2. И только ПОТОМ подключаем сигналы
        self._connect_signals()

    def _connect_signals(self):
        """Явное подключение сигналов с проверкой."""
        if self.bridge:
            logger.info("GUI: Подключение сигналов моста...")
            # Логи
            self.bridge.log_message_added.connect(self.append_log)
            # Статус
            self.bridge.status_updated.connect(self.update_status)
            # Сканер рынка
            self.bridge.market_scan_updated.connect(self.update_market_table)
            # Торговые сигналы (если есть отдельный сигнал)
            if hasattr(self.bridge, 'trading_signals_updated'):
                self.bridge.trading_signals_updated.connect(self.update_trading_signals_table)
            logger.info("GUI: Сигналы успешно подключены.")
        else:
            logger.error("GUI ОШИБКА: Bridge не передан в ControlCenterWidget!")

    def prepare_control_center_data(self, raw_data: list) -> list:
        """
        Подготавливает данные для ControlCenterWidget из сырых данных.
        """
        logger.info(f"[PrepareData] Обработка {len(raw_data) if raw_data else 0} элементов")
        processed_data = []
        for item in raw_data:
            # Логирование первого элемента для отладки
            if len(processed_data) == 0:
                logger.info(f"[PrepareData] Исходный элемент: {item}")
            
            processed_item = {
                'symbol': item.get('symbol', 'N/A'),
                'price': item.get('price', item.get('last_close', 0)),
                'change_24h': item.get('change_24h', item.get('normalized_atr_percent', 0)),
                # RSI берём напрямую, без масштабирования
                'rsi': item.get('rsi', item.get('trend_score', 50.0) * 50),
                'volatility': item.get('volatility', item.get('volatility_score', 0)),
                # Режим берём из правильного поля
                'regime': item.get('regime', 'Unknown')
            }
            processed_data.append(processed_item)
        
        logger.info(f"[PrepareData] Обработано {len(processed_data)} элементов, первый: {processed_data[0] if processed_data else 'N/A'}")
        return processed_data

    def on_display_mode_changed(self):
        """Переключает режим отображения таблицы"""
        if self.signals_radio.isChecked():
            # Режим торговых сигналов
            self.market_table.setHorizontalHeaderLabels(["Символ", "Цена", "Сигнал", "Стратегия", "Таймфрейм", "Время"])
        else:
            # Режим рыночных данных
            self.market_table.setHorizontalHeaderLabels(["Символ", "Цена", "Изм. %", "RSI", "Волатильность", "Режим"])
        
        # Обновляем данные в таблице в соответствии с новым режимом
        if hasattr(self, '_last_market_data') and self._last_market_data:
            if self.signals_radio.isChecked():
                self.update_trading_signals_table(self._last_market_data)
            else:
                processed_data = self.prepare_control_center_data(self._last_market_data)
                self.update_market_table(processed_data)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        # Вкладка 1: Дашборд
        self.dashboard_tab = QWidget()
        self._init_dashboard_tab(self.dashboard_tab)
        self.tabs.addTab(self.dashboard_tab, "Дашборд")

        # Вкладка 2: Управление
        if self.config:
            self.controls_tab = QWidget()
            self._init_controls_tab(self.controls_tab)
            self.tabs.addTab(self.controls_tab, "Управление Рисками")

        main_layout.addWidget(self.tabs)

    def _init_dashboard_tab(self, parent_widget):
        layout = QVBoxLayout(parent_widget)

        # Статус
        status_layout = QHBoxLayout()
        self.status_label = QLabel("Статус: Ожидание данных...")
        self.status_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #bd93f9;")
        status_layout.addWidget(self.status_label)
        layout.addLayout(status_layout)

        # Сканер
        layout.addWidget(QLabel("Сканер Рынка (Топ символов):"))
        self.market_table = QTableWidget()
        self.market_table.setColumnCount(6)
        self.market_table.setHorizontalHeaderLabels(["Символ", "Цена", "Изм. %", "RSI", "Волатильность", "Режим"])
        self.market_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.market_table.setAlternatingRowColors(True)
        self.market_table.setStyleSheet(
            "alternate-background-color: #44475a; background-color: #282a36; color: #f8f8f2;")
        layout.addWidget(self.market_table)
        
        # Добавляем переключатель режимов
        signal_mode_layout = QHBoxLayout()
        self.market_radio = QRadioButton("Рыночные данные")
        self.signals_radio = QRadioButton("Торговые сигналы")
        self.market_radio.setChecked(True)  # по умолчанию показываем рыночные данные
        signal_mode_layout.addWidget(QLabel("Режим отображения:"))
        signal_mode_layout.addWidget(self.market_radio)
        signal_mode_layout.addWidget(self.signals_radio)
        layout.addLayout(signal_mode_layout)
        
        # Подключаем переключение режимов
        self.market_radio.toggled.connect(self.on_display_mode_changed)
        self.signals_radio.toggled.connect(self.on_display_mode_changed)

    def _init_controls_tab(self, parent_widget):
        layout = QVBoxLayout(parent_widget)
        layout.setAlignment(Qt.AlignTop)

        # Риски
        risk_group = self._create_risk_management_group()
        layout.addWidget(risk_group)

        # Стратегии
        strategy_group = self._create_strategy_config_group()
        layout.addWidget(strategy_group)

        # Кнопки
        btn_layout = QHBoxLayout()
        self.save_button = QPushButton("Применить настройки")
        self.save_button.clicked.connect(self._save_and_apply_settings)
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_button)
        layout.addLayout(btn_layout)

        self.load_initial_settings()

    def _create_risk_management_group(self) -> QGroupBox:
        group_box = QGroupBox("Панель Управления Рисками")
        layout = QGridLayout(group_box)

        layout.addWidget(QLabel("Общая Агрессивность:"), 0, 0)
        self.aggressiveness_slider = QSlider(Qt.Horizontal)
        self.aggressiveness_slider.setRange(0, 100)
        self.aggressiveness_slider.valueChanged.connect(self._update_risk_labels)
        layout.addWidget(self.aggressiveness_slider, 0, 1)
        self.aggressiveness_label = QLabel("1.0% | 5 поз.")
        layout.addWidget(self.aggressiveness_label, 0, 2)

        layout.addWidget(QLabel("Макс. Дневная Просадка (%):"), 1, 0)
        self.daily_drawdown_spinbox = QDoubleSpinBox()
        self.daily_drawdown_spinbox.setRange(1.0, 20.0)
        self.daily_drawdown_spinbox.setSingleStep(0.5)
        layout.addWidget(self.daily_drawdown_spinbox, 1, 1)

        return group_box

    def _create_strategy_config_group(self) -> QGroupBox:
        group_box = QGroupBox("Конфигуратор Стратегий")
        layout = QVBoxLayout(group_box)

        self.regime_table = QTableWidget()
        self.regime_table.setColumnCount(2)
        self.regime_table.setHorizontalHeaderLabels(["Рыночный Режим", "Основная Стратегия"])
        self.regime_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.regime_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.regime_table)

        return group_box

    # --- СЛОТЫ ОБНОВЛЕНИЯ ---

    @Slot(list)
    def update_market_table(self, data: list):
        """Обновляет таблицу сканера."""
        # Логирование для отладки
        logger.info(f"[MarketTable] Получено данных: {len(data) if data else 0}")
        if data and len(data) > 0:
            logger.info(f"[MarketTable] Первый элемент: {data[0] if len(data) > 0 else 'N/A'}")

        if not data:
            logger.warning("[MarketTable] Данные пустые (data is None or empty)")
            return

        # ИСПРАВЛЕНИЕ: Игнорируем данные с малым количеством элементов (торговые сигналы)
        # Торговые сигналы приходят по 1 элементу, данные сканера - списком из 10+ элементов
        if len(data) < 2:  # Уменьшил порог с 5 до 2
            logger.warning(f"[MarketTable] Мало данных ({len(data)} элементов), возможно это торговый сигнал")
            return

        # Сохраняем последние данные для возможного переключения режимов
        self._last_market_data = data

        # Проверяем, в каком режиме мы находимся
        if hasattr(self, 'signals_radio') and self.signals_radio.isChecked():
            # Если включён режим торговых сигналов, используем другой метод
            logger.info("[MarketTable] Режим торговых сигналов, вызываем update_trading_signals_table")
            self.update_trading_signals_table(data)
            return

        # Убрано избыточное логирование

        # Подготавливаем данные для ControlCenterWidget
        processed_data = self.prepare_control_center_data(data)
        logger.info(f"[MarketTable] Обработано данных: {len(processed_data)}")

        # Отключаем сортировку для производительности
        self.market_table.setSortingEnabled(False)
        self.market_table.setRowCount(len(processed_data))
        # Убрано избыточное логирование

        for row_idx, item in enumerate(processed_data):
            # 1. Подготовка данных
            sym = str(item.get('symbol', 'N/A'))

            # Цена
            try:
                price_val = float(item.get('price', 0))
                price_str = f"{price_val:.5f}"
            except:
                price_str = "0.00000"

            # Изменение % (для цвета)
            try:
                chg_val = float(item.get('change_24h', 0))
                change_str = f"{chg_val:.2f}%"
            except:
                chg_val = 0.0
                change_str = "0.00%"

            # RSI
            try:
                rsi_val = float(item.get('rsi', 0))
                rsi_str = f"{rsi_val:.1f}"
            except:
                rsi_str = "0.0"

            # Волатильность
            try:
                vola_val = float(item.get('volatility', 0))
                vola_str = f"{vola_val:.4f}"
            except:
                vola_str = "0.0000"

            # Режим
            regime = str(item.get('regime', 'N/A'))

            # 2. Заполнение ячеек (ВСЕГО 6 КОЛОНОК)

            # Колонка 0: Символ
            self.market_table.setItem(row_idx, 0, QTableWidgetItem(sym))

            # Колонка 1: Цена
            self.market_table.setItem(row_idx, 1, QTableWidgetItem(price_str))

            # Колонка 2: Изменение % (с цветом)
            change_item = QTableWidgetItem(change_str)
            if chg_val > 0:
                change_item.setForeground(QColor("#50fa7b"))  # Зеленый
            elif chg_val < 0:
                change_item.setForeground(QColor("#ff5555"))  # Красный
            self.market_table.setItem(row_idx, 2, change_item)

            # Колонка 3: RSI
            self.market_table.setItem(row_idx, 3, QTableWidgetItem(rsi_str))

            # Колонка 4: Волатильность
            self.market_table.setItem(row_idx, 4, QTableWidgetItem(vola_str))

            # Колонка 5: Режим
            self.market_table.setItem(row_idx, 5, QTableWidgetItem(regime))

        # Включаем сортировку обратно
        self.market_table.setSortingEnabled(True)
        logger.info(f"[MarketTable] Таблица обновлена: {len(processed_data)} строк")

    @Slot(list)
    def update_trading_signals_table(self, data: list):
        """Обновляет таблицу торговых сигналов."""
        if not data: return
        
        # Сохраняем последние данные для возможного переключения режимов
        self._last_market_data = data
        
        # Проверяем, в каком режиме мы находимся
        if hasattr(self, 'market_radio') and self.market_radio.isChecked():
            # Если включён режим рыночных данных, используем другой метод
            processed_data = self.prepare_control_center_data(data)
            self.update_market_table(processed_data)
            return
        
        # Отключаем сортировку для производительности
        self.market_table.setSortingEnabled(False)
        self.market_table.setRowCount(len(data))

        for row_idx, item in enumerate(data):
            # 1. Подготовка данных для торговых сигналов
            sym = str(item.get('symbol', 'N/A'))
            signal_type = str(item.get('signal_type', 'N/A'))
            strategy = str(item.get('strategy', 'N/A'))
            timestamp = str(item.get('timestamp', 'N/A'))
            entry_price = item.get('entry_price', 0)
            timeframe = str(item.get('timeframe', 'N/A'))

            # Цена
            try:
                price_val = float(entry_price) if entry_price else 0
                price_str = f"{price_val:.5f}" if entry_price else "0.00000"
            except:
                price_str = "0.00000"

            # Изменение % - используем тип сигнала как индикатор
            change_str = signal_type
            chg_val = 1.0 if signal_type == 'BUY' else (-1.0 if signal_type == 'SELL' else 0.0)

            # RSI - используем стратегию
            rsi_str = strategy[:10]  # обрезаем до 10 символов

            # Волатильность - используем таймфрейм
            vola_str = timeframe

            # Режим - используем временную метку
            regime = timestamp

            # 2. Заполнение ячеек (ВСЕГО 6 КОЛОНОК)

            # Колонка 0: Символ
            self.market_table.setItem(row_idx, 0, QTableWidgetItem(sym))

            # Колонка 1: Цена
            self.market_table.setItem(row_idx, 1, QTableWidgetItem(price_str))

            # Колонка 2: Изменение % (с цвета)
            change_item = QTableWidgetItem(change_str)
            if chg_val > 0:
                change_item.setForeground(QColor("#50fa7b"))  # Зеленый
            elif chg_val < 0:
                change_item.setForeground(QColor("#ff5555"))  # Красный
            else:
                change_item.setForeground(QColor("#f8f8f2"))  # Белый
            self.market_table.setItem(row_idx, 2, change_item)

            # Колонка 3: RSI (Стратегия)
            self.market_table.setItem(row_idx, 3, QTableWidgetItem(rsi_str))

            # Колонка 4: Волатильность (Таймфрейм)
            self.market_table.setItem(row_idx, 4, QTableWidgetItem(vola_str))

            # Колонка 5: Режим (Время)
            self.market_table.setItem(row_idx, 5, QTableWidgetItem(regime))

        # Включаем сортировку обратно
        self.market_table.setSortingEnabled(True)

    @Slot(str, QColor)
    def append_log(self, message: str, color: QColor):
        # Системный лог удален из интерфейса
        pass

    @Slot(str, bool)
    def update_status(self, text, is_important):
        self.status_label.setText(f"Статус: {text}")
        color = "#ff5555" if is_important else "#50fa7b"
        self.status_label.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {color};")

    # --- Методы Настроек ---
    def load_initial_settings(self):
        if not self.config: return
        max_pos = self.config.MAX_OPEN_POSITIONS
        agg_value = int(((max_pos - 1) / 17.0) * 100) if max_pos < 18 else 100
        self.aggressiveness_slider.setValue(agg_value)
        self._update_risk_labels(agg_value)
        self.daily_drawdown_spinbox.setValue(self.config.MAX_DAILY_DRAWDOWN_PERCENT)

        regime_mapping = self.config.STRATEGY_REGIME_MAPPING
        available_strategies = ["AI_Model"]

        # --- ИСПРАВЛЕНИЕ: Безопасная загрузка стратегий ---
        if self.trading_system and hasattr(self.trading_system, 'core_system'):
            core = self.trading_system.core_system
            # Проверяем, что strategy_loader уже инициализирован
            if hasattr(core, 'strategy_loader') and core.strategy_loader is not None:
                try:
                    # Перезагружаем стратегии, чтобы получить актуальный список
                    strategies = core.strategy_loader.load_strategies()
                    available_strategies += [s.__class__.__name__ for s in strategies]
                except Exception as e:
                    logger.warning(f"GUI Warning: Не удалось загрузить стратегии: {e}")
        # --------------------------------------------------

        self.regime_table.setRowCount(len(regime_mapping))
        for i, (regime, strategy) in enumerate(regime_mapping.items()):
            self.regime_table.setItem(i, 0, QTableWidgetItem(regime))
            combo = QComboBox()
            combo.addItems(available_strategies)
            if strategy in available_strategies:
                combo.setCurrentText(strategy)
            self.regime_table.setCellWidget(i, 1, combo)
            self.regime_table.item(i, 0).setFlags(Qt.ItemIsEnabled)

    def _update_risk_labels(self, value):
        risk_percent = 0.5 + (value / 100.0) * 4.5
        max_pos = int(1 + (value / 100.0) * 17)
        self.aggressiveness_label.setText(f"{risk_percent:.1f}% | {max_pos} поз.")

    def _save_and_apply_settings(self):
        new_settings = {}
        agg_value = self.aggressiveness_slider.value()
        new_settings['RISK_PERCENTAGE'] = 0.5 + (agg_value / 100.0) * 4.5
        new_settings['MAX_OPEN_POSITIONS'] = int(1 + (agg_value / 100.0) * 17)
        new_settings['MAX_DAILY_DRAWDOWN_PERCENT'] = self.daily_drawdown_spinbox.value()

        new_regime_mapping = {}
        for i in range(self.regime_table.rowCount()):
            regime = self.regime_table.item(i, 0).text()
            combo = self.regime_table.cellWidget(i, 1)
            strategy = combo.currentText()
            new_regime_mapping[regime] = strategy
        new_settings['STRATEGY_REGIME_MAPPING'] = new_regime_mapping

        self.settings_changed.emit(new_settings)
        QMessageBox.information(self, "Успех", "Настройки применены!")

    def refresh_strategies(self):
        """
        Обновляет список доступных стратегий в выпадающих списках.
        Вызывается из главного окна после завершения инициализации.
        """
        self.load_initial_settings()