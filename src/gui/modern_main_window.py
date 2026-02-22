# src/gui/modern_main_window.py
"""
Современное главное окно с темной темой в стиле React-интерфейса
"""
import logging
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QTabWidget, QFrame, QTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QSplitter, QScrollArea, QProgressBar,
    QGraphicsDropShadowEffect, QStackedWidget
)
from PySide6.QtCore import Qt, Signal, QTimer, QSize, QRect, QPoint
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPen, QBrush, QIcon, QPixmap,
    QLinearGradient, QRadialGradient, QConicalGradient
)
import sys
import os

logger = logging.getLogger(__name__)

# Цветовая палитра в стиле React-кода
COLORS = {
    'bg': '#282a36',
    'panel': '#44475a',
    'text': '#f8f8f2',
    'border': '#6272a4',
    'green': '#50fa7b',
    'red': '#ff5555',
    'orange': '#ffb86c',
    'purple': '#bd93f9',
    'yellow': '#f1fa8c',
    'cyan': '#8be9fd',
    'pink': '#ff79c6'
}

class StatusIndicator(QWidget):
    """Индикатор статуса с анимацией"""
    def __init__(self, status='running', parent=None):
        super().__init__(parent)
        self.status = status
        self.setMinimumSize(12, 12)
        self.setMaximumSize(12, 12)
        
    def setStatus(self, status):
        self.status = status
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Выбор цвета в зависимости от статуса
        if self.status == 'running':
            color = QColor(COLORS['green'])
        elif self.status == 'stopped':
            color = QColor(COLORS['red'])
        elif self.status == 'warning':
            color = QColor(COLORS['orange'])
        else:
            color = QColor(COLORS['cyan'])
            
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, 12, 12)

class ModernCard(QFrame):
    """Современная карточка с тенью"""
    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.setObjectName("ModernCard")
        self.setStyleSheet(f"""
            QFrame#ModernCard {{
                background-color: {COLORS['panel']};
                border-radius: 8px;
                border: 1px solid {COLORS['border']};
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        if title:
            title_label = QLabel(title)
            title_label.setStyleSheet(f"""
                color: {COLORS['text']};
                font-size: 14px;
                font-weight: bold;
                margin-bottom: 10px;
            """)
            layout.addWidget(title_label)

class AnimatedButton(QPushButton):
    """Анимированная кнопка в стиле React"""
    def __init__(self, text="", icon=None, color='green', parent=None):
        super().__init__(text, parent)
        self.color = color
        self.setup_style()
        
        if icon:
            self.setIcon(icon)
            
    def setup_style(self):
        base_colors = {
            'green': (COLORS['green'], '#46d668'),
            'red': (COLORS['red'], '#e64a4a'),
            'purple': (COLORS['purple'], '#a984e0'),
            'cyan': (COLORS['cyan'], '#7ad5e9')
        }
        
        bg_color, hover_color = base_colors.get(self.color, (COLORS['green'], '#46d668'))
        
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_color};
                color: #282a36;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            QPushButton:pressed {{
                background-color: {bg_color};
                padding: 9px 15px 7px 17px;
            }}
        """)

class ModernMainWindow(QMainWindow):
    """
    Современное главное окно с темной темой
    """
    def __init__(self, bridge=None, config=None, trading_system=None):
        super().__init__()
        self.bridge = bridge
        self.config = config
        self.trading_system = trading_system
        
        # Настройка основного окна
        self.setWindowTitle("Genesis Reflex v24.0 - Современный Интерфейс")
        self.setGeometry(100, 100, 1400, 900)
        self.setMinimumSize(1200, 800)
        
        # Установка темной темы
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {COLORS['bg']};
                color: {COLORS['text']};
            }}
            QLabel {{
                color: {COLORS['text']};
                font-family: 'Segoe UI', Arial, sans-serif;
            }}
            QTabWidget::pane {{
                border: 1px solid {COLORS['border']};
                background-color: {COLORS['bg']};
            }}
            QTabBar::tab {{
                background-color: {COLORS['panel']};
                color: {COLORS['text']};
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }}
            QTabBar::tab:selected {{
                background-color: {COLORS['purple']};
                color: #282a36;
            }}
            QTextEdit {{
                background-color: #282a36;
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
            }}
            QTableWidget {{
                background-color: {COLORS['bg']};
                alternate-background-color: {COLORS['panel']};
                color: {COLORS['text']};
                gridline-color: {COLORS['border']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
            }}
            QTableWidget::item {{
                padding: 6px;
            }}
            QHeaderView::section {{
                background-color: {COLORS['panel']};
                color: {COLORS['text']};
                padding: 8px;
                border: 1px solid {COLORS['border']};
                font-weight: bold;
            }}
        """)
        
        # Инициализация UI
        self.init_ui()
        
        # Таймер для обновления времени
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)
        
    def init_ui(self):
        """Инициализация пользовательского интерфейса"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # Верхняя панель с заголовком и статусами
        self.create_header(main_layout)
        
        # Основная область с вкладками
        self.create_main_content(main_layout)
        
        # Нижняя панель с логами
        self.create_footer(main_layout)
        
    def create_header(self, parent_layout):
        """Создание верхней панели"""
        header_frame = QFrame()
        header_frame.setStyleSheet(f"background-color: {COLORS['panel']}; border-radius: 8px;")
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(20, 15, 20, 15)
        
        # Левая часть - заголовок и иконка
        left_layout = QHBoxLayout()
        left_layout.setSpacing(12)
        
        # Иконка бота
        bot_icon = QLabel("🤖")
        bot_icon.setStyleSheet(f"font-size: 24px; color: {COLORS['green']};")
        left_layout.addWidget(bot_icon)
        
        # Заголовок
        title_label = QLabel("Genesis Reflex v24.0")
        title_label.setStyleSheet(f"""
            color: {COLORS['text']};
            font-size: 20px;
            font-weight: bold;
            background: linear-gradient(90deg, {COLORS['green']} 0%, {COLORS['cyan']} 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        """)
        left_layout.addWidget(title_label)
        
        header_layout.addLayout(left_layout)
        
        # Центральная часть - статусы
        center_layout = QHBoxLayout()
        center_layout.setSpacing(20)
        
        # Статус подключения
        self.connection_status = self.create_status_widget("Подключение", "Активно", COLORS['green'])
        center_layout.addWidget(self.connection_status)
        
        # Статус системы
        self.system_status = self.create_status_widget("Система", "Работает", COLORS['green'])
        center_layout.addWidget(self.system_status)
        
        # Режим наблюдателя
        self.observer_mode_btn = AnimatedButton("Режим Наблюдателя", color='purple')
        self.observer_mode_btn.setCheckable(True)
        self.observer_mode_btn.setChecked(True)
        center_layout.addWidget(self.observer_mode_btn)
        
        header_layout.addLayout(center_layout)
        
        # Правая часть - время
        right_layout = QHBoxLayout()
        right_layout.setSpacing(15)
        
        # Время ПК
        self.pc_time_label = self.create_time_widget("Время ПК")
        right_layout.addWidget(self.pc_time_label)
        
        # Время сервера
        self.server_time_label = self.create_time_widget("Сервер", COLORS['green'])
        right_layout.addWidget(self.server_time_label)
        
        header_layout.addLayout(right_layout)
        
        parent_layout.addWidget(header_frame)
        
    def create_status_widget(self, label_text, value_text, color):
        """Создание виджета статуса"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Индикатор
        indicator = StatusIndicator()
        indicator.setStatus('running' if color == COLORS['green'] else 'warning')
        layout.addWidget(indicator)
        
        # Текст
        label = QLabel(f"{label_text}: {value_text}")
        label.setStyleSheet(f"color: {COLORS['text']}; font-size: 13px;")
        layout.addWidget(label)
        
        return widget
        
    def create_time_widget(self, label_text, color=COLORS['text']):
        """Создание виджета времени"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        
        # Фон
        widget.setStyleSheet(f"""
            background-color: #3a3c4a;
            border-radius: 20px;
        """)
        
        # Метка
        label = QLabel(label_text + ":")
        label.setStyleSheet(f"color: {COLORS['text']}; font-size: 12px;")
        layout.addWidget(label)
        
        # Время
        time_label = QLabel("--:--:--")
        time_label.setStyleSheet(f"color: {color}; font-family: 'Consolas'; font-size: 12px; font-weight: bold;")
        time_label.setObjectName("time_display")
        layout.addWidget(time_label)
        
        return widget
        
    def create_main_content(self, parent_layout):
        """Создание основной области контента"""
        # Создаем splitter для гибкого разделения
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet(f"QSplitter::handle {{ background-color: {COLORS['border']}; }}")
        
        # Левая панель - дашборд
        left_panel = self.create_dashboard_panel()
        splitter.addWidget(left_panel)
        
        # Правая панель - управление
        right_panel = self.create_control_panel()
        splitter.addWidget(right_panel)
        
        # Устанавливаем размеры
        splitter.setSizes([700, 500])
        
        parent_layout.addWidget(splitter)
        
    def create_dashboard_panel(self):
        """Создание панели дашборда"""
        panel = QFrame()
        panel.setStyleSheet(f"background-color: {COLORS['bg']};")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 10, 0)
        layout.setSpacing(15)
        
        # Заголовок
        title = QLabel("📊 Дашборд")
        title.setStyleSheet(f"color: {COLORS['text']}; font-size: 18px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)
        
        # Карточки с данными
        cards_layout = QVBoxLayout()
        cards_layout.setSpacing(12)
        
        # Сканер рынка
        market_card = ModernCard("📈 Сканер Рынка")
        self.market_table = self.create_modern_table([
            "Символ", "Цена", "Изм. %", "RSI", "Волатильность", "Режим"
        ])
        market_card.layout().addWidget(self.market_table)
        cards_layout.addWidget(market_card)
        
        # Оркестратор
        orchestrator_card = ModernCard("🎯 Распределение Стратегий")
        # Здесь будет диаграмма (пока placeholder)
        orchestrator_placeholder = QLabel("Диаграмма распределения стратегий")
        orchestrator_placeholder.setStyleSheet(f"color: {COLORS['text']}; padding: 20px;")
        orchestrator_placeholder.setAlignment(Qt.AlignCenter)
        orchestrator_card.layout().addWidget(orchestrator_placeholder)
        cards_layout.addWidget(orchestrator_card)
        
        layout.addLayout(cards_layout)
        layout.addStretch()
        
        return panel
        
    def create_control_panel(self):
        """Создание панели управления"""
        panel = QFrame()
        panel.setStyleSheet(f"background-color: {COLORS['bg']};")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(15)
        
        # Заголовок
        title = QLabel("⚙️ Управление")
        title.setStyleSheet(f"color: {COLORS['text']}; font-size: 18px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)
        
        # Кнопки управления
        buttons_layout = QVBoxLayout()
        buttons_layout.setSpacing(10)
        
        # Запуск системы
        start_btn = AnimatedButton("▶️ Запустить Систему", color='green')
        buttons_layout.addWidget(start_btn)
        
        # Остановка системы
        stop_btn = AnimatedButton("⏹️ Остановить Систему", color='red')
        buttons_layout.addWidget(stop_btn)
        
        # Экстренное закрытие
        emergency_btn = AnimatedButton("⚠️ Экстренное Закрытие", color='red')
        buttons_layout.addWidget(emergency_btn)
        
        # Обновление данных
        refresh_btn = AnimatedButton("🔄 Обновить Данные", color='cyan')
        buttons_layout.addWidget(refresh_btn)
        
        layout.addLayout(buttons_layout)
        
        # Статус потоков
        threads_card = ModernCard("🧵 Статус Потоков")
        self.threads_table = self.create_modern_table(["Поток", "Статус"])
        threads_card.layout().addWidget(self.threads_table)
        layout.addWidget(threads_card)
        
        layout.addStretch()
        
        return panel
        
    def create_modern_table(self, headers):
        """Создание современной таблицы"""
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setShowGrid(False)
        
        # Стилизация
        table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {COLORS['bg']};
                alternate-background-color: {COLORS['panel']};
                color: {COLORS['text']};
                border: none;
                border-radius: 6px;
            }}
            QTableWidget::item {{
                padding: 10px;
                border-bottom: 1px solid {COLORS['border']};
            }}
            QTableWidget::item:selected {{
                background-color: {COLORS['purple']};
                color: #282a36;
            }}
            QHeaderView::section {{
                background-color: {COLORS['panel']};
                color: {COLORS['text']};
                padding: 12px;
                border: none;
                font-weight: bold;
                font-size: 13px;
            }}
        """)
        
        return table
        
    def create_footer(self, parent_layout):
        """Создание нижней панели с логами"""
        footer_frame = QFrame()
        footer_frame.setStyleSheet(f"background-color: {COLORS['panel']}; border-radius: 8px;")
        layout = QVBoxLayout(footer_frame)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Заголовок логов
        log_title = QLabel("📋 Системные Логи")
        log_title.setStyleSheet(f"color: {COLORS['text']}; font-size: 14px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(log_title)
        
        # Область логов
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(150)
        layout.addWidget(self.log_area)
        
        parent_layout.addWidget(footer_frame)
        
    def update_time(self):
        """Обновление времени"""
        from datetime import datetime
        
        current_time = datetime.now().strftime("%H:%M:%S")
        
        # Обновляем время ПК
        pc_time_widget = self.findChild(QWidget, "pc_time_display")
        if pc_time_widget:
            pc_time_widget.setText(current_time)
            
        # Обновляем время сервера (симуляция)
        server_time = datetime.now().strftime("%H:%M:%S")
        server_time_widget = self.findChild(QWidget, "server_time_display")
        if server_time_widget:
            server_time_widget.setText(server_time)
            
    def append_log(self, message, color=COLORS['text']):
        """Добавление сообщения в лог"""
        timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")
        formatted_message = f"<span style='color:{color}'>[{timestamp}]</span> {message}"
        self.log_area.append(formatted_message)
        self.log_area.verticalScrollBar().setValue(
            self.log_area.verticalScrollBar().maximum()
        )

if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # Создаем тестовое окно
    window = ModernMainWindow()
    window.show()
    
    sys.exit(app.exec())