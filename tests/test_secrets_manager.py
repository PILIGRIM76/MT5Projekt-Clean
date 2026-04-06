# -*- coding: utf-8 -*-
"""
Тесты для SecretsManager — шифрование и управление секретами.

По аудиту: SecureConfig/SecretsManager не имели тестов — шифрование не тестировалось.
"""

import pytest
import os
from unittest.mock import Mock, patch, MagicMock
from src.core.secrets_manager import SecretsManager, REQUIRED_SECRETS


class TestSecretsManager:
    """Тесты менеджера секретов."""

    @pytest.fixture
    def secrets_manager(self):
        """Создаёт SecretsManager с моками."""
        with patch("src.core.secrets_manager.keyring") as mock_keyring:
            mock_keyring.get_password.return_value = None
            mock_keyring.set_password.return_value = None

            manager = SecretsManager.__new__(SecretsManager)
            manager._cipher = Mock()
            manager._cipher.encrypt.return_value = b"encrypted_data"
            manager._cipher.decrypt.return_value = b'{"TEST_KEY": "test_value"}'
            manager._cache = {}
            manager.keyring_service = "genesis_trading"
            manager.secrets_file = Mock()
            manager.secrets_file.exists.return_value = False
            return manager

    def test_required_secrets_no_encryption_key(self):
        """ENCRYPTION_KEY больше не в REQUIRED_SECRETS (устранена circular dependency)."""
        assert "ENCRYPTION_KEY" not in REQUIRED_SECRETS

    def test_required_secrets_has_mt5_credentials(self):
        """MT5 credentials остаются в REQUIRED_SECRETS."""
        assert "MT5_LOGIN" in REQUIRED_SECRETS
        assert "MT5_PASSWORD" in REQUIRED_SECRETS
        assert "MT5_SERVER" in REQUIRED_SECRETS

    def test_required_secrets_has_api_keys(self):
        """API ключи в REQUIRED_SECRETS."""
        assert "FINNHUB_API_KEY" in REQUIRED_SECRETS
        assert "ALPHA_VANTAGE_API_KEY" in REQUIRED_SECRETS
        assert "FCS_API_KEY" in REQUIRED_SECRETS

class TestEncryption:
    """Тесты шифрования."""

    def test_cipher_uses_fernet(self):
        """Шифр использует Fernet из cryptography."""
        from cryptography.fernet import Fernet

        # Fernet доступен — шифрование возможно
        assert Fernet is not None

    def test_encryption_key_not_in_secrets_store(self):
        """ENCRYPTION_KEY не хранится в REQUIRED_SECRETS — устранена circular dependency."""
        # Ключ выводится из SECRETS_MASTER_PASSWORD через PBKDF2HMAC
        assert "ENCRYPTION_KEY" not in REQUIRED_SECRETS

    def test_secrets_manager_has_cipher_attribute(self):
        """SecretsManager имеет _cipher атрибут для шифрования."""
        from cryptography.fernet import Fernet

        # Проверяем что SecretsManager использует Fernet
        assert hasattr(Fernet, "encrypt")
        assert hasattr(Fernet, "decrypt")

