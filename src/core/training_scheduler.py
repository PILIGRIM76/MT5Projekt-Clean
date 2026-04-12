"""
Планировщик автоматического переобучения моделей.
Запускает обучение по расписанию в фоновом режиме, когда рынки закрыты.
"""

import logging
import threading
import time
from datetime import datetime
from datetime import time as dt_time
from typing import Callable, Optional

import schedule

logger = logging.getLogger(__name__)


class TrainingScheduler:
    """
    Планировщик автоматического переобучения моделей.
    Работает в отдельном потоке и не блокирует основную систему.
    """

    def __init__(self, config, training_callback: Callable):
        """
        Args:
            config: Конфигурация системы
            training_callback: Функция для запуска обучения (принимает max_symbols, max_workers)
        """
        self.config = config
        self.training_callback = training_callback
        self.stop_event = threading.Event()
        self.scheduler_thread: Optional[threading.Thread] = None
        self.is_running = False
        self.last_training_time: Optional[datetime] = None
        self.training_in_progress = False

        # Настройки из конфигурации или значения по умолчанию
        # ИСПРАВЛЕНИЕ: Читаем из вложенного объекта auto_retraining
        auto_retrain_config = getattr(config, "auto_retraining", None)
        if auto_retrain_config:
            # Проверяем, это Pydantic модель или dict
            if isinstance(auto_retrain_config, dict):
                self.enabled = auto_retrain_config.get("enabled", True)
                self.schedule_time = auto_retrain_config.get("schedule_time", "02:00")
                self.max_symbols = auto_retrain_config.get("max_symbols", 30)  # ← ИСПРАВЛЕНО!
                self.max_workers = auto_retrain_config.get("max_workers", 3)
                self.interval_hours = auto_retrain_config.get("interval_hours", 24)
            else:
                # Pydantic модель
                self.enabled = getattr(auto_retrain_config, "enabled", True)
                self.schedule_time = getattr(auto_retrain_config, "schedule_time", "02:00")
                self.max_symbols = getattr(auto_retrain_config, "max_symbols", 30)  # ← ИСПРАВЛЕНО!
                self.max_workers = getattr(auto_retrain_config, "max_workers", 3)
                self.interval_hours = getattr(auto_retrain_config, "interval_hours", 24)
        else:
            # Fallback на старые атрибуты
            self.enabled = getattr(config, "AUTO_RETRAIN_ENABLED", True)
            self.schedule_time = getattr(config, "AUTO_RETRAIN_TIME", "02:00")
            self.max_symbols = getattr(config, "AUTO_RETRAIN_MAX_SYMBOLS", 30)
            self.max_workers = getattr(config, "AUTO_RETRAIN_MAX_WORKERS", 3)
            self.interval_hours = getattr(config, "AUTO_RETRAIN_INTERVAL_HOURS", 24)

        logger.info(f"TrainingScheduler инициализирован:")
        logger.info(f"  - Включен: {self.enabled}")
        logger.info(f"  - Время запуска: {self.schedule_time}")
        logger.info(f"  - Макс. символов: {self.max_symbols}")
        logger.info(f"  - Макс. потоков: {self.max_workers}")
        logger.info(f"  - Интервал: каждые {self.interval_hours} часов")

    def start(self):
        """Запускает планировщик в отдельном потоке."""
        logger.info("=" * 80)
        logger.info("🕐 TrainingScheduler.start() вызван")
        logger.info(f"   self.enabled = {self.enabled}")
        logger.info(f"   self.is_running = {self.is_running}")
        logger.info(f"   self.schedule_time = {self.schedule_time}")
        logger.info(f"   self.interval_hours = {self.interval_hours}")
        logger.info("=" * 80)

        if not self.enabled:
            logger.info("❌ Автоматическое переобучение отключено в настройках")
            return

        if self.is_running:
            logger.warning("⚠️ Планировщик переобучения уже запущен")
            return

        self.stop_event.clear()
        self.is_running = True

        # Настройка расписания
        self._setup_schedule()

        # Запуск потока планировщика
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, name="TrainingScheduler", daemon=True)
        self.scheduler_thread.start()
        logger.info("✅ Планировщик автоматического переобучения ЗАПУЩЕН")

    def stop(self):
        """Останавливает планировщик."""
        if not self.is_running:
            return

        logger.info("Остановка планировщика переобучения...")
        self.stop_event.set()
        self.is_running = False

        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self.scheduler_thread.join(timeout=5)

        schedule.clear()
        logger.info("Планировщик остановлен")

    def _setup_schedule(self):
        """Настраивает расписание запуска обучения."""
        schedule.clear()

        # Парсим время из строки "HH:MM"
        try:
            hour, minute = map(int, self.schedule_time.split(":"))
            schedule_time = dt_time(hour, minute)
        except ValueError:
            logger.error(f"Неверный формат времени переобучения: {self.schedule_time}. Используем 02:00")
            schedule_time = dt_time(2, 0)

        # Настраиваем расписание
        schedule.every(self.interval_hours).hours.do(self._scheduled_training_job)
        schedule.every().day.at(schedule_time.strftime("%H:%M")).do(self._scheduled_training_job)

        logger.info(f"Расписание настроено: переобучение каждые {self.interval_hours} ч + ежедневное в {self.schedule_time}")

    def _scheduled_training_job(self):
        """Задача планировщика для запуска обучения."""
        logger.info("=" * 80)
        logger.info(f"🕐 [{datetime.now().strftime('%H:%M:%S')}] Запланированное переобучение моделей...")
        logger.info(f"   training_in_progress={self.training_in_progress}")
        logger.info(f"   last_training_time={self.last_training_time}")
        logger.info("=" * 80)

        if self.training_in_progress:
            logger.warning("⚠️ Обучение уже запущено, пропускаем запланированный запуск")
            return

        # Запускаем обучение в отдельном потоке
        self.training_in_progress = True
        self.last_training_time = datetime.now()

        training_thread = threading.Thread(target=self._execute_training, name="ScheduledTraining", daemon=True)
        training_thread.start()
        logger.info("✅ Поток обучения запущен")

    def _scheduler_loop(self):
        """Основной цикл планировщика."""
        logger.info("Цикл планировщика запущен")

        while not self.stop_event.is_set():
            try:
                # Проверяем расписание
                schedule.run_pending()

                # Проверяем, не пора ли обучать по интервалу
                if self._should_train_by_interval():
                    self._run_training_job()

                # Спим 60 секунд
                self.stop_event.wait(60)

            except Exception as e:
                logger.error(f"Ошибка в цикле планировщика: {e}", exc_info=True)
                self.stop_event.wait(60)

        logger.info("Цикл планировщика завершён")

    def _should_train_by_interval(self) -> bool:
        """Проверяет, нужно ли запускать обучение по интервалу."""
        if self.training_in_progress:
            return False

        if self.last_training_time is None:
            return False  # Первый запуск только по расписанию

        hours_since_last = (datetime.now() - self.last_training_time).total_seconds() / 3600
        return hours_since_last >= self.interval_hours

    def _run_training_job(self):
        """Запускает задачу обучения в отдельном потоке."""
        if self.training_in_progress:
            logger.warning("Обучение уже выполняется, пропускаем запуск")
            return

        if not self._is_good_time_to_train():
            logger.info("Сейчас не лучшее время для обучения (активная торговая сессия)")
            return

        logger.info("=" * 80)
        logger.info("ЗАПУСК АВТОМАТИЧЕСКОГО ПЕРЕОБУЧЕНИЯ МОДЕЛЕЙ")
        logger.info(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 80)

        self.training_in_progress = True
        self.last_training_time = datetime.now()

        # Запускаем обучение в отдельном потоке, чтобы не блокировать планировщик
        training_thread = threading.Thread(target=self._execute_training, name="AutoTraining", daemon=True)
        training_thread.start()

    def _execute_training(self):
        """Выполняет обучение моделей."""
        try:
            logger.info("=" * 80)
            logger.info("🎓 НАЧАЛО ОБУЧЕНИЯ МОДЕЛЕЙ")
            logger.info(f"   Параметры: max_symbols={self.max_symbols}, max_workers={self.max_workers}")
            logger.info(f"   Время начала: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("=" * 80)

            logger.info(f"📢 Вызов training_callback(max_symbols={self.max_symbols}, max_workers={self.max_workers})...")

            # Вызываем callback функцию обучения
            self.training_callback(max_symbols=self.max_symbols, max_workers=self.max_workers)

            logger.info("=" * 80)
            logger.info("✅ АВТОМАТИЧЕСКОЕ ПЕРЕОБУЧЕНИЕ ЗАВЕРШЕНО УСПЕШНО")
            logger.info(f"   Время завершения: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("=" * 80)

        except Exception as e:
            logger.error(f"❌ Ошибка при автоматическом переобучении: {e}", exc_info=True)
        finally:
            self.training_in_progress = False
            logger.info("📢 training_in_progress = False")

    def _is_good_time_to_train(self) -> bool:
        """
        Проверяет, подходящее ли время для обучения.

        ВАЖНО: Для демо-счета (MT5_SERVER содержит 'Demo') обучение разрешено 24/7,
        так как нет риска реальных финансовых потерь.

        Для реального счета:
        Желательно обучать, когда основные рынки закрыты.
        """
        now = datetime.now()
        current_time = now.time()
        weekday = now.weekday()  # 0=Monday, 6=Sunday

        # === ИЗМЕНЕНИЕ: Проверка типа счета ===
        # Для демо-счета разрешаем обучение в любое время
        if self.config and hasattr(self.config, "MT5_SERVER"):
            server_name = self.config.MT5_SERVER or ""
            if "demo" in server_name.lower() or "Demo" in server_name:
                logger.debug(f"[TrainingScheduler] Демо-счет ({server_name}): обучение разрешено 24/7")
                return True

        # Для реального счета - проверка времени
        # Выходные - хорошее время для обучения
        if weekday in [5, 6]:  # Saturday, Sunday
            return True

        # В будние дни проверяем время
        # Forex торгуется 24/5, но есть "тихие часы"
        # Лучшее время: 00:00 - 06:00 по местному времени
        quiet_hours_start = dt_time(0, 0)
        quiet_hours_end = dt_time(6, 0)

        if quiet_hours_start <= current_time <= quiet_hours_end:
            return True

        # Также хорошо после закрытия американской сессии
        # (примерно 22:00 - 00:00 по Москве/GMT+3)
        late_hours_start = dt_time(22, 0)
        late_hours_end = dt_time(23, 59)

        if late_hours_start <= current_time <= late_hours_end:
            return True

        # Для реального счета в активную сессию - блокировка
        logger.debug(f"[TrainingScheduler] Реальный счет: обучение заблокировано до тихих часов")
        return False

    def trigger_manual_training(self):
        """Запускает обучение вручную (из GUI)."""
        logger.info("Ручной запуск переобучения моделей...")
        self._run_training_job()

    def update_settings(self, config) -> bool:
        """
        Обновляет настройки планировщика НА ЛЕТУ без перезагрузки.

        Args:
            config: Новая конфигурация (объект Settings или dict)

        Returns:
            True если настройки применены
        """
        logger.info("🔄 [TrainingScheduler] Обновление настроек...")

        try:
            # Читаем из вложенного объекта auto_retraining
            auto_retrain_config = getattr(config, "auto_retraining", None)
            if auto_retrain_config:
                if isinstance(auto_retrain_config, dict):
                    new_enabled = auto_retrain_config.get("enabled", True)
                    new_schedule_time = auto_retrain_config.get("schedule_time", "02:00")
                    new_interval_hours = auto_retrain_config.get("interval_hours", 0.5)
                    new_max_symbols = auto_retrain_config.get("max_symbols", 30)
                    new_max_workers = auto_retrain_config.get("max_workers", 3)
                else:
                    # Pydantic модель
                    new_enabled = getattr(auto_retrain_config, "enabled", True)
                    new_schedule_time = getattr(auto_retrain_config, "schedule_time", "02:00")
                    new_interval_hours = getattr(auto_retrain_config, "interval_hours", 0.5)
                    new_max_symbols = getattr(auto_retrain_config, "max_symbols", 30)
                    new_max_workers = getattr(auto_retrain_config, "max_workers", 3)
            else:
                # Fallback на старые атрибуты
                new_enabled = getattr(config, "AUTO_RETRAIN_ENABLED", True)
                new_schedule_time = getattr(config, "AUTO_RETRAIN_TIME", "02:00")
                new_interval_hours = getattr(config, "AUTO_RETRAIN_INTERVAL_HOURS", 0.5)
                new_max_symbols = getattr(config, "AUTO_RETRAIN_MAX_SYMBOLS", 30)
                new_max_workers = getattr(config, "AUTO_RETRAIN_MAX_WORKERS", 3)

            # Проверяем что изменилось
            changes = []
            if self.enabled != new_enabled:
                changes.append(f"enabled: {self.enabled} → {new_enabled}")
            if self.interval_hours != new_interval_hours:
                changes.append(f"interval_hours: {self.interval_hours} → {new_interval_hours}")
            if self.schedule_time != new_schedule_time:
                changes.append(f"schedule_time: {self.schedule_time} → {new_schedule_time}")
            if self.max_symbols != new_max_symbols:
                changes.append(f"max_symbols: {self.max_symbols} → {new_max_symbols}")
            if self.max_workers != new_max_workers:
                changes.append(f"max_workers: {self.max_workers} → {new_max_workers}")

            if not changes:
                logger.info("[TrainingScheduler] Настройки не изменились")
                return False

            logger.info(f"📝 [TrainingScheduler] Изменения: {', '.join(changes)}")

            # Применяем новые настройки
            self.enabled = new_enabled
            self.schedule_time = new_schedule_time
            self.interval_hours = new_interval_hours
            self.max_symbols = new_max_symbols
            self.max_workers = new_max_workers

            # Перенастраиваем расписание
            if self.is_running:
                self._setup_schedule()
                logger.info("✅ [TrainingScheduler] Расписание перенастроено")

            logger.info(
                f"✅ [TrainingScheduler] Настройки обновлены: "
                f"enabled={self.enabled}, interval={self.interval_hours}ч, "
                f"schedule={self.schedule_time}, max_sym={self.max_symbols}, "
                f"workers={self.max_workers}"
            )

            return True

        except Exception as e:
            logger.error(f"❌ [TrainingScheduler] Ошибка обновления настроек: {e}", exc_info=True)
            return False

    def get_status(self) -> dict:
        """Возвращает статус планировщика."""
        next_run = schedule.next_run() if schedule.jobs else None

        return {
            "enabled": self.enabled,
            "is_running": self.is_running,
            "training_in_progress": self.training_in_progress,
            "last_training_time": self.last_training_time.isoformat() if self.last_training_time else None,
            "next_scheduled_run": next_run.isoformat() if next_run else None,
            "schedule_time": self.schedule_time,
            "interval_hours": self.interval_hours,
            "max_symbols": self.max_symbols,
            "max_workers": self.max_workers,
        }
