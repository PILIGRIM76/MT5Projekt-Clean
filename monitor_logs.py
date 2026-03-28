# monitor_logs.py
"""
Монитор логов Genesis Trading System.

Использование:
    python monitor_logs.py --hours 4
    
Скрипт будет отслеживать логи и выводить:
- Ошибки (ERROR, CRITICAL)
- Предупреждения (WARNING)
- Статистику по компонентам
- Итоговый отчёт
"""

import argparse
import time
import os
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import json


class LogMonitor:
    """Монитор логов Genesis Trading System."""
    
    def __init__(self, log_file: str, hours: int = 4):
        """
        Инициализация монитора.
        
        Args:
            log_file: Путь к файлу логов
            hours: Длительность мониторинга в часах
        """
        self.log_file = Path(log_file)
        self.hours = hours
        self.start_time = datetime.now()
        self.end_time = self.start_time + timedelta(hours=hours)
        
        # Статистика
        self.stats = {
            'INFO': 0,
            'WARNING': 0,
            'ERROR': 0,
            'CRITICAL': 0,
            'total_lines': 0
        }
        
        # Компоненты
        self.components = defaultdict(lambda: {'errors': 0, 'warnings': 0})
        
        # Ошибки для отчёта
        self.errors_list = []
        self.warnings_list = []
        
        # Позиция в файле
        self.last_position = 0
        
        print(f"🔍 Монитор логов запущен")
        print(f"📁 Файл логов: {self.log_file}")
        print(f"⏰ Длительность: {hours} ч")
        print(f"🕐 Начало: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🕐 Окончание: {self.end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
    
    def parse_log_line(self, line: str) -> dict:
        """
        Разбирает строку лога.
        
        Args:
            line: Строка лога
            
        Returns:
            Словарь с компонентами лога
        """
        # Формат: 2026-03-28 10:00:00 - LEVEL - [Component] Message
        try:
            parts = line.strip().split(' - ', 3)
            if len(parts) >= 3:
                timestamp = parts[0]
                level = parts[1]
                component = parts[2].strip('[]') if parts[2].startswith('[') else parts[2]
                message = parts[3] if len(parts) > 3 else ''
                
                return {
                    'timestamp': timestamp,
                    'level': level,
                    'component': component,
                    'message': message
                }
        except Exception:
            pass
        
        return None
    
    def process_line(self, line: str):
        """
        Обрабатывает строку лога.
        
        Args:
            line: Строка лога
        """
        parsed = self.parse_log_line(line)
        if not parsed:
            return
        
        level = parsed['level']
        component = parsed['component']
        message = parsed['message']
        
        # Обновляем статистику
        self.stats['total_lines'] += 1
        if level in self.stats:
            self.stats[level] += 1
        
        # Обновляем компонент
        if level == 'ERROR' or level == 'CRITICAL':
            self.components[component]['errors'] += 1
            self.errors_list.append({
                'timestamp': parsed['timestamp'],
                'component': component,
                'message': message
            })
        elif level == 'WARNING':
            self.components[component]['warnings'] += 1
            self.warnings_list.append({
                'timestamp': parsed['timestamp'],
                'component': component,
                'message': message
            })
        
        # Выводим ошибки и критические сообщения
        if level in ['ERROR', 'CRITICAL']:
            print(f"❌ [{parsed['timestamp']}] {component}: {message}")
        elif level == 'WARNING':
            print(f"⚠️  [{parsed['timestamp']}] {component}: {message}")
    
    def read_new_lines(self):
        """Читает новые строки из файла логов."""
        try:
            if not self.log_file.exists():
                return
            
            with open(self.log_file, 'r', encoding='utf-8') as f:
                # Переходим к последней позиции
                f.seek(self.last_position)
                
                # Читаем новые строки
                for line in f:
                    if line.strip():
                        self.process_line(line)
                
                # Обновляем позицию
                self.last_position = f.tell()
                
        except Exception as e:
            print(f"Ошибка чтения логов: {e}")
    
    def print_intermediate_report(self):
        """Выводит промежуточный отчёт."""
        elapsed = datetime.now() - self.start_time
        elapsed_hours = elapsed.total_seconds() / 3600
        
        print("\n" + "=" * 60)
        print(f"📊 ПРОМЕЖУТОЧНЫЙ ОТЧЁТ ({elapsed_hours:.1f} ч)")
        print("=" * 60)
        print(f"Всего строк: {self.stats['total_lines']}")
        print(f"INFO: {self.stats['INFO']}")
        print(f"WARNING: {self.stats['WARNING']}")
        print(f"ERROR: {self.stats['ERROR']}")
        print(f"CRITICAL: {self.stats['CRITICAL']}")
        
        if self.components:
            print("\nКомпоненты с ошибками:")
            for comp, stats in self.components.items():
                if stats['errors'] > 0:
                    print(f"  {comp}: {stats['errors']} ошибок")
        
        print("=" * 60 + "\n")
    
    def print_final_report(self):
        """Выводит итоговый отчёт."""
        elapsed = datetime.now() - self.start_time
        elapsed_hours = elapsed.total_seconds() / 3600
        
        print("\n" + "=" * 70)
        print(" " * 20 + "📊 ИТОГОВЫЙ ОТЧЁТ 📊")
        print("=" * 70)
        print(f"Длительность мониторинга: {elapsed_hours:.2f} ч")
        print(f"Начало: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Окончание: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        
        print("\n📈 СТАТИСТИКА:")
        print(f"  Всего строк логов: {self.stats['total_lines']:,}")
        print(f"  INFO:     {self.stats['INFO']:>8,}")
        print(f"  WARNING:  {self.stats['WARNING']:>8,}")
        print(f"  ERROR:    {self.stats['ERROR']:>8,}")
        print(f"  CRITICAL: {self.stats['CRITICAL']:>8,}")
        
        # Ошибки в час
        if elapsed_hours > 0:
            errors_per_hour = self.stats['ERROR'] / elapsed_hours
            critical_per_hour = self.stats['CRITICAL'] / elapsed_hours
            print(f"\n  Ошибок в час: {errors_per_hour:.2f}")
            print(f"  Критических в час: {critical_per_hour:.2f}")
        
        # Компоненты с ошибками
        if self.components:
            print("\n🔧 КОМПОНЕНТЫ С ОШИБКАМИ:")
            sorted_components = sorted(
                self.components.items(),
                key=lambda x: x[1]['errors'],
                reverse=True
            )
            for comp, stats in sorted_components[:10]:  # Топ 10
                if stats['errors'] > 0:
                    print(f"  {comp}:")
                    print(f"    Ошибки: {stats['errors']}")
                    print(f"    Предупреждения: {stats['warnings']}")
        
        # Последние ошибки
        if self.errors_list:
            print(f"\n❌ ПОСЛЕДНИЕ ОШИБКИ (последние 10):")
            for error in self.errors_list[-10:]:
                print(f"  [{error['timestamp']}] {error['component']}")
                print(f"    {error['message'][:100]}...")
        
        # Предупреждения
        if self.warnings_list:
            print(f"\n⚠️  ПОСЛЕДНИЕ ПРЕДУПРЕЖДЕНИЯ (последние 10):")
            for warning in self.warnings_list[-10:]:
                print(f"  [{warning['timestamp']}] {warning['component']}")
                print(f"    {warning['message'][:100]}...")
        
        # Рекомендации
        print("\n💡 РЕКОМЕНДАЦИИ:")
        
        if self.stats['CRITICAL'] > 0:
            print("  ❗ КРИТИЧЕСКИЕ ОШИБКИ! Требуется немедленное вмешательство!")
        
        if self.stats['ERROR'] > 10:
            print(f"  ⚠️  Много ошибок ({self.stats['ERROR']}). Проверьте логи.")
        
        if self.stats['ERROR'] == 0 and self.stats['CRITICAL'] == 0:
            print("  ✅ Ошибок нет! Система работает стабильно.")
        
        # Сохраняем отчёт в файл
        report_file = Path('logs_monitor_report.json')
        report = {
            'monitoring_duration_hours': elapsed_hours,
            'start_time': self.start_time.isoformat(),
            'end_time': datetime.now().isoformat(),
            'statistics': self.stats,
            'components': dict(self.components),
            'errors_count': len(self.errors_list),
            'warnings_count': len(self.warnings_list),
            'last_errors': self.errors_list[-10:],
            'last_warnings': self.warnings_list[-10:]
        }
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 Полный отчёт сохранён в {report_file}")
        print("=" * 70)
    
    def run(self):
        """Запускает мониторинг."""
        print("\n🔄 Мониторинг запущен...\n")
        
        try:
            while datetime.now() < self.end_time:
                # Читаем новые строки
                self.read_new_lines()
                
                # Каждые 30 минут выводим промежуточный отчёт
                elapsed = datetime.now() - self.start_time
                if elapsed.total_seconds() % 1800 < 60:  # Каждые 30 мин
                    self.print_intermediate_report()
                
                # Пауза 1 секунда
                time.sleep(1)
            
            # Финальный отчёт
            self.read_new_lines()  # Последние строки
            self.print_final_report()
            
        except KeyboardInterrupt:
            print("\n\n⚠️  Мониторинг остановлен пользователем")
            self.print_final_report()


def main():
    parser = argparse.ArgumentParser(
        description='Монитор логов Genesis Trading System'
    )
    parser.add_argument(
        '--hours',
        type=int,
        default=4,
        help='Длительность мониторинга в часах (по умолчанию 4)'
    )
    parser.add_argument(
        '--log-file',
        type=str,
        default='logs/genesis.log',
        help='Путь к файлу логов (по умолчанию logs/genesis.log)'
    )
    parser.add_argument(
        '--errors-only',
        action='store_true',
        help='Показывать только ошибки (genesis_errors.log)'
    )
    
    args = parser.parse_args()
    
    # Определяем путь к файлу логов
    if args.errors_only:
        log_file = Path('logs/genesis_errors.log')
    else:
        log_file = Path(args.log_file)
    
    # Проверяем существование файла логов
    if not log_file.exists():
        print(f"❌ Файл логов не найден: {log_file}")
        print("\n📁 Доступные логи:")
        
        logs_dir = Path('logs')
        if logs_dir.exists():
            for log in logs_dir.glob('*.log'):
                print(f"  - {log}")
        else:
            print("  Папка logs/ не найдена")
        
        print("\n💡 Запустите Genesis Trading System для создания логов:")
        print("   python main_pyside.py")
        return
    
    # Запускаем монитор
    monitor = LogMonitor(log_file, args.hours)
    monitor.run()


if __name__ == '__main__':
    main()
