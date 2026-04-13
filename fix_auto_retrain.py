"""Добавить авто-запуск переобучения в trading_system.py"""

import sys

file_path = r"src\core\trading_system.py"

print("Читаю файл...")
with open(file_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

print(f"Всего строк: {len(lines)}")

# Находим строку с update_interval = 10
found_line = None
for i, line in enumerate(lines):
    if "update_interval = 10" in line and "FIX" in line:
        found_line = i
        print(f"Найдена строка {i}: {line.strip()}")
        break

if found_line is None:
    print("❌ Не нашёл строку с update_interval = 10")
    sys.exit(1)

# 1. Добавляем флаг после update_interval
insert_flag = """
        # Флаг чтобы не запускать переобучение повторно
        retrain_already_triggered = False
"""
lines.insert(found_line + 1, insert_flag)
print(f"✅ Добавлен флаг retrain_already_triggered")

# 2. Находим строку где отправляем данные в GUI
# Ищем: self._send_model_accuracy_to_gui()
found_gui = None
for i in range(found_line, len(lines)):
    if "self._send_model_accuracy_to_gui()" in lines[i]:
        found_gui = i
        print(f"Найдена строка GUI: {i}: {lines[i].strip()}")
        break

if found_gui is None:
    print("❌ Не нашёл строку с _send_model_accuracy_to_gui")
    sys.exit(1)

# 3. Вставляем код авто-запуска после этой строки
auto_retrain_code = """
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
"""

# Находим следующую строку "# Ждём следующий интервал"
found_wait = None
for i in range(found_gui, min(found_gui + 10, len(lines))):
    if "# Ждём следующий интервал" in lines[i]:
        found_wait = i
        print(f"Найдена строка wait: {i}: {lines[i].strip()}")
        break

if found_wait is None:
    print("❌ Не нашёл строку '# Ждём следующий интервал'")
    sys.exit(1)

# Вставляем код авто-запуска перед "# Ждём следующий интервал"
lines.insert(found_wait, auto_retrain_code)
print(f"✅ Добавлен код авто-запуска переобучения")

# Сохраняем файл
print("Сохраняю файл...")
with open(file_path, "w", encoding="utf-8") as f:
    f.writelines(lines)

print("✅ Файл обновлён!")
print("\nТеперь проверьте:")
print('  findstr /C:"АВТО-ЗАПУСК" src\\core\\trading_system.py')
