# -*- coding: utf-8 -*-
"""
Графики MainWindow — все методы обновления графиков.

Вынесены из main_pyside.py для уменьшения размера монолита.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Slot
from PySide6.QtGui import QColor

if TYPE_CHECKING:
    from main_pyside import MainWindow

logger = logging.getLogger(__name__)


class ChartsMixin:
    """Миксин с методами обновления графиков для MainWindow."""

    def update_pnl_chart(self: MainWindow, trade_history: list):
        logger.info(f"[GUI-PnL] Обновление графика P&L: {len(trade_history)} сделок")
        if not trade_history:
            self.pnl_curve.setData([], [])
            logger.debug("[GUI-PnL] История сделок пуста, график очищен")
            return
        try:
            if len(trade_history) > 1000:
                step = len(trade_history) // 1000
                trade_history = trade_history[::step]
                logger.debug(f"[GUI-PnL] История обрезана для производительности, шаг={step}")

            data = []
            for deal in trade_history:
                data.append({"profit": deal.profit, "time_close": deal.time_close.timestamp()})

            df = pd.DataFrame(data)
            if df.empty or "profit" not in df.columns or "time_close" not in df.columns:
                logger.warning("[GUI-PnL] DataFrame пуст или не содержит необходимых колонок")
                return

            df = df.sort_values(by="time_close")
            df["cumulative_profit"] = df["profit"].cumsum()

            timestamps = df["time_close"].values
            cumulative_profit = df["cumulative_profit"].values

            x_data = [float(t) for t in timestamps]
            y_data = [float(p) for p in cumulative_profit]

            self.pnl_curve.setData(x=x_data, y=y_data)
            self.pnl_plot.setTitle(f"Кривая доходности (P&L: {cumulative_profit[-1]:.2f})")
            logger.debug(f"[GUI-PnL] График успешно обновлен, итоговый P&L: {cumulative_profit[-1]:.2f}")
        except Exception as e:
            logger.error(f"[GUI-PnL] Ошибка при построении графика P&L: {e}", exc_info=True)

    def update_observer_pnl_chart(self: MainWindow, pnl_history: list):
        if not pnl_history:
            self.observer_pnl_curve.setData(x=[], y=[])
            return
        try:
            initial_balance = 10000
            cumulative_pnl = np.cumsum(pnl_history)
            equity_curve = initial_balance + cumulative_pnl

            x_data = list(np.arange(len(equity_curve)))
            y_data = [float(v) for v in equity_curve]

            self.observer_pnl_curve.setData(x=x_data, y=y_data)
            self.observer_pnl_plot.setTitle(f"Доходность (Наблюдатель: {cumulative_pnl[-1]:.2f})")
        except Exception as e:
            logger.error(f"Ошибка при построении графика P&L наблюдателя: {e}", exc_info=True)

    def update_training_chart(self: MainWindow, history_object):
        logger.info(f"[GUI-Training] Обновление графика обучения: type={type(history_object)}")
        try:
            if not hasattr(self, "loss_curve") or self.loss_curve is None:
                logger.warning("[GUI-Training] loss_curve не инициализирован")
                return

            if not hasattr(history_object, "history") or not history_object.history:
                logger.warning("[GUI-Training] История обучения пуста")
                self.loss_curve.setData(x=[], y=[])
                return

            history_dict = history_object.history
            logger.info(f"[GUI-Training] history_dict keys: {history_dict.keys()}")

            if "loss" in history_dict and history_dict["loss"]:
                loss_values = history_dict["loss"]
                logger.info(f"[GUI-Training] Получено {len(loss_values)} значений loss")

                if len(loss_values) > 0:
                    x_values = list(range(len(loss_values)))
                    y_values = [float(v) for v in loss_values]
                    logger.info(f"[GUI-Training] Обновление графика: {len(loss_values)} эпох, loss={loss_values[-1]:.4f}")
                    self.loss_curve.setData(x=x_values, y=y_values)
                    self.loss_plot.setTitle(f"Прогресс обучения (Loss: {loss_values[-1]:.4f})")
                    logger.info(f"[GUI-Training] График обновлен успешно")
                else:
                    logger.warning("[GUI-Training] Список loss пуст")
                    self.loss_curve.setData(x=[], y=[])
            else:
                logger.warning("[GUI-Training] История обучения не содержит данных о loss")
                self.loss_curve.setData(x=[], y=[])
        except Exception as e:
            logger.error(f"[GUI-Training] Ошибка при обновлении графика обучения: {e}", exc_info=True)

    def update_model_accuracy_chart(self: MainWindow, accuracy_data: dict):
        try:
            if not hasattr(self, "model_accuracy_bars") or self.model_accuracy_bars is None:
                logger.warning("[GUI-ModelAccuracy] Виджет не инициализирован")
                return

            if not accuracy_data:
                self.model_accuracy_bars.setOpts(x=[], height=[])
                return

            symbols = list(accuracy_data.keys())
            accuracies = [accuracy_data[s] for s in symbols]

            colors = []
            for acc in accuracies:
                if acc >= 0.5:
                    colors.append("#50fa7b")
                elif acc >= 0.4:
                    colors.append("#f1fa8c")
                else:
                    colors.append("#ff5555")

            x_positions = list(range(len(symbols)))
            self.model_accuracy_bars.setOpts(x=x_positions, height=accuracies, brushes=[pg.mkBrush(c) for c in colors])

            avg_accuracy = sum(accuracies) / len(accuracies) if accuracies else 0
            self.model_accuracy_plot_widget.setTitle(f"📊 Точность (средняя: {avg_accuracy:.1%})")

            self.model_accuracy_data = accuracy_data

            logger.info(f"[GUI-ModelAccuracy] График обновлён: {len(symbols)} символов, средняя точность: {avg_accuracy:.1%}")

        except Exception as e:
            logger.error(f"[GUI-ModelAccuracy] Ошибка при обновлении графика: {e}", exc_info=True)

    def update_retrain_progress_chart(self: MainWindow, progress_data: dict):
        try:
            if not hasattr(self, "retrain_progress_bars") or self.retrain_progress_bars is None:
                logger.warning("[GUI-RetrainProgress] Виджет не инициализирован")
                return

            if not progress_data:
                self.retrain_progress_bars.setOpts(x=[], height=[])
                return

            symbols = list(progress_data.keys())
            hours = [progress_data[s] for s in symbols]

            colors = []
            for h in hours:
                if h >= 1.0:
                    colors.append("#ff5555")
                elif h >= 0.5:
                    colors.append("#ffb86c")
                else:
                    colors.append("#50fa7b")

            x_positions = list(range(len(symbols)))
            self.retrain_progress_bars.setOpts(x=x_positions, height=hours, brushes=[pg.mkBrush(c) for c in colors])

            symbols_to_retrain = sum(1 for h in hours if h >= 1.0)
            self.retrain_progress_widget.setTitle(f"⏰ Прогресс переобучения (требуют: {symbols_to_retrain})")

            self.retrain_progress_data = progress_data

            logger.info(
                f"[GUI-RetrainProgress] График обновлён: {len(symbols)} символов, требуют переобучения: {symbols_to_retrain}"
            )

        except Exception as e:
            logger.error(f"[GUI-RetrainProgress] Ошибка при обновлении графика: {e}", exc_info=True)

    def update_candle_chart(self: MainWindow, df: pd.DataFrame, symbol: str):
        logger.info(
            f"[GUI-Chart] update_candle_chart: symbol={symbol}, len={len(df) if df is not None else 0}"
        )
        if df is None or df.empty or len(df) < 2:
            return
        try:
            self.price_plot.setTitle(f"График {symbol}")
            if len(df) > 200:
                df_chart = df.tail(200)
            else:
                df_chart = df

            # Используем колонку time как timestamps
            if 'time' in df_chart.columns:
                timestamps = (df_chart['time'].astype(np.int64) / 1e9).to_numpy().astype(np.float64)
            else:
                timestamps = (pd.to_datetime(df_chart.index).astype(np.int64) / 1e9).to_numpy().astype(np.float64)
            open_vals = df_chart["open"].values.astype(np.float64)
            high_vals = df_chart["high"].values.astype(np.float64)
            low_vals = df_chart["low"].values.astype(np.float64)
            close_vals = df_chart["close"].values.astype(np.float64)

            candlestick_data = np.column_stack((timestamps, open_vals, high_vals, low_vals, close_vals))
            self.candlestick_item.setData(candlestick_data)

            volume_vals = df_chart["tick_volume"].values
            self.volume_item.setOpts(x=timestamps, height=volume_vals)

            if len(timestamps) > 1:
                time_span = float(timestamps[-1] - timestamps[0])
                x_padding = max(time_span * 0.1, 3600)
                x_min = float(timestamps[0]) - x_padding
                x_max = float(timestamps[-1]) + x_padding

                price_range = max(high_vals) - min(low_vals)
                y_padding = max(price_range * 0.1, 1.0)
                y_min = min(low_vals) - y_padding
                y_max = max(high_vals) + y_padding

                self.price_plot.setXRange(x_min, x_max, padding=0.02)
                self.price_plot.setYRange(y_min, y_max, padding=0.02)
                logger.debug(
                    f"[GUI-Chart] Диапазон установлен: X=[{x_min:.0f}, {x_max:.0f}] ({time_span/3600:.1f}ч), Y=[{y_min:.2f}, {y_max:.2f}] ({price_range:.2f})"
                )

            logger.info(f"[GUI-Chart] График {symbol} успешно обновлен, {len(candlestick_data)} баров отображено")
        except Exception as e:
            logger.error(f"[GUI-Chart] Ошибка при обновлении графика {symbol}: {e}", exc_info=True)

    def update_trade_arrows(self: MainWindow, symbol: str):
        trade_points = []
        for deal in self.chart_trade_history:
            if deal.symbol == symbol:
                timestamp = deal.time_open.timestamp()
                price = deal.price_open
                arrow_symbol, color = ("t1", "g") if deal.trade_type == "BUY" else ("t", "r")
                trade_points.append(
                    {"pos": (timestamp, price), "symbol": arrow_symbol, "brush": pg.mkBrush(color), "size": 15}
                )
        self.trade_arrows_item.setData(trade_points)

    def update_market_regime_viz(self: MainWindow, regime: str):
        color = self.regime_colors.get(regime, QColor(0, 0, 0, 0))
        self.regime_region.setBrush(color)
        view_range = self.price_plot.vb.viewRange()
        self.regime_region.setRegion([view_range[0][0], view_range[0][1]])

    @Slot(float, str, float, bool)
    def update_drift_chart(self: MainWindow, timestamp: float, symbol: str, error: float, is_drift: bool):
        try:
            logger.info(f"[GUI Drift] Получены данные: Time={timestamp}, Sym={symbol}, Err={error:.4f}, Drift={is_drift}")

            point = {
                "x": float(timestamp),
                "y": float(error),
                "data": symbol,
            }

            if is_drift:
                self.drift_alert_points.append(point)
                logger.debug(f"[GUI Drift] Добавлена точка дрейфа: {symbol}, error={error:.4f}")
            else:
                self.drift_data_points.append(point)
                logger.debug(f"[GUI Drift] Добавлена нормальная точка: {symbol}, error={error:.4f}")

            if len(self.drift_data_points) > 200:
                self.drift_data_points.pop(0)
            if len(self.drift_alert_points) > 50:
                self.drift_alert_points.pop(0)

            x_data = [p["x"] for p in self.drift_data_points] if self.drift_data_points else []
            y_data = [p["y"] for p in self.drift_data_points] if self.drift_data_points else []

            if x_data and y_data:
                self.drift_scatter.setData(x=x_data, y=y_data)
            else:
                self.drift_scatter.setData(x=[], y=[])

            alert_x = [p["x"] for p in self.drift_alert_points] if self.drift_alert_points else []
            alert_y = [p["y"] for p in self.drift_alert_points] if self.drift_alert_points else []

            if alert_x and alert_y:
                self.drift_alert_scatter.setData(x=alert_x, y=alert_y)
            else:
                self.drift_alert_scatter.setData(x=[], y=[])

            self.drift_plot_widget.update()

            logger.debug(f"[GUI Drift] График обновлён успешно")

        except Exception as e:
            logger.error(f"[GUI Error] Ошибка отрисовки Drift Chart: {e}", exc_info=True)

    def update_orchestrator_panel(self: MainWindow, allocation_data: dict):
        # live_data шлёт {"strategies": {...}, "mode": ..., "risk": ...}
        strategies = allocation_data.get("strategies", allocation_data)
        if not isinstance(strategies, dict):
            return
        logger.info(f"[GUI-Orchestrator] Обновление: {len(strategies)} стратегий")
        try:
            labels = list(strategies.keys())
            values = [float(v) * 100 for v in strategies.values() if isinstance(v, (int, float))]
            x = np.arange(len(labels))
            self.orchestrator_bar_item.setOpts(x=x, height=values)
            ticks = [(i, label) for i, label in enumerate(labels)]
            self.orchestrator_chart_widget.getAxis("bottom").setTicks([ticks])
            logger.debug(f"[GUI-Orchestrator] Панель обновлена: {dict(zip(labels, values))}")
        except Exception as e:
            logger.error(f"[GUI-Orchestrator] Ошибка при обновлении панели Оркестратора: {e}", exc_info=True)

    def update_knowledge_graph(self: MainWindow, graph_json: str):
        import json
        if not self.kg_enabled_checkbox.isChecked():
            return
        try:
            graph_data = json.loads(graph_json)
            if self.is_graph_ready:
                self.graph_backend.graphDataUpdated.emit(graph_data)
            else:
                self.graph_data_queue = [graph_data]
        except Exception as e:
            logger.error(f"Ошибка в update_knowledge_graph: {e}")

    def on_js_ready(self: MainWindow):
        logger.info("JS Граф готов! Инициализация данных...")
        self.is_graph_ready = True

        if hasattr(self, "graph_data_queue") and self.graph_data_queue:
            latest_data = self.graph_data_queue[-1]
            logger.info(
                f"Отправка {len(self.graph_data_queue)} пакетов данных из очереди в Граф (отправляется только последний)."
            )
            self.graph_backend.graphDataUpdated.emit(latest_data)
            self.graph_data_queue.clear()
        else:
            logger.info("Очередь пуста. Запрос свежих данных из БД...")
            import threading
            threading.Thread(target=self._force_graph_update, daemon=True).start()

    def _force_graph_update(self: MainWindow):
        try:
            if hasattr(self, "trading_system") and hasattr(self.trading_system, "core_system"):
                core = self.trading_system.core_system
                if hasattr(core, "knowledge_graph_querier") and core.knowledge_graph_querier:
                    graph_data = core.knowledge_graph_querier.get_full_graph()
                    if graph_data:
                        self.graph_backend.graphDataUpdated.emit(graph_data)
        except Exception as e:
            logger.error(f"[GraphForce] Ошибка при принудительном обновлении графа: {e}", exc_info=True)
