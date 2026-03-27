#!/usr/bin/env python3
"""
Тест загрузки и работы классических стратегий
"""
from src.data_models import SignalType
from src.strategies.strategy_loader import StrategyLoader
from src.core.config_loader import load_config
import sys
import logging
import pandas as pd
import numpy as np

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Добавляем текущую директорию в path
sys.path.insert(0, '.')

# Импортируем необходимые модули


def test_strategies():
    """Тест загрузки и работы стратегий"""

    # 1. Загружаем конфиг
    logger.info("=== ТЕСТ 1: Загрузка конфига ===")
    try:
        config = load_config()
        logger.info(f"✓ Конфиг загружен")
        logger.info(
            f"  STRATEGY_REGIME_MAPPING: {config.STRATEGY_REGIME_MAPPING}")
    except Exception as e:
        logger.error(f"✗ Ошибка загрузки конфига: {e}")
        import traceback
        traceback.print_exc()
        return False

    # 2. Загружаем стратегии
    logger.info("\n=== ТЕСТ 2: Загрузка стратегий ===")
    try:
        loader = StrategyLoader(config)
        strategies = loader.load_strategies()
        logger.info(f"✓ Загружено {len(strategies)} стратегий:")
        for s in strategies:
            logger.info(f"  - {s.__class__.__name__}")

        if not strategies:
            logger.warning("✗ Не загружено ни одной стратегии!")
            return False
    except Exception as e:
        logger.error(f"✗ Ошибка загрузки стратегий: {e}")
        import traceback
        traceback.print_exc()
        return False

    # 3. Генерируем тестовые данные
    logger.info("\n=== ТЕСТ 3: Генерация тестовых данных ===")
    try:
        # Создаем простой DataFrame с OHLC данными
        np.random.seed(42)
        df = pd.DataFrame({
            'open': 1.09 + np.cumsum(np.random.uniform(-0.001, 0.001, 100)),
            'close': 1.09 + np.cumsum(np.random.uniform(-0.001, 0.001, 100)),
            'high': 1.10 + np.cumsum(np.random.uniform(-0.001, 0.001, 100)),
            'low': 1.08 + np.cumsum(np.random.uniform(-0.001, 0.001, 100)),
            'volume': np.random.randint(1000, 10000, 100),
        })

        # Убеждаемся что high >= low
        df['high'] = df[['open', 'high', 'close']].max(axis=1)
        df['low'] = df[['open', 'low', 'close']].min(axis=1)

        logger.info(f"✓ Создан DataFrame с {len(df)} строк")
        logger.info(f"  Столбцы: {list(df.columns)}")
        logger.info(
            f"  Диапазон цен: {df['low'].min():.5f} - {df['high'].max():.5f}")
    except Exception as e:
        logger.error(f"✗ Ошибка создания тестовых данных: {e}")
        import traceback
        traceback.print_exc()
    try:
        for strategy in strategies:
            strategy_name = strategy.__class__.__name__
            logger.info(f"\nТестируем {strategy_name}:")

            # Вызываем check_entry_conditions
            signal = strategy.check_entry_conditions(
                df, len(df) - 1, 3600)  # H1 = 3600 сек

            if signal:
                logger.info(
                    f"  ✓ Сигнал: {signal.type.name} (confidence={signal.confidence})")
            else:
                logger.info(f"  - Нет сигнала (None)")

        logger.info("\n✓ Все стратегии протестированы")
    except Exception as e:
        logger.error(f"✗ Ошибка при тестировании стратегий: {e}")
        import traceback
        traceback.print_exc()
        return False

    logger.info("\n=== ВСЕ ТЕСТЫ ПРОЙДЕНЫ ✓ ===")
    return True


if __name__ == "__main__":
    success = test_strategies()
    sys.exit(0 if success else 1)
