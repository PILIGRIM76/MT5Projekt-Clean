"""
Планировщик автоматического переобучения моделей.
Запускает обучение по расписанию в фоновом режиме, когда рынки закрыты.
"""
import logging
import threading
import time
from datetime import datetime, time as dt_time
from typing import Optional, Callable
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
        self.enabled = getattr(config, 'AUTO_RETRAIN_ENABLED', True)
        self.schedule_time = getattr(config, 'AUTO_RETRAIN_TIME', "02:00")  # Время в формате "HH:MM"
        self.max_symbols = getattr(config, 'AUTO_RETRAIN_MAX_SYMBOLS', 30)
        self.max_workers = getattr(config, 'AUTO_RETRAIN_MAX_WORKERS', 3)
        self.interval_hours = getattr(config, 'AUTO_RETRAIN_INTERVAL_HOURS', 24)  # Интервал в часах
        
        logger.info(f"TrainingScheduler инициализирован:")
        logger.info(f"  - Включен: {self.enabled}")
        logger.info(f"  - Время запуска: {self.schedule_time}")
        logger.info(f"  - Макс. символов: {self.max_symbols}")
        logger.info(f"  - Макс. потоков: {self.max_workers}")
        logger.info(f"  - Интервал: каждые {self.interval_hours} часов")
    
    def start(self):
        """Запускает планировщик в отдельном потоке."""
        if not self.enabled:
            logger.info("Автоматическое переобучение отключено в настройках")
            return
        
        if self.is_running:
            logger.warning("Планировщик переобучения уже запущен")
            return
        
        self.stop_event.clear()
        self.is_running = True
        
        # Настройка расписания
        self._setup_schedule()
        
        # Запуск потока планировщика
        self.scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name="TrainingScheduler",
            daemon=True
        )
        self.scheduler_thread.start()
        logger.info("Планировщик автоматического переобучения запущен")
    
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
        
        # Запуск по времени (например, в 02:00)
        schedule.every().day.at(self.schedule_time).do(self._run_training_job)
        
        logger.info(f"Расписание настроено: обучение каждый день в {self.schedule_time}")
    
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
        
        logger.info("="*80)
        logger.info("ЗАПУСК АВТОМАТИЧЕСКОГО ПЕРЕОБУЧЕНИЯ МОДЕЛЕЙ")
        logger.info(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("="*80)
        
        self.training_in_progress = True
        self.last_training_time = datetime.now()
        
        # Запускаем обучение в отдельном потоке, чтобы не блокировать планировщик
        training_thread = threading.Thread(
            target=self._execute_training,
            name="AutoTraining",
            daemon=True
        )
        training_thread.start()
    
    def _execute_training(self):
        """Выполняет обучение моделей."""
        try:
            logger.info(f"Начинаем обучение {self.max_symbols} символов в {self.max_workers} потоков...")
            
            # Вызываем callback функцию обучения
            self.training_callback(
                max_symbols=self.max_symbols,
                max_workers=self.max_workers
            )
            
            logger.info("="*80)
            logger.info("АВТОМАТИЧЕСКОЕ ПЕРЕОБУЧЕНИЕ ЗАВЕРШЕНО УСПЕШНО")
            logger.info(f"Время завершения: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("="*80)
            
        except Exception as e:
            logger.error(f"Ошибка при автоматическом переобучении: {e}", exc_info=True)
        finally:
            self.training_in_progress = False
    
    def _is_good_time_to_train(self) -> bool:
        """
        Проверяет, подходящее ли время для обучения.
        Желательно обучать, когда основные рынки закрыты.
        """
        now = datetime.now()
        current_time = now.time()
        weekday = now.weekday()  # 0=Monday, 6=Sunday
        
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
        
        return False
    
    def trigger_manual_training(self):
        """Запускает обучение вручную (из GUI)."""
        logger.info("Ручной запуск переобучения моделей...")
        self._run_training_job()
    
    def get_status(self) -> dict:
        """Возвращает статус планировщика."""
        next_run = schedule.next_run() if schedule.jobs else None
        
        return {
            'enabled': self.enabled,
            'is_running': self.is_running,
            'training_in_progress': self.training_in_progress,
            'last_training_time': self.last_training_time.isoformat() if self.last_training_time else None,
            'next_scheduled_run': next_run.isoformat() if next_run else None,
            'schedule_time': self.schedule_time,
            'interval_hours': self.interval_hours,
            'max_symbols': self.max_symbols,
            'max_workers': self.max_workers
        }
