#!/usr/bin/env python3
"""
Тест обновления баланса и эквити в реальном времени.
Проверяет что данные обновляются каждую секунду.
"""

import time
from datetime import datetime

import MetaTrader5 as mt5

print("=" * 70)
print("  Тест обновления баланса и эквити в реальном времени")
print("=" * 70)
print()

# Инициализация MT5
if not mt5.initialize():
    print("❌ Ошибка инициализации MT5")
    print(f"   Error: {mt5.last_error()}")
    exit(1)

print("✅ MT5 подключен")
print()

# Мониторинг в реальном времени
print("📊 Мониторинг баланса и эквити (20 обновлений):")
print("-" * 70)

last_balance = None
last_equity = None
update_count = 0

for i in range(20):
    account_info = mt5.account_info()

    if account_info:
        balance = account_info.balance
        equity = account_info.equity

        # Проверка изменений
        balance_changed = (balance != last_balance) if last_balance else False
        equity_changed = (equity != last_equity) if last_equity else False

        if balance_changed or equity_changed:
            update_count += 1

        # Индикатор изменений
        change_indicator = ""
        if balance_changed:
            change_indicator += " 🔄 Balance"
        if equity_changed:
            change_indicator += " 🔄 Equity"
        if not change_indicator:
            change_indicator = " (без изменений)"

        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] Баланс: ${balance:,.2f} | Эквити: ${equity:,.2f}{change_indicator}")

        last_balance = balance
        last_equity = equity
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Ошибка получения данных")

    time.sleep(1)

print()
print("=" * 70)
print(f"  Результат: {update_count}/20 обновлений с изменениями")
print("=" * 70)

if update_count > 0:
    print(f"✅ Эквити обновляется в реальном времени! ({update_count} раз)")
else:
    print("⚠️ Данные не изменялись (рынок стоит)")

mt5.shutdown()
