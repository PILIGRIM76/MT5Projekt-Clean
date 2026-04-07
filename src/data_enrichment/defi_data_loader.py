# src/data_enrichment/defi_data_loader.py
"""
DeFi Data Loader — Загрузка метрик протоколов из публичных источников.

Использует:
- DefiLlama API (TVL, APY, кредитные ставки) - полностью бесплатно, без ключей
- Публичные RPC ноды для проверки статуса сетей

Все данные бесплатны для чтения. Не требуют кошельков, подписей или депозитов.
"""

import logging
import time
import json
from datetime import datetime
from typing import Dict, List, Optional, Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.db.database_manager import DatabaseManager, DefiMetrics, DataEnrichmentLog

logger = logging.getLogger(__name__)


class DefiDataLoader:
    """
    Загрузчик DeFi метрик.
    Собирает TVL, доходности пулов, ставки кредитования и статус блокчейнов.
    """
    
    # Публичные эндпоинты (бесплатно, без API ключей)
    DEFILLAMA_YIELDS = "https://yields.llama.fi/pools"
    DEFILLAMA_PROTOCOLS = "https://api.llama.fi/protocols"
    
    # Фильтры для отсева мусора
    MIN_TVL = 1_000_000  # Минимум $1M TVL
    ALLOWED_CHAINS = {"Ethereum", "Arbitrum", "Polygon", "Base", "Optimism", "Avalanche"}
    TOP_POOLS_LIMIT = 150  # Сохраняем только топ N пулов
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        
        # Настройка сессии с повторными попытками
        self.session = requests.Session()
        retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry_strategy))
        self.session.headers.update({"User-Agent": "GenesisTradingBot/1.0"})

    def load_yields_and_tvl(self) -> int:
        """
        Загрузить доходности пулов (APY) и TVL из DefiLlama.
        
        Returns:
            Количество сохраненных метрик
        """
        start_time = time.time()
        logger.info("[DeFi] Загрузка доходностей и TVL из DefiLlama...")
        
        try:
            response = self.session.get(self.DEFILLAMA_YIELDS, timeout=30)
            response.raise_for_status()
            pools = response.json().get("data", [])
            
            logger.info(f"[DeFi] Получено {len(pools)} пулов. Фильтрация...")
            
            # Фильтруем только качественные пулы
            filtered_pools = [
                p for p in pools
                if p.get("chain") in self.ALLOWED_CHAINS
                and p.get("tvlUsd", 0) >= self.MIN_TVL
                and p.get("apy") is not None
            ]
            
            # Сортируем по TVL и берем топ
            filtered_pools.sort(key=lambda x: x.get("tvlUsd", 0), reverse=True)
            filtered_pools = filtered_pools[:self.TOP_POOLS_LIMIT]
            
            logger.info(f"[DeFi] Отфильтровано до {len(filtered_pools)} качественных пулов")
            
            # Сохраняем в БД
            saved_count = self._save_pools_to_db(filtered_pools)
            duration = time.time() - start_time
            
            self._log_enrichment("DefiLlama_Yields", "SUCCESS", saved_count, duration)
            logger.info(f"[DeFi] Загружено {saved_count} метрик за {duration:.2f}с")
            return saved_count
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[DeFi] Ошибка загрузки доходностей: {e}")
            self._log_enrichment("DefiLlama_Yields", "FAILED", 0, duration, str(e))
            return 0

    def _save_pools_to_db(self, pools: List[Dict]) -> int:
        """Пакетное сохранение пулов в БД."""
        session = self.db.Session()
        saved_count = 0
        
        try:
            for pool in pools:
                timestamp = datetime.utcnow()
                chain = pool.get("chain")
                protocol = pool.get("project")
                asset = pool.get("symbol")
                pool_id = pool.get("pool")
                
                # 1. Supply APY (доходность для поставщиков ликвидности)
                apy = pool.get("apy")
                if apy is not None:
                    metric = DefiMetrics(
                        timestamp=timestamp, chain=chain, protocol=protocol,
                        metric_type="supply_apy", asset=asset, value=float(apy),
                        pool_id=pool_id, extra_data=json.dumps({
                            "tvl_usd": pool.get("tvlUsd"),
                            "apy_mean_7d": pool.get("apyMean7d"),
                            "il_risk": pool.get("ilRisk"),
                            "exposure": pool.get("exposure")
                        })
                    )
                    session.add(metric)
                    saved_count += 1
                
                # 2. TVL (Total Value Locked)
                tvl = pool.get("tvlUsd")
                if tvl is not None:
                    metric = DefiMetrics(
                        timestamp=timestamp, chain=chain, protocol=protocol,
                        metric_type="tvl", asset=asset, value=float(tvl),
                        pool_id=pool_id, extra_data=None
                    )
                    session.add(metric)
                    saved_count += 1
                
                # 3. Reward APY (если есть дополнительные вознаграждения)
                reward_apy = pool.get("rewardApy")
                if reward_apy is not None:
                    metric = DefiMetrics(
                        timestamp=timestamp, chain=chain, protocol=protocol,
                        metric_type="reward_apy", asset=asset, value=float(reward_apy),
                        pool_id=pool_id, extra_data=None
                    )
                    session.add(metric)
                    saved_count += 1
            
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"[DeFi] Ошибка сохранения пулов: {e}")
        finally:
            session.close()
            
        return saved_count

    def load_lending_rates(self) -> int:
        """
        Загрузить ставки кредитования из Aave/Compound (через DefiLlama).
        Фильтруем только lending протоколы.
        """
        start_time = time.time()
        logger.info("[DeFi] Загрузка ставок кредитования...")
        
        try:
            response = self.session.get(self.DEFILLAMA_YIELDS, timeout=30)
            response.raise_for_status()
            pools = response.json().get("data", [])
            
            # Фильтруем только lending протоколы
            lending_protocols = {"aave-v2", "aave-v3", "compound-v2", "compound-v3", "spark", "radiant"}
            lending_pools = [p for p in pools if p.get("project") in lending_protocols]
            
            logger.info(f"[DeFi] Найдено {len(lending_pools)} lending пулов")
            
            session = self.db.Session()
            saved_count = 0
            
            try:
                for pool in lending_pools:
                    timestamp = datetime.utcnow()
                    # Aave/Compound обычно имеют supply и borrow apy в одном пуле
                    if pool.get("apy") is not None:
                        metric = DefiMetrics(
                            timestamp=timestamp,
                            chain=pool.get("chain"),
                            protocol=pool.get("project"),
                            metric_type="supply_apy",
                            asset=pool.get("symbol"),
                            value=float(pool["apy"]),
                            pool_id=pool.get("pool"),
                            extra_data=json.dumps({"tvl_usd": pool.get("tvlUsd")})
                        )
                        session.add(metric)
                        saved_count += 1
                    
                    # Если есть borrow rate (иногда в отдельном поле)
                    borrow_apy = pool.get("il7d") # Placeholder, DefiLlama иногда отдает иначе
                    # Для точных borrow ставок лучше использовать отдельные API, но пока берем что есть
                    
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"[DeFi] Ошибка сохранения lending ставок: {e}")
            finally:
                session.close()
                
            duration = time.time() - start_time
            self._log_enrichment("DefiLlama_Lending", "SUCCESS", saved_count, duration)
            logger.info(f"[DeFi] Загружено {saved_count} lending метрик за {duration:.2f}с")
            return saved_count
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[DeFi] Ошибка загрузки lending ставок: {e}")
            self._log_enrichment("DefiLlama_Lending", "FAILED", 0, duration, str(e))
            return 0

    def load_all(self) -> Dict[str, int]:
        """
        Загрузить все доступные DeFi данные.
        """
        logger.info("[DeFi] === НАЧАЛО ПОЛНОЙ ЗАГРУЗКИ DEFI ДАННЫХ ===")
        
        results = {
            "yields_tvl": self.load_yields_and_tvl(),
            "lending_rates": self.load_lending_rates(),
        }
        
        total = sum(results.values())
        logger.info(f"[DeFi] === ЗАГРУЗКА ЗАВЕРШЕНА: Всего {total} метрик ===")
        return results

    def _log_enrichment(self, source: str, status: str, records: int, duration: float, error: str = None):
        """Записать лог загрузки."""
        try:
            session = self.db.Session()
            log = DataEnrichmentLog(
                source=source, status=status, records_fetched=records,
                error_message=error, duration_seconds=duration
            )
            session.add(log)
            session.commit()
            session.close()
        except Exception as e:
            logger.error(f"[EnrichmentLog] Ошибка записи лога: {e}")
