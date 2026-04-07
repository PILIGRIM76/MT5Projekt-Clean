# src/gui/widgets/defi_widget.py
"""
DeFi Dashboard Widget — Отображение метрик DeFi протоколов в главном окне.
"""

import logging
from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, 
    QListWidget, QListWidgetItem, QPushButton, QWidget
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from src.db.database_manager import DefiMetrics

logger = logging.getLogger(__name__)


class DeFiWidget(QGroupBox):
    """
    Виджет для отображения лучших DeFi доходностей и TVL.
    Подключается к БД и обновляется автоматически.
    """
    
    # Сигналы
    refresh_requested = Signal()

    def __init__(self, parent=None, db_manager=None):
        super().__init__("📊 DeFi Metrics (Live)", parent)
        self.db_manager = db_manager
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: #f8f8f2;
                border: 2px solid #50fa7b;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 10px;
                color: #50fa7b;
            }
        """)
        
        self._init_ui()
        
        # Таймер автообновления (запускается в set_db_manager)
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.refresh_data)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 15, 5, 5)

        # Верхняя панель
        header = QHBoxLayout()
        self.status_label = QLabel("⚪ Подключение...")
        self.status_label.setStyleSheet("color: #8be9fd; font-size: 12px;")
        header.addWidget(self.status_label)
        
        header.addStretch()
        
        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedSize(30, 30)
        refresh_btn.setToolTip("Обновить данные")
        refresh_btn.clicked.connect(self.refresh_data)
        refresh_btn.setStyleSheet("""
            QPushButton { background: #444; color: white; border-radius: 4px; }
            QPushButton:hover { background: #50fa7b; color: black; }
        """)
        header.addWidget(refresh_btn)
        layout.addLayout(header)

        # Список лучших доходностей
        yields_group = QGroupBox("🔥 Top APY (Yield Farming)")
        yields_layout = QVBoxLayout(yields_group)
        self.yields_list = QListWidget()
        self.yields_list.setStyleSheet("""
            QListWidget { background-color: #1e1e1e; color: #50fa7b; border: none; }
            QListWidget::item { padding: 5px; border-bottom: 1px solid #333; }
        """)
        yields_layout.addWidget(self.yields_list)
        layout.addWidget(yields_group)

        # Список ставок кредитования
        lending_group = QGroupBox("💰 Lending Rates (Aave/Compound)")
        lending_layout = QVBoxLayout(lending_group)
        self.lending_list = QListWidget()
        self.lending_list.setStyleSheet("""
            QListWidget { background-color: #1e1e1e; color: #8be9fd; border: none; }
            QListWidget::item { padding: 5px; border-bottom: 1px solid #333; }
        """)
        lending_layout.addWidget(self.lending_list)
        layout.addWidget(lending_group)

        # Статус внизу
        self.last_update_label = QLabel("Обновлено: Никогда")
        self.last_update_label.setStyleSheet("color: #6272a4; font-size: 10px;")
        layout.addWidget(self.last_update_label)

    def set_db_manager(self, db_manager):
        """Установить менеджер БД и запустить обновление."""
        logger.info(f"[DeFiWidget] Установка db_manager: {db_manager is not None}")
        self.db_manager = db_manager
        
        # Запускаем таймер (раз в 5 минут)
        if not self.update_timer.isActive():
            self.update_timer.start(300000)
            logger.info("[DeFiWidget] Таймер автообновления запущен")
        
        # Сразу загружаем данные
        self.refresh_data()

    def refresh_data(self):
        """Загрузить данные из БД."""
        logger.info(f"[DeFiWidget] refresh_data вызван. db_manager={self.db_manager is not None}")
        if not self.db_manager:
            logger.warning("[DeFiWidget] db_manager не установлен, пропуск")
            return

        try:
            logger.info("[DeFiWidget] Создание сессии БД...")
            session = self.db_manager.Session()
            logger.info("[DeFiWidget] Сессия создана")

            # 1. Топ APY (за последние 24 часа, исключая подозрительно высокие > 1000%)
            since = datetime.utcnow() - timedelta(hours=24)
            logger.info(f"[DeFiWidget] Запрос APY с {since}")
            
            top_yields = session.query(DefiMetrics).filter(
                DefiMetrics.metric_type == "supply_apy",
                DefiMetrics.timestamp > since,
                DefiMetrics.value < 1000.0  # Фильтр скама/ошибок
            ).order_by(DefiMetrics.value.desc()).limit(10).all()

            logger.info(f"[DeFiWidget] Найдено {len(top_yields)} записей APY")

            self.yields_list.clear()
            for m in top_yields:
                # Формируем красивую строку
                color = "#50fa7b"
                if m.value > 20: color = "#ffb86c" # Высокий риск
                if m.value > 50: color = "#ff5555" # Очень высокий риск
                
                item_text = f"{m.protocol.upper()} | {m.chain} | {m.asset}"
                val_text = f"APY: {m.value:.2f}%"
                
                item = QListWidgetItem(f"{item_text}\n{val_text}")
                item.setForeground(QColor(color))
                self.yields_list.addItem(item)

            # 2. Топ Lending Rates (Supply APY для Aave/Compound)
            top_lending = session.query(DefiMetrics).filter(
                DefiMetrics.metric_type == "supply_apy",
                DefiMetrics.timestamp > since,
                DefiMetrics.protocol.in_(["aave-v3", "aave-v2", "compound-v3", "compound-v2"]),
                DefiMetrics.value < 100.0
            ).order_by(DefiMetrics.value.desc()).limit(5).all()

            self.lending_list.clear()
            for m in top_lending:
                item_text = f"{m.protocol.upper()} | {m.chain} | {m.asset}"
                val_text = f"Supply APY: {m.value:.2f}%"
                item = QListWidgetItem(f"{item_text}\n{val_text}")
                item.setForeground(QColor("#8be9fd"))
                self.lending_list.addItem(item)
            
            # Обновляем статус
            self.status_label.setText("🟢 Подключено")
            self.status_label.setStyleSheet("color: #50fa7b;")
            self.last_update_label.setText(f"Обновлено: {datetime.now().strftime('%H:%M:%S')}")
            
            if not top_yields:
                self.yields_list.addItem("Нет данных за 24ч. Нажмите 🔄 или запустите загрузку в Настройках.")
            else:
                logger.info(f"[DeFiWidget] Успешно обновлено {len(top_yields)} APY записей")

            session.close()

        except Exception as e:
            logger.error(f"[DeFiWidget] Ошибка обновления: {e}", exc_info=True)
            self.status_label.setText("🔴 Ошибка")
            self.status_label.setStyleSheet("color: #ff5555;")
