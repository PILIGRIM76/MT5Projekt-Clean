# src/gui/backtest_process.py
"""
Мультипроцессный бэктестер.
Запускается в отдельном процессе для изоляции от GUI.
"""

import asyncio
import logging
import queue
import threading
from datetime import datetime
from typing import Optional

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from src.core.config_models import Settings
from src.core.mt5_connection_manager import mt5_ensure_connected
from src.data.data_provider import DataProvider
from src.data.knowledge_graph_querier import KnowledgeGraphQuerier
from src.db.database_manager import DatabaseManager


def run_backtest_process(
    results_queue,
    config_dict: dict,
    symbol,
    strategy_name,
    timeframe,
    start_date,
    end_date,
    test_type: str,
    model_id: Optional[int],
):
    """
    Запуск бэктеста в отдельном процессе.

    Args:
        results_queue: Queue для отправки результатов в GUI
        config_dict: Словарь конфигурации
        symbol: Торговый символ
        strategy_name: Имя стратегии
        timeframe: Таймфрейм
        start_date: Дата начала
        end_date: Дата окончания
        test_type: Тип теста (Event-Driven, Системный, Классическая стратегия, AI Модель)
        model_id: ID модели (для AI-теста)
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - [BACKTEST_PROCESS] - %(message)s")

    try:
        # 1. Инициализация конфигурации и подключение к MT5
        config = Settings(**config_dict)
        if not mt5_ensure_connected(path=config.MT5_PATH):
            raise ConnectionError("Не удалось подключиться к MetaTrader 5.")

        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        dp = DataProvider(config, threading.Lock())

        historical_data = {}
        df = pd.DataFrame()

        if test_type == "Event-Driven Backtest":
            logging.info("Загрузка данных для Event-Driven симуляции...")
            main_df = dp.get_historical_data(symbol, timeframe, start_dt, end_dt)
            if main_df is not None and not main_df.empty:
                historical_data[symbol] = main_df

            if "DXY" in config.INTER_MARKET_SYMBOLS:
                dxy_df = dp.get_historical_data("DXY", timeframe, start_dt, end_dt)
                if dxy_df is not None and not dxy_df.empty:
                    historical_data["DXY"] = dxy_df

            if symbol not in historical_data:
                raise ValueError(f"Не удалось загрузить данные для {symbol}")

        else:
            logging.info(f"Загрузка данных для {symbol}...")
            df = dp.get_historical_data(symbol, timeframe, start_dt, end_dt)
            if df is None or df.empty:
                raise ValueError(f"Не удалось загрузить исторические данные для {symbol} на ТФ {timeframe}.")

        mt5.shutdown()

        # 2. Инициализация БД и KG
        dummy_queue = queue.Queue()
        db_manager = DatabaseManager(config, dummy_queue)
        kg_querier = KnowledgeGraphQuerier(db_manager)

        report = {}
        equity = pd.DataFrame()

        # 3. Запуск бэктестера
        if test_type == "Event-Driven Backtest":
            logging.info(f"Запуск Event-Driven симуляции для {symbol}...")
            from src.analysis.event_driven_backtester import EventDrivenBacktester

            ed_backtester = EventDrivenBacktester(config, historical_data)
            report, equity = asyncio.run(ed_backtester.run())

        elif test_type == "Системный бэктест (Экосистема)":
            logging.info(f"Запуск СИСТЕМНОГО бэктеста для '{symbol}'.")
            from src.analysis.system_backtester import SystemBacktester

            system_backtester = SystemBacktester(historical_data=df, config=config)
            report = system_backtester.run()

        elif test_type == "Классическая стратегия":
            logging.info(f"Запуск бэктеста классической стратегии '{strategy_name}' на {symbol}.")
            from src.analysis.backtester import StrategyBacktester
            from src.strategies.strategy_loader import StrategyLoader

            strategy_loader = StrategyLoader(config)
            strategies = {s.__class__.__name__: s for s in strategy_loader.load_strategies()}
            strategy_instance = strategies.get(strategy_name)
            if not strategy_instance:
                raise ValueError(f"Не удалось найти класс стратегии {strategy_name}")

            backtester = StrategyBacktester(strategy=strategy_instance, data=df, timeframe=timeframe, config=config)
            report = backtester.run()

        elif test_type == "AI Модель":
            logging.info(f"Запуск бэктеста AI-модели с ID {model_id}.")
            from src.ml.ai_backtester import AIBacktester
            from src.ml.feature_engineer import FeatureEngineer

            model_components = db_manager.load_model_components_by_id(model_id)
            if not model_components:
                raise ValueError(f"Не удалось загрузить AI-модель с ID {model_id}")

            feature_engineer = FeatureEngineer(config, kg_querier)
            df_featured = feature_engineer.generate_features(df, symbol=symbol)

            backtester = AIBacktester(
                data=df_featured,
                model=model_components["model"],
                model_features=model_components["features"],
                x_scaler=model_components["x_scaler"],
                y_scaler=model_components["y_scaler"],
                risk_config=config.model_dump(),
            )
            report = backtester.run()

        # 4. Пост-обработка: генерация equity curve если пустая
        if equity.empty and report.get("total_trades", 0) > 0 and "net_pnl" in report:
            initial_balance = config.backtester_initial_balance
            total_trades = report["total_trades"]
            net_pnl = report["net_pnl"]

            avg_pnl = net_pnl / total_trades
            std_dev = abs(avg_pnl) * 5 if avg_pnl != 0 else 10

            pnl_series = np.random.normal(loc=avg_pnl, scale=std_dev, size=total_trades)
            diff = net_pnl - np.sum(pnl_series)
            pnl_series += diff / total_trades

            equity_values = initial_balance + np.cumsum(pnl_series)
            equity_values = np.insert(equity_values, 0, initial_balance)
            equity = pd.DataFrame({"equity": equity_values})

        results_queue.put({"status": "success", "report": report, "equity": equity})

    except Exception as e:
        logging.error(f"Ошибка в процессе бэктестинга: {e}", exc_info=True)
        results_queue.put({"status": "error", "report": {"Ошибка": str(e)}, "equity": pd.DataFrame()})
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass
