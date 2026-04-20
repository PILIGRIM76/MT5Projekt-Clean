# src/gui/ai_training_widget.py
"""
Виджет обучения AI-моделей - вторая боковая вкладка.

Содержит:
- Кнопка принудительного обучения
- График прогресса переобучения
- Таймер обратного отсчета
- Статус обучения
"""

import logging

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class AITrainingWidget(QWidget):
    """Виджет обучения AI-моделей с прогрессом и таймером."""

    # Сигналы
    force_training_requested = Signal()

    def __init__(self, bridge=None, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.countdown_seconds = 0
        self.setup_ui()
        self._start_countdown_timer()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Группа обучения
        training_group = QGroupBox("🧠 Принудительное Обучение AI-моделей")
        training_layout = QVBoxLayout()

        desc_label = QLabel("""
        Запустите принудительный цикл переобучения AI-моделей.
        Используйте после сбора новых данных или при ухудшении точности.
        """)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #f8f8f2; padding: 5px;")
        training_layout.addWidget(desc_label)

        # Кнопка запуска обучения
        self.train_btn = QPushButton("🚀 Запустить принудительное обучение")
        self.train_btn.setStyleSheet("""
            QPushButton {
                background-color: #50fa7b;
                color: #282a36;
                padding: 15px;
                border-radius: 8px;
                font-weight: bold;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #3dd66a;
            }
            QPushButton:pressed {
                background-color: #27ae60;
            }
            QPushButton:disabled {
                background-color: #6272a4;
                color: #44475a;
            }
        """)
        self.train_btn.clicked.connect(self._on_train_clicked)
        training_layout.addWidget(self.train_btn)

        # Прогресс бар переобучения
        self.retrain_progress_widget = pg.PlotWidget(title="⏰ До переобучения (ч)")
        self.retrain_progress_widget.setMaximumHeight(150)
        self.retrain_progress_widget.showGrid(x=True, y=True, alpha=0.3)
        self.retrain_progress_widget.getAxis("bottom").setLabel("Символ")
        self.retrain_progress_widget.getAxis("left").setLabel("Часов")
        self.retrain_progress_widget.getAxis("left").setRange(0, 3)
        self.retrain_progress_bars = pg.BarGraphItem(x=[], height=[], width=0.5, brush="b")
        self.retrain_progress_widget.addItem(self.retrain_progress_bars)
        self.retrain_progress_data = {}
        training_layout.addWidget(self.retrain_progress_widget)

        # Таймер следующего обучения
        self.next_training_label = QLabel("⏳ Следующее обучение: --:--")
        self.next_training_label.setStyleSheet("""
            QLabel {
                background-color: #34495e;
                color: #f1fa8c;
                padding: 10px;
                border-radius: 5px;
                font-weight: bold;
                font-size: 14px;
            }
        """)
        self.next_training_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        training_layout.addWidget(self.next_training_label)

        # Статус обучения
        self.training_status_label = QLabel("Статус: Ожидание...")
        self.training_status_label.setStyleSheet("color: #8be9fd; font-size: 12px; font-style: italic;")
        self.training_status_label.setWordWrap(True)
        training_layout.addWidget(self.training_status_label)

        training_group.setLayout(training_layout)
        layout.addWidget(training_group)

        # Конфигуратор стратегий
        config_group = QGroupBox("⚙️ Конфигуратор Стратегий")
        config_layout = QVBoxLayout()

        self.strategy_table = QLabel("""
        | Рыночный Режим | Основная Стратегия |
        |----------------|-------------------|
        | Default        | AI Model          |
        | Strong Trend   | Moving Average    |
        | Low Volatility | Mean Reversion    |
        """)
        self.strategy_table.setStyleSheet("""
            QLabel {
                font-family: monospace;
                background-color: #282a36;
                color: #f8f8f2;
                padding: 10px;
                border-radius: 5px;
                font-size: 12px;
            }
        """)
        self.strategy_table.setWordWrap(True)
        config_layout.addWidget(self.strategy_table)

        config_group.setLayout(config_layout)
        layout.addWidget(config_group)

        layout.addStretch()

    def _start_countdown_timer(self):
        """Запускает таймер обратного отсчета."""
        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self._update_countdown)
        self.countdown_timer.start(1000)  # Каждую секунду

    def _on_train_clicked(self):
        """Обработка нажатия кнопки обучения."""
        logger.info("[AITraining] Запрошено принудительное обучение")
        self.train_btn.setEnabled(False)
        self.train_btn.setText("⏳ Обучение запущено...")
        self.training_status_label.setText("Статус: 🔄 Обучение запущено...")
        self.training_status_label.setStyleSheet("color: #f1fa8c; font-size: 12px; font-weight: bold;")

        # Эмитим сигнал
        self.force_training_requested.emit()

    def update_retrain_progress_chart(self, progress_data: dict):
        """
        Обновляет график прогресса переобучения.

        Args:
            progress_data: Словарь с данными о прогрессе
        """
        try:
            if not progress_data:
                logger.debug("[AITraining] Нет данных для отображения")
                self.retrain_progress_bars.setOpts(x=[], height=[])
                return

            # Проверяем формат данных
            if "total_symbols" in progress_data and "symbols_needing_retrain" in progress_data:
                # НОВЫЙ ФОРМАТ от AutoTrainer.get_retrain_progress()
                total = progress_data["total_symbols"]
                needs_count = progress_data["count_needing_retrain"]
                needs_percent = progress_data["progress_percent"]
                threshold = progress_data["threshold_percent"]
                can_retrain = progress_data["can_start_retrain"]
                symbols_needing = progress_data["symbols_needing_retrain"]

                # Данные для графика: только символы требующие переобучения
                symbols = symbols_needing
                hours = [1.0] * len(symbols_needing)
                colors = ["#ff5555"] * len(symbols)  # Все красные

                # Обновляем заголовок с порогом
                status_icon = "⚠️" if can_retrain else "✅"
                self.retrain_progress_widget.setTitle(
                    f"{status_icon} Прогресс: {needs_count}/{total} ({needs_percent:.0%}) / {threshold:.0%} порог"
                )
            else:
                # СТАРЫЙ ФОРМАТ: {symbol: hours_since_training}
                symbols = list(progress_data.keys())
                hours = [progress_data[s] for s in symbols]
                hours = [float(h) if not isinstance(h, (int, float)) else h for h in hours]

                # Цветовое кодирование
                colors = []
                for h in hours:
                    if h >= 1.0:
                        colors.append("#ff5555")  # Красный - пора переобучать!
                    elif h >= 0.5:
                        colors.append("#ffb86c")  # Оранжевый - скоро пора
                    else:
                        colors.append("#50fa7b")  # Зелёный - ещё рано

                symbols_to_retrain = sum(1 for h in hours if h >= 1.0)
                self.retrain_progress_widget.setTitle(f"⏰ Прогресс (требуют: {symbols_to_retrain})")

            # Обновляем график
            x_positions = list(range(len(symbols)))
            self.retrain_progress_bars.setOpts(x=x_positions, height=hours, brushes=[pg.mkBrush(c) for c in colors])

            # Сохраняем данные
            self.retrain_progress_data = progress_data

            logger.info(f"[AITraining] График обновлён: {len(symbols)} символов")

        except Exception as e:
            logger.error(f"[AITraining] Ошибка при обновлении графика: {e}", exc_info=True)

    def update_countdown(self, seconds_remaining: int):
        """Обновляет таймер обратного отсчета."""
        self.countdown_seconds = seconds_remaining
        self._update_countdown_display()

    def _update_countdown(self):
        """Обновляет отображение таймера."""
        self._update_countdown_display()

    def _update_countdown_display(self):
        """Обновляет текст таймера."""
        if self.countdown_seconds > 0:
            minutes = self.countdown_seconds // 60
            seconds = self.countdown_seconds % 60
            self.next_training_label.setText(f"⏳ Следующее обучение: {minutes}м {seconds}с")
        else:
            self.next_training_label.setText("⏳ Следующее обучение: --:--")

    def update_training_status(self, status: str, is_error: bool = False):
        """Обновляет статус обучения."""
        self.training_status_label.setText(f"Статус: {status}")
        if is_error:
            self.training_status_label.setStyleSheet("color: #ff5555; font-size: 12px; font-weight: bold;")
        elif "завершено" in status.lower() or "успешно" in status.lower():
            self.training_status_label.setStyleSheet("color: #50fa7b; font-size: 12px; font-weight: bold;")
        else:
            self.training_status_label.setStyleSheet("color: #8be9fd; font-size: 12px; font-style: italic;")

    def set_training_button_enabled(self, enabled: bool):
        """Включает/отключает кнопку обучения."""
        self.train_btn.setEnabled(enabled)
        if enabled:
            self.train_btn.setText("🚀 Запустить принудительное обучение")
        else:
            self.train_btn.setText("⏳ Обучение запущено...")
