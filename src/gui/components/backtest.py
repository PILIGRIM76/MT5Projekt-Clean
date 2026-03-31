# -*- coding: utf-8 -*-
"""
Компоненты для бэктестинга.

Содержит:
- run_backtest_process: Функция для запуска бэктеста в отдельном процессе
- DirectiveDialog: Диалог для управления R&D директивами
"""

import logging
import multiprocessing
import queue
import threading
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path

import pandas as pd
import numpy as np
import MetaTrader5 as mt5

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QGridLayout
from PySide6.QtCore import Slot, Signal

from src.core.config_models import Settings
from src.data.data_provider import DataProvider
from src.data.knowledge_graph_querier import KnowledgeGraphQuerier
from src.strategies.strategy_loader import StrategyLoader


def run_backtest_process(
    results_queue,
    config_dict: dict,
    symbol: str,
    strategy_name: str,
    timeframe: int,
    start_date,
    end_date,
    test_type: str,
    model_id: Optional[int]
):
    """
    Запуск бэктеста в отдельном процессе.
    
    Args:
        results_queue: Очередь для результатов
        config_dict: Словарь конфигурации
        symbol: Символ для тестирования
        strategy_name: Имя стратегии
        timeframe: Таймфрейм
        start_date: Дата начала
        end_date: Дата окончания
        test_type: Тип теста
        model_id: ID модели (для AI бэктеста)
    """
    # Настройка логирования внутри процесса
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - [BACKTEST_PROCESS] - %(message)s'
    )

    try:
        # 1. Инициализация конфигурации и подключение к MT5
        config = Settings(**config_dict)
        if not mt5.initialize(path=config.MT5_PATH):
            raise ConnectionError("Не удалось подключиться к MetaTrader 5.")

        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        # Инициализация провайдера данных
        dp = DataProvider(config, threading.Lock())

        # 2. Загрузка данных в зависимости от типа теста
        historical_data = {}  # Для Event-Driven
        df = pd.DataFrame()  # Для векторных тестов

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

        # 3. Инициализация вспомогательных компонентов
        dummy_queue = queue.Queue()
        from src.db.database_manager import DatabaseManager
        db_manager = DatabaseManager(config, dummy_queue)
        kg_querier = KnowledgeGraphQuerier(db_manager)

        report = {}
        equity = pd.DataFrame()

        # 4. Запуск соответствующего бэктестера
        if test_type == "Event-Driven Backtest":
            from src.analysis.event_driven_backtester import EventDrivenBacktester
            ed_backtester = EventDrivenBacktester(config, historical_data)
            report, equity = asyncio.run(ed_backtester.run())

        elif test_type == "Системный бэктест (Экосистема)":
            from src.analysis.system_backtester import SystemBacktester
            system_backtester = SystemBacktester(historical_data=df, config=config)
            report = system_backtester.run()

        elif test_type == "Классическая стратегия":
            from src.analysis.backtester import StrategyBacktester
            strategy_loader = StrategyLoader(config)
            strategies = {s.__class__.__name__: s for s in strategy_loader.load_strategies()}
            strategy_instance = strategies.get(strategy_name)
            if not strategy_instance:
                raise ValueError(f"Не удалось найти класс стратегии {strategy_name}")
            
            backtester = StrategyBacktester(
                strategy=strategy_instance, data=df, timeframe=timeframe, config=config
            )
            report = backtester.run()

        elif test_type == "AI Модель":
            from src.ml.ai_backtester import AIBacktester
            from src.ml.feature_engineer import FeatureEngineer
            
            model_components = db_manager.load_model_components_by_id(model_id)
            if not model_components:
                raise ValueError(f"Не удалось загрузить AI-модель с ID {model_id}")

            feature_engineer = FeatureEngineer(config, kg_querier)
            df_featured = feature_engineer.generate_features(df, symbol=symbol)
            risk_config_dict = config.model_dump()

            backtester = AIBacktester(
                data=df_featured,
                model=model_components['model'],
                model_features=model_components['features'],
                x_scaler=model_components['x_scaler'],
                y_scaler=model_components['y_scaler'],
                risk_config=risk_config_dict
            )
            report = backtester.run()

        # 5. Отправка результатов
        results_queue.put({
            'success': True,
            'report': report,
            'equity': equity.to_dict() if not equity.empty else {}
        })

    except Exception as e:
        logging.error(f"Ошибка бэктеста: {e}", exc_info=True)
        results_queue.put({
            'success': False,
            'error': str(e)
        })
    finally:
        mt5.shutdown()


class DirectiveDialog(QDialog):
    """Диалог для просмотра и управления R&D директивами."""
    
    directive_applied = Signal(dict)
    
    def __init__(self, directives: List[dict], parent=None):
        super().__init__(parent)
        self.directives = directives
        self.setWindowTitle("R&D Директивы")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Текст с директивами
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        
        # Форматирование директив
        for directive in self.directives:
            self.text_edit.append(f"<b>Стратегия:</b> {directive.get('strategy', 'N/A')}")
            self.text_edit.append(f"<b>Режим:</b> {directive.get('regime', 'N/A')}")
            self.text_edit.append(f"<b>Действие:</b> {directive.get('action', 'N/A')}")
            self.text_edit.append(f"<b>Причина:</b> {directive.get('reason', 'N/A')}")
            self.text_edit.append("-" * 50)
        
        layout.addWidget(self.text_edit)
        
        # Кнопки
        btn_layout = QHBoxLayout()
        
        apply_btn = QPushButton("Применить")
        apply_btn.clicked.connect(self.apply_directive)
        btn_layout.addWidget(apply_btn)
        
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
        self.setLayout(layout)
    
    @Slot()
    def apply_directive(self):
        """Применение выбранной директивы."""
        if self.directives:
            self.directive_applied.emit(self.directives[0])
            self.accept()
