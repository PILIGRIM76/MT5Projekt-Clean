# src/utils/analysis_utils.py

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def analyze_volatility(data, period: int = 14) -> Optional[float]:
    """
    Анализирует волатильность по ATR на основе DataFrame.
    """
    try:
        if not isinstance(data, pd.DataFrame):
            raise TypeError("На вход функции analyze_volatility должен подаваться DataFrame.")

        if len(data) < period:
            return None

        high = data['high']
        low = data['low']
        close = data['close']

        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1, skipna=False)
        atr = tr.rolling(window=period).mean().iloc[-1]

        if pd.isna(atr) or atr == 0:
            return None

        return atr
    except Exception as e:
        logger.error(f"Ошибка анализа волатильности: {e}", exc_info=True)
        return None

# Другие ваши утилиты могут быть здесь, но они не должны
# импортировать 'config' или управлять MT5 соединением.