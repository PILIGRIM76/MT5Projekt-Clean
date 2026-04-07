#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Скрипт загрузки данных из Yahoo Finance для обогащения базы данных Genesis.

Использование:
    python -m src.data_enrichment.load_data --symbols AAPL MSFT GOOGL TSLA
    python -m src.data_enrichment.load_data --all  # Загрузить все доступные данные
"""

import argparse
import logging
import sys
from pathlib import Path

# Добавляем корень проекта в path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.config_loader import load_config
from src.db.database_manager import DatabaseManager
from src.data_enrichment.yahoo_finance_loader import YahooFinanceLoader

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Стандартный набор символов для обогащения
DEFAULT_SYMBOLS = [
    # Технологии
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'NVDA', 'AMD', 'INTC', 'CRM',
    # Финансы
    'JPM', 'BAC', 'GS', 'MS', 'V', 'MA',
    # Энергетика
    'XOM', 'CVX', 'COP',
    # Здравоохранение
    'JNJ', 'PFE', 'UNH', 'MRNA',
    # Потребительские
    'WMT', 'PG', 'KO', 'PEP', 'MCD', 'NKE',
    # Промышленность
    'BA', 'CAT', 'GE',
    # Индексы/ETF
    'SPY', 'QQQ', 'IWM', 'DIA',
    # Волатильность
    'VIX',
    # Крипто (через прокси)
    'BTC-USD', 'ETH-USD',
]


def main():
    parser = argparse.ArgumentParser(description='Загрузка данных из Yahoo Finance')
    parser.add_argument('--symbols', nargs='+', help='Список тикеров для загрузки')
    parser.add_argument('--all', action='store_true', help='Загрузить все данные для стандартного набора')
    parser.add_argument('--fundamentals-only', action='store_true', help='Загрузить только фундаментальные данные')
    parser.add_argument('--earnings-only', action='store_true', help='Загрузить только календарь отчетов')
    parser.add_argument('--vix-only', action='store_true', help='Загрузить только историю VIX')
    
    args = parser.parse_args()
    
    # Загружаем конфигурацию
    config = load_config()
    
    # Создаем Database Manager
    from queue import Queue
    write_queue = Queue()
    db_manager = DatabaseManager(config, write_queue)
    
    # Создаем загрузчик
    loader = YahooFinanceLoader(db_manager)
    
    # Определяем символы
    symbols = args.symbols if args.symbols else DEFAULT_SYMBOLS
    
    if args.all or (not args.fundamentals_only and not args.earnings_only and not args.vix_only):
        # Загружаем ВСЕ
        results = loader.load_all(symbols)
        print("\n" + "="*60)
        print("РЕЗУЛЬТАТЫ ЗАГРУЗКИ:")
        print(f"  Фундаментальные данные: {results.get('fundamentals', 0)}")
        print(f"  Календарь отчетов:     {results.get('earnings', 0)}")
        print(f"  История VIX:           {results.get('vix_history', 0)}")
        print(f"  ВСЕГО:                 {sum(results.values())}")
        print("="*60)
    elif args.fundamentals_only:
        count = loader.load_fundamentals(symbols)
        print(f"\nЗагружено {count} записей фундаментальных данных")
    elif args.earnings_only:
        count = loader.load_earnings_calendar(symbols)
        print(f"\nЗагружено {count} предстоящих отчетов")
    elif args.vix_only:
        count = loader.load_vix_history()
        print(f"\nЗагружено {count} записей VIX")


if __name__ == '__main__':
    main()
