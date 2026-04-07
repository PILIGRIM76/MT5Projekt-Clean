# src/analysis/defi_analyzer.py
"""
DeFi Analyzer — Анализ DeFi метрик для использования в торговле.

Использует данные из defi_metrics (DefiLlama) для:
1. Фильтрации риска (высокий APY = риск скама)
2. Определения режима рынка (ставки кредитования = жадность/страх)
3. Генерации признаков для AI моделей
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func

from src.db.models import DefiMetrics

logger = logging.getLogger(__name__)


class DeFiAnalyzer:
    """
    Анализирует DeFi метрики и предоставляет торговые сигналы.
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

        # Пороги для анализа риска
        self.RISK_THRESHOLDS = {
            "apy_scam_risk": 100.0,  # APY > 100% = риск скама
            "apy_high_risk": 50.0,  # APY > 50% = высокий риск
            "apy_medium_risk": 20.0,  # APY > 20% = средний риск
            "tvl_drop_warning": 0.20,  # Падение TVL > 20% за неделю
            "min_tvl_safe": 10_000_000,  # Минимальный TVL для безопасности ($10M)
        }

        # Пороги для режима рынка
        self.REGIME_THRESHOLDS = {
            "lending_greed": 15.0,  # Ставки > 15% = Extreme Greed
            "lending_fear": 3.0,  # Ставки < 3% = Fear
            "total_tvl_bull": 100_000_000_000,  # Общий TVL > $100B = Bull
            "total_tvl_bear": 50_000_000_000,  # Общий TVL < $50B = Bear
        }

    def get_risk_assessment(self, symbol: str = None) -> Dict:
        """
        Оценка риска для конкретного актива или всего рынка.

        Returns:
            {
                "risk_level": "low" | "medium" | "high" | "scam",
                "max_apy": float,
                "avg_apy": float,
                "tvl_usd": float,
                "tvl_trend": "up" | "down" | "stable",
                "warnings": List[str]
            }
        """
        session = self.db.Session()
        result = {"risk_level": "low", "max_apy": 0.0, "avg_apy": 0.0, "tvl_usd": 0.0, "tvl_trend": "stable", "warnings": []}

        try:
            since = datetime.utcnow() - timedelta(hours=24)

            # Базовый фильтр
            query = session.query(DefiMetrics).filter(
                DefiMetrics.timestamp > since, DefiMetrics.value < 1000.0  # Исключаем явные ошибки
            )

            # Если указан символ — фильтруем
            if symbol:
                query = query.filter(DefiMetrics.asset.contains(symbol.split("-")[0]))

            metrics = query.all()

            if not metrics:
                return result

            # APY анализ
            apy_values = [m.value for m in metrics if m.metric_type == "supply_apy"]
            if apy_values:
                result["max_apy"] = max(apy_values)
                result["avg_apy"] = sum(apy_values) / len(apy_values)

                # Оценка риска по APY
                if result["max_apy"] > self.RISK_THRESHOLDS["apy_scam_risk"]:
                    result["risk_level"] = "scam"
                    result["warnings"].append(f"APY {result['max_apy']:.1f}% > 100% — риск скама!")
                elif result["max_apy"] > self.RISK_THRESHOLDS["apy_high_risk"]:
                    result["risk_level"] = "high"
                    result["warnings"].append(f"APY {result['max_apy']:.1f}% > 50% — высокий риск")
                elif result["max_apy"] > self.RISK_THRESHOLDS["apy_medium_risk"]:
                    result["risk_level"] = "medium"

            # TVL анализ
            tvl_values = [m.value for m in metrics if m.metric_type == "tvl"]
            if tvl_values:
                result["tvl_usd"] = max(tvl_values)

                if result["tvl_usd"] < self.RISK_THRESHOLDS["min_tvl_safe"]:
                    result["warnings"].append(f"TVL ${result['tvl_usd']/1_000_000:.1f}M < $10M — низкая ликвидность")

                # Тренд TVL (сравнение с неделей назад)
                since_week = datetime.utcnow() - timedelta(days=7)
                week_tvl = (
                    session.query(func.max(DefiMetrics.value))
                    .filter(
                        DefiMetrics.metric_type == "tvl", DefiMetrics.timestamp > since_week, DefiMetrics.timestamp < since
                    )
                    .scalar()
                )

                if week_tvl and week_tvl > 0:
                    tvl_change = (result["tvl_usd"] - week_tvl) / week_tvl
                    if tvl_change < -self.RISK_THRESHOLDS["tvl_drop_warning"]:
                        result["tvl_trend"] = "down"
                        result["warnings"].append(f"TVL упал на {abs(tvl_change)*100:.1f}% за неделю!")
                    elif tvl_change > 0.10:
                        result["tvl_trend"] = "up"

        except Exception as e:
            logger.error(f"[DeFiAnalyzer] Ошибка оценки риска: {e}")
        finally:
            session.close()

        return result

    def get_market_regime(self) -> Dict:
        """
        Определение режима рынка на основе DeFi данных.

        Returns:
            {
                "regime": "bull" | "bear" | "neutral",
                "sentiment": "greed" | "fear" | "neutral",
                "avg_lending_rate": float,
                "total_tvl": float,
                "signals": List[str]
            }
        """
        session = self.db.Session()
        result = {"regime": "neutral", "sentiment": "neutral", "avg_lending_rate": 0.0, "total_tvl": 0.0, "signals": []}

        try:
            since = datetime.utcnow() - timedelta(hours=24)

            # Средние ставки кредитования (Aave/Compound)
            lending_rates = (
                session.query(DefiMetrics)
                .filter(
                    DefiMetrics.metric_type == "supply_apy",
                    DefiMetrics.timestamp > since,
                    DefiMetrics.protocol.in_(["aave-v3", "aave-v2", "compound-v3", "compound-v2"]),
                    DefiMetrics.value < 100.0,
                )
                .all()
            )

            if lending_rates:
                rates = [m.value for m in lending_rates]
                result["avg_lending_rate"] = sum(rates) / len(rates)

                if result["avg_lending_rate"] > self.REGIME_THRESHOLDS["lending_greed"]:
                    result["sentiment"] = "greed"
                    result["signals"].append(f"Ставки кредитования {result['avg_lending_rate']:.1f}% — рынок жадный")
                elif result["avg_lending_rate"] < self.REGIME_THRESHOLDS["lending_fear"]:
                    result["sentiment"] = "fear"
                    result["signals"].append(f"Ставки кредитования {result['avg_lending_rate']:.1f}% — рынок боится")

            # Общий TVL
            tvl_metrics = (
                session.query(DefiMetrics).filter(DefiMetrics.metric_type == "tvl", DefiMetrics.timestamp > since).all()
            )

            if tvl_metrics:
                # Суммируем уникальные протоколы
                unique_pools = {}
                for m in tvl_metrics:
                    key = f"{m.protocol}_{m.asset}"
                    if key not in unique_pools or m.value > unique_pools[key]:
                        unique_pools[key] = m.value

                result["total_tvl"] = sum(unique_pools.values())

                if result["total_tvl"] > self.REGIME_THRESHOLDS["total_tvl_bull"]:
                    result["regime"] = "bull"
                    result["signals"].append(f"Общий TVL ${result['total_tvl']/1_000_000_000:.1f}B — бычий рынок")
                elif result["total_tvl"] < self.REGIME_THRESHOLDS["total_tvl_bear"]:
                    result["regime"] = "bear"
                    result["signals"].append(f"Общий TVL ${result['total_tvl']/1_000_000_000:.1f}B — медвежий рынок")

        except Exception as e:
            logger.error(f"[DeFiAnalyzer] Ошибка определения режима: {e}")
        finally:
            session.close()

        return result

    def get_ai_features(self, symbol: str = None) -> Dict:
        """
        Генерация признаков для AI моделей на основе DeFi данных.

        Returns:
            Dict с числовыми признаками:
            - defi_max_apy: Максимальная доходность
            - defi_avg_apy: Средняя доходность
            - defi_tvl_usd: TVL в USD
            - defi_lending_rate: Средняя ставка кредитования
            - defi_risk_score: Оценка риска (0-1)
            - defi_sentiment_score: Сентимент (-1 до +1)
        """
        risk = self.get_risk_assessment(symbol)
        regime = self.get_market_regime()

        # Нормализация риска (0 = безопасно, 1 = очень рискованно)
        if risk["risk_level"] == "low":
            risk_score = 0.0
        elif risk["risk_level"] == "medium":
            risk_score = 0.3
        elif risk["risk_level"] == "high":
            risk_score = 0.7
        else:  # scam
            risk_score = 1.0

        # Нормализация сентимента (-1 = fear, +1 = greed)
        if regime["sentiment"] == "fear":
            sentiment_score = -0.5
        elif regime["sentiment"] == "greed":
            sentiment_score = 0.5
        else:
            sentiment_score = 0.0

        return {
            "defi_max_apy": risk["max_apy"],
            "defi_avg_apy": risk["avg_apy"],
            "defi_tvl_usd": risk["tvl_usd"],
            "defi_lending_rate": regime["avg_lending_rate"],
            "defi_risk_score": risk_score,
            "defi_sentiment_score": sentiment_score,
            "defi_tvl_trend": 1.0 if risk["tvl_trend"] == "up" else (-1.0 if risk["tvl_trend"] == "down" else 0.0),
            "defi_regime_bull": 1.0 if regime["regime"] == "bull" else 0.0,
            "defi_regime_bear": 1.0 if regime["regime"] == "bear" else 0.0,
        }

    def get_trading_signals(self, symbol: str = None) -> Dict:
        """
        Генерация торговых сигналов на основе DeFi анализа.

        Returns:
            {
                "action": "buy" | "sell" | "hold" | "avoid",
                "confidence": float (0-1),
                "reasons": List[str]
            }
        """
        risk = self.get_risk_assessment(symbol)
        regime = self.get_market_regime()

        action = "hold"
        confidence = 0.5
        reasons = []

        # Сигналы риска
        if risk["risk_level"] == "scam":
            action = "avoid"
            confidence = 0.9
            reasons.extend(risk["warnings"])
        elif risk["risk_level"] == "high":
            action = "sell"
            confidence = 0.6
            reasons.extend(risk["warnings"])

        # Сигналы режима
        if regime["regime"] == "bull" and regime["sentiment"] == "greed":
            if action == "hold":
                action = "buy"
                confidence = 0.7
                reasons.extend(regime["signals"])
        elif regime["regime"] == "bear" and regime["sentiment"] == "fear":
            if action in ["hold", "buy"]:
                action = "sell"
                confidence = 0.6
                reasons.extend(regime["signals"])

        # TVL тренд
        if risk["tvl_trend"] == "down":
            if action == "buy":
                action = "hold"
                confidence = 0.4
            reasons.append("TVL падает — отток ликвидности")
        elif risk["tvl_trend"] == "up":
            if action == "hold":
                action = "buy"
                confidence = 0.6
            reasons.append("TVL растёт — приток ликвидности")

        return {
            "action": action,
            "confidence": confidence,
            "reasons": reasons,
            "risk_level": risk["risk_level"],
            "regime": regime["regime"],
            "sentiment": regime["sentiment"],
        }
