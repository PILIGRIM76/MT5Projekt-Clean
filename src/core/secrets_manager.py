# src/core/secrets_manager.py
"""
Secrets Manager — Менеджер безопасного хранения секретов.

Уровни хранения (по приоритету):
1. Environment Variables (переменные окружения)
2. Windows Credential Manager (через keyring)
3. Encrypted File (шифрованный файл как fallback)

Обеспечивает:
- Шифрование AES-256
- Аудит доступа
- Валидацию наличия секретов
- Миграцию из settings.json
"""

import base64
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)


# Список требуемых секретов для Genesis Trading System
REQUIRED_SECRETS = [
    # MT5 Credentials
    "MT5_LOGIN",
    "MT5_PASSWORD",
    "MT5_SERVER",
    # API Keys
    "FINNHUB_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
    "NEWS_API_KEY",
    "FCS_API_KEY",
    # Alerting
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "PUSHOVER_USER_KEY",
    "PUSHOVER_API_TOKEN",
    "ALERT_EMAIL_FROM",
    "ALERT_EMAIL_PASSWORD",
    "ALERT_EMAIL_RECIPIENTS",
    # Encryption
    "ENCRYPTION_KEY",
    # Database
    "DATABASE_PASSWORD",
    "POSTGRES_PASSWORD",
    # Grafana
    "GRAFANA_ADMIN_PASSWORD",
]

# Опциональные секреты
OPTIONAL_SECRETS = [
    "POLYGON_API_KEY",
    "TWELVE_DATA_API_KEY",
    "TWITTER_BEARER_TOKEN",
    "SANTIMENT_API_KEY",
    "FRED_API_KEY",
    "NEO4J_URI",
    "NEO4J_USER",
    "NEO4J_PASSWORD",
]


class SecretsManager:
    """
    Менеджер безопасного хранения секретов для Genesis Trading System.

    Атрибуты:
        secrets_file: Путь к зашифрованному файлу секретов
        keyring_service: Имя сервиса для Windows Credential Manager
    """

    def __init__(self, secrets_file: Optional[str] = None):
        """
        Инициализация Secrets Manager.

        Args:
            secrets_file: Путь к зашифрованному файлу (по умолчанию: secrets/encrypted_secrets.json)
        """
        self._lock = Lock()

        # Пути
        if secrets_file:
            self.secrets_file = Path(secrets_file)
        else:
            # По умолчанию в папке проекта
            if getattr(sys, "frozen", False):
                base_path = Path(sys.executable).parent
            else:
                base_path = Path(__file__).parent.parent.parent
            self.secrets_file = base_path / "secrets" / "encrypted_secrets.json"

        self.keyring_service = "GenesisTrading"

        # Кэш секретов
        self._secrets_cache: Dict[str, str] = {}
        self._access_log: List[Dict[str, Any]] = []

        # Инициализация шифрования
        self._cipher: Optional[Fernet] = None
        self._init_cipher()

        logger.info("Secrets Manager инициализирован")
        logger.info(f"  - Secrets File: {self.secrets_file}")
        logger.info(f"  - Keyring Service: {self.keyring_service}")

    def _init_cipher(self) -> None:
        """Инициализирует шифр для зашифрованного файла."""
        # Генерируем ключ из мастер-пароля
        # В production лучше использовать HSM или Azure Key Vault
        master_password = os.environ.get("SECRETS_MASTER_PASSWORD", "default_dev_password_change_in_production")

        salt = b"genesis_trading_salt_v1"  # В production использовать случайную соль

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(master_password.encode()))
        self._cipher = Fernet(key)

    def get_secret(self, key: str, cache: bool = True) -> Optional[str]:
        """
        Получает секрет из безопасного хранилища.

        Приоритет:
        1. Environment Variables
        2. Windows Credential Manager
        3. Encrypted File

        Args:
            key: Ключ секрета
            cache: Кэшировать ли значение

        Returns:
            Значение секрета или None
        """
        # Проверяем кэш
        if cache and key in self._secrets_cache:
            self._log_access(key, "cache", True)
            return self._secrets_cache[key]

        # 1. Environment Variables
        value = os.environ.get(key)
        if value:
            if cache:
                self._secrets_cache[key] = value
            self._log_access(key, "env", True)
            return value

        # 2. Windows Credential Manager
        try:
            import keyring

            value = keyring.get_password(self.keyring_service, key)
            if value:
                if cache:
                    self._secrets_cache[key] = value
                self._log_access(key, "keyring", True)
                return value
        except ImportError:
            logger.debug("keyring не установлен, пропускаем Credential Manager")
        except Exception as e:
            logger.debug(f"Ошибка чтения из keyring: {e}")

        # 3. Encrypted File
        value = self._get_from_encrypted_file(key)
        if value:
            if cache:
                self._secrets_cache[key] = value
            self._log_access(key, "file", True)
            return value

        # Не найдено
        self._log_access(key, "all", False)
        return None

    def store_secret(self, key: str, value: str, store_in_env: bool = False) -> bool:
        """
        Сохраняет секрет в безопасное хранилище.

        Args:
            key: Ключ секрета
            value: Значение секрета
            store_in_env: Сохранять ли в environment (не рекомендуется для production)

        Returns:
            True если успешно
        """
        with self._lock:
            try:
                # 1. Windows Credential Manager (предпочтительно)
                try:
                    import keyring

                    keyring.set_password(self.keyring_service, key, value)
                    logger.info(f"Secret '{key}' сохранён в Credential Manager")

                    # Обновляем кэш
                    self._secrets_cache[key] = value
                    return True

                except ImportError:
                    logger.warning("keyring не установлен, используем зашифрованный файл")

                # 2. Encrypted File
                self._store_in_encrypted_file(key, value)
                logger.info(f"Secret '{key}' сохранён в зашифрованный файл")

                # Обновляем кэш
                self._secrets_cache[key] = value
                return True

            except Exception as e:
                logger.error(f"Ошибка сохранения секрета '{key}': {e}")
                return False

    def delete_secret(self, key: str) -> bool:
        """
        Удаляет секрет из хранилища.

        Args:
            key: Ключ секрета

        Returns:
            True если успешно
        """
        with self._lock:
            try:
                # Удаляем из Credential Manager
                try:
                    import keyring

                    keyring.delete_password(self.keyring_service, key)
                except Exception:
                    pass

                # Удаляем из кэша
                if key in self._secrets_cache:
                    del self._secrets_cache[key]

                # Удаляем из файла
                self._remove_from_encrypted_file(key)

                logger.info(f"Secret '{key}' удалён")
                return True

            except Exception as e:
                logger.error(f"Ошибка удаления секрета '{key}': {e}")
                return False

    def list_secrets(self) -> List[str]:
        """
        Возвращает список всех сохранённых ключей.

        Returns:
            Список ключей
        """
        keys = set()

        # Из кэша
        keys.update(self._secrets_cache.keys())

        # Из зашифрованного файла
        try:
            if self.secrets_file.exists():
                with open(self.secrets_file, "rb") as f:
                    encrypted_data = f.read()
                    decrypted_data = self._cipher.decrypt(encrypted_data)
                    data = json.loads(decrypted_data)
                    keys.update(data.keys())
        except Exception:
            pass

        return sorted(list(keys))

    def validate_required_secrets(self) -> Dict[str, bool]:
        """
        Проверяет наличие всех требуемых секретов.

        Returns:
            Словарь {ключ: наличие}
        """
        validation = {}

        for key in REQUIRED_SECRETS:
            value = self.get_secret(key, cache=False)
            validation[key] = bool(value)

            if not value:
                logger.warning(f"Требуемый секрет отсутствует: {key}")

        # Логируем результат
        missing = [k for k, v in validation.items() if not v]
        if missing:
            logger.error(f"Отсутствуют требуемые секреты: {missing}")
        else:
            logger.info("Все требуемые секреты присутствуют")

        return validation

    def export_encrypted(self, filepath: str, password: str) -> bool:
        """
        Экспортирует секреты в зашифрованный файл.

        Args:
            filepath: Путь к файлу экспорта
            password: Пароль для шифрования

        Returns:
            True если успешно
        """
        with self._lock:
            try:
                # Собираем все секреты
                secrets = {}
                for key in self.list_secrets():
                    value = self.get_secret(key, cache=False)
                    if value:
                        secrets[key] = value

                # Шифруем
                cipher = self._create_cipher_from_password(password)
                data_json = json.dumps(secrets, indent=2)
                encrypted_data = cipher.encrypt(data_json.encode())

                # Сохраняем
                with open(filepath, "wb") as f:
                    f.write(encrypted_data)

                logger.info(f"Секреты экспортированы в {filepath}")
                return True

            except Exception as e:
                logger.error(f"Ошибка экспорта секретов: {e}")
                return False

    def import_encrypted(self, filepath: str, password: str) -> bool:
        """
        Импортирует секреты из зашифрованного файла.

        Args:
            filepath: Путь к файлу импорта
            password: Пароль для расшифровки

        Returns:
            True если успешно
        """
        with self._lock:
            try:
                # Читаем файл
                with open(filepath, "rb") as f:
                    encrypted_data = f.read()

                # Расшифровываем
                cipher = self._create_cipher_from_password(password)
                decrypted_data = cipher.decrypt(encrypted_data)
                secrets = json.loads(decrypted_data)

                # Сохраняем каждый секрет
                for key, value in secrets.items():
                    self.store_secret(key, value)

                logger.info(f"Секреты импортированы из {filepath}")
                return True

            except Exception as e:
                logger.error(f"Ошибка импорта секретов: {e}")
                return False

    def get_access_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Возвращает журнал доступа к секретам.

        Args:
            limit: Максимальное количество записей

        Returns:
            Список записей журнала
        """
        with self._lock:
            return self._access_log[-limit:]

    def migrate_from_settings(self, settings_path: str) -> Dict[str, bool]:
        """
        Мигрирует секреты из settings.json в безопасное хранилище.

        Args:
            settings_path: Путь к settings.json

        Returns:
            Словарь {ключ: успех миграции}
        """
        migration_results = {}

        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)

            # Ключи для миграции
            keys_to_migrate = [
                "MT5_LOGIN",
                "MT5_PASSWORD",
                "MT5_SERVER",
                "FINNHUB_API_KEY",
                "ALPHA_VANTAGE_API_KEY",
                "NEWS_API_KEY",
                "FCS_API_KEY",
                "TELEGRAM_API_ID",
                "TELEGRAM_API_HASH",
                "TELEGRAM_BOT_TOKEN",
                "TELEGRAM_CHAT_ID",
                "PUSHOVER_USER_KEY",
                "PUSHOVER_API_TOKEN",
                "ENCRYPTION_KEY",
            ]

            for key in keys_to_migrate:
                if key in settings:
                    value = settings[key]
                    if value and value not in ["", "your_password_here", "your_api_key_here"]:
                        success = self.store_secret(key, str(value))
                        migration_results[key] = success

                        if success:
                            logger.info(f"Мигрирован секрет: {key}")
                        else:
                            logger.error(f"Ошибка миграции секрета: {key}")

            return migration_results

        except Exception as e:
            logger.error(f"Ошибка миграции из settings.json: {e}")
            return migration_results

    def _get_from_encrypted_file(self, key: str) -> Optional[str]:
        """Получает секрет из зашифрованного файла."""
        try:
            if not self.secrets_file.exists():
                logger.debug(f"Secrets file не существует: {self.secrets_file}")
                return None

            logger.debug(f"Чтение секрета '{key}' из {self.secrets_file}")

            with open(self.secrets_file, "rb") as f:
                encrypted_data = f.read()

            logger.debug(f"Прочитано {len(encrypted_data)} байт зашифрованных данных")

            try:
                decrypted_data = self._cipher.decrypt(encrypted_data)
            except Exception as decrypt_error:
                logger.error(f"Ошибка расшифровки: {decrypt_error}")
                logger.error("Возможно, файл был повреждён или используется неверный ключ шифрования")
                return None

            data = json.loads(decrypted_data)
            logger.debug(f"Успешно расшифровано. Количество секретов: {len(data)}")
            logger.debug(f"Доступные ключи: {list(data.keys())}")

            value = data.get(key)
            if value:
                logger.debug(f"Секрет '{key}' найден")
            else:
                logger.debug(f"Секрет '{key}' не найден в файле")

            return value

        except Exception as e:
            logger.error(f"Ошибка чтения из зашифрованного файла: {e}", exc_info=True)
            return None

    def _store_in_encrypted_file(self, key: str, value: str) -> None:
        """Сохраняет секрет в зашифрованный файл."""
        # Читаем существующие данные
        data = {}
        if self.secrets_file.exists():
            try:
                with open(self.secrets_file, "rb") as f:
                    encrypted_data = f.read()
                decrypted_data = self._cipher.decrypt(encrypted_data)
                data = json.loads(decrypted_data)
            except Exception:
                data = {}

        # Добавляем новый секрет
        data[key] = value

        # Шифруем и сохраняем
        encrypted_data = self._cipher.encrypt(json.dumps(data).encode())

        # Создаём директорию если не существует
        self.secrets_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self.secrets_file, "wb") as f:
            f.write(encrypted_data)

    def _remove_from_encrypted_file(self, key: str) -> None:
        """Удаляет секрет из зашифрованного файла."""
        try:
            if not self.secrets_file.exists():
                return

            with open(self.secrets_file, "rb") as f:
                encrypted_data = f.read()

            decrypted_data = self._cipher.decrypt(encrypted_data)
            data = json.loads(decrypted_data)

            if key in data:
                del data[key]

                if data:
                    encrypted_data = self._cipher.encrypt(json.dumps(data).encode())
                    with open(self.secrets_file, "wb") as f:
                        f.write(encrypted_data)
                else:
                    self.secrets_file.unlink()

        except Exception as e:
            logger.debug(f"Ошибка удаления из зашифрованного файла: {e}")

    def _create_cipher_from_password(self, password: str) -> Fernet:
        """Создаёт шифр из пароля."""
        salt = b"genesis_trading_salt_v1"

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return Fernet(key)

    def _log_access(self, key: str, source: str, success: bool) -> None:
        """Логирует доступ к секрету."""
        entry = {"timestamp": datetime.now().isoformat(), "key": key, "source": source, "success": success}

        self._access_log.append(entry)

        # Ограничиваем размер лога
        if len(self._access_log) > 1000:
            self._access_log = self._access_log[-1000:]

        if not success:
            logger.warning(f"Неудачная попытка доступа к секрету: {key}")


# Глобальный экземпляр (singleton)
_secrets_manager: Optional[SecretsManager] = None


def get_secrets_manager() -> SecretsManager:
    """Возвращает глобальный экземпляр Secrets Manager."""
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
    return _secrets_manager


def get_secret(key: str) -> Optional[str]:
    """Получает секрет через глобальный менеджер."""
    return get_secrets_manager().get_secret(key)


def store_secret(key: str, value: str) -> bool:
    """Сохраняет секрет через глобальный менеджер."""
    return get_secrets_manager().store_secret(key, value)
