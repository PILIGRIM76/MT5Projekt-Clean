# 🔐 БЕЗОПАСНАЯ КОНФИГУРАЦИЯ GENESIS TRADING SYSTEM

**Версия:** 1.0  
**Дата:** 27 марта 2026

---

## 📋 СОДЕРЖАНИЕ

1. [Обзор](#обзор)
2. [Быстрый старт](#быстрый-старт)
3. [Генерация ключа шифрования](#генерация-ключа-шифрования)
4. [Шифрование чувствительных данных](#шифрование-чувствительных-данных)
5. [Настройка переменных окружения](#настройка-переменных-окружения)
6. [Миграция со старой конфигурации](#миграция-со-старой-конфигурации)
7. [Troubleshooting](#troubleshooting)

---

## ОБЗОР

### Почему это важно?

Ранее чувствительные данные (пароли, API ключи) хранились в открытом виде в файле `configs/settings.json`:

```json
{
    "MT5_PASSWORD": "mypassword123",  // ❌ В открытом виде!
    "FINNHUB_API_KEY": "abc123..."    // ❌ В открытом виде!
}
```

**Теперь:**
- Пароли и API ключи хранятся в зашифрованном виде
- Шифрование AES-256 через Fernet
- Ключ шифрования в переменной окружения
- Чувствительные данные не попадут в репозиторий

---

## БЫСТРЫЙ СТАРТ

### Шаг 1: Генерация ключа шифрования

```bash
python scripts/encrypt_config.py generate-key
```

**Вывод:**
```
============================================================
НОВЫЙ КЛЮЧ ШИФРОВАНИЯ:
============================================================
ENCRYPTION_KEY=ZmDfc37_60Gj2W5q3lLq8d9F3h5K7j2n4m6p8r0s=
============================================================
```

### Шаг 2: Создание .env файла

```bash
# Скопируйте пример
cp configs/.env.example configs/.env

# Или создайте вручную
echo ENCRYPTION_KEY=ZmDfc37_60Gj2W5q3lLq8d9F3h5K7j2n4m6p8r0s= > configs/.env
```

### Шаг 3: Шифрование паролей

```bash
# Зашифруйте пароль MT5
python scripts/encrypt_config.py encrypt "ваш_пароль_mt5"

# Зашифруйте API ключи
python scripts/encrypt_config.py encrypt "ваш_finnhub_api_key"
```

### Шаг 4: Обновление .env файла

Откройте `configs/.env` и замените значения на зашифрованные:

```bash
# configs/.env
MT5_LOGIN=52565344
MT5_PASSWORD=${ENC:AES256:gAAAAABhZ...}  # ✅ Зашифровано
FINNHUB_API_KEY=${ENC:AES256:gAAAAABhZ...}  # ✅ Зашифровано
```

---

## ГЕНЕРАЦИЯ КЛЮЧА ШИФРОВАНИЯ

### Автоматическая генерация

```bash
python scripts/encrypt_config.py generate-key
```

### Ручная генерация (Python)

```python
from cryptography.fernet import Fernet

key = Fernet.generate_key()
print(f"ENCRYPTION_KEY={key.decode()}")
```

### Требования к ключу

- **Формат:** URL-safe base64
- **Размер:** 32 байта (256 бит)
- **Кодировка:** Fernet (симметричное шифрование)

---

## ШИФРОВАНИЕ ЧУВСТВИТЕЛЬНЫХ ДАННЫХ

### Что нужно шифровать?

| Данные | Приоритет | Пример |
|--------|-----------|--------|
| MT5_PASSWORD | 🔴 Критично | Пароль от торгового счета |
| NEO4J_PASSWORD | 🔴 Критично | Пароль от графовой БД |
| FINNHUB_API_KEY | 🟡 Важно | API ключ для данных |
| NEWS_API_KEY | 🟡 Важно | API ключ для новостей |
| TELEGRAM_API_ID | 🟡 Важно | ID Telegram API |
| TELEGRAM_API_HASH | 🟡 Важно | Hash Telegram API |

### Шифрование отдельных значений

```bash
# Шифрование пароля
python scripts/encrypt_config.py encrypt "*u5qCsTe"

# Вывод:
# ${ENC:AES256:gAAAAABhZ2X7vK3mN9pL5qR8sT1uW4xY6zA2bC3dE4fF5gG6hH7iI8jJ9kK0lL1mM2nN3oO4pP5qQ6rR7sS8tT9uU0vV1wW2xX3yY4zZ5}
```

### Массовое шифрование (.env файл)

```bash
# 1. Установите ключ шифрования
export ENCRYPTION_KEY=ZmDfc37_60Gj2W5q3lLq8d9F3h5K7j2n4m6p8r0s=

# 2. Заполните configs/.env.example реальными данными

# 3. Зашифруйте все чувствительные данные
python scripts/encrypt_config.py encrypt-env
```

---

## НАСТРОЙКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ

### Структура .env файла

```bash
# ===========================================
# MT5 Connection
# ===========================================
MT5_LOGIN=52565344
MT5_PASSWORD=${ENC:AES256:gAAAAABhZ...}
MT5_SERVER=Alpari-MT5-Demo
MT5_PATH=C:/Program Files/Alpari MT5/terminal64.exe

# ===========================================
# API Keys (зашифрованные)
# ===========================================
FINNHUB_API_KEY=${ENC:AES256:gAAAAABhZ...}
ALPHA_VANTAGE_API_KEY=${ENC:AES256:gAAAAABhZ...}
NEWS_API_KEY=${ENC:AES256:gAAAAABhZ...}

# ===========================================
# Encryption Key
# ===========================================
ENCRYPTION_KEY=ZmDfc37_60Gj2W5q3lLq8d9F3h5K7j2n4m6p8r0s=
```

### Проверка загрузки

```bash
python -c "from src.core.config_loader import load_config; c = load_config(); print('MT5 Login:', c.MT5_LOGIN)"
```

---

## МИГРАЦИЯ СО СТАРОЙ КОНФИГУРАЦИИ

### Шаг 1: Резервное копирование

```bash
# Создайте резервную копию старой конфигурации
cp configs/settings.json configs/settings.json.backup
```

### Шаг 2: Извлечение чувствительных данных

Откройте `configs/settings.json` и найдите:

```json
{
    "MT5_LOGIN": "52565344",
    "MT5_PASSWORD": "*u5qCsTe",
    "FINNHUB_API_KEY": "d3jic09r01qkv9jvr6v0d3jic09r01qkv9jvr6vg",
    ...
}
```

### Шаг 3: Шифрование и перенос

```bash
# Сгенерируйте ключ
python scripts/encrypt_config.py generate-key

# Добавьте ключ в .env
echo ENCRYPTION_KEY=ваш_ключ >> configs/.env

# Зашифруйте и перенесите данные
python scripts/encrypt_config.py encrypt "*u5qCsTe"
# Скопируйте зашифрованное значение в .env
```

### Шаг 4: Очистка settings.json

Удалите чувствительные данные из `configs/settings.json`:

```json
{
    // ❌ УДАЛИТЬ эти поля:
    // "MT5_LOGIN": "...",
    // "MT5_PASSWORD": "...",
    // "FINNHUB_API_KEY": "...",
    
    // ✅ Оставить только нечувствительные настройки:
    "SYMBOLS_WHITELIST": ["EURUSD", "GBPUSD", ...],
    "RISK_PERCENTAGE": 0.5,
    ...
}
```

### Шаг 5: Проверка

```bash
# Проверьте загрузку конфигурации
python -c "from src.core.config_loader import load_config; c = load_config(); print('OK' if c.MT5_LOGIN else 'ERROR')"
```

---

## TROUBLESHOOTING

### Ошибка: "ENCRYPTION_KEY не установлен"

**Решение:**
```bash
# Установите ключ шифрования
export ENCRYPTION_KEY=ваш_ключ

# Или добавьте в .env
echo ENCRYPTION_KEY=ваш_ключ >> configs/.env
```

### Ошибка: "Неверный токен расшифровки"

**Причина:** Ключ шифрования не совпадает с тем, которым шифровали

**Решение:**
1. Найдите оригинальный ключ
2. Или перешифруйте данные новым ключом:
   ```bash
   python scripts/encrypt_config.py encrypt "ваш_пароль"
   ```

### Ошибка: "MT5_PASSWORD не найден"

**Причина:** Пароль не загружен из .env

**Решение:**
1. Проверьте наличие файла `configs/.env`
2. Убедитесь, что `MT5_PASSWORD` указан
3. Проверьте формат: `${ENC:AES256:...}`

### Система работает без шифрования

**Причина:** ENCRYPTION_KEY не установлен

**Проверка:**
```bash
python -c "import os; print('ENCRYPTION_KEY установлен' if os.environ.get('ENCRYPTION_KEY') else 'ENCRYPTION_KEY НЕ установлен')"
```

---

## БЕЗОПАСНОСТЬ

### ✅ Лучшие практики

1. **Никогда не коммитьте .env в репозиторий**
   ```bash
   # Проверьте .gitignore
   echo "configs/.env" >> .gitignore
   ```

2. **Храните ключ шифрования отдельно**
   - В CI/CD используйте secrets/variables
   - На сервере: переменные окружения системы

3. **Регулярно меняйте ключи**
   ```bash
   # Раз в 90 дней
   python scripts/encrypt_config.py generate-key
   ```

4. **Ограничьте доступ к файлам**
   ```bash
   # Windows
   icacls configs\.env /grant:r %USERNAME%:R
   
   # Linux/Mac
   chmod 600 configs/.env
   ```

### ❌ Чего избегать

- Не храните .env в облаках (Dropbox, Google Drive)
- Не передавайте ключи по email/мессенджерам
- Не используйте один ключ для нескольких проектов

---

## API ДЛЯ РАЗРАБОТЧИКОВ

### Использование в коде

```python
from src.core.secure_config import SecureConfigLoader

# Инициализация
loader = SecureConfigLoader()

# Расшифровка
password = loader.decrypt(os.environ.get('MT5_PASSWORD'))

# Загрузка учётных данных
mt5_creds = loader.load_mt5_credentials()
print(mt5_creds['login'])
print(mt5_creds['password'])  # Расшифровано

# Загрузка API ключей
api_keys = loader.load_api_keys()
print(api_keys['finnhub'])
```

### Шифрование в коде

```python
from src.core.secure_config import SecureConfigLoader

key = SecureConfigLoader.generate_key()
encrypted = SecureConfigLoader.encrypt_value("mypassword", key)
decrypted = SecureConfigLoader.decrypt(encrypted, key)
```

---

## ССЫЛКИ

- [Cryptography Fernet Documentation](https://cryptography.io/en/latest/fernet/)
- [Python-dotenv Documentation](https://pypi.org/project/python-dotenv/)
- [Pydantic Settings Documentation](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

---

*Документ составлен: 27 марта 2026*  
*Обновлено: 27 марта 2026*
