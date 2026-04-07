# src/gui/control_center_widget.py
import logging

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

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
        if self.trading_system and hasattr(self.trading_system, "core_system"):
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
            if hasattr(self.bridge, "trading_signals_updated"):
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

            symbol = item.get("symbol", "N/A")

            # Определяем тип провайдера
            provider_type = "MT5"
            if self._is_crypto_symbol(symbol):
                provider_type = "Crypto"

            processed_item = {
                "symbol": symbol,
                "provider_type": provider_type,
                "price": item.get("price", item.get("last_close", 0)),
                "change_24h": item.get("change_24h", item.get("normalized_atr_percent", 0)),
                # RSI берём напрямую, без масштабирования
                "rsi": item.get("rsi", item.get("trend_score", 50.0) * 50),
                "volatility": item.get("volatility", item.get("volatility_score", 0)),
                # Режим берём из правильного поля
                "regime": item.get("regime", "Unknown"),
            }
            processed_data.append(processed_item)

        logger.info(
            f"[PrepareData] Обработано {len(processed_data)} элементов, первый: {processed_data[0] if processed_data else 'N/A'}"
        )
        return processed_data

    def _is_crypto_symbol(self, symbol: str) -> bool:
        """Проверяет, является ли символ криптовалютным."""
        if not symbol or symbol == "N/A":
            return False
        crypto_suffixes = ["USDT", "BTC", "ETH", "BUSD", "USDC", "BNB", "SOL", "XRP", "DOGE", "ADA"]
        upper_symbol = symbol.upper()
        return any(upper_symbol.endswith(suffix) or upper_symbol.startswith(suffix) for suffix in crypto_suffixes)

    def on_display_mode_changed(self):
        """Переключает режим отображения таблицы"""
        if self.signals_radio.isChecked():
            # Режим торговых сигналов
            self.market_table.setHorizontalHeaderLabels(["Символ", "Цена", "Сигнал", "Стратегия", "Таймфрейм", "Время"])
        else:
            # Режим рыночных данных
            self.market_table.setHorizontalHeaderLabels(["Символ", "Тип", "Цена", "Изм. %", "RSI", "Волатильность", "Режим"])

        # Обновляем данные в таблице в соответствии с новым режимом
        if hasattr(self, "_last_market_data") and self._last_market_data:
            if self.signals_radio.isChecked():
                # Проверяем, что это реальные торговые сигналы, а не данные сканера
                if self._last_market_data and "rank" not in self._last_market_data[0]:
                    self.update_trading_signals_table(self._last_market_data)
                else:
                    logger.debug("[ModeChange] Данные — сканер (есть rank), таблица сигналов очищена")
                    # Очищаем таблицу сигналов
                    self.market_table.setRowCount(0)
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
        self.market_table.setColumnCount(7)
        self.market_table.setHorizontalHeaderLabels(["Символ", "Тип", "Цена", "Изм. %", "RSI", "Волатильность", "Режим"])
        self.market_table.setRowCount(0)  # Начальная очистка
        self.market_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.market_table.setAlternatingRowColors(True)
        self.market_table.setStyleSheet("alternate-background-color: #44475a; background-color: #282a36; color: #f8f8f2;")
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

        # === ИНФОРМАЦИОННОЕ СООБЩЕНИЕ ===
        info_box = QGroupBox("ℹ️ Управление Настройками Торговли")
        info_layout = QVBoxLayout(info_box)

        info_label = QLabel(
            "⚙️ <b>Настройки торговли и риск-менеджмента находятся в окне настроек.</b>\n\n"
            "Для изменения параметров торговли:\n"
            "1. Откройте <b>Настройки</b> (меню или кнопка на панели)\n"
            "2. Перейдите на вкладку <b>'Торговля'</b>\n"
            "3. Выберите режим торговли или настройте параметры вручную\n\n"
            "📊 <b>Режимы торговли:</b>\n"
            "• 🟢 Консервативный - минимальный риск\n"
            "• 🟡 Стандартный - баланс риск/доходность\n"
            "• 🔴 Агрессивный - высокий риск\n"
            "• ⚫ YOLO - максимальный риск\n"
            "• 🔧 Кастомный - ручная настройка"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("""
            QLabel {
                color: #f8f8f2;
                padding: 10px;
                background-color: #282a36;
                border-radius: 5px;
            }
        """)
        info_layout.addWidget(info_label)

        # Кнопка открытия настроек
        open_settings_btn = QPushButton("⚙️ Открыть Настройки Торговли")
        open_settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #bd93f9;
                color: #282a36;
                padding: 12px 24px;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #a37df5;
            }
        """)
        # Сигнал будет подключён в MainWindow
        open_settings_btn.clicked.connect(self._open_settings_requested)
        info_layout.addWidget(open_settings_btn)

        layout.addWidget(info_box)

        # === КНОПКА ПРИНУДИТЕЛЬНОГО ОБУЧЕНИЯ ===
        training_box = QGroupBox("🧠 Обучение AI-моделей")
        training_layout = QVBoxLayout(training_box)

        training_label = QLabel(
            "Запустите принудительный цикл переобучения AI-моделей.\n"
            "Используйте после сбора новых данных или при ухудшении точности."
        )
        training_label.setWordWrap(True)
        training_label.setStyleSheet("color: #f8f8f2; padding: 5px;")
        training_layout.addWidget(training_label)

        self.force_train_btn = QPushButton("🚀 Запустить принудительное обучение")
        self.force_train_btn.setStyleSheet("""
            QPushButton {
                background-color: #50fa7b;
                color: #282a36;
                padding: 12px 24px;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3dd66a;
            }
            QPushButton:disabled {
                background-color: #6272a4;
                color: #44475a;
            }
        """)
        self.force_train_btn.clicked.connect(self._force_training_requested)
        training_layout.addWidget(self.force_train_btn)

        self.training_status_label = QLabel("Статус: Ожидание...")
        self.training_status_label.setStyleSheet("color: #8be9fd; font-size: 12px;")
        training_layout.addWidget(self.training_status_label)

        layout.addWidget(training_box)

        # === ТЕКУЩИЕ ПАРАМЕТРЫ (только для просмотра) ===
        summary_group = QGroupBox("📈 Текущие Параметры (только просмотр)")
        summary_group.setToolTip("Эти параметры применяются из настроек. Для изменения откройте Настройки.")
        summary_layout = QGridLayout(summary_group)

        # Риск на сделку
        summary_layout.addWidget(QLabel("🎯 Риск на сделку:"), 0, 0)
        self.current_risk_label = QLabel("0.50%")
        self.current_risk_label.setFont(self.font())
        self.current_risk_label.setStyleSheet("color: #50fa7b; font-weight: bold; font-size: 14px;")
        self.current_risk_label.setAlignment(Qt.AlignRight)
        summary_layout.addWidget(self.current_risk_label, 0, 1)

        # Max позиций
        summary_layout.addWidget(QLabel("📊 Max позиций:"), 1, 0)
        self.current_positions_label = QLabel("5")
        self.current_positions_label.setStyleSheet("color: #8be9fd; font-weight: bold; font-size: 14px;")
        self.current_positions_label.setAlignment(Qt.AlignRight)
        summary_layout.addWidget(self.current_positions_label, 1, 1)

        # Max дневная просадка
        summary_layout.addWidget(QLabel("📉 Max дневная просадка:"), 2, 0)
        self.current_drawdown_label = QLabel("5.00%")
        self.current_drawdown_label.setStyleSheet("color: #ff5555; font-weight: bold; font-size: 14px;")
        self.current_drawdown_label.setAlignment(Qt.AlignRight)
        summary_layout.addWidget(self.current_drawdown_label, 2, 1)

        # Режим торговли
        summary_layout.addWidget(QLabel("🏷️ Активный режим:"), 3, 0)
        self.current_mode_label = QLabel("🟡 Стандартный")
        self.current_mode_label.setStyleSheet("color: #f1fa8c; font-weight: bold; font-size: 14px;")
        self.current_mode_label.setAlignment(Qt.AlignRight)
        summary_layout.addWidget(self.current_mode_label, 3, 1)

        summary_layout.setColumnStretch(0, 1)
        summary_layout.setColumnStretch(1, 1)
        layout.addWidget(summary_group)

        # Стратегии
        strategy_group = self._create_strategy_config_group()
        layout.addWidget(strategy_group)

        layout.addStretch()

    def _open_settings_requested(self):
        """Сигнал для открытия окна настроек."""
        # Ищем родительское окно и вызываем открытие настроек
        parent = self.parent()
        while parent:
            if hasattr(parent, "open_settings_window"):
                parent.open_settings_window()
                return
            parent = parent.parent()

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
        if hasattr(self, "signals_radio") and self.signals_radio.isChecked():
            # Если включён режим торговых сигналов, но это данные сканера (есть 'rank'), игнорируем
            if data and "rank" in data[0]:
                logger.debug("[MarketTable] Режим торговых сигналов, но данные — сканер (есть rank), пропускаю")
                return
            # Это реальные торговые сигналы
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
            sym = str(item.get("symbol", "N/A"))

            # Цена
            try:
                price_val = float(item.get("price", 0))
                price_str = f"{price_val:.5f}"
            except:
                price_str = "0.00000"

            # Изменение % (для цвета)
            try:
                chg_val = float(item.get("change_24h", 0))
                change_str = f"{chg_val:.2f}%"
            except:
                chg_val = 0.0
                change_str = "0.00%"

            # RSI
            try:
                rsi_val = float(item.get("rsi", 0))
                rsi_str = f"{rsi_val:.1f}"
            except:
                rsi_str = "0.0"

            # Волатильность
            try:
                vola_val = float(item.get("volatility", 0))
                vola_str = f"{vola_val:.4f}"
            except:
                vola_str = "0.0000"

            # Режим
            regime = str(item.get("regime", "N/A"))

            # Тип провайдера
            provider_type = item.get("provider_type", "MT5")

            # 2. Заполнение ячеек (ВСЕГО 7 КОЛОНОК)

            # Колонка 0: Символ
            sym_item = QTableWidgetItem(sym)
            if provider_type == "Crypto":
                # Крипто-символы с оранжевым фоном
                sym_item.setBackground(QColor("#f1fa8c"))
                sym_item.setForeground(QColor("#282a36"))
            self.market_table.setItem(row_idx, 0, sym_item)

            # Колонка 1: Тип провайдера
            type_item = QTableWidgetItem(provider_type)
            if provider_type == "Crypto":
                type_item.setBackground(QColor("#ffb86c"))
                type_item.setForeground(QColor("#282a36"))
            else:
                type_item.setForeground(QColor("#8be9fd"))
            self.market_table.setItem(row_idx, 1, type_item)

            # Колонка 2: Цена
            self.market_table.setItem(row_idx, 2, QTableWidgetItem(price_str))

            # Колонка 3: Изменение % (с цветом)
            change_item = QTableWidgetItem(change_str)
            if chg_val > 0:
                change_item.setForeground(QColor("#50fa7b"))  # Зеленый
            elif chg_val < 0:
                change_item.setForeground(QColor("#ff5555"))  # Красный
            self.market_table.setItem(row_idx, 3, change_item)

            # Колонка 4: RSI
            self.market_table.setItem(row_idx, 4, QTableWidgetItem(rsi_str))

            # Колонка 5: Волатильность
            self.market_table.setItem(row_idx, 5, QTableWidgetItem(vola_str))

            # Колонка 6: Режим
            self.market_table.setItem(row_idx, 6, QTableWidgetItem(regime))

        # Включаем сортировку обратно
        self.market_table.setSortingEnabled(True)
        logger.info(f"[MarketTable] Таблица обновлена: {len(processed_data)} строк")

    @Slot(list)
    def update_trading_signals_table(self, data: list):
        """Обновляет таблицу торговых сигналов."""
        logger.info(f"[TradingSignals] update_trading_signals_table вызван с {len(data) if data else 0} элементами")
        if not data:
            logger.warning("[TradingSignals] Данные пустые, пропускаю")
            return
        logger.info(f"[TradingSignals] Первый элемент: {data[0]}")

        # Проверяем тип данных — если это данные сканера (нет 'signal_type'), пропускаем
        first_item = data[0]
        if "signal_type" not in first_item:
            logger.debug("[TradingSignals] Это данные сканера (нет signal_type), а не торговые сигналы — пропускаю")
            return

        # Сохраняем последние данные для возможного переключения режимов
        self._last_market_data = data

        # Проверяем, в каком режиме мы находимся
        if hasattr(self, "market_radio") and self.market_radio.isChecked():
            # Если включён режим рыночных данных, используем другой метод
            processed_data = self.prepare_control_center_data(data)
            self.update_market_table(processed_data)
            return

        # Отключаем сортировку для производительности
        self.market_table.setSortingEnabled(False)
        self.market_table.setRowCount(len(data))

        for row_idx, item in enumerate(data):
            # 1. Подготовка данных для торговых сигналов
            sym = str(item.get("symbol", "N/A"))
            signal_type = str(item.get("signal_type", "N/A"))
            strategy = str(item.get("strategy", "N/A"))
            timestamp = str(item.get("timestamp", "N/A"))
            entry_price = item.get("entry_price", 0)
            timeframe = str(item.get("timeframe", "N/A"))

            # Цена
            try:
                price_val = float(entry_price) if entry_price else 0
                price_str = f"{price_val:.5f}" if entry_price else "0.00000"
            except:
                price_str = "0.00000"

            # Изменение % - используем тип сигнала как индикатор
            change_str = signal_type
            chg_val = 1.0 if signal_type == "BUY" else (-1.0 if signal_type == "SELL" else 0.0)

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
        """Загружает текущие настройки для отображения в панели параметров."""
        if not self.config:
            return

        # Обновляем метки текущих параметров
        self.current_risk_label.setText(f"{self.config.RISK_PERCENTAGE:.2f}%")
        self.current_positions_label.setText(str(self.config.MAX_OPEN_POSITIONS))
        self.current_drawdown_label.setText(f"{self.config.MAX_DAILY_DRAWDOWN_PERCENT:.2f}%")

        # Загрузка режима торговли
        if hasattr(self.config, "trading_mode"):
            trading_mode = self.config.trading_mode
            current_mode = trading_mode.get("current_mode", "standard")
            modes_enabled = trading_mode.get("enabled", False)

            if modes_enabled and current_mode in TRADING_MODES:
                mode_data = TRADING_MODES[current_mode]
                self.current_mode_label.setText(f"{mode_data['icon']} {mode_data['name']}")
                self.current_mode_label.setStyleSheet(f"color: {mode_data['color']}; font-weight: bold; font-size: 14px;")
            else:
                self.current_mode_label.setText("⚙️ Ручной режим")
                self.current_mode_label.setStyleSheet("color: #6272a4; font-weight: bold; font-size: 14px;")
        else:
            self.current_mode_label.setText("🟡 Стандартный")

        # Загрузка конфигурации стратегий
        regime_mapping = self.config.STRATEGY_REGIME_MAPPING
        available_strategies = ["AI_Model"]

        # --- ИСПРАВЛЕНИЕ: Безопасная загрузка стратегий ---
        if self.trading_system and hasattr(self.trading_system, "core_system"):
            core = self.trading_system.core_system
            # Проверяем, что strategy_loader уже инициализирован
            if hasattr(core, "strategy_loader") and core.strategy_loader is not None:
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

    def refresh_strategies(self):
        """
        Обновляет список доступных стратегий в выпадающих списках.
        Вызывается из главного окна после завершения инициализации.
        """
        self.load_initial_settings()

    def update_trading_settings_display(self, settings: dict):
        """
        Обновляет отображение текущих настроек торговли.

        Args:
            settings: Dict с настройками (RISK_PERCENTAGE, MAX_OPEN_POSITIONS, etc.)
        """
        if "RISK_PERCENTAGE" in settings:
            self.current_risk_label.setText(f"{settings['RISK_PERCENTAGE']:.2f}%")
        if "MAX_OPEN_POSITIONS" in settings:
            self.current_positions_label.setText(str(settings["MAX_OPEN_POSITIONS"]))
        if "MAX_DAILY_DRAWDOWN_PERCENT" in settings:
            self.current_drawdown_label.setText(f"{settings['MAX_DAILY_DRAWDOWN_PERCENT']:.2f}%")
        if "trading_mode" in settings:
            mode = settings["trading_mode"]
            current_mode = mode.get("current_mode", "standard")
            modes_enabled = mode.get("enabled", False)

            if modes_enabled and current_mode in TRADING_MODES:
                mode_data = TRADING_MODES[current_mode]
                self.current_mode_label.setText(f"{mode_data['icon']} {mode_data['name']}")
                self.current_mode_label.setStyleSheet(f"color: {mode_data['color']}; font-weight: bold; font-size: 14px;")
            else:
                self.current_mode_label.setText("⚙️ Ручной режим")
                self.current_mode_label.setStyleSheet("color: #6272a4; font-weight: bold; font-size: 14px;")

    def _force_training_requested(self):
        """Запуск принудительного обучения AI-моделей."""
        if not self.trading_system:
            self.training_status_label.setText("❌ Торговая система не подключена")
            self.training_status_label.setStyleSheet("color: #ff5555; font-size: 12px;")
            return

        self.force_train_btn.setEnabled(False)
        self.training_status_label.setText("⏳ Запуск цикла обучения...")
        self.training_status_label.setStyleSheet("color: #f1fa8c; font-size: 12px;")

        try:
            self.trading_system.force_training_cycle()
            self.training_status_label.setText("✅ Цикл обучения запущен (следите за графиками)")
            self.training_status_label.setStyleSheet("color: #50fa7b; font-size: 12px;")
        except Exception as e:
            self.training_status_label.setText(f"❌ Ошибка: {e}")
            self.training_status_label.setStyleSheet("color: #ff5555; font-size: 12px;")
        finally:
            # Разблокируем кнопку через 5 секунд
            from PySide6.QtCore import QTimer

            QTimer.singleShot(5000, lambda: self.force_train_btn.setEnabled(True))
