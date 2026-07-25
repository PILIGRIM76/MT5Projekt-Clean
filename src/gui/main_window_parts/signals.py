# -*- coding: utf-8 -*-
"""
Сигналы и обработчики MainWindow — connect_signals, trading actions, updates.

Вынесены из main_pyside.py для уменьшения размера монолита.
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import queue
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QColor, QAction, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QMenu,
    QMessageBox,
)

if TYPE_CHECKING:
    from main_pyside import MainWindow

from src.core.config_loader import load_config
from src.gui.dialogs import DirectiveDialog
from src.gui.models import GenericTableModel
from src.gui.backtest_process import run_backtest_process

logger = logging.getLogger(__name__)


class SignalsMixin:
    """Миксин с обработчиками сигналов и событий для MainWindow."""

    def connect_signals(self: MainWindow):
        self.start_button.clicked.connect(self.start_trading)
        self.stop_button.clicked.connect(self.stop_trading)
        self.settings_button.clicked.connect(self.open_settings_window)
        self.bridge.drift_data_updated.connect(self.update_drift_chart)

        self.observer_checkbox.clicked.connect(self.on_observer_checkbox_clicked)

        self.update_button.clicked.connect(self.apply_update)
        self.bridge.update_status_changed.connect(self.update_update_status)
        self.bridge.status_updated.connect(self.update_status)
        self.bridge.balance_updated.connect(self.update_balance)
        self.bridge.log_message_added.connect(self.add_log_message, Qt.ConnectionType.QueuedConnection)
        self.bridge.positions_updated.connect(self.update_positions_table)
        self.bridge.history_updated.connect(self.update_history_table)
        self.bridge.training_history_updated.connect(self.update_training_chart, Qt.ConnectionType.QueuedConnection)
        self.bridge.candle_chart_updated.connect(self.update_candle_chart)
        self.bridge.pnl_updated.connect(self.update_pnl_chart)
        self.bridge.market_scan_updated.connect(self.update_market_scanner_view)
        logger.info("[GUI] Сигнал market_scan_updated подключен к update_market_scanner_view")
        self.bridge.uptime_updated.connect(self.update_uptime)
        self.bridge.rd_progress_updated.connect(self.update_rd_view)
        self.history_table.clicked.connect(self.on_history_trade_clicked)
        self.bridge.xai_data_ready.connect(self.display_xai_chart)
        self.close_pos_button.clicked.connect(self.close_selected_position)
        self.close_all_pos_button.clicked.connect(self.close_all_positions)
        self.bridge.all_positions_closed.connect(self.on_all_positions_closed)
        self.force_rd_button.clicked.connect(self.force_rd)
        self.bridge.market_regime_updated.connect(self.update_market_regime_viz)
        self.bt_run_button.clicked.connect(self.run_backtest)
        self.bt_test_type_combo.currentIndexChanged.connect(self._on_backtest_type_changed)
        self.bridge.backtest_finished.connect(self.display_backtest_results)

        self.bridge.model_accuracy_updated.connect(self.update_model_accuracy_chart, Qt.ConnectionType.QueuedConnection)
        self.bridge.retrain_progress_updated.connect(self.update_retrain_progress_chart, Qt.ConnectionType.QueuedConnection)
        logger.info("[GUI] Сигналы model_accuracy_updated и retrain_progress_updated подключены")

        self.bridge.initialization_failed.connect(self.on_initialization_failed)
        self.bridge.initialization_successful.connect(self.on_initialization_successful)

        self.bridge.directives_updated.connect(self.update_directives_table)
        self.bridge.times_updated.connect(self.update_times)
        self.create_directive_button.clicked.connect(self.open_create_directive_dialog)
        self.delete_directive_button.clicked.connect(self._delete_selected_directive)
        self.restart_system_button.clicked.connect(self._prompt_and_restart)
        self.refresh_models_button.clicked.connect(self.refresh_model_list)
        self.demote_model_button.clicked.connect(self.demote_selected_model)
        self.bridge.model_list_updated.connect(self.update_models_table)
        self.good_trade_button.clicked.connect(lambda: self.record_feedback(1))
        self.bad_trade_button.clicked.connect(lambda: self.record_feedback(-1))
        self.bridge.orchestrator_allocation_updated.connect(self.update_orchestrator_panel)
        self.bridge.knowledge_graph_updated.connect(self.update_knowledge_graph)
        self.bridge.observer_pnl_updated.connect(self.update_observer_pnl_chart)
        self.bridge.thread_status_updated.connect(self.update_thread_status)
        self.control_center_tab.settings_changed.connect(self.on_runtime_settings_changed)
        self.kg_enabled_checkbox.stateChanged.connect(self.on_kg_toggle)
        self.bridge.heavy_initialization_finished.connect(self.on_heavy_initialization_finished_slot)

        self.bridge.pnl_kpis_updated.connect(self.update_pnl_kpis)

        if hasattr(self.bridge, "trading_signals_updated"):
            self.bridge.trading_signals_updated.connect(self.control_center_tab.update_trading_signals_table)

    @Slot()
    def on_observer_checkbox_clicked(self: MainWindow):
        desired_state = self.observer_checkbox.isChecked()
        if not desired_state:
            reply = QMessageBox.question(
                self,
                "Подтверждение",
                "Вы уверены, что хотите отключить Режим Наблюдателя и перейти в рабочий режим?\n"
                "Система сможет открывать реальные сделки.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.Yes:
                import asyncio
                asyncio.ensure_future(self.trading_system.set_observer_mode(False))
            else:
                self.observer_checkbox.setChecked(True)
        else:
            import asyncio
            asyncio.ensure_future(self.trading_system.set_observer_mode(True))

    def _delete_selected_directive(self: MainWindow):
        selected_indexes = self.directives_table.selectionModel().selectedRows()
        if not selected_indexes:
            QMessageBox.warning(self, "Внимание", "Не выбрана ни одна директива для удаления.")
            return

        directive_type_item = self.directives_model.index(selected_indexes[0].row(), 0)
        directive_type = self.directives_model.data(directive_type_item, Qt.ItemDataRole.DisplayRole)

        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Вы уверены, что хотите удалить директиву '{directive_type}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.Yes:
            logger.info(f"GUI: Отправка команды на удаление директивы '{directive_type}'.")
            self.trading_system.core_system.delete_directive(directive_type)

    def _prompt_and_restart(self: MainWindow):
        reply = QMessageBox.question(
            self,
            "Подтверждение перезапуска",
            "Вы уверены, что хотите перезапустить систему? Все текущие операции будут остановлены.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.Yes:
            self.update_status("Перезапуск системы...", is_error=False)

            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText("Перезапуск системы...")
            msg.setInformativeText("Пожалуйста, подождите. Приложение будет перезапущено.")
            msg.setStandardButtons(QMessageBox.StandardButton.NoButton)
            msg.show()

            QApplication.processEvents()

            self.trading_system.core_system.restart_system()

    def update_times(self: MainWindow, pc_time_str: str, server_time_str: str):
        self.pc_time_label.setText(f"PC Время: {pc_time_str}")
        self.server_time_label.setText(f"Время сервера: {server_time_str}")

    def update_directives_table(self: MainWindow, directives: list):
        logger.info(f"[GUI-Directives] Обновление таблицы директив: {len(directives)} директив")
        try:
            table_data = []
            for d in directives:
                table_data.append(
                    [d.get("type", "N/A"), d.get("value", "N/A"), d.get("reason", "N/A"), d.get("expires_at", "N/A")]
                )
            self.directives_model = GenericTableModel(table_data, self.directives_headers)
            self.directives_table.setModel(self.directives_model)
        except Exception as e:
            logger.error(f"[GUI-Directives] Ошибка при обновлении таблицы директив: {e}", exc_info=True)

    def open_create_directive_dialog(self: MainWindow):
        logger.info("[GUI-Dialog] Открытие диалога создания директивы")
        dialog = DirectiveDialog(self)
        try:
            if dialog.exec():
                data = dialog.get_data()
                logger.info(f"[GUI-Dialog] Создание директивы: тип={data['type']}, значение={data.get('value', 'N/A')}")
                self.trading_system.add_directive(
                    directive_type=data["type"],
                    reason=data["reason"],
                    duration_hours=data["duration_hours"],
                    value=data["value"],
                )
            else:
                logger.info("[GUI-Dialog] Диалог создания директивы закрыт без сохранения")
        except Exception as e:
            logger.error(f"[GUI-Dialog] Ошибка при создании директивы: {e}", exc_info=True)

    def show_scanner_context_menu(self: MainWindow, position):
        index = self.scanner_table.indexAt(position)
        if not index.isValid():
            return
        symbol = self.scanner_model.data(index.siblingAtColumn(1), Qt.ItemDataRole.DisplayRole)
        if not symbol:
            return
        menu = QMenu()
        blacklist_action = QAction(f"Добавить '{symbol}' в черный список (временно)", self)
        blacklist_action.triggered.connect(lambda: self.add_symbol_to_blacklist(symbol))
        menu.addAction(blacklist_action)
        menu.exec(self.scanner_table.viewport().mapToGlobal(position))

    def add_symbol_to_blacklist(self: MainWindow, symbol: str):
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Вы уверены, что хотите временно исключить '{symbol}' из торговли до следующего перезапуска?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.Yes:
            logger.warning(f"GUI: Символ '{symbol}' добавлен в черный список.")
            self.trading_system.add_to_blacklist(symbol)
            self.update_status(f"Символ {symbol} временно исключен из торговли.", False)

    def refresh_model_list(self: MainWindow):
        logger.info("Запрос на обновление списка моделей из GUI...")
        threading.Thread(target=self._fetch_and_update_models, daemon=True).start()

    def _fetch_and_update_models(self: MainWindow):
        models = self.trading_system.get_all_models()
        self.bridge.model_list_updated.emit(models)

    def update_models_table(self: MainWindow, models: list):
        logger.info(f"[GUI-Models] Обновление таблицы моделей: {len(models)} моделей")
        try:
            table_data = []
            for model in models:
                table_data.append(
                    [
                        model.get("id"),
                        model.get("symbol"),
                        model.get("type"),
                        model.get("version"),
                        model.get("status"),
                        model.get("sharpe"),
                        model.get("profit_factor"),
                        model.get("date"),
                    ]
                )
            self.models_model = GenericTableModel(table_data, self.models_headers)
            self.models_table.setModel(self.models_model)
        except Exception as e:
            logger.error(f"[GUI-Models] Ошибка при обновлении таблицы моделей: {e}", exc_info=True)

    def demote_selected_model(self: MainWindow):
        selected_indexes = self.models_table.selectionModel().selectedRows()
        if not selected_indexes:
            QMessageBox.warning(self, "Внимание", "Не выбрана ни одна модель для разжалования.")
            return
        model_id_item = self.models_model.index(selected_indexes[0].row(), 0)
        model_id = int(self.models_model.data(model_id_item, Qt.ItemDataRole.DisplayRole))
        status_item = self.models_model.index(selected_indexes[0].row(), 4)
        status = self.models_model.data(status_item, Qt.ItemDataRole.DisplayRole)
        if status != "Чемпион":
            QMessageBox.information(self, "Информация", "Выбранная модель не является чемпионом.")
            return
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Вы уверены, что хотите разжаловать модель #{model_id}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.Yes:
            success = self.trading_system.demote_champion(model_id)
            if success:
                QMessageBox.information(
                    self,
                    "Успех",
                    f"Модель #{model_id} успешно разжалована. Система выберет нового чемпиона в следующем R&D цикле.",
                )
                self.refresh_model_list()
            else:
                QMessageBox.critical(self, "Ошибка", f"Не удалось разжаловать модель #{model_id}.")

    def run_backtest(self: MainWindow):
        test_type = self.bt_test_type_combo.currentText()
        symbol = self.bt_symbol_combo.currentText()
        timeframe_text = self.bt_timeframe_combo.currentText()
        timeframe = self.timeframe_map.get(timeframe_text)
        start_date = self.bt_start_date.date().toPython()
        end_date = self.bt_end_date.date().toPython()
        model_id = None
        strategy_name = None
        if test_type == "Классическая стратегия":
            strategy_name = self.bt_strategy_combo.currentText()
            if not all([symbol, strategy_name, timeframe is not None]):
                QMessageBox.warning(self, "Ошибка", "Пожалуйста, выберите символ, стратегию и таймфрейм.")
                return
            self.bt_report_text.setText(f"Запуск бэктеста для {strategy_name} на {symbol} ({timeframe_text})...")
        elif test_type == "AI Модель":
            selected_model_text = self.bt_strategy_combo.currentText()
            if "Нет обученных моделей" in selected_model_text or not selected_model_text:
                QMessageBox.warning(self, "Ошибка", "Пожалуйста, выберите AI модель.")
                return
            try:
                model_id = int(selected_model_text.split(" ")[1])
            except (ValueError, IndexError):
                QMessageBox.critical(self, "Ошибка", f"Не удалось извлечь ID из строки: {selected_model_text}")
                return
            self.bt_report_text.setText(f"Запуск бэктеста для AI Модели ID:{model_id}...")
        self.bt_run_button.setEnabled(False)
        self.results_queue = multiprocessing.Queue()
        config_dict = self.trading_system.config.model_dump()
        self.backtest_process = multiprocessing.Process(
            target=run_backtest_process,
            args=(
                self.results_queue,
                config_dict,
                symbol,
                strategy_name,
                timeframe,
                start_date,
                end_date,
                test_type,
                model_id,
            ),
        )
        self.backtest_process.start()
        self.backtest_check_timer = QTimer(self)
        self.backtest_check_timer.timeout.connect(self.check_backtest_results)
        self.backtest_check_timer.start(100)

    def check_backtest_results(self: MainWindow):
        try:
            result = self.results_queue.get_nowait()
            self.backtest_check_timer.stop()
            report = result["report"]
            equity_df = result["equity"]
            self.display_backtest_results(report, equity_df)

            def cleanup_process():
                self.backtest_process.join(timeout=5)
                if self.backtest_process.is_alive():
                    logger.warning("Процесс бэктеста не завершился штатно, принудительное завершение.")
                    self.backtest_process.terminate()
                    self.backtest_process.join()
                self.backtest_process.close()
                logger.info("Процесс бэктеста успешно завершен и очищен.")

            cleanup_thread = threading.Thread(target=cleanup_process, daemon=True)
            cleanup_thread.start()
        except queue.Empty:
            pass

    def display_backtest_results(self: MainWindow, report: dict, equity_df: pd.DataFrame):
        report_text = "--- Отчет по Бэктесту ---\n\n"
        for key, value in report.items():
            report_text += f"{key}: {value}\n"
        self.bt_report_text.setText(report_text)
        if not equity_df.empty:
            self.bt_equity_curve.setData(x=np.arange(len(equity_df)), y=equity_df["equity"].values)
        else:
            self.bt_equity_curve.clear()
        self.bt_run_button.setEnabled(True)

    def apply_update(self: MainWindow):
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            "Вы уверены, что хотите применить обновление и перезапустить систему?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.Yes:
            self.update_status_label.setText("Применение обновления...")
            self.update_button.setEnabled(False)
            QApplication.processEvents()
            self.trading_system.core_system.auto_updater.apply_update_and_restart()

    def update_update_status(self: MainWindow, message: str, is_available: bool):
        self.update_status_label.setText(f"🔄 Статус: {message}")
        self.update_button.setEnabled(is_available)
        if is_available:
            self.update_status_label.setStyleSheet("color: #ffb86c; font-weight: bold;")
        else:
            self.update_status_label.setStyleSheet("color: #50fa7b;")
        self._update_version_and_monitoring_info()

    def _update_version_and_monitoring_info(self: MainWindow):
        try:
            if not hasattr(self, "trading_system") or not self.trading_system:
                return

            adapter = self.trading_system

            if hasattr(adapter, "core_system") and adapter.core_system:
                manager = adapter.core_system.hot_reload_manager

                if manager:
                    status = manager.get_update_status()

                    local_commit = status.get("local_commit")
                    if local_commit:
                        self.update_version_label.setText(f"📦 Версия: v{local_commit[:8]}")
                    else:
                        self.update_version_label.setText("📦 Версия: N/A")

                    if status.get("monitoring"):
                        self.update_monitoring_label.setText("👁️ Мониторинг: ✅ Активен")
                        self.update_monitoring_label.setStyleSheet("color: #50fa7b;")
                    else:
                        self.update_monitoring_label.setText("👁️ Мониторинг: ❌ Не активен")
                        self.update_monitoring_label.setStyleSheet("color: #ff5555;")

                    last_check_ts = status.get("last_check")
                    if last_check_ts and last_check_ts > 0:
                        last_check = datetime.fromtimestamp(last_check_ts)
                        self.update_last_check_label.setText(f"⏰ Последняя проверка: {last_check.strftime('%H:%M:%S')}")
                    else:
                        self.update_last_check_label.setText("⏰ Последняя проверка: Ещё не проверялось")
        except Exception as e:
            logger.error(f"[MainWindow] Ошибка обновления информации об обновлениях: {e}", exc_info=True)

    def on_initialization_failed(self: MainWindow):
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        QMessageBox.critical(
            self,
            "Ошибка Запуска",
            "Не удалось подключиться к терминалу MetaTrader 5. Проверьте, что терминал запущен, и проверьте логи для деталей.",
        )

    def on_history_trade_clicked(self: MainWindow, index):
        if not index.isValid():
            return
        ticket_item = self.history_model.index(index.row(), 0)
        try:
            ticket = int(self.history_model.data(ticket_item, Qt.ItemDataRole.DisplayRole))
        except (ValueError, TypeError):
            return
        self.good_trade_button.setEnabled(False)
        self.bad_trade_button.setEnabled(False)
        self.current_xai_ticket = None
        self.xai_label.setText(f"Загрузка данных для сделки #{ticket}...")
        self.xai_web_view.setHtml(
            "<html><body style='background-color:#282a36;'><h3 style='color:#f8f8f2; text-align:center;'>Загрузка...</h3></body></html>"
        )
        threading.Thread(target=self.fetch_and_display_xai, args=(ticket,), daemon=True).start()

    def fetch_and_display_xai(self: MainWindow, ticket: int):
        xai_data = self.trading_system.core_system.get_xai_data_for_trade(ticket)
        self.bridge.xai_data_ready.emit(xai_data, ticket)

    def display_xai_chart(self: MainWindow, xai_data: dict, ticket: int):
        import shap
        import matplotlib.pyplot as plt
        from PySide6.QtCore import QUrl

        if not xai_data or "shap_values" not in xai_data or "base_value" not in xai_data:
            self.xai_label.setText(f"Данные анализа для сделки #{ticket} отсутствуют или неполны.")
            self.xai_web_view.setHtml(
                "<html><body style='background-color:#282a36;'><h3 style='color:#f8f8f2; text-align:center;'>Данные отсутствуют.</h3></body></html>"
            )
            return
        self.xai_label.setText(f"Интерактивный анализ влияния факторов на сделку #{ticket}")
        try:
            shap_values_dict = xai_data.get("shap_values", {})
            base_value = xai_data.get("base_value", 0.5)
            shap_values_array = np.array(list(shap_values_dict.values()))
            feature_names = list(shap_values_dict.keys())
            force_plot = shap.force_plot(base_value, shap_values_array, feature_names=feature_names, matplotlib=False)
            self.good_trade_button.setEnabled(True)
            self.bad_trade_button.setEnabled(True)
            self.current_xai_ticket = ticket
            if self.temp_html_file and os.path.exists(self.temp_html_file):
                os.remove(self.temp_html_file)
            fd, self.temp_html_file = tempfile.mkstemp(suffix=".html")
            os.close(fd)
            shap.save_html(self.temp_html_file, force_plot)
            plt.close("all")
            self.xai_web_view.setUrl(QUrl.fromLocalFile(self.temp_html_file))
        except Exception as e:
            logger.error(f"Ошибка при создании SHAP force plot: {e}", exc_info=True)
            self.xai_web_view.setHtml(f"<html><body><h3>Ошибка: {e}</h3></body></html>")

    def record_feedback(self: MainWindow, feedback_value: int):
        if self.current_xai_ticket is None:
            return
        logger.info(f"Отправка отзыва ({feedback_value}) для сделки #{self.current_xai_ticket} в ядро системы.")
        self.trading_system.core_system.record_human_feedback(trade_ticket=self.current_xai_ticket, feedback=feedback_value)
        self.good_trade_button.setEnabled(False)
        self.bad_trade_button.setEnabled(False)

    def start_trading(self: MainWindow):
        logger.info("[GUI-Action] Пользователь нажал кнопку 'Запустить торговлю'")
        try:
            if self.trading_system.core_system.running:
                logger.warning("[GUI-Action] Система уже запущена, игнорируем повторный запуск")
                return

            logger.info("[GUI-Action] Запуск торгового цикла...")
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.status_label.setText("Запуск системы...")
            QApplication.processEvents()

            def _run_async():
                import asyncio

                async def _start_all():
                    # 1. Запуск ядра (EventBus, подписки)
                    await self.trading_system.core_system.start()
                    logger.info("[Core] TradingSystem started")

                    # 2. Запуск обучения
                    config = self.trading_system.config
                    try:
                        from src.core.training_scheduler import TrainingScheduler
                        scheduler = TrainingScheduler(config)
                        scheduler.start()
                        logger.info("[Training] TrainingScheduler started")
                    except Exception as e:
                        logger.warning(f"[Training] Failed to start: {e}")

                    # 3. Запуск ML сервиса
                    try:
                        from src.core.services.ml_service import MLService
                        from src.db.database_manager import DatabaseManager
                        from src.ml.feature_engineer import FeatureEngineer
                        from src.data.knowledge_graph_querier import KnowledgeGraphQuerier

                        db = DatabaseManager(config, __import__('queue').Queue())
                        kg = KnowledgeGraphQuerier(db)
                        fe = FeatureEngineer(config, kg)
                        ml_service = MLService(config, fe, db, kg)
                        await ml_service.start()
                        logger.info("[ML] MLService started")
                    except Exception as e:
                        logger.warning(f"[ML] Failed to start: {e}")

                    # 4. Запуск оркестратора
                    try:
                        from src.core.services.orchestrator_service import OrchestratorService
                        orch = OrchestratorService(self.trading_system.core_system)
                        await orch.start()
                        logger.info("[Orchestrator] Started")
                    except Exception as e:
                        logger.warning(f"[Orchestrator] Failed to start: {e}")

                    # 5. Статус
                    self.bridge.status_updated.emit("Система запущена. Торговля активна.", False)
                    self.bridge.trading_started.emit(True)
                    self.start_button.setEnabled(True)
                    self.stop_button.setEnabled(True)
                    logger.info("[GUI-Action] Все сервисы запущены")

                asyncio.run(_start_all())

            threading.Thread(target=_run_async, daemon=True).start()
            logger.info("[GUI-Action] Торговая система запускается в фоновом потоке")
        except Exception as e:
            logger.error(f"[GUI-Action] Ошибка при запуске торговли: {e}", exc_info=True)

    def on_initialization_successful(self: MainWindow, symbols: list):
        logger.info(f"Инициализация успешна. Получено {len(symbols)} символов для бэктестера.")

        self.bt_symbol_combo.clear()
        self.bt_symbol_combo.addItems(symbols)
        self._on_backtest_type_changed()
        self.refresh_model_list()

        if hasattr(self, "control_center_tab"):
            self.control_center_tab.refresh_strategies()

        self.stop_button.setEnabled(True)

        QTimer.singleShot(3000, self._update_version_and_monitoring_info)

        success, message = self.trading_system.connect_to_terminal_adapter()

        if success:
            self.bridge.status_updated.emit("Соединение установлено. Запуск торговых циклов...", False)
            self.sound_manager.play("system_start")
            self.stop_button.setEnabled(True)

            if self.trading_system.core_system.running:
                logger.info("[GUI] Система уже запущена, пропускаю повторный вызов start_all_threads()")
            else:
                logger.warning("[GUI] Система НЕ запущена! Вызываю start_all_threads()")
                self.trading_system.start_all_threads()

            QTimer.singleShot(5000, self._send_initial_training_data)
        else:
            error_msg = f"Ошибка подключения к MT5: {message}"
            self.bridge.status_updated.emit(error_msg, True)
            self.sound_manager.play("error")
            self.bridge.initialization_failed.emit()

    def _send_initial_training_data(self: MainWindow):
        logger.info("[GUI] Отправка начальных данных для графиков переобучения...")
        if hasattr(self.trading_system.core_system, "_send_model_accuracy_to_gui"):
            self.trading_system.core_system._send_model_accuracy_to_gui()
        if hasattr(self.trading_system.core_system, "_send_retrain_progress_to_gui"):
            self.trading_system.core_system._send_retrain_progress_to_gui()

    def stop_trading(self: MainWindow):
        logger.info("[GUI-Action] Пользователь нажал кнопку 'Остановить торговлю'")
        try:
            if self.trading_system.core_system.running:
                self.sound_manager.play("system_stop")
                self.trading_system.stop()
                self.update_status("Команда на остановку отправлена...", is_error=False)
                logger.info("[GUI-Action] Команда на остановку торговой системы отправлена")
            else:
                logger.warning("[GUI-Action] Система уже остановлена")

            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)

            self.uptime_label.setText("Время работы: остановлено")
        except Exception as e:
            logger.error(f"[GUI-Action] Ошибка при остановке торговли: {e}", exc_info=True)

    def close_all_positions(self: MainWindow):
        logger.info("[GUI-Action] Пользователь нажал кнопку 'Закрыть все позиции'")
        try:
            reply = QMessageBox.question(
                self,
                "Подтверждение",
                f"Вы уверены, что хотите закрыть ВСЕ открытые позиции по рынку?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.Yes:
                logger.warning("[GUI-Action] Подтверждено закрытие ВСЕХ позиций")
                self.sound_manager.play("error")
                self.trading_system.emergency_close_all_positions()
                self.close_pos_button.setEnabled(False)
                self.close_all_pos_button.setEnabled(False)
                self.bridge.status_updated.emit("Команда на закрытие всех позиций отправлена...", False)
            else:
                logger.info("[GUI-Action] Закрытие всех позиций отменено пользователем")
        except Exception as e:
            logger.error(f"[GUI-Action] Ошибка при закрытии всех позиций: {e}", exc_info=True)

    def on_all_positions_closed(self: MainWindow):
        self.close_pos_button.setEnabled(True)
        self.close_all_pos_button.setEnabled(True)
        self.bridge.status_updated.emit("Все позиции закрыты.", False)

    def update_rd_view(self: MainWindow, progress_data: dict):
        logger.info(f"[GUI-RD] Обновление R&D: {progress_data}")
        self.rd_model.update_data(progress_data)
        self.rd_table.scrollToBottom()

    def close_selected_position(self: MainWindow):
        logger.info("[GUI-Action] Пользователь нажал кнопку 'Закрыть выбранную позицию'")
        try:
            selected_indexes = self.positions_table.selectionModel().selectedRows()
            if not selected_indexes:
                logger.warning("[GUI-Action] Не выбрана ни одна позиция для закрытия")
                QMessageBox.warning(self, "Внимание", "Не выбрана ни одна позиция.")
                return
            ticket_item = self.positions_model.index(selected_indexes[0].row(), 0)
            ticket = int(self.positions_model.data(ticket_item, Qt.ItemDataRole.DisplayRole))
            reply = QMessageBox.question(
                self,
                "Подтверждение",
                f"Закрыть позицию #{ticket} по рынку?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.Yes:
                logger.info(f"[GUI-Action] Подтверждено закрытие позиции #{ticket}")
                self.trading_system.emergency_close_position(ticket)
            else:
                logger.info(f"[GUI-Action] Закрытие позиции #{ticket} отменено пользователем")
        except Exception as e:
            logger.error(f"[GUI-Action] Ошибка при закрытии выбранной позиции: {e}", exc_info=True)

    def toggle_observer_mode(self: MainWindow):
        self.trading_system.toggle_observer_mode()

    def set_paper_trading_mode(self: MainWindow, enabled: bool):
        self.trading_system.set_paper_trading_mode(enabled)

    def get_trading_mode(self: MainWindow) -> str:
        return self.trading_system.get_trading_mode()

    def update_status(self: MainWindow, message, is_error):
        logger.info(f"[GUI-Status] Обновление статуса: '{message}', ошибка={is_error}")
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: red;" if is_error else "")

    def update_balance(self: MainWindow, balance, equity):
        logger.info(f"[GUI-Balance] update_balance вызван: balance={balance}, equity={equity}")
        self.balance_label.setText(f"Баланс: {balance:.2f}")
        self.equity_label.setText(f"Эквити: {equity:.2f}")

        open_pnl = equity - balance
        open_pnl_pct = (open_pnl / balance * 100) if balance > 0 else 0

        if hasattr(self, "open_pnl_label"):
            color = "#50fa7b" if open_pnl >= 0 else "#ff5555"
            pnl_text = f"<span style='font-weight: bold; color:{color}'>{open_pnl:+.2f} ({open_pnl_pct:+.2f}%)</span>"
            self.open_pnl_label.setText(pnl_text)

    def add_log_message(self: MainWindow, text: str, color: QColor):
        char_format = QTextCharFormat()
        char_format.setForeground(color)
        cursor = self.log_text_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.setCharFormat(char_format)
        cursor.insertText(text + "\n")
        cursor.setCharFormat(QTextCharFormat())
        self.log_text_edit.ensureCursorVisible()

    def update_positions_table(self: MainWindow, positions: list):
        try:
            table_data = []
            for pos_dict in positions:
                ticket = pos_dict.get("ticket")
                pos_type = "BUY" if pos_dict.get("type") == 0 else "SELL"
                strategy_name = pos_dict.get("strategy_display", "Загрузка...")
                timeframe_str = pos_dict.get("timeframe_display", "N/A")
                bars_in_trade = pos_dict.get("bars_in_trade_display", "-")
                profit = float(pos_dict.get("profit", 0.0))

                row_data = [
                    ticket,
                    pos_dict.get("symbol"),
                    strategy_name,
                    pos_type,
                    pos_dict.get("volume"),
                    f"{pos_dict.get('price_open', 0):.5f}",
                    f"{profit:.2f}",
                    bars_in_trade,
                    timeframe_str,
                ]
                table_data.append(row_data)

            self.positions_model = GenericTableModel(table_data, self.positions_headers)
            self.positions_table.setModel(self.positions_model)
        except Exception as e:
            logger.error(f"[GUI-Positions] Ошибка при обновлении таблицы позиций: {e}", exc_info=True)

    def update_history_table(self: MainWindow, deals: list):
        logger.info(f"[GUI-History] Обновление истории сделок: {len(deals)} сделок")
        try:
            table_data = []
            for deal in deals:
                time_str = deal.time_close.strftime("%Y-%m-%d %H:%M")
                timeframe_display = deal.timeframe.replace("TIMEFRAME_", "") if deal.timeframe else "N/A"
                table_data.append(
                    [
                        deal.ticket,
                        deal.symbol,
                        deal.strategy,
                        deal.trade_type,
                        deal.volume,
                        f"{deal.price_close:.5f}",
                        time_str,
                        f"{deal.profit:.2f}",
                        timeframe_display,
                    ]
                )

            self.history_model = GenericTableModel(table_data, self.history_headers)
            self.history_table.setModel(self.history_model)
            self.chart_trade_history = deals
            current_symbol = self.price_plot.titleLabel.text.replace("График ", "")
            if current_symbol:
                self.update_trade_arrows(current_symbol)
        except Exception as e:
            logger.error(f"[GUI-History] Ошибка при обновлении таблицы истории: {e}", exc_info=True)

    def update_market_scanner_view(self: MainWindow, ranked_list: list):
        logger.info(f"[DEBUG] update_market_scanner_view ВЫЗВАН с {len(ranked_list) if ranked_list else 0} элементами")

        if ranked_list and len(ranked_list) > 0:
            logger.info(f"[DEBUG] Первый элемент: {ranked_list[0]}")

        if not ranked_list or len(ranked_list) == 0:
            logger.warning("[Scanner] Пустые данные, пропускаем обновление")
            return

        logger.info(f"[GUI-Scanner] Обновление сканера: {len(ranked_list)} символов")

        try:
            if len(ranked_list) > 100:
                ranked_list = ranked_list[:100]

            table_data = []
            for item in ranked_list:
                row = [
                    int(item.get("rank", 0)) if item.get("rank") else "-",
                    str(item.get("symbol", "N/A")),
                    f"{float(item.get('total_score', 0)):.3f}",
                    f"{float(item.get('volatility_score', 0)):.3f}",
                    f"{float(item.get('normalized_atr_percent', 0)):.3f}%",
                    f"{float(item.get('trend_score', 0)):.3f}",
                    f"{float(item.get('liquidity_score', 0)):.3f}",
                    f"{float(item.get('spread_pips', -1.0)):.1f}",
                ]
                table_data.append(row)

            if not hasattr(self, "scanner_model") or self.scanner_model is None:
                self.scanner_model = GenericTableModel(table_data, self.scanner_headers)
                self.scanner_table.setModel(self.scanner_model)
            else:
                self.scanner_model.update_data(table_data)

            if not hasattr(self, "_scanner_columns_resized"):
                header = self.scanner_table.horizontalHeader()
                for i in range(len(self.scanner_headers)):
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
                self._scanner_columns_resized = True
        except Exception as e:
            logger.error(f"[GUI-Scanner] Ошибка при обновлении сканера: {e}", exc_info=True)

    def update_uptime(self: MainWindow, uptime_str: str):
        self.uptime_label.setText(f"Время работы: {uptime_str}")

    def open_settings_window(self: MainWindow):
        logger.info("[GUI-Dialog] Открытие окна настроек")
        dialog = self.settings_window
        dialog.settings_saved.connect(self.on_settings_saved)
        try:
            if dialog.exec():
                logger.info("[GUI-Dialog] Окно настроек закрыто с сохранением, применяем изменения...")
                new_config = load_config()
                self.trading_system.update_configuration(new_config)
            else:
                logger.info("[GUI-Dialog] Окно настроек закрыто без сохранения")
        except Exception as e:
            logger.error(f"[GUI-Dialog] Ошибка при работе с окном настроек: {e}", exc_info=True)

    def on_settings_saved(self: MainWindow):
        logger.info("Обнаружено сохранение настроек. Применение изменений на лету...")
        try:
            new_config = load_config()
            self.trading_system.update_configuration(new_config)

            if hasattr(self, "control_center_tab"):
                trading_settings = {
                    "RISK_PERCENTAGE": new_config.RISK_PERCENTAGE,
                    "MAX_OPEN_POSITIONS": new_config.MAX_OPEN_POSITIONS,
                    "MAX_DAILY_DRAWDOWN_PERCENT": new_config.MAX_DAILY_DRAWDOWN_PERCENT,
                    "trading_mode": getattr(new_config, "trading_mode", {"current_mode": "standard", "enabled": False}),
                }
                self.control_center_tab.update_trading_settings_display(trading_settings)

            self.update_status("Настройки успешно применены.", is_error=False)
            self.update_scheduler_status_display()
        except Exception as e:
            logger.error(f"Ошибка при применении новых настроек: {e}")
            self.update_status("Ошибка при применении настроек. См. логи.", is_error=True)

    def update_thread_status(self: MainWindow, thread_name: str, status: str):
        if thread_name in self.thread_status_labels:
            label = self.thread_status_labels[thread_name]
            status_colors = {
                "RUNNING": ("#50fa7b", "РАБОТАЕТ"),
                "STOPPING": ("#f1fa8c", "ОСТАНОВКА..."),
                "STOPPED": ("#ff5555", "ОСТАНОВЛЕН"),
            }
            color, text = status_colors.get(status.upper(), ("#f8f8f2", status))
            label.setText(text)
            label.setStyleSheet(f"font-weight: bold; color: {color};")
            QApplication.processEvents()

    def force_training(self: MainWindow):
        logger.info("[GUI-Action] Пользователь нажал кнопку 'Запустить цикл обучения'")
        try:
            self.trading_system.force_training_cycle()
            QMessageBox.information(self, "Запрос отправлен", "Команда на запуск цикла обучения отправлена в фоновый поток.")
        except Exception as e:
            logger.error(f"[GUI-Action] Ошибка при запуске цикла обучения: {e}", exc_info=True)

    def force_rd(self: MainWindow):
        logger.info("[GUI-Action] Пользователь нажал кнопку 'Запустить R&D цикл'")
        try:
            self.trading_system.force_rd_cycle()
            QMessageBox.information(self, "Запрос отправлен", "Команда на запуск R&D цикла отправлена в фоновый поток.")
        except Exception as e:
            logger.error(f"[GUI-Action] Ошибка при запуске R&D цикла: {e}", exc_info=True)

    def on_runtime_settings_changed(self: MainWindow, new_settings: dict):
        logger.info(f"[GUI] Применение настроек в реальном времени: {list(new_settings.keys())}")
        self.trading_system.core_system.update_runtime_settings(new_settings)
        if hasattr(self, "control_center_tab"):
            self.control_center_tab.update_trading_settings_display(new_settings)
        self.update_status("Настройки применены", is_error=False)

    @Slot()
    def on_heavy_initialization_finished_slot(self: MainWindow):
        self.start_button.setEnabled(True)
        if hasattr(self, "defi_widget") and hasattr(self.trading_system.core_system, "db_manager"):
            logger.info("[DeFi] Подключение к БД...")
            self.defi_widget.set_db_manager(self.trading_system.core_system.db_manager)

    def on_filter_request(self: MainWindow, filter_type: str, filter_value: str):
        logger.info(f"KG Filter Request: Type={filter_type}, Value={filter_value}")
        threading.Thread(target=self._fetch_and_send_filtered_graph, args=(filter_type, filter_value), daemon=True).start()

    def _fetch_and_send_filtered_graph(self: MainWindow, filter_type: str, filter_value: str):
        try:
            db_manager = self.trading_system.core_system.db_manager
            if db_manager is None:
                return
            graph_data = db_manager.get_graph_data(limit=50)
            if graph_data:
                self.graph_backend.graphDataUpdated.emit(graph_data)
        except Exception as e:
            logger.error(f"Ошибка при фильтрации графа: {e}")

    def update_scheduler_status_display(self: MainWindow):
        try:
            project_root = Path(os.path.dirname(os.path.abspath(__file__)))

            maint_label = self.scheduler_status_labels.get("Maintenance")
            if maint_label:
                maint_time_str = self.scheduler_manager.get_task_trigger_time("GenesisMaintenance")
                maint_status_file = project_root / ".." / ".." / ".." / "database" / "maintenance_status.json"

                last_run_str = ""
                if maint_status_file.exists():
                    try:
                        with open(maint_status_file, "r") as f:
                            data = json.load(f)
                            last_run_utc = datetime.fromisoformat(data["last_run_utc"])
                            last_run_local = last_run_utc.astimezone()
                            last_run_str = f" (Выполнено: {last_run_local.strftime('%d.%m %H:%M')})"
                    except Exception as e:
                        logger.error(f"Ошибка чтения файла статуса обслуживания: {e}")

                display_text = f"Ежедневно в {maint_time_str}" if maint_time_str else "Не настроено"
                maint_label.setText(display_text + last_run_str)
                maint_label.setStyleSheet("color: #8be9fd;" if maint_time_str else "color: #f1fa8c;")

            opt_label = self.scheduler_status_labels.get("Optimization")
            if opt_label:
                opt_time_str = self.scheduler_manager.get_task_trigger_time("GenesisWeeklyOptimization")
                opt_status_file = project_root / ".." / ".." / ".." / "database" / "optimization_status.json"

                last_run_str = ""
                if opt_status_file.exists():
                    try:
                        with open(opt_status_file, "r") as f:
                            data = json.load(f)
                            last_run_utc = datetime.fromisoformat(data["last_run_utc"])
                            last_run_local = last_run_utc.astimezone()
                            last_run_str = f" (Выполнено: {last_run_local.strftime('%d.%m %H:%M')})"
                    except Exception as e:
                        logger.error(f"Ошибка чтения файла статуса оптимизации: {e}")

                display_text = f"Еженедельно (Сб) в {opt_time_str}" if opt_time_str else "Не настроено"
                opt_label.setText(display_text + last_run_str)
                opt_label.setStyleSheet("color: #8be9fd;" if opt_time_str else "color: #f1fa8c;")

        except Exception as e:
            logger.error(f"Критическая ошибка в update_scheduler_status_display: {e}", exc_info=True)
