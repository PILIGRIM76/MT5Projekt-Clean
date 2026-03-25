# 🚀 Сборка через GitHub Actions

**Преимущества:**
- ✅ Чистая среда (без конфликтов версий)
- ✅ Все зависимости устанавливаются заново
- ✅ Автоматическая сборка при каждом теге
- ✅ Артефакты доступны для скачивания

---

## 📋 Шаг 1: Подготовка репозитория

### 1.1 Загрузите проект на GitHub

```bash
cd F:\MT5Qoder\MT5Projekt-Clean
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/ВАШ_НИК/MT5Projekt-Clean.git
git push -u origin main
```

### 1.2 Проверьте workflow

Файл `.github/workflows/build.yml` уже создан.

---

## 📋 Шаг 2: Запуск сборки

### Вариант 1: Автоматическая сборка при теге

```bash
# Создайте тег версии
git tag v13.0.0
git push origin v13.0.0
```

GitHub Actions автоматически запустит сборку.

### Вариант 2: Ручной запуск

1. Перейдите в репозиторий на GitHub
2. Вкладка **Actions**
3. Выберите workflow **Build EXE**
4. Нажмите **Run workflow**
5. Выберите ветку (main)
6. Нажмите **Run workflow**

---

## 📋 Шаг 3: Скачивание артефакта

### После завершения сборки:

1. Перейдите в **Actions** → **Build EXE**
2. Выберите последний запуск
3. В разделе **Artifacts** скачайте:
   - `GenesisTrading-Build.zip`

**Срок хранения:** 90 дней

---

## 📋 Шаг 4: Публикация Release (автоматически)

При создании тега (v13.0.0):

1. GitHub создаст **Release**
2. Прикрепит файлы:
   - `GenesisTrading_Portable_v13.0.0.zip`
   - `GenesisTrading.exe`

**Ссылка:** `https://github.com/ВАШ_НИК/MT5Projekt-Clean/releases`

---

## ⚙️ Настройка workflow

### Изменение версии Python

В `.github/workflows/build.yml`:

```yaml
- name: Setup Python
  uses: actions/setup-python@v5
  with:
    python-version: '3.9'  # <-- Измените версию
```

### Изменение имени артефакта

```yaml
- name: Upload artifact
  uses: actions/upload-artifact@v4
  with:
    name: GenesisTrading-v13.0.0  # <-- Новое имя
```

---

## 🐛 Решение проблем

### Проблема 1: Сборка не запускается

**Проверьте:**
- Файл `.github/workflows/build.yml` существует
- Имя файла точно `build.yml` (не `build.yaml`)
- Права доступа к репозиторию

### Проблема 2: Ошибка зависимостей

**Решение:**
1. Проверьте `requirements.txt`
2. Убедитесь, что все пакеты доступны на PyPI
3. Проверьте логи сборки в Actions

### Проблема 3: Превышен лимит времени

GitHub Actions: 6 часов на сборку.

**Решение:**
- Уменьшите количество зависимостей
- Используйте кэш pip

---

## 📊 Лимиты GitHub Actions

| Тип аккаунта | Лимит |
|--------------|-------|
| **Free** | 2000 минут/месяц |
| **Pro** | 3000 минут/месяц |
| **Team** | 50000 минут/месяц |
| **Enterprise** | 200000 минут/месяц |

**Время сборки:** ~30-40 минут

---

## 🔐 Секреты (для будущих функций)

Для авто-публикации в Releases:

1. **Settings** → **Secrets and variables** → **Actions**
2. **New repository secret**
3. Добавьте:
   - `GITHUB_TOKEN` (автоматически)

---

## 📁 Структура workflow

```yaml
name: Build EXE              # Имя workflow

on:
  push:
    tags:
      - 'v*'                # Запуск при тегах v*
  workflow_dispatch:         # Ручной запуск

jobs:
  build-windows:
    runs-on: windows-latest  # Windows среда
    
    steps:
    - uses: actions/checkout@v4        # Исходный код
    - uses: actions/setup-python@v5   # Python
    - run: pip install ...             # Зависимости
    - run: .\build.bat                 # Сборка
    - uses: actions/upload-artifact@v4 # Загрузка
```

---

## ✅ Чеклист

- [ ] Проект загружен на GitHub
- [ ] Файл `.github/workflows/build.yml` создан
- [ ] `requirements.txt` актуален
- [ ] Запущен workflow (тег или вручную)
- [ ] Артефакт скачан
- [ ] Release создан (если тег)

---

## 🆘 Поддержка

**Документация GitHub Actions:**
https://docs.github.com/en/actions

**Примеры workflow:**
https://github.com/actions/starter-workflows

---

**Удачной сборки! 🚀**
