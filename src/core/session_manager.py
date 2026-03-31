# src/core/session_manager.py

import logging
from datetime import datetime, time

from src.core.config_models import Settings

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, config: Settings):
        self.sessions = config.trading_sessions
        self.asset_types = config.asset_types
        self.config = config
        logger.info("Менеджер сессий (SessionManager) инициализирован.")

    def get_asset_type(self, symbol: str) -> str:
        """Определяет тип рынка для данного символа."""
        if symbol in self.asset_types:
            return self.asset_types[symbol]
        for key, asset_type in self.asset_types.items():
            if symbol.startswith(key):
                return asset_type
        return "FOREX"

    def is_trading_hours(self, symbol: str) -> bool:
        """Проверяет, находится ли актив в своей торговой сессии."""
        asset_type = self.get_asset_type(symbol)

        if asset_type not in self.sessions:
            logger.warning(f"Для типа актива {asset_type} не определена торговая сессия. Торговля разрешена по умолчанию.")
            return True

        now_utc = datetime.utcnow()
        day_of_week = now_utc.weekday()

        # 1. Сначала проверяем, не выходной ли это, если торговля на выходных запрещена.
        if not self.config.ALLOW_WEEKEND_TRADING:
            # 5 = Суббота, 6 = Воскресенье
            if asset_type in ["FOREX", "NYSE"] and day_of_week >= 5:
                logger.info(f"Торговля по {symbol} ({asset_type}) закрыта (выходной день).")
                return False

        session_times = self.sessions[asset_type]
        start_time = time.fromisoformat(session_times[0])
        end_time = time.fromisoformat(session_times[1])
        current_time = now_utc.time()

        # 2. Если это не выходной (или торговля на выходных разрешена), проверяем время.

        # --- ИСПРАВЛЕНИЕ: Добавлена логика для сессий, переходящих через полночь ---
        if start_time <= end_time:
            # Обычная сессия (например, 09:00 - 17:00)
            is_active = start_time <= current_time <= end_time
        else:
            # Сессия, переходящая через полночь (например, 23:00 - 01:00)
            is_active = current_time >= start_time or current_time <= end_time
        # --------------------------------------------------------------------------

        if not is_active:
            logger.info(
                f"Торговля по {symbol} ({asset_type}) сейчас закрыта. Сессия: {start_time}-{end_time} UTC. Текущее время: {current_time} UTC."
            )

        return is_active
