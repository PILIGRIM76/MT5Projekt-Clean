# src/gui/styles.py

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# --- 1. Светлая тема (улучшенная стандартная) ---
LIGHT_STYLE = """
    QWidget {
        font-family: Segoe UI;
        font-size: 10pt;
    }
    QMainWindow, QDialog {
        background-color: #f0f0f0;
    }
    QFrame {
        border: 1px solid #d0d0d0;
        border-radius: 4px;
    }
    QPushButton {
        background-color: #e0e0e0;
        border: 1px solid #c0c0c0;
        padding: 5px 10px;
        border-radius: 4px;
    }
    QPushButton:hover {
        background-color: #e8e8e8;
        border-color: #0078d7;
    }
    QPushButton:pressed {
        background-color: #d0d0d0;
    }
    QLineEdit, QTextEdit {
        border: 1px solid #c0c0c0;
        border-radius: 4px;
        padding: 4px;
        background-color: #ffffff;
    }
    QTableView {
        border: 1px solid #c0c0c0;
        gridline-color: #e0e0e0;
    }
    QHeaderView::section {
        background-color: #e8e8e8;
        padding: 4px;
        border: 1px solid #d0d0d0;
    }
    QTabWidget::pane {
        border-top: 1px solid #d0d0d0;
    }
    QTabBar::tab {
        background: #f0f0f0;
        border: 1px solid #c0c0c0;
        padding: 6px 12px;
        border-bottom: none;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
    }
    QTabBar::tab:selected {
        background: #ffffff;
    }
    QTabBar::tab:!selected:hover {
        background: #e8e8e8;
    }
"""

# --- 2. Темная тема (в стиле "Dracula") ---
DARK_STYLE = """
    QWidget {
        font-family: Segoe UI;
        font-size: 10pt;
        color: #f8f8f2; /* Светлый текст для ВСЕХ виджетов по умолчанию */
        background-color: #282a36;
    }
    QMainWindow, QDialog {
        background-color: #282a36;
    }
    QFrame {
        border: 1px solid #44475a;
        border-radius: 4px;
    }
    QPushButton {
        background-color: #44475a;
        border: 1px solid #6272a4;
        padding: 5px 10px;
        border-radius: 4px;
    }
    QPushButton:hover {
        background-color: #51556a;
        border-color: #bd93f9;
    }
    QPushButton:pressed {
        background-color: #3a3c4a;
    }

    /* --- ИСПРАВЛЕНИЕ: Разделяем стили для QLineEdit и QTextEdit --- */

    /* Стиль для полей ввода, где текст ВСЕГДА должен быть белым */
    QLineEdit {
        border: 1px solid #44475a;
        border-radius: 4px;
        padding: 4px;
        background-color: #3a3c4a;
        color: #f8f8f2;
    }

    /* Стиль для виджета логов. ВАЖНО: мы НЕ указываем здесь 'color' */
    QTextEdit {
        border: 1px solid #44475a;
        border-radius: 4px;
        padding: 4px;
        background-color: #3a3c4a;
    }

    /* ------------------------------------------------------------- */

    QTableView {
        border: 1px solid #44475a;
        gridline-color: #44475a;
    }
    QHeaderView::section {
        background-color: #44475a;
        padding: 4px;
        border: 1px solid #6272a4;
    }
    QTabWidget::pane {
        border-top: 1px solid #44475a;
    }
    QTabBar::tab {
        background: #282a36;
        border: 1px solid #44475a;
        padding: 6px 12px;
        border-bottom: none;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
    }
    QTabBar::tab:selected {
        background: #44475a;
        color: #50fa7b;
    }
    QTabBar::tab:!selected:hover {
        background: #3a3c4a;
    }
    QStatusBar {
        background-color: #44475a;
    }


    /* Стиль для верхней KPI-панели */
    QFrame#KpiBar {
        border-bottom: 1px solid #44475a;
        border-radius: 0px;
    }

    /* Стиль для индикатора просадки */
    QProgressBar {
        border: 1px solid #6272a4;
        border-radius: 4px;
        text-align: center;
        color: #f8f8f2;
    }
    QProgressBar::chunk {
        background-color: #ff5555; /* Красный цвет для заполнения */
        width: 10px;
        margin: 0.5px;
    }

    /* Стиль для кнопок-переключателей в центре */
    QPushButton:checkable:checked {
        background-color: #bd93f9;
        color: #282a36;
        border: 1px solid #f8f8f2;
    }
"""


# --- 3. Функция загрузки QSS из файла ---


def load_qss_file(file_path: str) -> str:
    """
    Загружает QSS файл и возвращает его содержимое.
    Если файл не найден, возвращает пустую строку.
    """
    try:
        path = Path(file_path)
        if path.exists():
            content = path.read_text(encoding="utf-8")
            logger.info(f"[QSS] Загружен файл стилей: {file_path} ({len(content)} байт)")
            return content
        else:
            logger.warning(f"[QSS] Файл стилей не найден: {file_path}")
            return ""
    except Exception as e:
        logger.error(f"[QSS] Ошибка загрузки файла стилей {file_path}: {e}")
        return ""


def get_light_theme_qss() -> str:
    """
    Возвращает содержимое light_theme.qss.
    Автоматически ищет файл в директории src/gui/.
    Приоритет: light_theme_safe.qss -> light_theme.qss
    """
    # Определяем путь к директории styles.py
    styles_dir = Path(__file__).parent

    # Сначала пробуем безопасную версию
    safe_path = styles_dir / "light_theme_safe.qss"
    if safe_path.exists():
        content = safe_path.read_text(encoding="utf-8")
        logger.info(f"[QSS] Загружен безопасный файл стилей: {safe_path} ({len(content)} байт)")
        return content

    # Fallback на полный файл
    qss_path = styles_dir / "light_theme.qss"
    return load_qss_file(str(qss_path))
