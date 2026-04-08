"""
Adaptive Retrain Scheduler — планировщик переобучения на основе метрик деградации.

Вместо жёсткого интервала (72ч) использует:
1. Минимальный интервал между ретренами (защита от спама)
2. Триггер деградации Sharpe (срочный ретрен)
3. Адаптивное окно по режиму рынка (calm=72h, volatile=24h)
4. Обновление baseline после успешного ретрена
"""

from datetime import datetime, timedelta
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class AdaptiveRetrainScheduler:
    """Планировщик переобучения на основе метрик деградации."""
    
    def __init__(
        self,
        min_interval_hours: int = 12,
        max_interval_hours: int = 72,
        sharpe_drop_threshold: float = 0.2,
        volatility_regimes: Optional[Dict[str, int]] = None
    ):
        """
        Args:
            min_interval_hours: Минимум часов между ретренами
            max_interval_hours: Максимум часов (плановый ретрен)
            sharpe_drop_threshold: Падение Sharpe (в %) для срочного ретрена
            volatility_regimes: Интервалы для режимов рынка {regime: hours}
        """
        self.min_interval = timedelta(hours=min_interval_hours)
        self.max_interval = timedelta(hours=max_interval_hours)
        self.sharpe_threshold = sharpe_drop_threshold
        
        # Сокращение интервала для волатильных режимов
        self.regime_intervals = volatility_regimes or {
            "calm": 72,
            "normal": 48,
            "volatile": 24,
            "extreme": 12
        }
        
        self.last_retrain: Optional[datetime] = None
        self.baseline_sharpe: Optional[float] = None
        
        logger.info(
            f"📅 AdaptiveRetrainScheduler инициализирован: "
            f"min={min_interval_hours}h, max={max_interval_hours}h, "
            f"sharpe_threshold={sharpe_drop_threshold:.0%}"
        )
    
    def should_retrain(
        self,
        current_metrics: Dict[str, float],
        current_regime: str = "normal"
    ) -> bool:
        """
        Определяет, нужно ли переобучать модель прямо сейчас.
        
        Args:
            current_metrics: Текущие метрики (sharpe_ratio, win_rate, etc.)
            current_regime: Текущий режим рынка
            
        Returns:
            True если нужен ретрен
        """
        now = datetime.utcnow()
        
        # 1. Защита от слишком частых ретренов
        if self.last_retrain and (now - self.last_retrain) < self.min_interval:
            hours_since = (now - self.last_retrain).total_seconds() / 3600
            logger.debug(
                f"🕐 Retrain skipped: {hours_since:.1f}h < {self.min_interval.total_seconds()/3600:.0f}h minimum"
            )
            return False
        
        # 2. Срочный триггер: падение качества
        if self._check_performance_decay(current_metrics):
            logger.warning("🔥 Performance decay detected → urgent retrain")
            return True
        
        # 3. Плановый ретрен: адаптивное окно по режиму рынка
        max_wait = timedelta(hours=self.regime_intervals.get(current_regime, 48))
        if self.last_retrain and (now - self.last_retrain) >= max_wait:
            hours_since = (now - self.last_retrain).total_seconds() / 3600
            logger.info(
                f"📅 Scheduled retrain: regime={current_regime}, "
                f"last={hours_since:.1f}h ago (max={max_wait.total_seconds()/3600:.0f}h)"
            )
            return True
        
        return False
    
    def _check_performance_decay(self, metrics: Dict[str, float]) -> bool:
        """
        Проверяет деградацию ключевых метрик.
        
        Returns:
            True если обнаружена деградация
        """
        if self.baseline_sharpe is None:
            # Первый запуск: запоминаем базовый Sharpe
            self.baseline_sharpe = metrics.get("sharpe_ratio", 0.0)
            logger.info(f"📊 Baseline Sharpe установлен: {self.baseline_sharpe:.3f}")
            return False
        
        current_sharpe = metrics.get("sharpe_ratio", 0.0)
        
        # Защита от деления на ноль
        baseline_abs = max(abs(self.baseline_sharpe), 0.01)
        decay = (self.baseline_sharpe - current_sharpe) / baseline_abs
        
        if decay > self.sharpe_threshold:
            logger.warning(
                f"📉 Sharpe decay: {decay:.1%} "
                f"(baseline={self.baseline_sharpe:.3f}, current={current_sharpe:.3f}, "
                f"threshold={self.sharpe_threshold:.1%})"
            )
            return True
        
        # Дополнительная проверка: WinRate падение
        baseline_wr = metrics.get("baseline_win_rate")
        if baseline_wr is not None:
            current_wr = metrics.get("win_rate", 0.0)
            wr_decay = (baseline_wr - current_wr) / max(baseline_wr, 0.01)
            if wr_decay > 0.15:  # 15% падение WinRate
                logger.warning(
                    f"📉 WinRate decay: {wr_decay:.1%} "
                    f"(baseline={baseline_wr:.1%}, current={current_wr:.1%})"
                )
                return True
        
        return False
    
    def mark_retrain_done(self, new_sharpe: Optional[float] = None) -> None:
        """
        Вызывается после успешного переобучения.
        
        Args:
            new_sharpe: Новый Sharpe обновлённой модели (становится baseline)
        """
        self.last_retrain = datetime.utcnow()
        if new_sharpe is not None:
            old_sharpe = self.baseline_sharpe
            self.baseline_sharpe = new_sharpe
            logger.info(
                f"✅ Retraining completed: Sharpe {old_sharpe:.3f} → {new_sharpe:.3f}"
            )
        else:
            logger.info("✅ Retraining completed, scheduler reset")
    
    def get_time_until_next_check(self) -> timedelta:
        """
        Возвращает время до следующей проверки необходимости ретрена.
        
        Returns:
            timedelta до следующей проверки
        """
        if self.last_retrain is None:
            return timedelta(hours=1)  # Первая проверка через час
        
        now = datetime.utcnow()
        time_since = now - self.last_retrain
        
        # Следующая проверка через min_interval
        next_check = self.last_retrain + self.min_interval
        
        if next_check <= now:
            return timedelta(minutes=30)  # Скоро проверяем чаще
        
        return next_check - now
    
    def get_status(self) -> Dict[str, any]:
        """
        Возвращает статус планировщика для мониторинга.
        
        Returns:
            Dict с информацией о состоянии
        """
        now = datetime.utcnow()
        hours_since = (
            (now - self.last_retrain).total_seconds() / 3600
            if self.last_retrain else None
        )
        
        return {
            "last_retrain": self.last_retrain.isoformat() if self.last_retrain else None,
            "hours_since_retrain": hours_since,
            "baseline_sharpe": self.baseline_sharpe,
            "min_interval_hours": self.min_interval.total_seconds() / 3600,
            "max_interval_hours": self.max_interval.total_seconds() / 3600,
            "sharpe_threshold": self.sharpe_threshold,
            "regime_intervals": self.regime_intervals,
        }
