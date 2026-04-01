# -*- coding: utf-8 -*-
"""Модели таблиц для GUI."""

import logging
from typing import Any, Dict, List

from PySide6.QtCore import QAbstractTableModel, Qt


class DictTableModel(QAbstractTableModel):
    """Модель таблицы для отображения списка словарей."""

    def __init__(self, data: List[Dict[str, Any]], headers: List[str], key_map: List[str]):
        super().__init__()
        self._data = data
        self._headers = headers
        self._key_map = key_map

    def rowCount(self, index):
        return len(self._data)

    def columnCount(self, index):
        return len(self._headers)

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if 0 <= section < len(self._headers):
                return self._headers[section]
        return None


class GenericTableModel(QAbstractTableModel):
    """Универсальная модель таблицы для отображения данных."""

    def __init__(self, data: List[List[Any]], headers: List[str]):
        super().__init__()
        self._data = data
        self._headers = headers

    def data(self, index, role):
        # --- Блок для отображения текста в ячейке (остается без изменений) ---
        if role == Qt.DisplayRole:
            if 0 <= index.row() < len(self._data) and 0 <= index.column() < len(self._data[index.row()]):
                return str(self._data[index.row()][index.column()])
            return None

        if role == Qt.ToolTipRole:
            if 0 <= index.row() < len(self._data):
                row_data = self._data[index.row()]
                headers = self._headers

                # Формируем красивую подсказку с использованием HTML
                tooltip_lines = []
                for header, value in zip(headers, row_data):
                    # Убираем переносы строк из заголовков для красивого отображения
                    clean_header = header.replace("\n", " ")
                    tooltip_lines.append(f"<b>{clean_header}:</b> {value}")

                # Соединяем все строки в одну с помощью HTML-переноса строки
                return "<br>".join(tooltip_lines)

        return None

    def rowCount(self, index):
        return len(self._data)

    def update_data(self, new_data: List[List[Any]]):
        """
        Обновляет данные модели.

        Args:
            new_data: новые данные для таблицы
        """
        # ОТЛАДКА: Логируем каждое обновление
        logger = logging.getLogger(__name__)
        logger.info(f"[GenericTableModel] update_data вызван с {len(new_data)} строками")

        self.layoutAboutToBeChanged.emit()
        self._data = new_data
        self.layoutChanged.emit()

    def columnCount(self, index):
        return len(self._headers)

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if 0 <= section < len(self._headers):
                return self._headers[section]
        return None


class RDTableModel(GenericTableModel):
    """Модель таблицы для отображения данных генетического программирования."""

    def __init__(self, headers: List[str]):
        super().__init__([], headers)

    def update_data(self, new_row_dict: Dict[str, Any]):
        """Добавляет новую строку в таблицу."""
        self.beginInsertRows(self.index(len(self._data), 0), len(self._data), len(self._data))
        row_data = [
            new_row_dict.get("generation", "N/A"),
            f"{new_row_dict.get('best_fitness', 0.0):.4f}",
            new_row_dict.get("config", new_row_dict.get("strategy_str", "N/A")),  # Поддержка обоих ключей
        ]
        self._data.append(row_data)
        self.endInsertRows()
