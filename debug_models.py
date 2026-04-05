#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Диагностика загрузки моделей для BITCOIN и XAUUSD.
"""

import logging
import queue

import MetaTrader5 as mt5

from src.core.config_loader import load_config
from src.db.database_manager import DatabaseManager, Scaler, TrainedModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

config = load_config()
db = DatabaseManager(config, queue.Queue())

symbols_to_check = ["BITCOIN", "XAUUSD"]
timeframe = mt5.TIMEFRAME_H1

for symbol in symbols_to_check:
    logger.info(f"\n{'='*60}")
    logger.info(f"ПРОВЕРКА: {symbol}")
    logger.info(f"{'='*60}")

    session = db.Session()

    # 1. Проверяем модели
    models = session.query(TrainedModel).filter_by(symbol=symbol, timeframe=timeframe).all()
    logger.info(f"Моделей найдено: {len(models)}")

    for model in models:
        logger.info(f"  - ID:{model.id}, Type:{model.model_type}, Champion:{model.is_champion}, Version:{model.version}")

    # 2. Проверяем чемпионов
    champions = session.query(TrainedModel).filter_by(symbol=symbol, timeframe=timeframe, is_champion=True).all()
    logger.info(f"Чемпионов найдено: {len(champions)}")

    # 3. Проверяем scalers
    scaler = session.query(Scaler).filter_by(symbol=symbol).first()
    logger.info(f"Scaler найдён: {'ДА' if scaler else 'НЕТ'}")

    # 4. Пробуем загрузить
    logger.info(f"\nПопытка загрузки champion моделей...")
    champion_models, x_scaler, y_scaler = db.load_champion_models(symbol, timeframe)

    if champion_models:
        logger.info(f"✅ Модели загружены: {list(champion_models.keys())}")
    else:
        logger.error(f"❌ Модели НЕ загружены!")

    if x_scaler:
        logger.info(f"✅ X Scaler загружен")
    else:
        logger.error(f"❌ X Scaler НЕ загружен!")

    if y_scaler:
        logger.info(f"✅ Y Scaler загружен")
    else:
        logger.error(f"❌ Y Scaler НЕ загружен!")

    session.close()

logger.info(f"\n{'='*60}")
logger.info("ДИАГНОСТИКА ЗАВЕРШЕНА")
logger.info(f"{'='*60}")
