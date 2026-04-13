# src/gui/analytics_tab.py
"""
Вкладка Аналитики - мониторинг обучения AI моделей в реальном времени.

Виджеты:
1. Прогресс-бар обучения
2. График Loss (train/val)
3. График точности моделей по символам
4. Статус обучения
"""

import logging
import time
from collections import deque

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class AnalyticsTab(QWidget):
    """Вкладка аналитики для мониторинга обучения AI моделей."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loss_x = deque(maxlen=100)  # Последние 100 точек
        self.loss_train_y = deque(maxlen=100)
        self.loss_val_y = deque(maxlen=100)
        self.iteration_counter = 0
        self.setup_ui()

    def setup_ui(self):
        """Создание UI компонентов."""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # === 1. Блок прогресса обучения ===
        progress_group = QGroupBox("📊 Прогресс Обучения")
        progress_layout = QVBoxLayout()

        self.progress_label = QLabel("⏸️ Ожидание начала обучения...")
        self.progress_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #f1fa8c; padding: 5px;")
        progress_layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #6272a4;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
                height: 25px;
            }
            QProgressBar::chunk {
                background-color: #50fa7b;
                border-radius: 3px;
            }
        """)
        progress_layout.addWidget(self.progress_bar)

        progress_group.setLayout(progress_layout)
        main_layout.addWidget(progress_group)

        # === 2. График Loss ===
        loss_group = QGroupBox("📈 Динамика Loss (Функция Потерь)")
        loss_layout = QVBoxLayout()

        loss_info_label = QLabel(
            "Мониторинг train/val loss в реальном времени.\n" "Желтая линия = Train Loss, Красная = Val Loss"
        )
        loss_info_label.setStyleSheet("color: #8be9fd; font-size: 12px; padding: 5px;")
        loss_info_label.setWordWrap(True)
        loss_layout.addWidget(loss_info_label)

        self.loss_plot = pg.PlotWidget()
        self.loss_plot.setMaximumHeight(250)
        self.loss_plot.setTitle("Loss по итерациям")
        self.loss_plot.setLabel("left", "Loss Value")
        self.loss_plot.setLabel("bottom", "Iteration")
        self.loss_plot.showGrid(x=True, y=True, alpha=0.3)
        self.loss_plot.addLegend()

        # Линии для train и val loss
        self.train_loss_curve = self.loss_plot.plot([], [], pen=pg.mkPen("y", width=2), name="Train Loss")
        self.val_loss_curve = self.loss_plot.plot([], [], pen=pg.mkPen("r", width=2), name="Val Loss")

        loss_layout.addWidget(self.loss_plot)

        # Метки текущих значений
        loss_values_layout = QHBoxLayout()
        self.train_loss_label = QLabel("Train Loss: --")
        self.train_loss_label.setStyleSheet("color: #f1fa8c; font-weight: bold; font-size: 13px;")
        loss_values_layout.addWidget(self.train_loss_label)

        self.val_loss_label = QLabel("Val Loss: --")
        self.val_loss_label.setStyleSheet("color: #ff5555; font-weight: bold; font-size: 13px;")
        loss_values_layout.addWidget(self.val_loss_label)

        loss_layout.addLayout(loss_values_layout)

        loss_group.setLayout(loss_layout)
        main_layout.addWidget(loss_group)

        # === 3. График точности моделей ===
        accuracy_group = QGroupBox("🎯 Точность Моделей по Символам")
        accuracy_layout = QVBoxLayout()

        accuracy_info_label = QLabel("Точность валидации для каждого символа (последнее обучение)")
        accuracy_info_label.setStyleSheet("color: #8be9fd; font-size: 12px; padding: 5px;")
        accuracy_info_label.setWordWrap(True)
        accuracy_layout.addWidget(accuracy_info_label)

        self.accuracy_plot = pg.PlotWidget()
        self.accuracy_plot.setMaximumHeight(250)
        self.accuracy_plot.setTitle("Validation Accuracy по символам")
        self.accuracy_plot.setLabel("left", "Accuracy (%)")
        self.accuracy_plot.setLabel("bottom", "Symbol")
        self.accuracy_plot.showGrid(x=True, y=True, alpha=0.3)

        self.accuracy_bar_item = None

        accuracy_layout.addWidget(self.accuracy_plot)

        accuracy_group.setLayout(accuracy_layout)
        main_layout.addWidget(accuracy_group)

        # === 4. Кнопки управления ===
        controls_group = QGroupBox("⚡ Управление")
        controls_layout = QHBoxLayout()

        self.clear_btn = QPushButton("🗑️ Очистить Графики")
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #6272a4;
                color: white;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #7f8c8d;
            }
        """)
        self.clear_btn.clicked.connect(self.clear_all_charts)
        controls_layout.addWidget(self.clear_btn)

        self.test_btn = QPushButton("🧪 Тестовые Данные")
        self.test_btn.setStyleSheet("""
            QPushButton {
                background-color: #bd93f9;
                color: white;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #a37df5;
            }
        """)
        self.test_btn.clicked.connect(self.load_test_data)
        controls_layout.addWidget(self.test_btn)

        controls_group.setLayout(controls_layout)
        main_layout.addWidget(controls_group)

        main_layout.addStretch()
        logger.info("[AnalyticsTab] UI создан")

    def clear_all_charts(self):
        """Очистка всех графиков."""
        self.loss_x.clear()
        self.loss_train_y.clear()
        self.loss_val_y.clear()
        self.iteration_counter = 0

        self.train_loss_curve.setData([], [])
        self.val_loss_curve.setData([], [])
        self.accuracy_plot.clear()
        self.accuracy_bar_item = None

        self.progress_bar.setValue(0)
        self.progress_label.setText("⏸️ Ожидание начала обучения...")
        self.train_loss_label.setText("Train Loss: --")
        self.val_loss_label.setText("Val Loss: --")

        logger.info("[AnalyticsTab] Все графики очищены")

    def load_test_data(self):
        """Загрузка тестовых данных для проверки отрисовки."""
        logger.info("[AnalyticsTab] Загрузка тестовых данных...")

        # Тестируем прогресс
        for i in range(0, 101, 10):
            self.update_progress_bar(i, f"Итерация {i}/100")
            time.sleep(0.1)

        # Тестируем loss
        import random

        for i in range(20):
            train_loss = 0.7 * (0.9**i) + random.uniform(-0.02, 0.02)
            val_loss = 0.75 * (0.88**i) + random.uniform(-0.03, 0.03)
            self.update_loss_graph(train_loss, val_loss)
            time.sleep(0.05)

        # Тестируем точность
        test_accuracy = {
            "EURUSD": 0.78,
            "GBPUSD": 0.75,
            "USDJPY": 0.82,
            "AUDUSD": 0.71,
            "BITCOIN": 0.68,
        }
        self.update_accuracy_chart(test_accuracy)

        self.progress_label.setText("✅ Тестовые данные загружены!")
        logger.info("[AnalyticsTab] Тестовые данные загружены")

    # === СЛОТЫ ОБНОВЛЕНИЯ ===

    def update_progress_bar(self, value: int, text: str):
        """
        Обновление прогресс-бара обучения.

        Args:
            value: Процент выполнения (0-100)
            text: Текстовое описание статуса
        """
        self.progress_bar.setValue(value)
        self.progress_label.setText(f"🔄 {text}")

        # Меняем цвет при завершении
        if value >= 100:
            self.progress_label.setText("✅ Обучение завершено!")
            self.progress_bar.setStyleSheet("""
                QProgressBar::chunk {
                    background-color: #50fa7b;
                }
            """)
        elif value > 50:
            self.progress_bar.setStyleSheet("""
                QProgressBar::chunk {
                    background-color: #f1fa8c;
                }
            """)

        logger.debug(f"[AnalyticsTab] Прогресс: {value}% - {text}")

    def update_loss_graph(self, train_loss: float, val_loss: float):
        """
        Отрисовка графика Loss в реальном времени.

        Args:
            train_loss: Train loss значение
            val_loss: Validation loss значение
        """
        self.iteration_counter += 1
        self.loss_x.append(self.iteration_counter)
        self.loss_train_y.append(train_loss)
        self.loss_val_y.append(val_loss)

        # Обновляем кривые
        self.train_loss_curve.setData(list(self.loss_x), list(self.loss_train_y))
        self.val_loss_curve.setData(list(self.loss_x), list(self.loss_val_y))

        # Обновляем метки
        self.train_loss_label.setText(f"Train Loss: {train_loss:.4f}")
        self.val_loss_label.setText(f"Val Loss: {val_loss:.4f}")

        # Авто-масштабирование
        self.loss_plot.enableAutoRange("xy")

        logger.debug(f"[AnalyticsTab] Loss обновлен: train={train_loss:.4f}, val={val_loss:.4f}")

    def update_accuracy_chart(self, accuracy_data: dict):
        """
        Обновление графика точности моделей.

        Args:
            accuracy_data: {symbol: accuracy} словарь
        """
        if not accuracy_data:
            logger.warning("[AnalyticsTab] Пустые данные точности")
            return

        symbols = list(accuracy_data.keys())
        values = [v * 100 for v in accuracy_data.values()]  # Преобразуем в проценты

        # Очищаем старый график
        self.accuracy_plot.clear()

        # Цветовое кодирование
        colors = []
        for v in values:
            if v >= 75:
                colors.append("#50fa7b")  # Зеленый - хорошо
            elif v >= 60:
                colors.append("#f1fa8c")  # Желтый - средне
            else:
                colors.append("#ff5555")  # Красный - плохо

        # Создаем столбчатую диаграмму
        x_positions = list(range(len(symbols)))
        self.accuracy_bar_item = pg.BarGraphItem(
            x=x_positions, height=values, width=0.6, brushes=[pg.mkBrush(c) for c in colors]
        )
        self.accuracy_plot.addItem(self.accuracy_bar_item)

        # Устанавливаем диапазон Y
        self.accuracy_plot.setYRange(0, 100)

        # Средняя точность
        avg_accuracy = sum(values) / len(values) if values else 0
        self.accuracy_plot.setTitle(f"Точность: {avg_accuracy:.1f}% (средняя)")

        logger.info(f"[AnalyticsTab] Точность обновлена: {len(symbols)} символов, средняя={avg_accuracy:.1f}%")
