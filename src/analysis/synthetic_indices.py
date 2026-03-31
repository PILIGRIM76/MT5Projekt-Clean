# src/analysis/synthetic_indices.py
import logging
from typing import Dict

import pandas as pd

logger = logging.getLogger(__name__)


def calculate_synthetic_dxy(data_dict: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Рассчитывает синтетический индекс доллара (DXY) на основе доступных валютных пар.
    Использует упрощенную формулу, взвешивая валюты поровну.
    """
    logger.info("Расчет синтетического индекса DXY...")
    dxy_components = {"EURUSD": -0.576, "USDJPY": 0.136, "GBPUSD": -0.119, "USDCAD": 0.091, "USDCHF": 0.036}

    returns_df = pd.DataFrame()

    for symbol, weight in dxy_components.items():
        if symbol in data_dict and not data_dict[symbol].empty:
            df = data_dict[symbol]
            returns = df["close"].pct_change()

            # Инвертируем вес для пар, где USD не является базовой валютой
            if not symbol.startswith("USD"):
                returns_df[symbol] = returns * -1
            else:
                returns_df[symbol] = returns

    if returns_df.empty:
        logger.warning("Недостаточно данных для расчета синтетического DXY.")
        return pd.DataFrame()

    # Расчет взвешенного индекса
    synthetic_dxy_returns = (returns_df * pd.Series(dxy_components)).sum(axis=1)

    # Создаем индекс, начинающийся со 100
    synthetic_dxy_index = 100 * (1 + synthetic_dxy_returns).cumprod()

    # Формируем DataFrame, похожий на реальные котировки
    dxy_df = pd.DataFrame(index=synthetic_dxy_index.index)
    dxy_df["close"] = synthetic_dxy_index

    # Добавляем базовые индикаторы, необходимые для Оркестратора
    dxy_df["EMA_50"] = dxy_df["close"].ewm(span=50, adjust=False).mean()
    plus_dm = dxy_df["close"].diff()
    minus_dm = dxy_df["close"].diff() * -1
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0

    tr = dxy_df["close"].diff().abs()
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()

    plus_di = 100 * (plus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr)

    dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di))
    dxy_df["ADX_14"] = dx.ewm(alpha=1 / 14, adjust=False).mean()

    dxy_df.dropna(inplace=True)

    logger.info(f"Синтетический DXY успешно рассчитан. Последнее значение: {dxy_df['close'].iloc[-1]:.2f}")
    return dxy_df


def calculate_synthetic_vix(data_dict: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Рассчитывает синтетический индекс волатильности (VIX) для рынка Forex.
    Основан на среднем нормализованном ATR по ключевым валютным парам.
    """
    logger.info("Расчет синтетического индекса волатильности (VIX)...")
    vix_components = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "XAUUSD"]

    atr_norm_df = pd.DataFrame()

    for symbol in vix_components:
        if symbol in data_dict and not data_dict[symbol].empty:
            df = data_dict[symbol]
            if "ATR_14" in df.columns and "close" in df.columns:
                # Нормализуем ATR, чтобы сравнивать волатильность разных инструментов
                atr_norm_df[symbol] = (df["ATR_14"] / df["close"]) * 100

    if atr_norm_df.empty:
        logger.warning("Недостаточно данных для расчета синтетического VIX.")
        return pd.DataFrame()

    # Усредняем нормализованную волатильность
    synthetic_vix_series = atr_norm_df.mean(axis=1)

    # Формируем DataFrame
    vix_df = pd.DataFrame(index=synthetic_vix_series.index)
    vix_df["close"] = synthetic_vix_series
    vix_df.dropna(inplace=True)

    logger.info(f"Синтетический VIX успешно рассчитан. Последнее значение: {vix_df['close'].iloc[-1]:.4f}")
    return vix_df
