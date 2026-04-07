# -*- coding: utf-8 -*-
"""
MT5 Symbol Helper — Утилиты для корректной работы с символами MT5.

Решает проблемы:
- Брокер-суффиксы (EURUSDc, EURUSD.pro, EURUSDm)
- symbol_select без ожидания подгрузки
- Проверка видимости символов в Market Watch
"""

import logging
import time
from typing import Dict, List, Optional, Set

import MetaTrader5 as mt5

from src.core.mt5_connection_manager import mt5_ensure_connected

logger = logging.getLogger(__name__)


class SymbolHelper:
    """
    Помощник для работы с символами MT5.

    Гарантирует:
    - Корректное сопоставление имён символов с брокер-суффиксами
    - Успешный symbol_select с ожиданием подгрузки
    - Проверку видимости и торговых режимов
    """

    _symbol_map_cache: Optional[Dict[str, str]] = None  # {'EURUSD': 'EURUSDc', ...}
    _lock = None  # Будет установлен извне

    @classmethod
    def reset_cache(cls):
        """Сбросить кэш символов."""
        cls._symbol_map_cache = None

    @classmethod
    def build_symbol_map(
        cls,
        base_symbols: List[str],
        mt5_lock=None,
    ) -> Dict[str, str]:
        """
        Построить карту соответствия: базовое_имя -> реальное_имя_у_брокера.

        Args:
            base_symbols: Список базовых имён ['EURUSD', 'GBPUSD', ...]
            mt5_lock: Lock для потокобезопасности

        Returns:
            Словарь {'EURUSD': 'EURUSDc', 'GBPUSD': 'GBPUSD', ...}
        """
        if cls._symbol_map_cache is not None:
            return cls._symbol_map_cache

        lock = mt5_lock or cls._lock

        # Получаем все доступные символы
        all_symbols = []
        if lock:
            with lock:
                mt5_ensure_connected()
                all_symbols = mt5.symbols_get() or []
        else:
            mt5_ensure_connected()
            all_symbols = mt5.symbols_get() or []

        if not all_symbols:
            logger.warning("[SymbolHelper] Не удалось получить список символов от брокера")
            cls._symbol_map_cache = {s: s for s in base_symbols}
            return cls._symbol_map_cache

        # Создаём карту поиска
        broker_symbols: List[str] = [s.name for s in all_symbols]
        logger.info(f"[SymbolHelper] Получено {len(broker_symbols)} символов от брокера")

        # Логируем примеры для отладки
        examples = broker_symbols[:20]
        logger.info(f"[SymbolHelper] Примеры символов: {examples}")

        symbol_map = {}
        unresolved = []

        for base in base_symbols:
            # 1. Точное совпадение
            if base in broker_symbols:
                symbol_map[base] = base
                continue

            # 2. Ищем по префиксу (EURUSD → EURUSDc, EURUSD.pro, EURUSDm)
            matches = [s for s in broker_symbols if s.upper().startswith(base.upper())]
            if matches:
                # Берём первый совпавший (обычно самый короткий)
                best_match = min(matches, key=len)
                symbol_map[base] = best_match
                logger.debug(f"[SymbolHelper] {base} → {best_match}")
            else:
                unresolved.append(base)

        # Для неразрешённых — используем базовое имя (может быть ошибка позже)
        for base in unresolved:
            symbol_map[base] = base
            logger.warning(f"[SymbolHelper] Символ {base} не найден у брокера, будет использовано базовое имя")

        cls._symbol_map_cache = symbol_map
        return symbol_map

    @classmethod
    def resolve_symbol(cls, base_symbol: str, mt5_lock=None) -> str:
        """
        Разрешить базовое имя в реальное имя брокера.

        Args:
            base_symbol: Базовое имя (EURUSD)
            mt5_lock: Lock для потокобезопасности

        Returns:
            Реальное имя (EURUSDc или EURUSD если совпадает)
        """
        if cls._symbol_map_cache is None:
            # Если карта не построена, возвращаем как есть
            return base_symbol
        return cls._symbol_map_cache.get(base_symbol, base_symbol)

    @classmethod
    def select_and_wait(
        cls,
        symbol: str,
        mt5_lock=None,
        timeout: float = 2.0,
    ) -> bool:
        """
        Выбрать символ в Market Watch и дождаться его доступности.

        Args:
            symbol: Имя символа (уже разрешённое через resolve_symbol)
            mt5_lock: Lock для потокобезопасности
            timeout: Максимальное время ожидания (сек)

        Returns:
            True если символ успешно выбран и доступен
        """
        lock = mt5_lock or cls._lock

        def _try_select() -> bool:
            result = mt5.symbol_select(symbol, True)
            if not result:
                return False
            # Ждём появления symbol_info
            deadline = time.time() + timeout
            while time.time() < deadline:
                info = mt5.symbol_info(symbol)
                if info is not None and info.visible:
                    return True
                time.sleep(0.1)
            return False

        if lock:
            with lock:
                mt5_ensure_connected()
                return _try_select()
        else:
            mt5_ensure_connected()
            return _try_select()

    @classmethod
    def get_visible_symbols(cls, mt5_lock=None) -> Set[str]:
        """Получить множество видимых символов в Market Watch."""
        lock = mt5_lock or cls._lock

        if lock:
            with lock:
                mt5_ensure_connected()
                symbols = mt5.symbols_get()
                if symbols:
                    return {s.name for s in symbols if s.visible}
                return set()
        else:
            mt5_ensure_connected()
            symbols = mt5.symbols_get()
            if symbols:
                return {s.name for s in symbols if s.visible}
            return set()
