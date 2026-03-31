# -*- coding: utf-8 -*-
"""
Модели данных для Qt таблиц.

Содержит:
- DictTableModel: Модель для списка словарей
- GenericTableModel: Универсальная модель для DataFrame
- RDTableModel: Модель для R&D директив
"""

from PySide6.QtCore import QAbstractTableModel, Qt
import pandas as pd


class DictTableModel(QAbstractTableModel):
    """Модель для отображения списка словарей в таблице."""
    
    def __init__(self, data: list[dict], headers: list[str], key_map: list[str]):
        super().__init__()
        self._data = data
        self._headers = headers
        self._key_map = key_map

    def rowCount(self, index=None):
        return len(self._data)

    def columnCount(self, index=None):
        return len(self._headers)

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            row = index.row()
            col = index.column()
            if 0 <= row < len(self._data) and 0 <= col < len(self._key_map):
                key = self._key_map[col]
                value = self._data[row].get(key, '')
                return str(value)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if 0 <= section < len(self._headers):
                return self._headers[section]
        return None


class GenericTableModel(QAbstractTableModel):
    """Универсальная модель для отображения pandas DataFrame."""
    
    def __init__(self, df: pd.DataFrame, headers: list[str] = None):
        super().__init__()
        self._df = df
        self._headers = headers if headers else df.columns.tolist()

    def rowCount(self, index=None):
        return len(self._df)

    def columnCount(self, index=None):
        return len(self._headers)

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            row = index.row()
            col = index.column()
            if 0 <= row < len(self._df) and 0 <= col < len(self._headers):
                value = self._df.iloc[row, col]
                return str(value)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if 0 <= section < len(self._headers):
                return self._headers[section]
        return None


class RDTableModel(GenericTableModel):
    """Модель для отображения R&D директив с дополнительными методами."""
    
    def __init__(self, df: pd.DataFrame, headers: list[str] = None):
        super().__init__(df, headers)
    
    def get_directive(self, row: int) -> dict:
        """Получение данных директивы по строке."""
        if 0 <= row < len(self._df):
            return self._df.iloc[row].to_dict()
        return None
    
    def update_directive(self, row: int, data: dict):
        """Обновление данных директивы."""
        if 0 <= row < len(self._df):
            for key, value in data.items():
                if key in self._df.columns:
                    self._df.at[row, key] = value
            self.layoutChanged.emit()
