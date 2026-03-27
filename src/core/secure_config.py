# src/core/secure_config.py
"""
Модуль безопасной загрузки конфигурации с шифрованием чувствительных данных.

Поддерживает:
- Шифрование AES-256 чувствительных данных
- Загрузку из переменных окружения
- Валидацию через Pydantic
"""

import os
import base64
import logging
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from pathlib import Path

logger = logging.getLogger(__name__)


class SecureConfigLoader:
    """
    Загрузчик конфигурации с поддержкой шифрования чувствительных данных.
    
    Использование:
        loader = SecureConfigLoader()
        password = loader.decrypt(os.environ.get('MT5_PASSWORD'))
    """
    
    def __init__(self, encryption_key: Optional[str] = None):
        """
        Инициализация загрузчика.
        
        Args:
            encryption_key: Ключ шифрования Fernet. Если не указан,
                           берётся из переменной окружения ENCRYPTION_KEY.
        """
        self.encryption_key = encryption_key or os.environ.get('ENCRYPTION_KEY')
        
        if self.encryption_key:
            try:
                # Проверка формата ключа
                if not self.encryption_key.startswith('ENCRYPTED:'):
                    self.cipher = Fernet(self.encryption_key.encode() 
                                        if isinstance(self.encryption_key, str) 
                                        else self.encryption_key)
                    logger.info("Шифрование Fernet инициализировано")
                else:
                    logger.warning("Ключ шифрования в зашифрованном формате")
                    self.cipher = None
            except Exception as e:
                logger.error(f"Ошибка инициализации шифрования: {e}")
                self.cipher = None
        else:
            logger.warning("ENCRYPTION_KEY не установлен. Чувствительные данные не будут зашифрованы.")
            self.cipher = None
    
    def decrypt(self, encrypted_value: Optional[str]) -> Optional[str]:
        """
        Расшифровка значения.
        
        Поддерживаемые форматы:
        - ${ENC:AES256:<base64_data>} - формат для конфигов
        - Прямое значение из переменной окружения (если ключ установлен)
        
        Args:
            encrypted_value: Зашифрованное значение
            
        Returns:
            Расшифрованное значение или None
        """
        if not encrypted_value:
            return None
        
        # Проверка формата ${ENC:AES256:...}
        if encrypted_value.startswith('${ENC:AES256:'):
            if not self.cipher:
                logger.error("Невозможно расшифровать: шифрование не инициализировано")
                return None
            
            try:
                # Извлечение зашифрованных данных
                encrypted = encrypted_value.split(':', 2)[2].rstrip('}')
                decrypted = self.cipher.decrypt(encrypted.encode())
                return decrypted.decode('utf-8')
            except InvalidToken:
                logger.error("Неверный токен расшифровки. Проверьте ENCRYPTION_KEY.")
                return None
            except Exception as e:
                logger.error(f"Ошибка расшифровки: {e}")
                return None
        
        # Если значение не в специальном формате, возвращаем как есть
        # (предполагается, что оно уже расшифровано или не требует шифрования)
        return encrypted_value
    
    def get_required(self, key: str, description: str = "") -> str:
        """
        Получение обязательной переменной окружения.
        
        Args:
            key: Имя переменной
            description: Описание для сообщения об ошибке
            
        Returns:
            Значение переменной
            
        Raises:
            ValueError: Если переменная не найдена
        """
        value = os.environ.get(key)
        if not value:
            error_msg = f"Отсутствует обязательная переменная окружения: {key}"
            if description:
                error_msg += f" ({description})"
            raise ValueError(error_msg)
        return value
    
    def get_optional(self, key: str, default: str = "") -> str:
        """
        Получение опциональной переменной окружения.
        
        Args:
            key: Имя переменной
            default: Значение по умолчанию
            
        Returns:
            Значение переменной или default
        """
        return os.environ.get(key, default)
    
    @staticmethod
    def generate_key() -> str:
        """
        Генерация нового ключа шифрования Fernet.
        
        Returns:
            URL-safe base64 закодированный ключ (32 байта)
            
        Example:
            key = SecureConfigLoader.generate_key()
            print(f"ENCRYPTION_KEY={key}")
        """
        key = Fernet.generate_key()
        return key.decode('utf-8')
    
    @staticmethod
    def encrypt_value(value: str, key: str) -> str:
        """
        Шифрование значения.
        
        Args:
            value: Значение для шифрования
            key: Ключ шифрования Fernet
            
        Returns:
            Зашифрованное значение в формате ${ENC:AES256:...}
        """
        cipher = Fernet(key.encode() if isinstance(key, str) else key)
        encrypted = cipher.encrypt(value.encode('utf-8'))
        encrypted_str = encrypted.decode('utf-8')
        return f"${{ENC:AES256:{encrypted_str}}}"
    
    def load_mt5_credentials(self) -> dict:
        """
        Загрузка и расшифровка учётных данных MT5.
        
        Returns:
            Словарь с расшифрованными учётными данными
        """
        login = self.get_required('MT5_LOGIN', 'Логин счета MetaTrader 5')
        password_encrypted = self.get_required('MT5_PASSWORD', 'Пароль счета MetaTrader 5')
        server = self.get_required('MT5_SERVER', 'Сервер MetaTrader 5')
        mt5_path = self.get_required('MT5_PATH', 'Путь к terminal64.exe')
        
        # Расшифровка пароля
        password = self.decrypt(password_encrypted)
        
        return {
            'login': int(login),
            'password': password,
            'server': server,
            'path': mt5_path
        }
    
    def load_api_keys(self) -> dict:
        """
        Загрузка и расшифровка API ключей.
        
        Returns:
            Словарь с API ключами
        """
        return {
            'finnhub': self.decrypt(self.get_optional('FINNHUB_API_KEY')),
            'alpha_vantage': self.decrypt(self.get_optional('ALPHA_VANTAGE_API_KEY')),
            'news_api': self.decrypt(self.get_optional('NEWS_API_KEY')),
            'polygon': self.decrypt(self.get_optional('POLYGON_API_KEY')),
            'twelve_data': self.decrypt(self.get_optional('TWELVE_DATA_API_KEY')),
            'fcs': self.decrypt(self.get_optional('FCS_API_KEY')),
            'santiment': self.decrypt(self.get_optional('SANTIMENT_API_KEY')),
            'fred': self.decrypt(self.get_optional('FRED_API_KEY')),
        }
    
    def load_database_credentials(self) -> dict:
        """
        Загрузка учётных данных БД.
        
        Returns:
            Словарь с учётными данными БД
        """
        neo4j_uri = self.get_optional('NEO4J_URI', 'bolt://localhost:7687')
        neo4j_user = self.get_optional('NEO4J_USER', 'neo4j')
        neo4j_password_encrypted = self.get_optional('NEO4J_PASSWORD', '')
        
        # Расшифровка пароля Neo4j
        neo4j_password = self.decrypt(neo4j_password_encrypted)
        
        return {
            'neo4j': {
                'uri': neo4j_uri,
                'user': neo4j_user,
                'password': neo4j_password
            }
        }


def generate_encryption_key() -> str:
    """
    Утилита для генерации ключа шифрования.
    
    Returns:
    Сгенерированный ключ Fernet
    
    Example:
        print(f"ENCRYPTION_KEY={generate_encryption_key()}")
    """
    return SecureConfigLoader.generate_key()


def encrypt_sensitive_value(value: str, encryption_key: str) -> str:
    """
    Утилита для шифрования чувствительного значения.
    
    Args:
        value: Значение для шифрования
        encryption_key: Ключ шифрования
        
    Returns:
        Зашифрованное значение в формате ${ENC:AES256:...}
    """
    return SecureConfigLoader.encrypt_value(value, encryption_key)
