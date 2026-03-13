# 🚀 КАК ЗАПУСТИТЬ GENESIS TRADING SYSTEM

**Дата:** 22 февраля 2026  
**Версия:** 1.0.0 (финальная, рабочая)

---

## 📦 Шаг 1: Установка

### Запусти установщик:

```
F:\MT5Qoder\MT5Projekt-Clean\installer_output\GenesisTrading_Setup_v1.0.0.exe
```

### Или из PowerShell:

```powershell
& "F:\MT5Qoder\MT5Projekt-Clean\installer_output\GenesisTrading_Setup_v1.0.0.exe"
```

### Следуй инструкциям:

1. Выбери язык (English/Russian)
2. Прими лицензию
3. Выбери папку (по умолчанию: `C:\Program Files\Genesis Trading System`)
4. Выбери компоненты (опционально: Desktop icon)
5. Нажми "Install"
6. На последнем экране:
   - ☑️ Поставь галочку "Launch Genesis Trading System"
   - Нажми "Finish"

---

## 🎯 Шаг 2: Первый запуск

### Автоматический запуск:

Если поставил галочку на последнем экране, программа запустится автоматически.

### Ручной запуск:

#### Из Start Menu:
```
Пуск → Genesis Trading System → Genesis Trading System
```

#### Из Desktop (если создал ярлык):
```
Двойной клик по ярлыку "Genesis Trading System"
```

#### Из PowerShell:
```powershell
& "C:\Program Files\Genesis Trading System\GenesisTrading.exe"
```

---

## ⚙️ Шаг 3: Настройка (ВАЖНО!)

### Перед использованием настрой `settings.json`:

```powershell
notepad "C:\Program Files\Genesis Trading System\configs\settings.json"
```

### Измени следующие параметры:

```json
{
  "MT5_LOGIN": "ВАШ_ЛОГИН",
  "MT5_PASSWORD": "ВАШ_ПАРОЛЬ",
  "MT5_SERVER": "ВАШ_СЕРВЕР",
  "MT5_PATH": "C:/Program Files/MetaTrader 5/terminal64.exe"
}
```

**Пример:**
```json
{
  "MT5_LOGIN": "12345678",
  "MT5_PASSWORD": "MyPassword123",
  "MT5_SERVER": "Alpari-MT5-Demo",
  "MT5_PATH": "C:/Program Files/Alpari MT5/terminal64.exe"
}
```

---

## ✅ Шаг 4: Проверка работы

### Проверь, что программа запущена:

```powershell
Get-Process -Name "GenesisTrading" -ErrorAction SilentlyContinue
```

**Ожидается:**
```
Handles  NPM(K)    PM(K)      WS(K)     CPU(s)     Id  SI ProcessName
-------  ------    -----      -----     ------     --  -- -----------
    xxx      xx   xxxxxx     xxxxxx       x.xx  xxxxx   x GenesisTrading
```

### Проверь логи:

```powershell
Get-Content "C:\Program Files\Genesis Trading System\logs\genesis_system.log" -Tail 20
```

**Ожидается:**
- Нет ошибок `ModuleNotFoundError`
- Есть логи инициализации
- Система запускается

### Проверь GUI:

- ✅ Главное окно открылось
- ✅ Вкладки отображаются
- ✅ Нет ошибок на экране

---

## 🐛 Устранение проблем

### Проблема 1: Программа не запускается

**Проверь:**
```powershell
Test-Path "C:\Program Files\Genesis Trading System\GenesisTrading.exe"
```

**Если False:**
- Переустанови программу
- Проверь, что установка завершилась успешно

### Проблема 2: Ошибка "ModuleNotFoundError"

**Проверь версию установщика:**
```powershell
$file = Get-Item "F:\MT5Qoder\MT5Projekt-Clean\installer_output\GenesisTrading_Setup_v1.0.0.exe"
$file.LastWriteTime
```

**Должно быть:** 22.02.2026 18:10 или позже

**Если старше:**
- Удали программу
- Установи заново с НОВЫМ установщиком

### Проблема 3: Программа крашится сразу

**Проверь логи:**
```powershell
Get-Content "C:\Program Files\Genesis Trading System\logs\genesis_system.log" -Tail 50
```

**Если логов нет:**
- Проверь, что MT5 установлен
- Проверь `settings.json`
- Проверь права доступа к папке

### Проблема 4: GUI не открывается

**Проверь процесс:**
```powershell
Get-Process -Name "GenesisTrading" | Select-Object Id, CPU, WorkingSet64
```

**Если процесс есть, но GUI нет:**
- Подожди 30-60 секунд (инициализация)
- Проверь, что MT5 запущен
- Перезапусти программу

---

## 📊 Что должно работать

После успешного запуска:

- ✅ GUI открывается
- ✅ Вкладки: Dashboard, Market Scanner, Signals, Positions, R&D, Logs
- ✅ Логи создаются в `./logs/`
- ✅ База данных создаётся в `./database/`
- ✅ Подключение к MT5 (если настроен)
- ✅ Сканирование рынка работает
- ✅ Графики отображаются

---

## 🔧 Полезные команды

### Перезапуск программы:

```powershell
# Останови
Get-Process -Name "GenesisTrading" | Stop-Process -Force

# Запусти
& "C:\Program Files\Genesis Trading System\GenesisTrading.exe"
```

### Просмотр логов в реальном времени:

```powershell
Get-Content "C:\Program Files\Genesis Trading System\logs\genesis_system.log" -Wait -Tail 20
```

### Проверка размера базы данных:

```powershell
Get-Item "C:\Program Files\Genesis Trading System\database\trading_system.db" | Select-Object Name, Length, LastWriteTime
```

### Очистка логов:

```powershell
Remove-Item "C:\Program Files\Genesis Trading System\logs\*.log"
```

---

## 📚 Дополнительная документация

- **QUICK_START.md** - Быстрый старт для пользователей
- **TROUBLESHOOTING_PROMPT.md** - Решение проблем
- **QUICK_FIX_GUIDE.md** - Быстрые исправления
- **README.md** - Полная документация

---

## 🆘 Поддержка

### GitHub:
https://github.com/PILIGRIM76/MT5Projekt-Clean

### Issues:
https://github.com/PILIGRIM76/MT5Projekt-Clean/issues

### Releases:
https://github.com/PILIGRIM76/MT5Projekt-Clean/releases

---

## ✅ Чеклист первого запуска

- [ ] Установщик запущен
- [ ] Программа установлена
- [ ] `settings.json` настроен (MT5 credentials)
- [ ] Программа запускается без ошибок
- [ ] GUI открывается
- [ ] Логи создаются
- [ ] База данных создаётся
- [ ] Нет ошибок в логах

**Если все пункты выполнены - система готова к работе! ✅**

---

**Удачной торговли! 🚀**

**Помни: Тестируй на демо-счёте минимум 30 дней!**
