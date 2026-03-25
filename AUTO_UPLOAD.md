# 🚀 Автоматическая загрузка на GitHub

## Вариант 1: Автоматическая загрузка (рекомендуется)

### 1️⃣ Установите GitHub CLI

**Скачайте и установите:**
https://cli.github.com/

**Или через winget:**
```powershell
winget install --id GitHub.cli
```

**Или через Chocolatey:**
```powershell
choco install gh
```

### 2️⃣ Запустите автоматическую загрузку

```batch
cd F:\MT5Qoder\MT5Projekt-Clean
auto_upload_github.bat
```

### 3️⃣ Пройдите авторизацию

Скрипт попросит авторизоваться на GitHub:

1. Выберите **HTTPS**
2. Нажмите **Enter** для открытия браузера
3. Войдите в свой аккаунт GitHub
4. Скопируйте код и вставьте в терминал

### 4️⃣ Готово!

Скрипт автоматически:
- ✅ Создаст репозиторий
- ✅ Загрузит файлы
- ✅ Создаст тег версии
- ✅ Запустит сборку

---

## Вариант 2: Ручная загрузка (без GitHub CLI)

### 1️⃣ Создайте репозиторий

Перейдите: **https://github.com/new**

- **Repository name:** `MT5Projekt-Clean`
- **Description:** Genesis Trading System - Саморазвивающаяся торговая экосистема
- **Visibility:** Public
- **НЕ** ставьте галочку "Initialize with README"
- Нажмите **Create repository**

### 2️⃣ Скопируйте команды

GitHub покажет команды. Выполните их по порядку:

```powershell
# Перейти в проект
cd F:\MT5Qoder\MT5Projekt-Clean

# Настроить удалённый репозиторий
git remote add origin https://github.com/ВАШ_НИК/MT5Projekt-Clean.git

# Установить главную ветку
git branch -M main

# Загрузить файлы
git push -u origin main

# Создать тег версии
git tag v13.0.0
git push origin v13.0.0
```

---

## ✅ После загрузки

### Проверьте Actions

Перейдите: **https://github.com/ВАШ_НИК/MT5Projekt-Clean/actions**

**Статусы:**
- 🟡 **In Progress** - идёт сборка
- 🟢 **Success** - сборка завершена
- 🔴 **Failed** - ошибка

### Скачайте артефакт

Через **30-50 минут**:

1. Откройте последний запуск (зелёный)
2. Прокрутите до **Artifacts**
3. Скачайте `GenesisTrading-v13.0.0.zip`

---

## 🔧 Решение проблем

### "Git not found"

Установите Git: https://git-scm.com/download/win

### "gh not found"

Установите GitHub CLI: https://cli.github.com/

### "Permission denied"

Проверьте:
- Логин на GitHub
- Доступ к репозиторию
- Авторизацию: `gh auth login`

### "Remote origin already exists"

```powershell
git remote remove origin
git remote add origin https://github.com/ВАШ_НИК/MT5Projekt-Clean.git
```

---

## 📞 Поддержка

**Документация GitHub CLI:**
https://cli.github.com/manual/

**GitHub Actions:**
https://docs.github.com/en/actions

---

**Удачной загрузки! 🚀**
