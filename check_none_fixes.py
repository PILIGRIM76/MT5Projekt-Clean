#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для проверки исправления ошибок: '<' not supported between NoneType and float
Автор: GitHub Copilot
Дата: 26 марта 2026
"""

import re
import os
from pathlib import Path


class NoneComparisonChecker:
    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.issues_found = []
        self.fixes_verified = []

    def check_file(self, file_path: str, patterns: list) -> dict:
        """Проверяет файл на наличие паттернов"""
        results = {'file': file_path, 'issues': [], 'status': 'OK'}

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')

            for pattern_name, pattern, line_range in patterns:
                for line_num, line in enumerate(lines, 1):
                    if re.search(pattern, line):
                        if line_range is None or line_range[0] <= line_num <= line_range[1]:
                            results['issues'].append({
                                'line': line_num,
                                'pattern': pattern_name,
                                'content': line.strip()
                            })

        except Exception as e:
            results['status'] = f'ERROR: {str(e)}'
            return results

        if results['issues']:
            results['status'] = 'FOUND_ISSUES'
        return results

    def verify_fixes(self):
        """Проверяет все исправления"""
        print("=" * 80)
        print("🔍 ПРОВЕРКА ИСПРАВЛЕНИЯ ОШИБОК: '<' not supported between NoneType и float")
        print("=" * 80)

        # Исправление 1: risk_engine.py
        print(
            "\n✅ ПРОВЕРКА 1: risk_engine.py - Исправление return None → return None, None")
        print("-" * 80)
        risk_engine_path = os.path.join(
            self.workspace_root, 'src/risk/risk_engine.py')
        patterns = [
            ('return_none', r'^\s*return None,\s*None', (380, 385)),
        ]
        result = self.check_file(risk_engine_path, patterns)
        if result['issues']:
            print("✅ НАЙДЕНО: return None, None на строках:")
            for issue in result['issues']:
                print(f"   Строка {issue['line']}: {issue['content']}")
        else:
            print("⚠️  ВНИМАНИЕ: return None, None не найдено на линиях 380, 385")

        # Исправление 2: trade_executor.py - Stop Loss Check
        print("\n✅ ПРОВЕРКА 2: trade_executor.py - Stop Loss проверка (строка 307)")
        print("-" * 80)
        executor_path = os.path.join(
            self.workspace_root, 'src/core/services/trade_executor.py')
        patterns = [
            ('stop_loss_none_check',
             r'if stop_loss_in_price is None or stop_loss_in_price <= 0:', (300, 320)),
        ]
        result = self.check_file(executor_path, patterns)
        if result['issues']:
            print("✅ НАЙДЕНО: Проверка stop_loss_in_price is None на строковых:")
            for issue in result['issues']:
                print(f"   Строка {issue['line']}: {issue['content']}")
        else:
            print("⚠️  ВНИМАНИЕ: Проверка stop_loss_in_price не найдена")

        # Проверка 3: trade_executor.py - TWAP SL Check
        print("\n✅ ПРОВЕРКА 3: trade_executor.py - TWAP SL проверка (строка 225)")
        print("-" * 80)
        patterns = [
            ('sl_distance_none_check',
             r'if sl_distance is None or sl_distance <= 0:', (220, 235)),
        ]
        result = self.check_file(executor_path, patterns)
        if result['issues']:
            print("✅ НАЙДЕНО: Проверка sl_distance is None на строках:")
            for issue in result['issues']:
                print(f"   Строка {issue['line']}: {issue['content']}")
        else:
            print("⚠️  ВНИМАНИЕ: Проверка sl_distance не найдена")

        # Проверка 4: trade_executor.py - Point Check
        print("\n✅ ПРОВЕРКА 4: trade_executor.py - symbol_info.point проверка (строка 410)")
        print("-" * 80)
        patterns = [
            ('point_not_none', r'if symbol_info.point is not None and symbol_info.point > 0:', (405, 415)),
        ]
        result = self.check_file(executor_path, patterns)
        if result['issues']:
            print("✅ НАЙДЕНО: Проверка symbol_info.point is not None на строках:")
            for issue in result['issues']:
                print(f"   Строка {issue['line']}: {issue['content']}")
        else:
            print("⚠️  ВНИМАНИЕ: Проверка point не найдена")

        # Проверка 5: trade_executor.py - Fair Spread Check
        print("\n✅ ПРОВЕРКА 5: trade_executor.py - fair_spread проверка (строка 476)")
        print("-" * 80)
        patterns = [
            ('fair_spread_none_check', r'if fair_spread is None:', (470, 485)),
        ]
        result = self.check_file(executor_path, patterns)
        if result['issues']:
            print("✅ НАЙДЕНО: Проверка fair_spread is None на строках:")
            for issue in result['issues']:
                print(f"   Строка {issue['line']}: {issue['content']}")
        else:
            print("⚠️  ВНИМАНИЕ: Проверка fair_spread не найдена")

        # Проверка 6: trade_executor.py - Volatility Check
        print(
            "\n✅ ПРОВЕРКА 6: trade_executor.py - is_tight_spread проверка (строка 493-494)")
        print("-" * 80)
        patterns = [
            ('tight_spread_check',
             r'symbol_info.point is not None and current_spread_price <', (490, 500)),
        ]
        result = self.check_file(executor_path, patterns)
        if result['issues']:
            print("✅ НАЙДЕНО: Проверка is_tight_spread на строках:")
            for issue in result['issues']:
                print(f"   Строка {issue['line']}: {issue['content']}")
        else:
            print("⚠️  ВНИМАНИЕ: Проверка is_tight_spread не найдена")

        # Проверка 7: trading_system.py - Stop Loss None Check
        print("\n✅ ПРОВЕРКА 7: trading_system.py - stop_loss_in_price проверка (строка 2100-2115)")
        print("-" * 80)
        trading_system_path = os.path.join(
            self.workspace_root, 'src/core/trading_system.py')
        patterns = [
            ('stop_loss_none_in_trading',
             r'if lot_size is None or lot_size <= 0 or stop_loss_in_price is None:', (2095, 2120)),
        ]
        result = self.check_file(trading_system_path, patterns)
        if result['issues']:
            print("✅ НАЙДЕНО: Проверка stop_loss_in_price в условии на строках:")
            for issue in result['issues']:
                print(f"   Строка {issue['line']}: {issue['content']}")
        else:
            print("⚠️  ВНИМАНИЕ: Проверка stop_loss_in_price в условии не найдена")

        # Проверка 8: trade_executor.py - Profit Check
        print("\n✅ ПРОВЕРКА 8: trade_executor.py - profit проверка (строка 825-827)")
        print("-" * 80)
        patterns = [
            ('profit_none_check', r'if profit is None:', (820, 835)),
        ]
        result = self.check_file(executor_path, patterns)
        if result['issues']:
            print("✅ НАЙДЕНО: Проверка profit is None на строках:")
            for issue in result['issues']:
                print(f"   Строка {issue['line']}: {issue['content']}")
        else:
            print("⚠️  ВНИМАНИЕ: Проверка profit не найдена")

        print("\n" + "=" * 80)
        print("✅ ПРОВЕРКА ЗАВЕРШЕНА")
        print("=" * 80)


def main():
    """Главная функция"""
    workspace_root = r'f:\MT5Qoder\MT5Projekt-Clean'

    if not os.path.exists(workspace_root):
        print(f"❌ Ошибка: Рабочая папка не найдена: {workspace_root}")
        return

    checker = NoneComparisonChecker(workspace_root)
    checker.verify_fixes()


if __name__ == '__main__':
    main()
