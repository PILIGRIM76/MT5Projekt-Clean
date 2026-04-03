# src/web/server.py
"""
Веб-сервер для Genesis Trading System с Rate Limiting и валидацией.

Особенности:
- Rate Limiting для защиты от злоупотреблений
- Валидация входных данных через Pydantic
- WebSocket для реального времени
"""

import asyncio
import json
import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi import Path as FastApiPath
from fastapi import Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Rate Limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from src.data_models import ClosePositionRequest, TradeRequest

from .data_models import ControlResponse, HistoricalTrade, Position, SystemStatus

if TYPE_CHECKING:
    from src.core.trading_system import TradingSystem

logger = logging.getLogger(__name__)


# --- Rate Limiting настройка ---
limiter = Limiter(key_func=get_remote_address)


async def rate_limit_exception_handler(request: Request, exc: Exception):
    """Обработчик превышения rate limit."""
    return HTTPException(status_code=429, detail=f"Слишком много запросов. Попробуйте позже.", headers={"Retry-After": "60"})


# --- Глобальное состояние ---
class AppState:
    def __init__(self, trading_system_ref: "TradingSystem"):
        self.trading_system = trading_system_ref
        self.ws_manager = ConnectionManager()
        # Используем потокобезопасную очередь из asyncio
        # Но так как мы пишем в нее из разных потоков, нам нужен loop, в котором она создана.
        # Для упрощения, создадим её позже, внутри lifespan, или будем использовать call_soon_threadsafe
        self.update_queue: Optional[asyncio.Queue] = None
        self.latest_status: Optional[SystemStatus] = None
        self.latest_positions: List[Position] = []
        self.loop: Optional[asyncio.AbstractEventLoop] = None


app_state: Optional[AppState] = None


# --- Менеджер соединений ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"[Web] Клиент подключен. Всего: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info("[Web] Клиент отключен.")

    async def broadcast(self, message: dict):
        for connection in self.active_connections[:]:
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)


# --- Обработчик логов ---
class WebLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.setLevel(logging.INFO)
        self.setFormatter(logging.Formatter("%(asctime)s - %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record):
        # Проверяем, что сервер запущен и очередь готова
        # --- ИСПРАВЛЕНИЕ: Добавляем try-except для защиты от удаленных объектов ---
        try:
            if app_state and app_state.loop and app_state.update_queue and not app_state.loop.is_closed():
                msg = self.format(record)
                color = "#f8f8f2"
                if record.levelno == logging.WARNING:
                    color = "#f1fa8c"
                elif record.levelno >= logging.ERROR:
                    color = "#ff5555"
                elif "CRITICAL" in msg or "УСПЕХ" in msg:
                    color = "#50fa7b"

                log_entry = {"message": f"<span style='color:{color}'>{msg}</span>"}
                message = {"type": "log_message", "payload": log_entry}

                # Потокобезопасная отправка в очередь цикла событий сервера
                app_state.loop.call_soon_threadsafe(app_state.update_queue.put_nowait, message)
        except (RuntimeError, AttributeError):
            # Игнорируем ошибки при закрытии приложения
            pass
        except Exception:
            # Игнорируем прочие ошибки логирования, чтобы не крашить сервер
            pass


# --- Фоновая задача рассылки ---
async def update_broadcaster():
    logger.info("[Web] Broadcaster запущен.")
    while True:
        try:
            if app_state is None or app_state.update_queue is None:
                await asyncio.sleep(1)
                continue

            # Ждем сообщение из очереди
            update_data = await app_state.update_queue.get()

            # Обновляем кэш состояния
            if update_data["type"] == "status_update":
                try:
                    app_state.latest_status = SystemStatus(**update_data["payload"])
                except:
                    pass
            elif update_data["type"] == "positions_update":
                try:
                    app_state.latest_positions = [Position(**pos) for pos in update_data["payload"]]
                except:
                    pass

            # Рассылаем всем клиентам
            await app_state.ws_manager.broadcast(update_data)
            app_state.update_queue.task_done()

        except asyncio.CancelledError:
            logger.info("[Web] Broadcaster остановлен.")
            break
        except Exception as e:
            logger.error(f"[Web] Ошибка в Broadcaster: {e}", exc_info=True)
            await asyncio.sleep(0.1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Инициализируем очередь и loop внутри контекста сервера
    if app_state:
        app_state.loop = asyncio.get_running_loop()
        app_state.update_queue = asyncio.Queue(maxsize=500)
        logger.info(f"[Web] Event Loop захвачен: {app_state.loop}")

    task = asyncio.create_task(update_broadcaster())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# Инициализация приложения с Rate Limiting
app = FastAPI(title="Genesis Reflex API", lifespan=lifespan)

# Добавляем middleware
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class WebServer:
    def __init__(self, trading_system_ref: "TradingSystem"):
        global app_state
        if app_state is None:
            app_state = AppState(trading_system_ref)
        else:
            app_state.trading_system = trading_system_ref

        self.config = trading_system_ref.config.web_dashboard
        self.server: Optional[uvicorn.Server] = None
        self.server_thread: Optional[threading.Thread] = None
        self.setup_routes()

    def broadcast_drift_update(self, timestamp: float, symbol: str, error: float, is_drift: bool):
        """Широковещательная рассылка данных о дрейфе концепции."""
        payload = {"timestamp": timestamp, "symbol": symbol, "error": error, "is_drift": is_drift}
        self._put_to_queue_threadsafe({"type": "drift_update", "payload": payload})

    def _put_to_queue_threadsafe(self, message: dict):
        # Используем call_soon_threadsafe для передачи данных из других потоков
        global app_state  # Объявляем global в начале

        if app_state and app_state.loop and app_state.update_queue:
            try:
                # Проверка что event loop еще открыт
                if app_state.loop.is_closed():
                    # Тихо пропускаем если loop закрыт (сервер остановлен)
                    app_state = None  # Отключаем дальнейшие попытки
                    return
                app_state.loop.call_soon_threadsafe(app_state.update_queue.put_nowait, message)
            except RuntimeError as e:
                # Event loop is closed - не логируем как ошибку, это нормально при остановке
                if "Event loop is closed" in str(e):
                    app_state = None  # Отключаем дальнейшие попытки
                    return
                logger.debug(f"[Web] Ошибка добавления в очередь: {e}")
            except Exception as e:
                logger.debug(f"[Web] Ошибка добавления в очередь: {e}")

    def broadcast_status_update(self, status_obj: SystemStatus):
        self._put_to_queue_threadsafe({"type": "status_update", "payload": status_obj.model_dump()})

    def broadcast_positions_update(self, positions_list: List[Dict[str, Any]]):
        self._put_to_queue_threadsafe({"type": "positions_update", "payload": positions_list})

    def broadcast_history_update(self, history_data: List[Dict[str, Any]]):
        self._put_to_queue_threadsafe({"type": "history_update", "payload": history_data})

    def broadcast_orchestrator_update(self, allocation: Dict[str, float]):
        self._put_to_queue_threadsafe({"type": "orchestrator_update", "payload": allocation})

    def broadcast_market_regime(self, regime: str):
        self._put_to_queue_threadsafe({"type": "market_regime_update", "payload": {"regime": regime}})

    def setup_routes(self):
        """Настройка API routes с Rate Limiting."""

        # --- Health Check & Metrics (без лимитов) ---

        @app.get("/health")
        async def health_check():
            """
            Health check endpoint для Kubernetes/monitoring.

            Returns:
                {"status": "healthy" | "unhealthy", "timestamp": "..."}
            """
            from src.core.services_container import get_all_health_checks

            health_checks = get_all_health_checks()

            all_healthy = all(check.get("status") == "healthy" for check in health_checks.values())

            return {
                "status": "healthy" if all_healthy else "unhealthy",
                "timestamp": datetime.now().isoformat(),
                "components": health_checks,
            }

        @app.get("/health/live")
        async def liveness_probe():
            """Liveness probe для Kubernetes."""
            return {"status": "alive"}

        @app.get("/health/ready")
        async def readiness_probe():
            """Readiness probe для Kubernetes."""
            if app_state and app_state.trading_system and app_state.trading_system.running:
                return {"status": "ready"}
            raise HTTPException(status_code=503, detail="System not ready")

        @app.get("/metrics")
        async def get_metrics():
            """
            Prometheus metrics endpoint.

            Returns метрики в формате Prometheus.
            """
            from fastapi.responses import Response
            from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

            return Response(
                content=generate_latest(),
                media_type=CONTENT_TYPE_LATEST,
            )

        # --- Public API (высокие лимиты) ---

        @app.get("/api/v1/status", response_model=SystemStatus)
        @limiter.limit("60/minute")  # 60 запросов в минуту
        async def get_status(request: Request):
            """Получение статуса системы."""
            if app_state and app_state.latest_status:
                ts = app_state.trading_system
                if ts.start_time:
                    delta = datetime.now() - ts.start_time
                    app_state.latest_status.uptime = str(delta).split(".")[0]
                return app_state.latest_status

            if app_state and app_state.trading_system:
                ts = app_state.trading_system
                return SystemStatus(
                    is_running=ts.running,
                    mode="Наблюдатель" if ts.observer_mode else "Торговля",
                    uptime="0:00:00",
                    balance=0.0,
                    equity=0.0,
                    current_drawdown=0.0,
                )
            return SystemStatus(is_running=False, mode="Ожидание", uptime="0:00:00", balance=0, equity=0)

        @app.get("/api/v1/positions", response_model=List[Position])
        @limiter.limit("30/minute")  # 30 запросов в минуту
        async def get_positions(request: Request):
            """Получение списка открытых позиций."""
            return app_state.latest_positions if app_state else []

        @app.get("/api/v1/history", response_model=List[HistoricalTrade])
        @limiter.limit("30/minute")  # 30 запросов в минуту
        async def get_history(request: Request):
            """Получение истории сделок."""
            if not app_state or not app_state.trading_system:
                return []
            history_deals = app_state.trading_system.db_manager.get_trade_history()
            return [
                HistoricalTrade(ticket=d.ticket, symbol=d.symbol, profit=d.profit, time_close=d.time_close)
                for d in history_deals
            ]

        # --- Control API (низкие лимиты - критичные операции) ---

        @app.post("/api/v1/control/start", response_model=ControlResponse)
        @limiter.limit("5/minute")  # Макс 5 запусков в минуту
        async def start_system(request: Request):
            """Запуск торговой системы."""
            if app_state.trading_system.running:
                return ControlResponse(success=False, message="Система уже запущена.")
            threading.Thread(target=app_state.trading_system.start_all_threads).start()
            return ControlResponse(success=True, message="Команда на запуск отправлена.")

        @app.post("/api/v1/control/stop", response_model=ControlResponse)
        @limiter.limit("5/minute")  # Макс 5 остановок в минуту
        async def stop_system(request: Request):
            """Остановка торговой системы."""
            if not app_state.trading_system.running:
                return ControlResponse(success=False, message="Система не запущена.")
            app_state.trading_system.stop()
            return ControlResponse(success=True, message="Команда на остановку отправлена.")

        @app.post("/api/v1/control/close_all", response_model=ControlResponse)
        @limiter.limit("3/minute")  # Макс 3 аварийных закрытия в минуту
        async def close_all_positions(request: Request):
            """Аварийное закрытие всех позиций."""
            threading.Thread(target=app_state.trading_system.emergency_close_all_positions).start()
            return ControlResponse(success=True, message="Команда на закрытие всех позиций отправлена.")

        @app.post("/api/v1/control/close/{ticket}", response_model=ControlResponse)
        @limiter.limit("10/minute")  # Макс 10 закрытий позиций в минуту
        async def close_position(request: Request, ticket: int = FastApiPath(..., title="Ticket ID", gt=0)):
            """Закрытие конкретной позиции по ticket."""
            threading.Thread(target=app_state.trading_system.emergency_close_position, args=(ticket,)).start()
            return ControlResponse(success=True, message=f"Команда на закрытие позиции #{ticket} отправлена.")

        @app.post("/api/v1/control/observer_mode", response_model=ControlResponse)
        @limiter.limit("10/minute")  # Макс 10 переключений в минуту
        async def set_observer_mode(request: Request, enable: bool):
            """Включение/выключение режима наблюдателя."""
            if app_state.trading_system.observer_mode != enable:
                app_state.trading_system.set_observer_mode(enable)
            status = "включен" if enable else "выключен"
            return ControlResponse(success=True, message=f"Режим наблюдателя {status}.")

        # --- WebSocket (без rate limiting, но с защитой от disconnect) ---

        @app.websocket("/api/ws/updates")
        async def websocket_endpoint(websocket: WebSocket):
            await app_state.ws_manager.connect(websocket)
            try:
                # 1. Отправляем последний известный статус
                if app_state.latest_status:
                    await websocket.send_json({"type": "status_update", "payload": app_state.latest_status.model_dump()})
                # 2. Отправляем последние позиции
                if app_state.latest_positions:
                    await websocket.send_json(
                        {"type": "positions_update", "payload": [pos.model_dump() for pos in app_state.latest_positions]}
                    )
                # 3. Отправляем данные оркестратора
                if app_state.trading_system.risk_engine.default_capital_allocation:
                    await websocket.send_json(
                        {
                            "type": "orchestrator_update",
                            "payload": app_state.trading_system.risk_engine.default_capital_allocation,
                        }
                    )
                # 4. Отправляем историю для графика P&L
                history_deals = app_state.trading_system.db_manager.get_trade_history()
                if history_deals:
                    history_payload = [
                        json.loads(
                            HistoricalTrade(
                                ticket=d.ticket, symbol=d.symbol, profit=d.profit, time_close=d.time_close
                            ).model_dump_json()
                        )
                        for d in history_deals
                    ]
                    await websocket.send_json({"type": "history_update", "payload": history_payload})
                else:
                    # Отправляем пустой массив, чтобы инициализировать график
                    await websocket.send_json({"type": "history_update", "payload": []})

                # Оптимизация: Избегайте постоянного ожидания текста
                while True:
                    try:
                        await asyncio.wait_for(websocket.receive_text(), timeout=30)
                    except asyncio.TimeoutError:
                        # Периодически проверяем соединение
                        continue
            except WebSocketDisconnect:
                app_state.ws_manager.disconnect(websocket)
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                app_state.ws_manager.disconnect(websocket)

        # --- ИСПРАВЛЕННОЕ МОНТИРОВАНИЕ СТАТИКИ ---
        path_relative = Path(__file__).resolve().parent.parent.parent / "assets" / "dashboard"
        path_cwd = Path.cwd() / "assets" / "dashboard"
        final_dashboard_path = None
        if path_relative.exists() and (path_relative / "index.html").exists():
            final_dashboard_path = path_relative
        elif path_cwd.exists() and (path_cwd / "index.html").exists():
            final_dashboard_path = path_cwd
        if final_dashboard_path:
            logger.info(f"[Web] Дашборд найден по пути: {final_dashboard_path}")
            app.mount("/", StaticFiles(directory=final_dashboard_path, html=True), name="dashboard")
        else:
            logger.error(f"[Web] !!! ОШИБКА: Папка assets/dashboard не найдена.")

            # Добавляем запасной маршрут для отображения ошибки
            @app.get("/")
            async def root_error():
                return {
                    "error": "Dashboard files not found",
                    "message": "Please check that 'assets/dashboard/index.html' exists.",
                    "checked_paths": [str(path_relative), str(path_cwd)],
                }

            @app.get("/")
            async def root_error():
                return {
                    "error": "Dashboard files not found",
                    "message": "Please check that 'assets/dashboard/index.html' exists.",
                    "checked_paths": [str(path_relative), str(path_cwd)],
                }

    def start(self):
        if self.server_thread and self.server_thread.is_alive():
            return

        log_config = uvicorn.config.LOGGING_CONFIG
        log_config["formatters"]["access"]["fmt"] = "%(asctime)s - %(levelname)s - [Web] %(message)s"

        config = uvicorn.Config(app, host=self.config.host, port=self.config.port, log_level="warning", log_config=log_config)
        self.server = uvicorn.Server(config)

        self.server_thread = threading.Thread(target=self.server.run, daemon=True, name="WebServerThread")
        self.server_thread.start()
        logger.info(f"Веб-сервер запущен: http://{self.config.host}:{self.config.port}")

    def stop(self):
        if self.server:
            self.server.should_exit = True
