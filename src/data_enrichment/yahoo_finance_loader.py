# src/data_enrichment/yahoo_finance_loader.py
"""
Yahoo Finance Data Loader — Загрузка фундаментальных данных, календаря отчетов и настроений.

Использует библиотеку yfinance (бесплатно, без API ключа).

Установить: pip install yfinance
"""

import logging
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import yfinance as yf
import pandas as pd

from src.db.database_manager import DatabaseManager
from src.db.database_manager import FundamentalData, EarningsCalendar, MarketSentiment, DataEnrichmentLog

logger = logging.getLogger(__name__)


class YahooFinanceLoader:
    """
    Загрузчик данных из Yahoo Finance.
    
    Загружает:
    1. Фундаментальные данные (P/E, EPS, Market Cap, и т.д.)
    2. Даты отчетов (Earnings Calendar)
    3. Исторические данные для VIX (индекс волатильности)
    """
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    def load_fundamentals(self, symbols: List[str]) -> int:
        """
        Загрузить фундаментальные данные для списка символов.
        
        Args:
            symbols: Список тикеров (например, ['AAPL', 'MSFT', 'GOOGL'])
        
        Returns:
            Количество загруженных записей
        """
        start_time = time.time()
        loaded_count = 0
        
        logger.info(f"[YahooFinance] Загрузка фундаментальных данных для {len(symbols)} символов...")
        
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info
                
                if not info:
                    logger.warning(f"[YahooFinance] Нет данных для {symbol}")
                    continue
                
                # Создаем запись в БД
                fundamental = FundamentalData(
                    symbol=symbol,
                    timestamp=datetime.utcnow(),
                    
                    # Оценочные метрики
                    pe_ratio=info.get('trailingPE'),
                    forward_pe=info.get('forwardPE'),
                    peg_ratio=info.get('pegRatio'),
                    price_to_book=info.get('priceToBook'),
                    price_to_sales=info.get('priceToSalesTrailing12Months'),
                    enterprise_value=info.get('enterpriseValue'),
                    ev_to_revenue=info.get('enterpriseToRevenue'),
                    ev_to_ebitda=info.get('enterpriseToEbitda'),
                    
                    # Финансовые метрики
                    eps=info.get('trailingEps'),
                    revenue=info.get('totalRevenue'),
                    net_income=info.get('netIncomeToCommon'),
                    profit_margin=info.get('profitMargins'),
                    operating_margin=info.get('operatingMargins'),
                    roe=info.get('returnOnEquity'),
                    roa=info.get('returnOnAssets'),
                    debt_to_equity=info.get('debtToEquity'),
                    current_ratio=info.get('currentRatio'),
                    
                    # Рыночные метрики
                    market_cap=info.get('marketCap'),
                    shares_outstanding=info.get('sharesOutstanding'),
                    float_shares=info.get('floatShares'),
                    
                    # Дивиденды
                    dividend_yield=info.get('dividendYield'),
                    dividend_rate=info.get('dividendRate'),
                    payout_ratio=info.get('payoutRatio'),
                    five_year_avg_dividend_yield=info.get('fiveYearAvgDividendYield'),
                    
                    # Аналитики
                    target_mean_price=info.get('targetMeanPrice'),
                    target_high_price=info.get('targetHighPrice'),
                    target_low_price=info.get('targetLowPrice'),
                    recommendation_mean=info.get('recommendationMean'),
                    number_of_analyst_opinions=info.get('numberOfAnalystOpinions'),
                )
                
                # Сохраняем в БД
                session = self.db.Session()
                try:
                    session.add(fundamental)
                    session.commit()
                    loaded_count += 1
                    logger.debug(f"[YahooFinance] Загружены данные для {symbol}: P/E={fundamental.pe_ratio}, Cap={fundamental.market_cap}")
                except Exception as e:
                    session.rollback()
                    logger.error(f"[YahooFinance] Ошибка сохранения {symbol}: {e}")
                finally:
                    session.close()
                
                # Пауза чтобы не превысить лимиты
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"[YahooFinance] Ошибка загрузки {symbol}: {e}")
        
        duration = time.time() - start_time
        self._log_enrichment('YahooFinance_Fundamentals', 'SUCCESS', loaded_count, duration)
        
        logger.info(f"[YahooFinance] Загружено {loaded_count}/{len(symbols)} записей за {duration:.2f}с")
        return loaded_count
    
    def load_earnings_calendar(self, symbols: List[str], days_ahead: int = 90) -> int:
        """
        Загрузить даты предстоящих отчетов компаний.
        
        Args:
            symbols: Список тикеров
            days_ahead: На сколько дней вперед загружать
        
        Returns:
            Количество загруженных записей
        """
        start_time = time.time()
        loaded_count = 0
        
        logger.info(f"[YahooFinance] Загрузка календаря отчетов для {len(symbols)} символов...")
        
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                earnings_dates = ticker.earnings_dates
                
                if earnings_dates is None or earnings_dates.empty:
                    continue
                
                session = self.db.Session()
                try:
                    for idx, row in earnings_dates.iterrows():
                        earnings_date = idx.to_pydatetime() if hasattr(idx, 'to_pydatetime') else idx
                        
                        # Пропускаем прошедшие отчеты
                        if earnings_date < datetime.now():
                            continue
                        
                        # Пропускаем слишком далекие отчеты
                        if earnings_date > datetime.now() + timedelta(days=days_ahead):
                            continue
                        
                        eps_estimate = row.get('EPS Estimate')
                        eps_actual = row.get('Reported EPS')
                        
                        # Расчет сюрприза
                        surprise_percent = None
                        if eps_estimate and eps_actual and eps_estimate != 0:
                            surprise_percent = ((eps_actual - eps_estimate) / abs(eps_estimate)) * 100
                        
                        earning = EarningsCalendar(
                            symbol=symbol,
                            earnings_date=earnings_date,
                            eps_estimate=eps_estimate if eps_estimate != '-' and pd.notna(eps_estimate) else None,
                            eps_actual=eps_actual if eps_actual != '-' and pd.notna(eps_actual) else None,
                            surprise_percent=surprise_percent,
                        )
                        
                        session.add(earning)
                        loaded_count += 1
                    
                    session.commit()
                    
                except Exception as e:
                    session.rollback()
                    logger.error(f"[YahooFinance] Ошибка сохранения отчетов {symbol}: {e}")
                finally:
                    session.close()
                
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"[YahooFinance] Ошибка загрузки отчетов {symbol}: {e}")
        
        duration = time.time() - start_time
        self._log_enrichment('YahooFinance_Earnings', 'SUCCESS', loaded_count, duration)
        
        logger.info(f"[YahooFinance] Загружено {loaded_count} предстоящих отчетов за {duration:.2f}с")
        return loaded_count
    
    def load_vix_history(self, days: int = 365) -> int:
        """
        Загрузить историю индекса волатильности VIX.
        
        Args:
            days: Сколько дней истории загрузить
        
        Returns:
            Количество загруженных записей
        """
        start_time = time.time()
        
        logger.info(f"[YahooFinance] Загрузка истории VIX за {days} дней...")
        
        try:
            vix = yf.download('^VIX', period=f'{days}d', progress=False)
            
            if vix.empty:
                logger.warning("[YahooFinance] Нет данных VIX")
                return 0
            
            loaded_count = 0
            session = self.db.Session()
            
            try:
                for timestamp, row in vix.iterrows():
                    # Приводим timestamp к datetime
                    if hasattr(timestamp, 'to_pydatetime'):
                        ts = timestamp.to_pydatetime()
                    else:
                        ts = timestamp
                    
                    sentiment = MarketSentiment(
                        timestamp=ts,
                        vix=row.get('Close'),
                    )
                    
                    session.add(sentiment)
                    loaded_count += 1
                
                session.commit()
                
            except Exception as e:
                session.rollback()
                logger.error(f"[YahooFinance] Ошибка сохранения VIX: {e}")
                return 0
            finally:
                session.close()
            
            duration = time.time() - start_time
            self._log_enrichment('YahooFinance_VIX', 'SUCCESS', loaded_count, duration)
            
            logger.info(f"[YahooFinance] Загружено {loaded_count} записей VIX за {duration:.2f}с")
            return loaded_count
            
        except Exception as e:
            logger.error(f"[YahooFinance] Ошибка загрузки VIX: {e}")
            self._log_enrichment('YahooFinance_VIX', 'FAILED', 0, time.time() - start_time, str(e))
            return 0
    
    def load_all(self, symbols: List[str]) -> Dict[str, int]:
        """
        Загрузить ВСЕ данные из Yahoo Finance.
        
        Args:
            symbols: Список тикеров
        
        Returns:
            Словарь с количеством загруженных записей по каждому типу
        """
        logger.info(f"[YahooFinance] === НАЧАЛО ПОЛНОЙ ЗАГРУЗКИ ДАННЫХ ===")
        
        results = {
            'fundamentals': self.load_fundamentals(symbols),
            'earnings': self.load_earnings_calendar(symbols),
            'vix_history': self.load_vix_history(),
        }
        
        total = sum(results.values())
        logger.info(f"[YahooFinance] === ЗАГРУЗКА ЗАВЕРШЕНА: Всего {total} записей ===")
        
        return results
    
    def _log_enrichment(self, source: str, status: str, records: int, duration: float, error: str = None):
        """Записать лог загрузки."""
        try:
            session = self.db.Session()
            log = DataEnrichmentLog(
                source=source,
                status=status,
                records_fetched=records,
                error_message=error,
                duration_seconds=duration
            )
            session.add(log)
            session.commit()
            session.close()
        except Exception as e:
            logger.error(f"[EnrichmentLog] Ошибка записи лога: {e}")
