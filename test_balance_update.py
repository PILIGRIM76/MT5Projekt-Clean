#!/usr/bin/env python3
"""
Тест обновления баланса в реальном времени.
"""

import time
from datetime import datetime

import MetaTrader5 as mt5

print("=" * 60)
print("  Тест обновления баланса в реальном времени")
print("=" * 60)
print()

# Инициализация MT5
if not mt5.initialize():
    print("❌ Ошибка инициализации MT5")
    print(f"   Error: {mt5.last_error()}")
    exit(1)

print("✅ MT5 подключен")
print()

# Мониторинг баланса
print("📊 Мониторинг баланса (10 обновлений):")
print("-" * 60)

last_balance = None
last_equity = None

for i in range(10):
    account_info = mt5.account_info()

    if account_info:
        balance = account_info.balance
        equity = account_info.equity

        # Проверка изменений
        balance_changed = (balance != last_balance) if last_balance else False
        equity_changed = (equity != last_equity) if last_equity else False

        change_indicator = ""
        if balance_changed or equity_changed:
            change_indicator = "🔄 ИЗМЕНЕНИЕ"

        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] Баланс: ${balance:,.2f} | Эквити: ${equity:,.2f} {change_indicator}")

        last_balance = balance
        last_equity = equity
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Ошибка получения данных")

    time.sleep(1)

print()
print("=" * 60)
print("  Тест завершен!")
print("=" * 60)

mt5.shutdown()
