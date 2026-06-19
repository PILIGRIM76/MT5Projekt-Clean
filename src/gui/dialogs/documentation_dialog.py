#!/usr/bin/env python3
"""
Диалог просмотра документации для Genesis Trading System.
Отображает руководство пользователя в формате Markdown.
"""

import logging
import os
import re
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class DocumentationDialog(QDialog):
    """
    Диалог для просмотра руководства пользователя.

    Загружает Markdown файл и отображает его с навигацией по разделам.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📘 Руководство пользователя")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)

        self.doc_path = self._find_documentation()
        self.raw_content = ""
        self.sections = []

        self._init_ui()
        self._load_documentation()
        self._populate_toc()

    def _find_documentation(self) -> Path:
        """Находит файл документации."""
        # Ищем в нескольких местах
        search_paths = [
            Path(__file__).parent.parent.parent.parent / "docs" / "user_guide.md",
            Path(__file__).parent.parent.parent.parent.parent / "docs" / "user_guide.md",
            Path.cwd() / "docs" / "user_guide.md",
        ]

        for path in search_paths:
            if path.exists():
                return path

        return None

    def _init_ui(self):
        """Инициализация UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Заголовок
        header = QWidget()
        header.setStyleSheet("background-color: #282a36; border-bottom: 2px solid #bd93f9;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 10, 20, 10)

        title_label = QLabel("📘 Руководство пользователя Genesis Trading System")
        title_label.setStyleSheet("color: #f8f8f2; font-size: 16px; font-weight: bold;")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # Кнопка закрыть
        close_btn = QPushButton("✕ Закрыть")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff5555;
                color: #f8f8f2;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ff6e6e;
            }
            QPushButton:pressed {
                background-color: #ff4444;
            }
        """)
        close_btn.clicked.connect(self.accept)
        header_layout.addWidget(close_btn)

        main_layout.addWidget(header, 0)

        # Основной контент (сплиттер)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Левая панель — оглавление
        toc_widget = QWidget()
        toc_widget.setStyleSheet("background-color: #1e1f29;")
        toc_widget.setMinimumWidth(250)
        toc_widget.setMaximumWidth(350)
        toc_layout = QVBoxLayout(toc_widget)
        toc_layout.setContentsMargins(10, 10, 10, 10)

        toc_title = QLabel("📑 Оглавление")
        toc_title.setStyleSheet("color: #bd93f9; font-size: 14px; font-weight: bold;")
        toc_layout.addWidget(toc_title)

        self.toc_list = QListWidget()
        self.toc_list.setStyleSheet("""
            QListWidget {
                background-color: #282a36;
                color: #f8f8f2;
                border: 1px solid #44475a;
                border-radius: 4px;
                padding: 5px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 8px;
                border-radius: 3px;
                margin: 2px 0;
            }
            QListWidget::item:hover {
                background-color: #44475a;
            }
            QListWidget::item:selected {
                background-color: #6272a4;
                color: #f8f8f2;
            }
        """)
        self.toc_list.itemClicked.connect(self._on_toc_clicked)
        toc_layout.addWidget(self.toc_list)

        splitter.addWidget(toc_widget)

        # Правая панель — контент
        content_widget = QWidget()
        content_widget.setStyleSheet("background-color: #282a36;")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(10, 10, 10, 10)

        self.text_display = QTextEdit()
        self.text_display.setReadOnly(True)
        self.text_display.setStyleSheet("""
            QTextEdit {
                background-color: #282a36;
                color: #f8f8f2;
                border: 1px solid #44475a;
                border-radius: 4px;
                padding: 15px;
                font-family: 'Segoe UI', 'Arial', sans-serif;
                font-size: 14px;
                line-height: 1.6;
            }
            QTextEdit::verticalScrollBar {
                background-color: #44475a;
                width: 12px;
                border-radius: 6px;
            }
            QTextEdit::verticalScrollBar::handle {
                background-color: #6272a4;
                border-radius: 6px;
                min-height: 30px;
            }
            QTextEdit::verticalScrollBar::handle:hover {
                background-color: #bd93f9;
            }
        """)
        content_layout.addWidget(self.text_display)

        splitter.addWidget(content_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        main_layout.addWidget(splitter, 1)

        # Нижняя панель
        footer = QWidget()
        footer.setStyleSheet("background-color: #1e1f29; border-top: 1px solid #44475a;")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 8, 20, 8)

        info_label = QLabel("💡 Нажмите на раздел в оглавлении для быстрого перехода")
        info_label.setStyleSheet("color: #6272a4; font-size: 11px;")
        footer_layout.addWidget(info_label)

        footer_layout.addStretch()

        # Кнопка открыть файл
        open_file_btn = QPushButton("📂 Открыть файл")
        open_file_btn.setStyleSheet("""
            QPushButton {
                background-color: #44475a;
                color: #f8f8f2;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #6272a4;
            }
        """)
        open_file_btn.clicked.connect(self._open_file_location)
        footer_layout.addWidget(open_file_btn)

        main_layout.addWidget(footer, 0)

    def _load_documentation(self):
        """Загружает документацию из файла."""
        if not self.doc_path or not self.doc_path.exists():
            self.raw_content = """# 📘 Руководство пользователя

## ⚠️ Файл документации не найден

Файл `docs/user_guide.md` не найден в директории проекта.

### Где должен находиться файл:
- `docs/user_guide.md` в корне проекта

### Как исправить:
1. Убедитесь, что файл `user_guide.md` существует в папке `docs/`
2. Перезапустите приложение

---

*Документация будет отображена здесь после размещения файла.*
"""
            return

        try:
            with open(self.doc_path, "r", encoding="utf-8") as f:
                self.raw_content = f.read()
        except Exception as e:
            logger.error(f"Ошибка загрузки документации: {e}")
            self.raw_content = f"# ⚠️ Ошибка загрузки\n\nНе удалось прочитать файл документации:\n```\n{e}\n```"

        # Парсим разделы для оглавления
        self._parse_sections()

        # Отображаем контент
        html = self._markdown_to_html(self.raw_content)
        self.text_display.setHtml(html)

    def _parse_sections(self):
        """Парсит разделы Markdown для оглавления."""
        self.sections = []
        lines = self.raw_content.split("\n")

        for i, line in enumerate(lines):
            # Ищем заголовки H2 (##)
            if line.startswith("## ") and not line.startswith("###"):
                title = line.replace("## ", "").strip()
                self.sections.append({"title": title, "line": i})

    def _populate_toc(self):
        """Заполняет список оглавления."""
        self.toc_list.clear()

        for section in self.sections:
            item = QListWidgetItem(section["title"])
            item.setToolTip(f"Перейти к разделу: {section['title']}")
            self.toc_list.addItem(item)

    def _on_toc_clicked(self, item):
        """Обработчик клика по оглавлению."""
        index = self.toc_list.row(item)
        if index < len(self.sections):
            section = self.sections[index]
            # Находим позицию в тексте
            cursor = self.text_display.textCursor()
            cursor.movePosition(QTextCursor.Start)

            # Ищем заголовок в HTML
            search_text = section["title"]
            html = self.text_display.toHtml()

            # Простой поиск по тексту
            self.text_display.moveCursor(QTextCursor.Start)
            found = self.text_display.find(search_text)

            if not found:
                # Альтернативный поиск
                for line in self.raw_content.split("\n"):
                    if search_text in line:
                        # Находим примерную позицию
                        break

    def _markdown_to_html(self, markdown_text: str) -> str:
        """Простой конвертер Markdown в HTML."""
        html = markdown_text

        # Экранируем HTML спецсимволы
        html = html.replace("&", "&amp;")
        html = html.replace("<", "&lt;")
        html = html.replace(">", "&gt;")

        # Заголовки
        html = re.sub(r"^#### (.+)$", r"<h4 style='color:#50fa7b; margin-top:20px;'>\1</h4>", html, flags=re.MULTILINE)
        html = re.sub(r"^### (.+)$", r"<h3 style='color:#ffb86c; margin-top:25px;'>\1</h3>", html, flags=re.MULTILINE)
        html = re.sub(
            r"^## (.+)$",
            r"<h2 style='color:#bd93f9; border-bottom:1px solid #44475a; padding-bottom:5px; margin-top:30px;'>\1</h2>",
            html,
            flags=re.MULTILINE,
        )
        html = re.sub(
            r"^# (.+)$", r"<h1 style='color:#ff79c6; font-size:24px; margin-top:40px;'>\1</h1>", html, flags=re.MULTILINE
        )

        # Жирный текст
        html = re.sub(r"\*\*(.+?)\*\*", r"<b style='color:#f1fa8c;'>\1</b>", html)

        # Курсив
        html = re.sub(r"\*(.+?)\*", r"<i>\1</i>", html)

        # Инлайн код
        html = re.sub(
            r"`([^`]+)`",
            r"<code style='background-color:#44475a; color:#50fa7b; padding:2px 6px; border-radius:3px; font-family:Consolas,monospace;'>\1</code>",
            html,
        )

        # Блоки кода
        def replace_code_block(match):
            lang = match.group(1) or ""
            code = match.group(2)
            lang_label = f"<span style='color:#6272a4; font-size:11px;'>{lang}</span>" if lang else ""
            return f"""<div style='background-color:#1e1f29; border:1px solid #44475a; border-radius:5px; padding:15px; margin:10px 0; font-family:Consolas,monospace; font-size:13px; overflow-x:auto;'>
                {lang_label}
                <pre style='margin:5px 0 0 0; color:#f8f8f2;'>{code}</pre>
            </div>"""

        html = re.sub(r"```(\w*)\n(.*?)```", replace_code_block, html, flags=re.DOTALL)

        # Цитаты
        def replace_blockquote(match):
            content = match.group(1)
            return f"<div style='border-left:3px solid #bd93f9; padding-left:15px; margin:10px 0; color:#888; font-style:italic;'>{content}</div>"

        html = re.sub(r"^> (.+)$", replace_blockquote, html, flags=re.MULTILINE)

        # Горизонтальная линия
        html = html.replace("---", "<hr style='border:none; border-top:1px solid #44475a; margin:20px 0;'>")

        # Маркированные списки
        html = re.sub(r"^- (.+)$", r"<li style='margin:5px 0;'>\1</li>", html, flags=re.MULTILINE)
        html = re.sub(r"((?:<li.*?</li>\n?)+)", r"<ul style='list-style-type:disc; padding-left:20px;'>\1</ul>", html)

        # Нумерованные списки
        html = re.sub(r"^\d+\. (.+)$", r"<li style='margin:5px 0;'>\1</li>", html, flags=re.MULTILINE)

        # Параграфы (двойные переносы строк)
        html = html.replace("\n\n", "</p><p style='margin:10px 0;'>")
        html = f"<p style='margin:10px 0;'>{html}</p>"

        # Одинарные переносы
        html = html.replace("\n", "<br>")

        # Ссылки
        html = re.sub(r"\[(.+?)\]\((.+?)\)", r"<a href='\2' style='color:#8be9fd; text-decoration:underline;'>\1</a>", html)

        # Эмодзи — оставляем как есть (они уже в Unicode)

        return html

    def _open_file_location(self):
        """Открывает папку с файлом документации."""
        if self.doc_path and self.doc_path.exists():
            import subprocess
            import sys

            if sys.platform.startswith("win"):
                os.startfile(str(self.doc_path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(self.doc_path)])
            else:
                subprocess.Popen(["xdg-open", str(self.doc_path)])
        else:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                "Файл не найден",
                "Файл документации не найден.\n\n" "Ожидаемое расположение: docs/user_guide.md",
            )
