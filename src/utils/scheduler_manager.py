# src/utils/scheduler_manager.py

import subprocess
import sys
import os
import logging
import xml.etree.ElementTree as ET

from typing import Optional

logger = logging.getLogger(__name__)


class SchedulerManager:
    """
    Управляет созданием и удалением задач в Планировщике заданий Windows.
    Версия 2.0: Поддерживает разные триггеры.
    """

    def __init__(self):
        self.is_windows = sys.platform.startswith('win')

    def get_task_trigger_time(self, task_name: str) -> Optional[str]:
        """Читает XML-определение задачи и извлекает из него время запуска."""
        if not self.is_windows:
            return None

        # Запрашиваем определение задачи в формате XML
        success, xml_output = self._run_command(["schtasks", "/Query", "/TN", task_name, "/XML", "ONE"])
        if not success:
            return None

        try:
            # Убираем BOM (Byte Order Mark), который может присутствовать в выводе Windows
            if xml_output.startswith('\ufeff'):
                xml_output = xml_output[1:]

            root = ET.fromstring(xml_output)
            # Ищем время в элементе StartBoundary
            # Путь может отличаться в зависимости от локализации, но этот самый частый
            namespace = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"
            start_boundary = root.find(f".//{namespace}StartBoundary")

            if start_boundary is not None and start_boundary.text:
                # Извлекаем только время из строки вида "2025-01-01T03:00:00"
                time_str = start_boundary.text.split('T')[1]
                return time_str[:5]  # Возвращаем "HH:mm"
        except Exception as e:
            logger.error(f"Ошибка парсинга XML для задачи '{task_name}': {e}")

        return None

    def _run_command(self, command: list) -> tuple[bool, str]:
        if not self.is_windows:
            return False, "Планировщик заданий доступен только в Windows."
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            result = subprocess.run(
                command, capture_output=True, text=True, check=False,
                startupinfo=startupinfo, encoding='cp866', errors='replace'
            )
            if result.returncode == 0:
                return True, result.stdout
            else:
                if "/Query" in command and "/TN" in command and result.returncode == 1:
                    return False, "Задача не найдена."
                logger.error(f"Ошибка выполнения schtasks: {result.stderr}")
                return False, result.stderr
        except Exception as e:
            logger.error(f"Критическая ошибка при вызове schtasks: {e}")
            return False, str(e)

    def task_exists(self, task_name: str) -> bool:
        """Проверяет, существует ли задача с указанным именем."""
        success, _ = self._run_command(["schtasks", "/Query", "/TN", task_name])
        return success

    def create_task(self, task_name: str, script_name: str, trigger_type: str,
                    trigger_time: str = None, trigger_day: str = "SAT") -> tuple[bool, str]:
        """Создает задачу с разными типами триггеров."""
        # Определяем базовую директорию проекта
        # Если запускается из scripts/, то родительская директория
        script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        
        # Проверяем, является ли script_name полным путём
        if os.path.isabs(script_name):
            script_path = script_name
        else:
            # Скрипты планировщика находятся в папке scripts/
            scripts_dir = os.path.join(script_dir, 'scripts')
            if not os.path.exists(scripts_dir):
                # Если scripts/ не найдена, возможно мы уже в ней или в src/
                # Пробуем найти относительно корня проекта
                parent_dir = os.path.dirname(script_dir)
                scripts_dir = os.path.join(parent_dir, 'scripts')
            
            script_path = os.path.join(scripts_dir, script_name)

        if not os.path.exists(script_path):
            return False, f"Не найден скрипт: {script_path}"

        trigger_xml = ""
        if trigger_type.upper() == 'ONSTART':
            trigger_xml = "<BootTrigger><Enabled>true</Enabled></BootTrigger>"


        elif trigger_type.upper() in ['DAILY', 'WEEKLY']:

            if not trigger_time:
                return False, "Для триггеров DAILY и WEEKLY необходимо указать время (trigger_time)."

            if trigger_type.upper() == 'DAILY':

                trigger_xml = f"""<CalendarTrigger>

            <StartBoundary>2025-01-01T{trigger_time}:00</StartBoundary>

            <Enabled>true</Enabled>

            <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>

          </CalendarTrigger>"""


            elif trigger_type.upper() == 'WEEKLY':

                day_map = {

                    "MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday",

                    "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday", "SUN": "Sunday"

                }

                full_day_name = day_map.get(trigger_day.upper(), "Saturday")

                trigger_xml = f"""<CalendarTrigger>

            <StartBoundary>2025-01-01T{trigger_time}:00</StartBoundary>

            <Enabled>true</Enabled>

            <ScheduleByWeek><DaysOfWeek><{full_day_name} /></DaysOfWeek></ScheduleByWeek>

          </CalendarTrigger>"""
        else:
            return False, f"Неизвестный тип триггера: {trigger_type}"

        xml_content = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>{trigger_xml}</Triggers>
  <Principals><Principal id="Author"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>false</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable><Enabled>true</Enabled><Hidden>false</Hidden><RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT2H</ExecutionTimeLimit><Priority>7</Priority></Settings>
  <Actions Context="Author"><Exec><Command>"{script_path}"</Command><WorkingDirectory>"{script_dir}"</WorkingDirectory></Exec></Actions>
</Task>"""

        temp_xml_path = os.path.join(script_dir, f"{task_name}_task.xml")
        try:
            with open(temp_xml_path, "w", encoding="utf-16") as f:
                f.write(xml_content)
        except Exception as e:
            return False, f"Не удалось создать временный XML-файл: {e}"

        command = ["schtasks", "/Create", "/TN", task_name, "/XML", temp_xml_path, "/F"]
        success, message = self._run_command(command)

        if os.path.exists(temp_xml_path):
            os.remove(temp_xml_path)

        if success:
            return True, f"Задача '{task_name}' успешно создана."
        else:
            if "отказано в доступе" in message.lower():
                return False, "Отказано в доступе. Запустите программу от имени Администратора."
            return False, f"Не удалось создать задачу '{task_name}': {message}"

    def delete_task(self, task_name: str) -> tuple[bool, str]:
        """Удаляет задачу по имени."""
        command = ["schtasks", "/Delete", "/TN", task_name, "/F"]
        success, message = self._run_command(command)
        if success:
            return True, f"Задача '{task_name}' успешно удалена."
        else:
            if "отказано в доступе" in message.lower():
                return False, "Отказано в доступе. Запустите программу от имени Администратора."
            return False, f"Не удалось удалить задачу '{task_name}': {message}"