# 🔨 Инструкция по сборке EXE

## 📋 Требования

### Обязательно:
- Python 3.10+
- Все зависимости установлены (`pip install -r requirements.txt`)
- 10GB+ свободного места на диске
- Windows 10/11

### Опционально (для создания установщика):
- [Inno Setup](https://jrsoftware.org/isdl.php) - для создания Windows installer

---

## 🚀 Быстрая сборка

### Вариант 1: Полная сборка (рекомендуется)

```batch
BUILD_RELEASE.bat
```

Это создаст:
- ✅ Portable ZIP (GenesisTrading_Portable_v1.0.0.zip)
- ✅ Windows Installer (если установлен Inno Setup)

**Время:** 15-20 минут

---

### Вариант 2: Только EXE

```batch
build_exe.bat
```

Результат: `dist\GenesisTrading\GenesisTrading.exe`

**Время:** 10-15 минут

---

### Вариант 3: Только Portable ZIP

```batch
REM Сначала собери EXE
build_exe.bat

REM Затем создай portable версию
create_portable.bat
```

Результат: `GenesisTrading_Portable_v1.0.0.zip`

---

## 📦 Что включено в сборку

### EXE файл содержит:
- ✅ Все Python библиотеки
- ✅ PySide6 (GUI)
- ✅ PyTorch (ML)
- ✅ LightGBM (ML)
- ✅ FAISS (Vector DB)
- ✅ Все зависимости

### Дополнительные файлы:
- 📁 `assets/` - Иконки, звуки, HTML
- 📁 `configs/` - Конфигурационные файлы
- 📄 `README.md` - Документация
- 📄 `QUICK_START.md` - Быстрый старт
- 📄 `TROUBLESHOOTING_PROMPT.md` - Решение проблем

---

## 🔧 Ручная сборка (для разработчиков)

### Шаг 1: Подготовка

```batch
REM Активируй виртуальное окружение
venv\Scripts\activate

REM Установи PyInstaller
pip install pyinstaller
```

### Шаг 2: Сборка

```batch
REM Очисти старые файлы
rmdir /s /q build dist

REM Собери EXE
pyinstaller genesis_trading.spec --clean --noconfirm
```

### Шаг 3: Копирование файлов

```batch
REM Скопируй конфиги
xcopy /E /I /Y configs dist\GenesisTrading\configs

REM Скопируй документацию
copy README.md dist\GenesisTrading\
copy QUICK_START.md dist\GenesisTrading\

REM Создай папки
mkdir dist\GenesisTrading\database
mkdir dist\GenesisTrading\logs
```

### Шаг 4: Тестирование

```batch
REM Запусти EXE
dist\GenesisTrading\GenesisTrading.exe
```

---

## 📊 Размеры файлов

Примерные размеры:

| Файл | Размер |
|------|--------|
| GenesisTrading.exe | ~50-100 MB |
| Полная папка dist\GenesisTrading | ~500-800 MB |
| Portable ZIP | ~300-500 MB |
| Windows Installer | ~300-500 MB |

---

## ⚠️ Возможные проблемы

### Проблема 1: "Module not found"

**Решение:**
```batch
REM Добавь модуль в genesis_trading.spec в hiddenimports
hiddenimports = [
    'your_missing_module',
    ...
]
```

### Проблема 2: "Failed to execute script"

**Решение:**
```batch
REM Запусти с консолью для отладки
REM В genesis_trading.spec измени:
console=True  # Было False
```

### Проблема 3: Большой размер EXE

**Решение:**
```batch
REM Исключи ненужные библиотеки в genesis_trading.spec:
excludes=[
    'matplotlib',
    'IPython',
    'jupyter',
    ...
]
```

### Проблема 4: Долгая сборка

**Нормально!** Сборка занимает 10-20 минут из-за:
- Большого количества зависимостей
- PyTorch (большая библиотека)
- Компрессии UPX

---

## 🎯 Оптимизация размера

### Уменьшение размера EXE:

1. **Используй CPU-only версии:**
```batch
pip uninstall torch
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

2. **Исключи ненужные модели:**
```python
# В genesis_trading.spec
excludes=[
    'matplotlib',
    'IPython',
    'jupyter',
    'notebook',
    'pytest',
    'sphinx',
    'tensorboard',
]
```

3. **Используй UPX компрессию:**
```python
# В genesis_trading.spec
upx=True,
upx_exclude=[],
```

---

## 📤 Публикация на GitHub

### Шаг 1: Создай Release

```batch
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```

### Шаг 2: Загрузи файлы

На GitHub:
1. Перейди в Releases
2. Нажми "Create a new release"
3. Выбери тег v1.0.0
4. Загрузи файлы:
   - `GenesisTrading_Portable_v1.0.0.zip`
   - `GenesisTrading_Setup_v1.0.0.exe` (если есть)

### Шаг 3: Обнови README

Добавь ссылки на скачивание:
```markdown
## 📥 Download

- [Portable ZIP](https://github.com/PILIGRIM76/MT5Projekt-Clean/releases/download/v1.0.0/GenesisTrading_Portable_v1.0.0.zip)
- [Windows Installer](https://github.com/PILIGRIM76/MT5Projekt-Clean/releases/download/v1.0.0/GenesisTrading_Setup_v1.0.0.exe)
```

---

## 🧪 Тестирование сборки

### Чеклист перед публикацией:

- [ ] EXE запускается без ошибок
- [ ] GUI отображается корректно
- [ ] Подключение к MT5 работает
- [ ] Конфигурация загружается
- [ ] Логи создаются
- [ ] База данных создаётся
- [ ] Все функции работают
- [ ] Нет критических ошибок в логах

### Тестовый сценарий:

1. Распакуй portable версию
2. Настрой `configs\settings.json`
3. Запусти `GenesisTrading.exe`
4. Проверь подключение к MT5
5. Запусти систему
6. Подожди 5 минут
7. Проверь логи
8. Останови систему

---

## 📝 Changelog

### v1.0.0 (2026-02-22)

**Новое:**
- ✨ Safety Monitor (защита от потерь >3%)
- ✨ Model Validation (PF≥1.5, WR≥40%)
- ✨ VectorDB оптимизация (-99.3% disk I/O)

**Улучшения:**
- 🔧 Риск: 2.0% → 0.5% (-75%)
- 🔧 Позиции: 18 → 5 (-72%)
- 🔧 Данные: 2000 → 10000 баров (+400%)

**Исправления:**
- 🐛 Feature duplication
- 🐛 KG feature reliability
- 🐛 MT5 connection handling

---

## 🆘 Поддержка

Если возникли проблемы со сборкой:

1. Проверь логи PyInstaller
2. Проверь `build\GenesisTrading\warn-GenesisTrading.txt`
3. Создай Issue на GitHub
4. Приложи логи и описание проблемы

---

**Удачной сборки! 🚀**
