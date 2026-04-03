# -*- coding: utf-8 -*-
"""
Виджет мониторинга баз данных для Genesis Trading System.
Отображает статус и статистику по всем подключенным БД.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class DatabaseStatsWorker(QThread):
    """Рабочий поток для асинхронного получения статистики из БД."""

    stats_ready = Signal(dict)  # Сигнал с готовой статистикой
    error_occurred = Signal(str)  # Сигнал об ошибке

    def __init__(self, db_path: str, trading_system=None):
        super().__init__()
        self.db_path = db_path
        self.trading_system = trading_system
        self._stop_flag = False

    def stop(self):
        """Остановка потока."""
        self._stop_flag = True

    def run(self):
        """Получение статистики в отдельном потоке."""
        try:
            stats = self._collect_stats()
            if not self._stop_flag:
                self.stats_ready.emit(stats)
        except Exception as e:
            if not self._stop_flag:
                logger.error(f"Ошибка сбора статистики БД: {e}")
                self.error_occurred.emit(str(e))

    def _collect_stats(self) -> dict:
        """Сбор статистики по всем базам данных."""
        result = {
            "postgres": {"connected": False, "stats": {}},
            "timescaledb": {"connected": False, "stats": {}},
            "questdb": {"connected": False, "stats": {}},
            "qdrant": {"connected": False, "stats": {}},
            "redis": {"connected": False, "stats": {}},
            "sqlite": {"connected": False, "stats": {}},
        }

        # PostgreSQL/SQLite статистика
        try:
            import sqlite3
            from pathlib import Path

            logger.info(f"[DB-Monitor] Путь к БД: {self.db_path}")

            db_paths = [
                Path(self.db_path) / "trading_system.db" if self.db_path else None,
                Path("F:/Enjen/database/trading_system.db"),
                Path("database/trading_system.db"),
            ]

            logger.info(f"[DB-Monitor] Проверяем пути: {db_paths}")

            for db_path in filter(None, db_paths):
                logger.info(f"[DB-Monitor] Проверка пути: {db_path}, существует: {db_path.exists()}")

                if db_path.exists():
                    logger.info(f"[DB-Monitor] Подключение к БД: {db_path}")
                    conn = sqlite3.connect(db_path, timeout=5)
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()

                    # Считаем записи по таблицам
                    table_stats = {}
                    total_rows = 0

                    for table in [
                        "trade_history",
                        "candle_data",
                        "market_data",  # Исторические рыночные данные (70+ лет)
                        "trained_models",
                        "news_articles",
                        "strategy_performance",
                        "active_directives",
                    ]:
                        try:
                            cursor.execute(f"SELECT COUNT(*) FROM {table}")
                            count = cursor.fetchone()[0]
                            table_stats[table] = count
                            total_rows += count
                            logger.info(f"[DB-Monitor] Таблица {table}: {count:,} записей")
                        except Exception as e:
                            logger.warning(f"[DB-Monitor] Ошибка подсчета {table}: {e}")

                    conn.close()

                    result["sqlite"]["connected"] = True
                    result["sqlite"]["stats"] = {
                        "rows": total_rows,
                        "tables": len(table_stats),
                        "size": self._get_db_size(db_path),
                        "details": table_stats,
                    }

                    logger.info(f"[DB-Monitor] Всего записей: {total_rows:,}")

                    # PostgreSQL (если используется)
                    result["postgres"]["connected"] = True
                    result["postgres"]["stats"] = {
                        "rows": total_rows,
                        "tables": len(table_stats),
                        "details": table_stats,
                    }

                    break

        except Exception as e:
            logger.error(f"[DB-Monitor] Ошибка получения статистики: {e}", exc_info=True)

        # Qdrant статистика
        try:
            # Проверяем MultiDatabaseManager
            if self.trading_system and hasattr(self.trading_system, "multi_db_manager"):
                qdrant = self.trading_system.multi_db_manager.get_qdrant()
                if qdrant and qdrant.enabled:
                    result["qdrant"]["connected"] = True
                    # Получаем количество документов из коллекции
                    try:
                        collection_info = qdrant._client.get_collection(qdrant.collection_name)
                        doc_count = collection_info.vectors_count if hasattr(collection_info, "vectors_count") else 0
                        result["qdrant"]["stats"] = {
                            "rows": doc_count,
                            "size": f"{doc_count} vectors",
                        }
                    except:
                        result["qdrant"]["stats"] = {
                            "rows": 0,
                            "size": "Коллекция не создана",
                        }
            # Fallback на vector_db_manager
            elif self.trading_system and hasattr(self.trading_system, "vector_db_manager"):
                if self.trading_system.vector_db_manager.is_ready():
                    doc_count = len(self.trading_system.vector_db_manager.documents)
                    result["qdrant"]["connected"] = True
                    result["qdrant"]["stats"] = {
                        "rows": doc_count,
                        "size": f"{doc_count} vectors",
                    }
        except Exception as e:
            logger.debug(f"Qdrant статистика недоступна: {e}")

        # Redis статистика
        try:
            if self.trading_system and hasattr(self.trading_system, "redis_client"):
                result["redis"]["connected"] = True
                result["redis"]["stats"] = {
                    "connections": 1,
                    "size": "In-Memory",
                }
        except Exception as e:
            logger.debug(f"Redis статистика недоступна: {e}")

        return result

    def _get_db_size(self, db_path: Path) -> str:
        """Получение размера файла БД."""
        try:
            size_bytes = db_path.stat().st_size
            if size_bytes < 1024 * 1024:
                return f"{size_bytes / 1024:.1f} KB"
            elif size_bytes < 1024 * 1024 * 1024:
                return f"{size_bytes / (1024 * 1024):.1f} MB"
            else:
                return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
        except:
            return "N/A"


class DatabaseStatusWidget(QFrame):
    """Виджет отображения статуса одной базы данных."""

    def __init__(self, db_name: str, db_type: str, port: int):
        super().__init__()
        self.db_name = db_name
        self.db_type = db_type
        self.port = port

        self.init_ui()

    def init_ui(self):
        """Инициализация UI."""
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self.setStyleSheet("""
            DatabaseStatusWidget {
                background-color: #2b2b2b;
                border-radius: 8px;
                border: 1px solid #3c3f41;
            }
        """)

        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # Заголовок
        header_layout = QHBoxLayout()

        self.status_indicator = QLabel("●")
        self.status_indicator.setFont(QFont("Segoe UI", 16))
        self.status_indicator.setStyleSheet("color: #FFA500;")  # Оранжевый по умолчанию
        header_layout.addWidget(self.status_indicator)

        title_label = QLabel(f"<b>{self.db_name}</b>")
        title_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        title_label.setStyleSheet("color: #FFFFFF;")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        type_label = QLabel(self.db_type)
        type_label.setFont(QFont("Segoe UI", 9))
        type_label.setStyleSheet("color: #AAAAAA;")
        header_layout.addWidget(type_label)

        port_label = QLabel(f":{self.port}")
        port_label.setFont(QFont("Segoe UI", 9))
        port_label.setStyleSheet("color: #888888;")
        header_layout.addWidget(port_label)

        layout.addLayout(header_layout)

        # Разделитель
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #3c3f41;")
        line.setFixedHeight(1)
        layout.addWidget(line)

        # Статистика
        self.stats_layout = QGridLayout()
        self.stats_layout.setSpacing(6)

        # Метки статистики
        self.stats_labels = {}
        stats_fields = [
            ("rows", "Записей:", "0"),
            ("size", "Размер:", "N/A"),
            ("tables", "Таблиц:", "0"),
            ("connections", "Подключения:", "0"),
        ]

        for i, (key, label, default) in enumerate(stats_fields):
            label_widget = QLabel(f"{label}")
            label_widget.setStyleSheet("color: #AAAAAA;")
            label_widget.setFont(QFont("Segoe UI", 9))

            value_widget = QLabel(str(default))
            value_widget.setStyleSheet("color: #FFFFFF; font-weight: bold;")
            value_widget.setFont(QFont("Segoe UI", 9, QFont.Bold))
            value_widget.setMinimumWidth(80)

            self.stats_layout.addWidget(label_widget, i, 0)
            self.stats_layout.addWidget(value_widget, i, 1)

            self.stats_labels[key] = value_widget

        layout.addLayout(self.stats_layout)
        layout.addStretch()

        self.setLayout(layout)

    @Slot(dict)
    def update_status(self, status_data: dict):
        """Обновление статуса БД."""
        try:
            # Статус подключения
            is_connected = status_data.get("connected", False)
            if is_connected:
                self.status_indicator.setStyleSheet("color: #00FF00;")  # Зеленый
                self.status_indicator.setToolTip("Подключено")
            else:
                self.status_indicator.setStyleSheet("color: #FF0000;")  # Красный
                self.status_indicator.setToolTip("Отключено")

            # Обновление статистики
            if "stats" in status_data:
                stats = status_data["stats"]

                if "rows" in stats:
                    self.stats_labels["rows"].setText(f"{stats['rows']:,}")

                if "size" in stats:
                    self.stats_labels["size"].setText(stats["size"])

                if "tables" in stats:
                    self.stats_labels["tables"].setText(str(stats["tables"]))

                if "connections" in stats:
                    self.stats_labels["connections"].setText(str(stats["connections"]))

            logger.debug(f"Обновлен статус БД {self.db_name}: connected={is_connected}")

        except Exception as e:
            logger.error(f"Ошибка обновления статуса {self.db_name}: {e}")


class DatabaseMonitorWidget(QWidget):
    """Основной виджет мониторинга баз данных."""

    refresh_requested = Signal()

    def __init__(self, trading_system=None, settings_window=None):
        super().__init__()
        self.trading_system = trading_system
        self.settings_window = settings_window
        self.db_widgets = {}
        self.current_db_path = "database"  # Путь по умолчанию

        # Асинхронный воркер для сбора статистики
        self.stats_worker = None
        self.stats_thread = None

        self.init_ui()
        self.setup_database_widgets()

        # Подключаемся к сигналу изменения пути к базе данных
        if self.settings_window:
            self.settings_window.database_path_changed.connect(self.update_database_path)

        # Автообновление каждые 5 секунд
        self.refresh_requested.connect(self.refresh_all_statuses)
        self._start_auto_refresh()

    @Slot(str)
    def update_database_path(self, new_path: str):
        """Обновление пути к базе данных при изменении настроек."""
        self.current_db_path = new_path
        logger.info(f"Путь к базе данных обновлен: {new_path}")
        # Немедленно обновляем статус
        self.refresh_all_statuses()

    def _start_stats_worker(self):
        """Запуск асинхронного сбора статистики."""
        try:
            # Останавливаем предыдущий воркер если есть
            if self.stats_worker:
                self.stats_worker.stop()
                self.stats_worker.wait(1000)

            # Создаем новый воркер
            self.stats_worker = DatabaseStatsWorker(db_path=self.current_db_path, trading_system=self.trading_system)

            # Подключаем сигналы
            self.stats_worker.stats_ready.connect(self._on_stats_ready, Qt.QueuedConnection)
            self.stats_worker.error_occurred.connect(self._on_stats_error, Qt.QueuedConnection)

            # Запускаем в отдельном потоке
            self.stats_worker.start()
            logger.debug("Асинхронный сбор статистики БД запущен")

        except Exception as e:
            logger.error(f"Ошибка запуска воркера статистики: {e}")

    @Slot(dict)
    def _on_stats_ready(self, stats: dict):
        """Обработка готовой статистики (вызывается в главном потоке)."""
        try:
            for db_name, db_status in stats.items():
                if db_name in self.db_widgets:
                    self.db_widgets[db_name].update_status(db_status)
            logger.debug("Статистика БД обновлена в GUI")
        except Exception as e:
            logger.error(f"Ошибка обновления статистики в GUI: {e}")

    @Slot(str)
    def _on_stats_error(self, error_msg: str):
        """Обработка ошибки сбора статистики."""
        logger.warning(f"Ошибка сбора статистики БД: {error_msg}")

    def init_ui(self):
        """Инициализация UI."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Заголовок
        header_label = QLabel("📊 Мониторинг баз данных")
        header_label.setFont(QFont("Segoe UI", 16, QFont.Bold))
        header_label.setStyleSheet("color: #FFFFFF; padding: 10px;")
        main_layout.addWidget(header_label)

        # Скролл для виджетов БД
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Контейнер для виджетов
        self.container = QWidget()
        self.container_layout = QVBoxLayout()
        self.container_layout.setSpacing(12)
        self.container_layout.setContentsMargins(10, 10, 10, 10)
        self.container.setLayout(self.container_layout)

        scroll.setWidget(self.container)
        main_layout.addWidget(scroll)

        # Кнопка обновления
        refresh_btn = QLabel("🔄 Обновить")
        refresh_btn.setStyleSheet("""
            QLabel {
                background-color: #3c3f41;
                color: #FFFFFF;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QLabel:hover {
                background-color: #4c4f51;
            }
        """)
        refresh_btn.mousePressEvent = lambda e: self.refresh_all_statuses()
        refresh_btn.setCursor(Qt.PointingHandCursor)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(refresh_btn)
        main_layout.addLayout(btn_layout)

        self.setLayout(main_layout)

    def setup_database_widgets(self):
        """Создание виджетов для всех БД."""
        databases = [
            ("PostgreSQL", "Relational", 5432),
            ("TimescaleDB", "Time-Series", 5433),
            ("QuestDB", "Time-Series", 9000),
            ("Qdrant", "Vector", 6333),
            ("Redis", "Key-Value", 6379),
            ("SQLite", "Embedded", 0),
        ]

        for db_name, db_type, port in databases:
            widget = DatabaseStatusWidget(db_name, db_type, port)
            self.container_layout.addWidget(widget)
            self.db_widgets[db_name.lower()] = widget

        self.container_layout.addStretch()

    def _start_auto_refresh(self):
        """Запуск автообновления."""
        try:
            if self.trading_system and hasattr(self.trading_system, "db_manager"):
                # Обновление каждые 5 секунд
                from PySide6.QtCore import QTimer

                self.timer = QTimer()
                self.timer.timeout.connect(self.refresh_all_statuses)
                self.timer.start(5000)  # 5 секунд
                logger.info("Автообновление мониторинга БД запущено")
        except Exception as e:
            logger.debug(f"Автообновление недоступно: {e}")

    @Slot()
    def refresh_all_statuses(self):
        """Запуск асинхронного обновления статуса всех БД."""
        self._start_stats_worker()

    def closeEvent(self, event):
        """Корректная остановка воркера при закрытии виджета."""
        if self.stats_worker:
            self.stats_worker.stop()
            self.stats_worker.wait(2000)
        event.accept()

    def _get_database_stats(self, db_name: str) -> dict:
        """Получение статистики по конкретной БД."""
        stats = {
            "rows": 0,
            "size": "N/A",
            "tables": 0,
            "connections": 0,
        }

        try:
            if not self.trading_system:
                return stats

            # PostgreSQL
            if db_name == "postgres" and hasattr(self.trading_system, "db_manager"):
                stats["tables"] = 13  # Известное количество таблиц
                stats["rows"] = self._get_postgres_row_count()

            # TimescaleDB
            elif db_name == "timescaledb":
                stats["tables"] = 5
                stats["size"] = "~2 GB"

            # Qdrant
            elif db_name == "qdrant" and hasattr(self.trading_system, "vector_db_manager"):
                if self.trading_system.vector_db_manager.is_ready():
                    stats["rows"] = len(self.trading_system.vector_db_manager.documents)
                    stats["size"] = f"{len(self.trading_system.vector_db_manager.documents)} vectors"

            # Redis
            elif db_name == "redis":
                stats["connections"] = 1
                stats["size"] = "In-Memory"

            # SQLite
            elif db_name == "sqlite" and hasattr(self.trading_system, "db_manager"):
                stats["tables"] = 10
                stats["size"] = "~50 MB"

        except Exception as e:
            logger.debug(f"Не удалось получить статистику {db_name}: {e}")

        return stats

    def _get_postgres_row_count(self) -> int:
        """Подсчет записей в PostgreSQL/SQLite."""
        try:
            if hasattr(self.trading_system, "db_manager"):
                session = self.trading_system.db_manager.Session()

                # Считаем записи в основных таблицах
                from src.db.database_manager import CandleData, NewsArticle, TradeHistory, TrainedModel

                total = 0
                stats = {}
                for model, name in [
                    (TradeHistory, "trades"),
                    (CandleData, "candles"),
                    (TrainedModel, "models"),
                    (NewsArticle, "news"),
                ]:
                    try:
                        count = session.query(model).count()
                        total += count
                        stats[name] = count
                    except Exception as e:
                        logger.debug(f"Не удалось получить {name}: {e}")

                session.close()

                # Сохраняем для отображения
                self._last_stats = stats
                return total
        except Exception as e:
            logger.debug(f"Ошибка подсчета записей: {e}")

        # Fallback: пробуем напрямую из SQLite
        try:
            import sqlite3
            from pathlib import Path

            # Проверяем путь из конфига или стандартный
            db_paths = [
                Path(self.current_db_path) / "trading_system.db",
                Path("F:/Enjen/database/trading_system.db"),
                Path("database/trading_system.db"),
            ]

            for db_path in db_paths:
                if db_path.exists():
                    logger.debug(f"Подключение к базе данных: {db_path}")
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()

                    total = 0
                    table_stats = {}
                    for table in ["trade_history", "trained_models", "news_articles", "candle_data"]:
                        try:
                            cursor.execute(f"SELECT COUNT(*) FROM {table}")
                            count = cursor.fetchone()[0]
                            total += count
                            table_stats[table] = count
                        except Exception as e:
                            logger.debug(f"Таблица {table} не найдена: {e}")

                    conn.close()

                    # Сохраняем детальную статистику
                    self._last_detailed_stats = table_stats
                    return total

        except Exception as e:
            logger.debug(f"Fallback проверка не удалась: {e}")

        return 0


class DatabaseTableWidget(QTableWidget):
    """Таблица с детальным отображением данных БД."""

    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        """Инициализация UI."""
        self.setColumnCount(6)
        self.setHorizontalHeaderLabels(["База данных", "Тип", "Статус", "Записей", "Размер", "Последнее обновление"])

        self.horizontalHeader().setStretchLastSection(True)
        self.setAlternatingRowColors(True)
        self.setStyleSheet("""
            QTableWidget {
                background-color: #2b2b2b;
                color: #FFFFFF;
                gridline-color: #3c3f41;
            }
            QHeaderView::section {
                background-color: #3c3f41;
                color: #FFFFFF;
                padding: 8px;
                border: none;
            }
            QTableWidget::item {
                padding: 6px;
            }
        """)
