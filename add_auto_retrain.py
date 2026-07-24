"""Скрипт для добавления авто-запуска переобучения в trading_system.py"""

file_path = r"src\core\trading_system.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Добавляем флаг retrain_already_triggered
old1 = """        update_interval = 10  # FIX: 10 секунд вместо 300 (5 минут)

        # Первая задержка 5 секунд для быстрого старта"""

new1 = """        update_interval = 10  # FIX: 10 секунд вместо 300 (5 минут)

        # Флаг чтобы не запускать переобучение повторно
        retrain_already_triggered = False

        # Первая задержка 5 секунд для быстрого старта"""

content = content.replace(old1, new1)

# 2. Добавляем авто-запуск переобучения
old2 = """                # Обновляем прогресс переобучения И точность моделей
                if self.bridge:
                    self._send_retrain_progress_to_gui()
                    self._send_model_accuracy_to_gui()

                # Ждём следующий интервал"""

new2 = """                # Обновляем прогресс переобучения И точность моделей
                if self.bridge:
                    self._send_retrain_progress_to_gui()
                    self._send_model_accuracy_to_gui()

                    # АВТО-ЗАПУСК ПЕРЕОБУЧЕНИЯ: Проверяем порог каждые 10 секунд
                    if not retrain_already_triggered and hasattr(self, 'auto_trainer') and self.auto_trainer:
                        try:
                            progress = self.auto_trainer.get_retrain_progress()
                            if progress['can_start_retrain']:
                                logger.info(f"🚀 АВТО-ЗАПУСК: Порог достигнут! {progress['count_needing_retrain']}/{progress['total_symbols']} ({progress['progress_percent']:.1%}) >= {progress['threshold_percent']:.0%}")
                                retrain_already_triggered = True
                                self._auto_retrain_callback(
                                    max_symbols=self.config.auto_retraining.max_symbols,
                                    max_workers=self.config.auto_retraining.max_workers
                                )
                        except Exception as check_error:
                            logger.error(f"Ошибка проверки порога авто-переобучения: {check_error}")

                # Ждём следующий интервал"""

content = content.replace(old2, new2)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("✅ trading_system.py обновлён - добавлен авто-запуск переобучения!")
