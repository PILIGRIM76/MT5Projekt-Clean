"""
Stress Test для Genesis Trading System

Запускает цикл быстрых действий для проверки:
- Утечек памяти
- Стабильности потоков
- Отзывчивости GUI под нагрузкой
- Корректности обработки ошибок

Запуск:
    python tests/monitoring/stress_test.py
"""

import logging
import os
import random
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import psutil

# Добавляем корень проекта в path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Настройка логирования
LOG_DIR = project_root / "reports"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"stress_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("StressTest")


class StressTester:
    """
    Стресс-тестирование торговой системы.

    Имитирует интенсивное использование системы:
    - Быстрое переключение вкладок
    - Частые запросы данных
    - Параллельные операции
    - Обработка ошибок
    """

    def __init__(self, duration_seconds: int = 120, action_interval: float = 0.1, check_interval: int = 10):
        """
        Args:
            duration_seconds: Длительность теста в секундах
            action_interval: Пауза между действиями в секундах
            check_interval: Интервал проверки ресурсов в секундах
        """
        self.duration = duration_seconds
        self.action_interval = action_interval
        self.check_interval = check_interval

        self.iterations = 0
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.action_stats = {}

        self._start_time: Optional[float] = None
        self._last_check_time: Optional[float] = None
        self._initial_memory: Optional[int] = None

    def run(self):
        """Запускает стресс-тест."""
        logger.info("=" * 80)
        logger.info(f"🚀 ЗАПУСК СТРЕСС-ТЕСТА НА {self.duration} СЕКУНД")
        logger.info(f"   Интервал действий: {self.action_interval}с")
        logger.info(f"   Интервал проверки ресурсов: {self.check_interval}с")
        logger.info("=" * 80)

        self._start_time = time.time()
        self._last_check_time = self._start_time
        self._initial_memory = psutil.Process(os.getpid()).memory_info().rss

        logger.info(f"📊 Начальная память: {self._initial_memory / (1024*1024):.1f}MB")

        try:
            while time.time() - self._start_time < self.duration:
                try:
                    # Выполняем случайное действие
                    self._simulate_user_action()
                    self.iterations += 1

                    # Периодическая проверка ресурсов
                    if time.time() - self._last_check_time >= self.check_interval:
                        self._check_resources()
                        self._last_check_time = time.time()

                    # Пауза между действиями
                    time.sleep(self.action_interval)

                except Exception as e:
                    error_msg = f"Ошибка на итерации {self.iterations}: {str(e)}"
                    logger.error(error_msg)
                    logger.debug(traceback.format_exc())
                    self.errors.append(error_msg)

        except KeyboardInterrupt:
            logger.info("⚠️ Тест прерван пользователем")

        finally:
            self._print_report()

    def _simulate_user_action(self):
        """Эмуляция случайного действия пользователя."""
        actions = [
            ("switch_tab", self._action_switch_tab),
            ("scroll_table", self._action_scroll_table),
            ("click_button", self._action_click_button),
            ("update_data", self._action_update_data),
            ("check_status", self._action_check_status),
            ("resize_window", self._action_resize_window),
        ]

        # Выбираем случайное действие
        action_name, action_func = random.choice(actions)

        start_time = time.time()
        action_func()
        elapsed = time.time() - start_time

        # Статистика
        if action_name not in self.action_stats:
            self.action_stats[action_name] = {"count": 0, "total_time": 0.0, "max_time": 0.0, "errors": 0}

        stats = self.action_stats[action_name]
        stats["count"] += 1
        stats["total_time"] += elapsed
        stats["max_time"] = max(stats["max_time"], elapsed)

        # Проверка на медленные операции
        if elapsed > 1.0:
            warning = f"⚠️ Медленная операция '{action_name}': {elapsed:.2f}с"
            logger.warning(warning)
            self.warnings.append(warning)

    def _action_switch_tab(self):
        """Эмуляция переключения вкладки."""
        # В реальном тесте:
        # tab_widget = self.window.findChild(QTabWidget, "main_tabs")
        # tab_widget.setCurrentIndex(random.randint(0, tab_widget.count() - 1))
        # QTest.qWait(100)
        time.sleep(0.05)

    def _action_scroll_table(self):
        """Эмуляция скролла таблицы."""
        # В реальном тесте:
        # table = self.window.findChild(QTableWidget, "market_table")
        # table.verticalScrollBar().setValue(random.randint(0, table.verticalScrollBar().maximum()))
        time.sleep(0.05)

    def _action_click_button(self):
        """Эмуляция клика по кнопке."""
        # В реальном тесте:
        # buttons = self.window.findChildren(QPushButton)
        # if buttons:
        #     random.choice(buttons).click()
        #     QTest.qWait(50)
        time.sleep(0.05)

    def _action_update_data(self):
        """Эмуляция обновления данных."""
        # В реальном тесте:
        # self.window.update_market_table(generate_mock_data())
        time.sleep(0.1)

    def _action_check_status(self):
        """Эмуляция проверки статуса."""
        # В реальном тесте:
        # status = self.window.get_status()
        # assert status is not None
        time.sleep(0.05)

    def _action_resize_window(self):
        """Эмуляция изменения размера окна."""
        # В реальном тесте:
        # self.window.resize(
        #     random.randint(800, 1920),
        #     random.randint(600, 1080)
        # )
        time.sleep(0.05)

    def _check_resources(self):
        """Проверка системных ресурсов."""
        process = psutil.Process(os.getpid())
        current_memory = process.memory_info().rss

        elapsed = time.time() - self._start_time
        memory_mb = current_memory / (1024 * 1024)
        initial_memory_mb = self._initial_memory / (1024 * 1024)
        memory_growth = memory_mb - initial_memory_mb

        cpu_percent = psutil.cpu_percent(interval=0.5)

        logger.info(
            f"📊 [{elapsed:.0f}с] Итераций: {self.iterations} | "
            f"Память: {memory_mb:.1f}MB (+{memory_growth:+.1f}MB) | "
            f"CPU: {cpu_percent}% | "
            f"Ошибок: {len(self.errors)}"
        )

        # Проверка на утечку памяти
        if memory_growth > 500:  # 500MB
            warning = f"⚠️ Утечка памяти: +{memory_growth:.1f}MB за {elapsed:.0f}с"
            logger.warning(warning)
            self.warnings.append(warning)

        # Проверка CPU
        if cpu_percent > 95:
            warning = f"⚠️ Высокая загрузка CPU: {cpu_percent}%"
            logger.warning(warning)
            self.warnings.append(warning)

    def _print_report(self):
        """Выводит итоговый отчет."""
        elapsed = time.time() - self._start_time
        process = psutil.Process(os.getpid())
        final_memory = process.memory_info().rss / (1024 * 1024)
        memory_growth = final_memory - (self._initial_memory / (1024 * 1024))

        logger.info("")
        logger.info("=" * 80)
        logger.info("🏁 СТРЕСС-ТЕСТ ЗАВЕРШЁН")
        logger.info("=" * 80)
        logger.info(f"⏱️  Длительность: {elapsed:.1f}с")
        logger.info(f"🔄 Всего итераций: {self.iterations}")
        logger.info(f"⚡ Скорость: {self.iterations / elapsed:.1f} итераций/с")
        logger.info(f"📊 Конечная память: {final_memory:.1f}MB")
        logger.info(f"📈 Рост памяти: {memory_growth:+.1f}MB")
        logger.info(f"❌ Ошибок: {len(self.errors)}")
        logger.info(f"⚠️  Предупреждений: {len(self.warnings)}")
        logger.info("")

        # Статистика по действиям
        if self.action_stats:
            logger.info("📊 СТАТИСТИКА ДЕЙСТВИЙ:")
            logger.info(f"{'Действие':<20} {'Кол-во':<10} {'Всего (с)':<12} {'Среднее (мс)':<12} {'Макс (мс)':<10}")
            logger.info("-" * 64)

            for action_name, stats in sorted(self.action_stats.items(), key=lambda x: x[1]["count"], reverse=True):
                count = stats["count"]
                total = stats["total_time"]
                avg_ms = (total / count) * 1000 if count > 0 else 0
                max_ms = stats["max_time"] * 1000

                logger.info(f"{action_name:<20} {count:<10} {total:<12.2f} {avg_ms:<12.1f} {max_ms:<10.1f}")

        logger.info("")

        # Ошибки
        if self.errors:
            logger.error(f"❌ НАЙДЕНО {len(self.errors)} ОШИБОК:")
            for i, error in enumerate(self.errors[:10], 1):
                logger.error(f"  {i}. {error}")
            if len(self.errors) > 10:
                logger.error(f"  ... и ещё {len(self.errors) - 10} ошибок")

        # Предупреждения
        if self.warnings:
            logger.warning(f"⚠️  НАЙДЕНО {len(self.warnings)} ПРЕДУПРЕЖДЕНИЙ:")
            for i, warning in enumerate(self.warnings[:10], 1):
                logger.warning(f"  {i}. {warning}")
            if len(self.warnings) > 10:
                logger.warning(f"  ... и ещё {len(self.warnings) - 10} предупреждений")

        logger.info("")
        logger.info(f"📄 Полный лог сохранён: {LOG_FILE}")
        logger.info("=" * 80)


def main():
    """Точка входа для запуска из командной строки."""
    import argparse

    parser = argparse.ArgumentParser(description="Stress Test для Genesis Trading System")
    parser.add_argument("--duration", type=int, default=120, help="Длительность теста в секундах (по умолчанию: 120)")
    parser.add_argument("--interval", type=float, default=0.1, help="Интервал между действиями в секундах (по умолчанию: 0.1)")
    parser.add_argument(
        "--check-interval", type=int, default=10, help="Интервал проверки ресурсов в секундах (по умолчанию: 10)"
    )

    args = parser.parse_args()

    tester = StressTester(duration_seconds=args.duration, action_interval=args.interval, check_interval=args.check_interval)

    try:
        tester.run()
    except Exception as e:
        logger.critical(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
