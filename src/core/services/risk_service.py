# src/core/services/risk_service.py
"""
Risk Service - Сервис для управления рисками.

Инкапсулирует логику риск-менеджмента из TradingSystem.
"""

import logging
from typing import TYPE_CHECKING, Optional, Dict, Any, List
import threading

import MetaTrader5 as mt5
import pandas as pd

from src.core.services.base_service import BaseService, HealthStatus

if TYPE_CHECKING:
    from src.core.trading_system import TradingSystem
    from src.risk.risk_engine import RiskEngine

logger = logging.getLogger(__name__)


class RiskService(BaseService):
    """
    Сервис риск-менеджмента.
    
    Отвечает за:
    - Проверку дневной просадки
    - Расчет VaR портфеля
    - Проверку токсичных режимов
    - Хеджирование позиций
    - Лимиты на позиции
    """
    
    def __init__(self, trading_system: 'TradingSystem', risk_engine: 'RiskEngine'):
        super().__init__(name="RiskService")
        self.trading_system = trading_system
        self.risk_engine = risk_engine
        self._check_count = 0
        self._hedge_count = 0
        self._last_var_check: Optional[float] = None
        self._last_drawdown_check: Optional[float] = None

    def _on_start(self) -> None:
        """Запуск сервиса рисков"""
        self._logger.info("Запуск сервиса рисков...")
        
        # Проверка наличия risk_engine
        if not self.risk_engine:
            raise RuntimeError("RiskEngine не инициализирован")
        
        self._logger.info("Сервис рисков запущен")

    def _on_stop(self) -> None:
        """Остановка сервиса рисков"""
        self._logger.info("Остановка сервиса рисков...")
        # Очистка ресурсов если нужна

    def _health_check(self) -> HealthStatus:
        """Проверка здоровья сервиса рисков"""
        checks = {
            "risk_engine_exists": self.risk_engine is not None,
            "system_running": self.trading_system.running,
            "var_within_limits": self._check_var_limits(),
            "drawdown_within_limits": self._check_drawdown_limits(),
        }
        
        is_healthy = all(checks.values())
        
        details = {
            "check_count": self._check_count,
            "hedge_count": self._hedge_count,
            "last_var": self._last_var_check,
            "last_drawdown": self._last_drawdown_check,
        }
        
        message = "OK" if is_healthy else "Превышены лимиты риска"
        
        return HealthStatus(
            is_healthy=is_healthy,
            checks=checks,
            details=details,
            message=message
        )

    def _check_var_limits(self) -> bool:
        """Проверить VaR портфеля"""
        try:
            positions = mt5.positions_get()
            if not positions:
                return True
            
            var = self.risk_engine.calculate_portfolio_var(positions, {})
            self._last_var_check = var
            
            max_var = self.trading_system.config.MAX_PORTFOLIO_VAR_PERCENT
            is_ok = var <= max_var
            
            if not is_ok:
                self._logger.warning(f"VaR портфеля {var:.2%} превышает лимит {max_var:.2%}")
            
            return is_ok
        except Exception as e:
            self._logger.error(f"Ошибка проверки VaR: {e}")
            return True  # Не блокируем торговлю из-за ошибки

    def _check_drawdown_limits(self) -> bool:
        """Проверить дневную просадку"""
        try:
            account_info = mt5.account_info()
            if not account_info:
                return True
            
            balance = account_info.balance
            equity = account_info.equity
            
            # Расчет просадки от баланса
            drawdown = ((balance - equity) / balance * 100) if balance > 0 else 0
            self._last_drawdown_check = drawdown
            
            max_dd = self.trading_system.config.MAX_DAILY_DRAWDOWN_PERCENT
            is_ok = drawdown <= max_dd
            
            if not is_ok:
                self._logger.warning(f"Просадка {drawdown:.2f}% превышает лимит {max_dd:.2f}%")
            
            return is_ok
        except Exception as e:
            self._logger.error(f"Ошибка проверки просадки: {e}")
            return True

    def check_and_apply_hedging(
        self,
        positions: List,
        data_dict: Dict[str, pd.DataFrame],
        account_info
    ) -> Optional[tuple]:
        """
        Проверить и применить хеджирование.
        
        Args:
            positions: Список открытых позиций
            data_dict: Данные по символам
            account_info: Информация об аккаунте
            
        Returns:
            tuple: (symbol, signal, lot_size) если хеджирование применено, иначе None
        """
        try:
            result = self.risk_engine.check_and_apply_hedging(
                positions, data_dict, account_info
            )
            
            if result:
                self._hedge_count += 1
                symbol, signal, lot_size = result
                self._logger.critical(
                    f"ХЕДЖИРОВАНИЕ: {signal.type.name} {lot_size:.2f} по {symbol}"
                )
            
            return result
        except Exception as e:
            self._logger.error(f"Ошибка хеджирования: {e}", exc_info=True)
            return None

    def calculate_position_size(
        self,
        symbol: str,
        df: pd.DataFrame,
        account_info,
        trade_type,
        strategy_name: str
    ) -> tuple:
        """
        Рассчитать размер позиции.
        
        Returns:
            tuple: (lot_size, stop_loss_price)
        """
        try:
            lot_size, sl_price = self.risk_engine.calculate_position_size(
                symbol=symbol,
                df=df,
                account_info=account_info,
                trade_type=trade_type,
                strategy_name=strategy_name
            )
            
            self._check_count += 1
            return lot_size, sl_price
        except Exception as e:
            self._logger.error(f"Ошибка расчета позиции: {e}", exc_info=True)
            return None, None

    def is_trade_safe(self, symbol: str) -> bool:
        """
        Проверить безопасность торговли для символа.
        
        Returns:
            bool: True если торговля безопасна
        """
        try:
            return self.risk_engine.is_trade_safe_from_events(symbol)
        except Exception as e:
            self._logger.error(f"Ошибка проверки безопасности: {e}")
            return True

    def get_risk_metrics(self) -> Dict[str, Any]:
        """Получить метрики риска"""
        try:
            positions = mt5.positions_get()
            if not positions:
                return {
                    "var": 0.0,
                    "correlation_risk": 0.0,
                    "concentration_risk": 0.0,
                }
            
            data_dict = {}  # Получить данные
            var = self.risk_engine.calculate_portfolio_var(positions, data_dict)
            
            return {
                "var": var,
                "correlation_risk": self._calculate_correlation_risk(positions),
                "concentration_risk": self._calculate_concentration_risk(positions),
            }
        except Exception as e:
            self._logger.error(f"Ошибка получения метрик риска: {e}")
            return {"var": 0.0, "correlation_risk": 0.0, "concentration_risk": 0.0}

    def _calculate_correlation_risk(self, positions) -> float:
        """Рассчитать риск корреляции"""
        # Упрощенная реализация
        symbols = set(p.symbol for p in positions)
        if len(symbols) <= 1:
            return 0.0
        
        # Проверка корреляций
        high_correlation_count = 0
        threshold = self.trading_system.config.CORRELATION_THRESHOLD
        
        # Здесь должна быть логика проверки корреляций
        # Для заглушки возвращаем 0
        
        return high_correlation_count / len(symbols) if symbols else 0.0

    def _calculate_concentration_risk(self, positions) -> float:
        """Рассчитать риск концентрации"""
        if not positions:
            return 0.0
        
        total_volume = sum(p.volume for p in positions)
        if total_volume == 0:
            return 0.0
        
        # Найти largest position
        max_volume = max(p.volume for p in positions)
        concentration = max_volume / total_volume
        
        return concentration if concentration > 0.5 else 0.0

    def get_status(self) -> Dict[str, Any]:
        """Получить расширенный статус сервиса"""
        base_status = super().get_status()
        risk_metrics = self.get_risk_metrics()
        
        base_status.update({
            "check_count": self._check_count,
            "hedge_count": self._hedge_count,
            "risk_metrics": risk_metrics,
        })
        
        return base_status
