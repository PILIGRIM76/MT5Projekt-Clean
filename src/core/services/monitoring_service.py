# src/core/services/monitoring_service.py
"""
Monitoring Service - Сервис для мониторинга системы и обновления GUI.

Инкапсулирует логику мониторинга из TradingSystem.
"""

import logging
import time
import threading
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional, Dict, Any, List

import MetaTrader5 as mt5

from src.core.services.base_service import BaseService, HealthStatus

if TYPE_CHECKING:
    from src.core.trading_system import TradingSystem

logger = logging.getLogger(__name__)


class MonitoringService(BaseService):
    """
    Сервис мониторинга - обновляет данные GUI и проверяет состояние системы.
    
    Отвечает за:
    - Обновление баланса/эквити
    - Обновление позиций
    - Проверку закрытых сделок
    - Обновление времени работы
    - Проверку scheduled задач
    """
    
    def __init__(self, trading_system: 'TradingSystem', interval_seconds: float = 3.0):
        super().__init__(name="MonitoringService")
        self.trading_system = trading_system
        self.interval_seconds = interval_seconds
        self._iteration_count = 0
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Тайминги для разных задач
        self._last_heavy_check_time = 0.0
        self._last_graph_update_time = 0.0
        self._last_kpi_update_time = 0.0
        
        # Интервалы
        self._heavy_check_interval = 3  # секунды
        self._graph_update_interval = 30  # секунды
        self._kpi_update_interval = 60  # секунды
        
        # НОВОЕ: Счётчик ошибок авторизации для экспоненциальной задержки
        self._auth_error_count = 0
        self._last_auth_error_time = None
        self._auth_error_logged = False  # Флаг для дедупликации логов

    def _on_start(self) -> None:
        """Запуск сервиса мониторинга"""
        self._logger.info("Запуск сервиса мониторинга...")
        self._stop_event.clear()
        
        # Запуск в отдельном потоке
        self._thread = threading.Thread(
            target=self._monitoring_loop,
            daemon=True,
            name="MonitoringService-Thread"
        )
        self._thread.start()

    def _on_stop(self) -> None:
        """Остановка сервиса мониторинга"""
        self._logger.info("Остановка сервиса мониторинга...")
        self._stop_event.set()
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                self._logger.warning("Поток мониторинга не завершился за 5с")

    def _monitoring_loop(self) -> None:
        """Основной цикл мониторинга"""
        self._logger.info("Цикл мониторинга запущен")
        
        while not self._stop_event.is_set():
            current_time = time.time()
            
            try:
                # Проверка scheduled задач
                self._check_scheduled_tasks()
                
                # Обновление графа знаний (если включено)
                if (current_time - self._last_graph_update_time > self._graph_update_interval
                    and self.trading_system.config.ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION):
                    self._update_knowledge_graph()
                    self._last_graph_update_time = current_time
                
                # Обновление KPI
                if current_time - self._last_kpi_update_time > self._kpi_update_interval:
                    self._update_pnl_kpis()
                    self._last_kpi_update_time = current_time
                
                # Основная проверка с MT5
                self._perform_mt5_check(current_time)
                
                self._iteration_count += 1
                self.increment_operations()
                
            except Exception as e:
                error_msg = f"Ошибка в цикле мониторинга: {e}"
                self._logger.error(error_msg, exc_info=True)
                self.record_error(error_msg)
            
            # Пауза
            self._stop_event.wait(1)  # Проверка каждую секунду
        
        self._logger.info(f"Цикл мониторинга завершен. Итераций: {self._iteration_count}")

    def _perform_mt5_check(self, current_time: float) -> None:
        """Выполнить проверку MT5"""
        lock_acquired = False

        try:
            # Быстрая проверка лока (1 сек таймаут)
            if not self.trading_system.mt5_lock.acquire(timeout=1):
                self._logger.debug("[Monitoring] MT5 Lock занят, пропуск цикла")
                return

            lock_acquired = True

            # Инициализация MT5 - сначала мягкое подключение
            if not mt5.initialize(path=self.trading_system.config.MT5_PATH):
                # Если не вышло, пробуем полную авторизацию
                if not mt5.initialize(
                    path=self.trading_system.config.MT5_PATH,
                    login=int(self.trading_system.config.MT5_LOGIN),
                    password=self.trading_system.config.MT5_PASSWORD,
                    server=self.trading_system.config.MT5_SERVER
                ):
                    err_code = mt5.last_error()
                    
                    # Специальная обработка ошибки -6 (Authorization failed)
                    if isinstance(err_code, tuple) and err_code[0] == -6:
                        # Увеличиваем счётчик ошибок
                        self._auth_error_count += 1
                        self._last_auth_error_time = datetime.now()
                        
                        # Логгируем только первую ошибку или каждую 10-ю для снижения шума
                        if not self._auth_error_logged or self._auth_error_count % 10 == 0:
                            self._logger.error(
                                f"[Monitoring] КРИТИЧНО: MT5 Authorization Failed. "
                                f"Терминал может быть закрыт или учетная запись заблокирована. "
                                f"Ошибка: {err_code} (попытка #{self._auth_error_count})")
                            if not self._auth_error_logged:
                                self._logger.warning(
                                    f"[Monitoring] Переключение на FALLBACK: классические стратегии без live-ордеров")
                                self._auth_error_logged = True
                            else:
                                self._logger.debug(f"[Monitoring] Повтор ошибки авторизации (всего: {self._auth_error_count})")
                        
                        # Устанавливаем флаг что торговля недоступна
                        self.trading_system.mt5_connection_failed = True
                        
                        # Экспоненциальная задержка: min(2^count, 30) секунд
                        delay = min(2 ** min(self._auth_error_count, 5), 30)
                        self._logger.debug(f"[Monitoring] Задержка перед следующей попыткой: {delay} сек.")
                        self._stop_event.wait(delay)
                        return
                    else:
                        self._logger.error(f"[Monitoring] Не удалось инициализировать MT5. Код ошибки: {err_code}")
                        return

            # Если соединение восстановлено, сбросим флаг
            if self.trading_system.mt5_connection_failed:
                self._logger.info(
                    f"[Monitoring] ✓ MT5 соединение восстановлено! Возврат в NORMAL режим торговли")
                self.trading_system.mt5_connection_failed = False
                # Сбрасываем счётчик ошибок при успешном подключении
                self._auth_error_count = 0
                self._auth_error_logged = False

            try:
                # Обновление баланса
                account_info = mt5.account_info()
                if account_info:
                    self._update_balance(account_info)

                # Обновление позиций (легкое)
                self._update_positions_light()

                # Тяжелая проверка
                if current_time - self._last_heavy_check_time > self._heavy_check_interval:
                    self._perform_heavy_check()
                    self._last_heavy_check_time = current_time

            finally:
                mt5.shutdown()

        except Exception as e:
            self._logger.error(f"Ошибка MT5 проверки: {e}", exc_info=True)
            self.record_error(str(e))
        finally:
            if lock_acquired:
                self.trading_system.mt5_lock.release()

    def _perform_heavy_check(self) -> None:
        """Выполнить тяжелую проверку (позиции, история)"""
        try:
            positions = mt5.positions_get()
            if positions:
                self._update_positions_full(positions)
            
            # Проверка закрытых позиций
            found_new = self.trading_system._check_and_log_closed_positions()
            if found_new or self.trading_system.history_needs_update:
                history = self.trading_system.db_manager.get_trade_history()
                if history:
                    self.trading_system._safe_gui_update('update_history_view', history)
                    self.trading_system._safe_gui_update('update_pnl_graph', history)
                self.trading_system.history_needs_update = False
                
        except Exception as e:
            self._logger.error(f"Ошибка в тяжелой проверке: {e}", exc_info=True)

    def _update_balance(self, account_info) -> None:
        """Обновить баланс в GUI"""
        self.trading_system._safe_gui_update(
            'update_balance',
            account_info.balance,
            account_info.equity
        )
        self.trading_system._last_known_balance = account_info.balance
        self.trading_system._last_known_equity = account_info.equity

    def _update_positions_light(self) -> None:
        """Легкое обновление позиций (только прибыль)"""
        if hasattr(self.trading_system, '_last_positions_cache'):
            positions = mt5.positions_get()
            if positions and self.trading_system._last_positions_cache:
                updated_positions = []
                for p in positions:
                    cached = next(
                        (pos for pos in self.trading_system._last_positions_cache 
                         if pos.get('ticket') == p.ticket),
                        None
                    )
                    if cached:
                        pos_dict = cached.copy()
                        pos_dict['profit'] = p.profit
                        updated_positions.append(pos_dict)
                
                if updated_positions:
                    self.trading_system._safe_gui_update(
                        'update_positions_view', updated_positions
                    )

    def _update_positions_full(self, positions) -> None:
        """Полное обновление позиций"""
        # Реализация аналогична существующей логике в TradingSystem
        pass

    def _check_scheduled_tasks(self) -> None:
        """Проверить запланированные задачи"""
        self.trading_system._check_scheduled_tasks()

    def _update_knowledge_graph(self) -> None:
        """Обновить граф знаний"""
        try:
            graph_data = self.trading_system.db_manager.get_graph_data()
            if graph_data:
                import json
                graph_json = json.dumps(graph_data)
                self.trading_system.knowledge_graph_updated.emit(graph_json)
        except Exception as e:
            self._logger.error(f"Ошибка обновления графа: {e}", exc_info=True)

    def _update_pnl_kpis(self) -> None:
        """Обновить PnL KPI"""
        try:
            self.trading_system._update_pnl_kpis()
        except Exception as e:
            self._logger.error(f"Ошибка обновления KPI: {e}", exc_info=True)

    def _health_check(self) -> HealthStatus:
        """Проверка здоровья сервиса мониторинга"""
        checks = {
            "thread_alive": self._thread is not None and self._thread.is_alive(),
            "system_running": self.trading_system.running,
        }
        
        is_healthy = all(checks.values())
        
        details = {
            "iterations": self._iteration_count,
            "last_heavy_check": datetime.fromtimestamp(self._last_heavy_check_time).isoformat(),
        }
        
        return HealthStatus(
            is_healthy=is_healthy,
            checks=checks,
            details=details,
            message="OK" if is_healthy else "Сервис мониторинга нездоров"
        )
