# src/analysis/market_screener.py
import pandas as pd
from typing import Dict, List, Tuple, Any
import MetaTrader5 as mt5
import logging
import threading
from src.core.config_models import Settings

logger = logging.getLogger(__name__)


class MarketScreener:
    """
    Анализирует и ранжирует рыночные инструменты на основе волатильности, тренда и ликвидности.
    Версия 2.3 с надежным подключением к MT5.
    """

    def __init__(self, config: Settings, mt5_lock: threading.Lock):
        self.config = config
        self.mt5_lock = mt5_lock

    def rank_symbols(self, data_dict: Dict[str, pd.DataFrame]) -> Tuple[List[str], List[dict]]:
        symbol_scores: Dict[str, Dict[str, Any]] = {}

        ideal_min_vol = self.config.screener_volatility.ideal_min_percent
        ideal_max_vol = self.config.screener_volatility.ideal_max_percent
        adx_threshold = self.config.screener_trend.adx_threshold
        ideal_max_spread_pips = self.config.screener_liquidity.ideal_max_spread_pips
        vol_weight = self.config.screener_weights.volatility
        trend_weight = self.config.screener_weights.trend
        liq_weight = self.config.screener_weights.liquidity

        with self.mt5_lock:
            if not mt5.initialize(path=self.config.MT5_PATH):
                logger.error("MarketScreener: Не удалось подключиться к MT5 для расчета ликвидности.")
                return [], []

            try:
                for key, df in data_dict.items():
                    try:
                        symbol = key.rsplit('_', 1)[0]
                    except (IndexError, ValueError):
                        continue

                    required_cols = ['ATR_14', 'ADX_14', 'close']
                    if df.empty or not all(col in df.columns for col in required_cols):
                        continue

                    last_atr = df['ATR_14'].iloc[-1]
                    last_close = df['close'].iloc[-1]
                    if last_close == 0:
                        continue

                    normalized_atr = (last_atr / last_close) * 100

                    if ideal_min_vol <= normalized_atr <= ideal_max_vol:
                        volatility_score = 1.0
                    elif normalized_atr > ideal_max_vol:
                        distance = normalized_atr - ideal_max_vol
                        max_distance = (ideal_max_vol - ideal_min_vol) * 3
                        volatility_score = max(0.0, 1.0 - distance / max_distance) if max_distance > 0 else 0.0
                    else:
                        distance = ideal_min_vol - normalized_atr
                        max_distance = (ideal_max_vol - ideal_min_vol) * 2
                        volatility_score = max(0.0, 1.0 - distance / max_distance) if max_distance > 0 else 0.0

                    adx = df['ADX_14'].iloc[-1]
                    trend_score = 1.0 if adx > adx_threshold else 0.5

                    liquidity_score = 0.0
                    spread_pips = -1.0
                    tick = mt5.symbol_info_tick(symbol)
                    info = mt5.symbol_info(symbol)
                    if tick and info and info.point > 0:
                        spread_pips = round((tick.ask - tick.bid) / info.point)
                        liquidity_score = max(0.0,
                                              1.0 - (spread_pips - ideal_max_spread_pips) / (ideal_max_spread_pips * 4))

                    total_score = (volatility_score * vol_weight) + (trend_score * trend_weight) + (
                                liquidity_score * liq_weight)

                    current_item_data = {
                        "symbol": symbol, "total_score": total_score, "volatility_score": volatility_score,
                        "normalized_atr_percent": normalized_atr, "trend_score": trend_score,
                        "liquidity_score": liquidity_score, "spread_pips": spread_pips
                    }

                    if symbol in symbol_scores:
                        if total_score > symbol_scores[symbol]['total_score']:
                            symbol_scores[symbol] = current_item_data
                    else:
                        symbol_scores[symbol] = current_item_data
            finally:
                mt5.shutdown()

        ranked_list = list(symbol_scores.values())
        ranked_list.sort(key=lambda x: x['total_score'], reverse=True)
        top_n = self.config.TOP_N_SYMBOLS
        top_symbols_names = [item['symbol'] for item in ranked_list[:top_n]]
        for i, item in enumerate(ranked_list):
            item['rank'] = i + 1

        return top_symbols_names, ranked_list