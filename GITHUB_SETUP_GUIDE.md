# 🚀 Настройка GitHub репозитория - Пошаговая инструкция

**Версия:** 13.0.0  
**Дата:** 25 марта 2026

---

## 📋 Шаг 1: Инициализация Git

### Запустите скрипт инициализации:

```batch
cd F:\MT5Qoder\MT5Projekt-Clean
init_git.bat
```

**Что сделает скрипт:**
- ✅ Проверит наличие Git
- ✅ Создаст Git репозиторий
- ✅ Создаст `.gitignore`
- ✅ Добавит файлы
- ✅ Создаст первый коммит

---

## 📋 Шаг 2: Создание репозитория на GitHub

### 2.1 Перейдите на GitHub

https://github.com/new

### 2.2 Создайте репозиторий

1. **Repository name:** `MT5Projekt-Clean`
2. **Description:** Genesis Trading System - Саморазвивающаяся торговая экосистема
3. **Visibility:** Public (или Private)
4. ❌ **Не** ставьте галочки на "Initialize with README"
5. Нажмите **Create repository**

---

## 📋 Шаг 3: Настройка удалённого репозитория

### 3.1 Скопируйте команду из GitHub

После создания репозитория GitHub покажет команды. Скопируйте первую строку:

```bash
git remote add origin https://github.com/ВАШ_НИК/MT5Projekt-Clean.git
```

### 3.2 Выполните команду в проекте

Откройте PowerShell в папке проекта:

```powershell
cd F:\MT5Qoder\MT5Projekt-Clean
git remote add origin https://github.com/ВАШ_НИК/MT5Projekt-Clean.git
```

### 3.3 Проверьте подключение

```bash
git remote -v
```

**Должно показать:**
```
origin  https://github.com/ВАШ_НИК/MT5Projekt-Clean.git (fetch)
origin  https://github.com/ВАШ_НИК/MT5Projekt-Clean.git (push)
```

---

## 📋 Шаг 4: Загрузка на GitHub

### Запустите скрипт загрузки:

```batch
upload_to_github.bat
```

**Что сделает скрипт:**
- ✅ Добавит все файлы
- ✅ Создаст коммит
- ✅ Отправит на GitHub
- ✅ Создаст тег версии

### Введите версию при запросе:

```
Введите версию (например, 13.0.0): 13.0.0
```

---

## 📋 Шаг 5: Проверка сборки

### 5.1 Перейдите в Actions

https://github.com/ВАШ_НИК/MT5Projekt-Clean/actions

### 5.2 Выберите workflow

Нажмите на **"🚀 Build Genesis Trading EXE"**

### 5.3 Следите за прогрессом

Сборка занимает **30-50 минут**.

**Статусы:**
- 🟡 **In Progress** - идёт сборка
- 🟢 **Success** - сборка завершена успешно
- 🔴 **Failed** - ошибка сборки

---

## 📋 Шаг 6: Скачивание артефакта

### После успешной сборки:

1. Перейдите в **Actions** → **🚀 Build Genesis Trading EXE**
2. Выберите последний запуск (зелёный)
3. Прокрутите вниз до **Artifacts**
4. Скачайте:
   - `GenesisTrading-v13.0.0.zip` - основная версия
   - `GenesisTrading-Portable-v13.0.0.zip` - portable версия

**Срок хранения:** 30 дней

---

## 📋 Шаг 7: Публикация Release (автоматически)

### При создании тега (v13.0.0):

GitHub автоматически создаст **Release**:

1. Перейдите в **Releases**
2. Нажмите на последний релиз
3. Скачайте файлы:
   - `GenesisTrading.exe`
   - `GenesisTrading_Portable_v13.0.0.zip`

**Ссылка:** `https://github.com/ВАШ_НИК/MT5Projekt-Clean/releases`

---

## 🔧 Ручное управление

### Создать тег вручную:

```bash
git tag v13.0.1
git push origin v13.0.1
```

### Отправить изменения:

```bash
git add .
git commit -m "Описание изменений"
git push origin main
```

### Обновить версию:

```bash
# Измените версию в pyproject.toml
# Затем:
git tag v13.1.0
git push origin v13.1.0
```

---

## ⚙️ Настройка workflow

### Изменение версии Python

Откройте `.github/workflows/build.yml`:

```yaml
- name: 🐍 Setup Python
  uses: actions/setup-python@v5
  with:
    python-version: '3.10'  # <-- Измените версию
```

### Изменение времени сборки

```yaml
jobs:
  build-windows:
    timeout-minutes: 180  # <-- Максимум 180 минут
```

### Добавление тестов

```yaml
- name: 🧪 Run tests
  run: |
    pytest tests/
  shell: cmd
```

---

## 🐛 Решение проблем

### Проблема 1: "Git not found"

**Решение:**
```bash
# Установите Git
https://git-scm.com/download/win

# Перезапустите терминал
```

### Проблема 2: "Remote origin already exists"

**Решение:**
```bash
git remote remove origin
git remote add origin https://github.com/НИК/MT5Projekt-Clean.git
```

### Проблема 3: "Permission denied"

**Решение:**
1. Проверьте логин на GitHub
2. Убедитесь, что у вас есть доступ к репозиторию
3. Для Private репозиториев настройте SSH ключи

### Проблема 4: Сборка не запускается

**Проверьте:**
- Файл `.github/workflows/build.yml` существует
- Имя файла точно `build.yml`
- Ветка называется `main` или `master`

### Проблема 5: "No space left on device"

GitHub предоставляет 14 GB.

**Решение:**
```yaml
- name: 🗑️ Free disk space
  run: |
    rm -rf /c/Program\ Files/dotnet
    rm -rf /c/Android
```

---

## 📊 Лимиты GitHub Actions

| Тип аккаунта | Лимит минут | Хранилище |
|--------------|-------------|-----------|
| **Free** | 2000/месяц | 500 MB |
| **Pro** | 3000/месяц | 2 GB |
| **Team** | 50000/месяц | 10 GB |
| **Enterprise** | 200000/месяц | 50 GB |

**Время одной сборки:** ~30-50 минут

---

## ✅ Чеклист настройки

- [ ] Git установлен
- [ ] `init_git.bat` выполнен
- [ ] Репозиторий создан на GitHub
- [ ] `git remote add origin` выполнен
- [ ] `upload_to_github.bat` выполнен
- [ ] Тег версии создан
- [ ] Сборка в Actions запущена
- [ ] Артефакт скачан
- [ ] Release создан

---

## 📁 Структура проекта для GitHub

```
MT5Projekt-Clean/
├── .github/
│   └── workflows/
│       └── build.yml          # Workflow для сборки
├── .gitignore                 # Игнорируемые файлы
├── requirements.txt           # Зависимости Python
├── pyproject.toml            # Конфигурация проекта
├── main_pyside.py            # Точка входа
├── src/                      # Исходный код
├── configs/                  # Конфигурации
├── assets/                   # Ресурсы
└── GenesisTrading_Build/     # Скрипты сборки
    ├── build.bat
    ├── deploy.bat
    ├── create_portable.bat
    └── GenesisTrading.spec
```

---

## 🔐 Безопасность

### Никогда не загружайте на GitHub:

- ❌ `configs/settings.json` (пароли)
- ❌ `*.db` (базы данных)
- ❌ `*.log` (логи)
- ❌ `ai_models/` (модели)
- ❌ `.env` (секреты)

**Эти файлы добавлены в `.gitignore`**

---

## 🆘 Поддержка

**Документация GitHub:**
- Actions: https://docs.github.com/en/actions
- Repositories: https://docs.github.com/en/repositories

**Примеры workflow:**
https://github.com/actions/starter-workflows

---

## 📞 Контакты

**GitHub Issues:**
https://github.com/ВАШ_НИК/MT5Projekt-Clean/issues

---

**Удачной публикации! 🚀**

*Последнее обновление: 25 марта 2026*
