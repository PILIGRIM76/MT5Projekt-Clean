"""
Тесты для DatabaseManager - ключевые методы

Фокус на тестировании основных методов без создания реальной БД.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pandas as pd
import pytest


@pytest.fixture
def mock_session():
    """Фикстура для мок сессии SQLAlchemy"""
    session = Mock()
    session.query = Mock()
    session.add = Mock()
    session.commit = Mock()
    session.rollback = Mock()
    session.close = Mock()
    session.merge = Mock()
    session.delete = Mock()
    return session


class TestDatabaseManagerDirectives:
    """Тесты директив"""

    def test_save_directives_success(self, mock_session):
        """Тест успешного сохранения директив"""
        from src.db.database_manager import ActiveDirective, DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)

        directives = [
            ActiveDirective(
                directive_type="TEST_1",
                value="value1",
                reason="reason1",
                expires_at=datetime.utcnow() + timedelta(days=1),
            )
        ]

        DatabaseManager.save_directives(dm, directives)

        mock_session.merge.assert_called()
        mock_session.commit.assert_called()

    def test_save_directives_error_handling(self, mock_session):
        """Тест обработки ошибок при сохранении директив"""
        from src.db.database_manager import ActiveDirective, DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)
        mock_session.commit.side_effect = Exception("DB Error")

        directives = [
            ActiveDirective(
                directive_type="TEST",
                value="value",
                reason="reason",
                expires_at=datetime.utcnow() + timedelta(days=1),
            )
        ]

        # Не должно вызывать исключений
        DatabaseManager.save_directives(dm, directives)
        mock_session.rollback.assert_called()

    def test_get_active_directives_success(self, mock_session):
        """Тест успешного получения активных директив"""
        from src.db.database_manager import ActiveDirective, DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)

        mock_directives = [
            ActiveDirective(
                directive_type="ACTIVE_1",
                value="value1",
                reason="reason1",
                expires_at=datetime.utcnow() + timedelta(days=1),
            )
        ]

        mock_session.query.return_value.filter.return_value.all.return_value = mock_directives

        directives = DatabaseManager.get_active_directives(dm)

        assert len(directives) == 1
        assert directives[0].directive_type == "ACTIVE_1"

    def test_get_active_directives_expired(self, mock_session):
        """Тест что истекшие директивы не возвращаются"""
        from src.db.database_manager import ActiveDirective, DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)

        mock_directives = [
            ActiveDirective(
                directive_type="EXPIRED_1",
                value="value1",
                reason="reason1",
                expires_at=datetime.utcnow() - timedelta(days=1),  # Истекла
            )
        ]

        mock_session.query.return_value.filter.return_value.all.return_value = mock_directives

        directives = DatabaseManager.get_active_directives(dm)

        # Истекшие директивы должны быть отфильтрованы query
        assert len(directives) == 0

    def test_delete_directive_success(self, mock_session):
        """Тест успешного удаления директивы"""
        from src.db.database_manager import ActiveDirective, DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)

        mock_directive = ActiveDirective(
            directive_type="TO_DELETE",
            value="value",
            reason="reason",
            expires_at=datetime.utcnow() + timedelta(days=1),
        )

        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_directive

        result = DatabaseManager.delete_directive_by_type(dm, "TO_DELETE")

        assert result is True
        mock_session.delete.assert_called_once_with(mock_directive)
        mock_session.commit.assert_called()

    def test_delete_directive_not_found(self, mock_session):
        """Тест удаления несуществующей директивы"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        result = DatabaseManager.delete_directive_by_type(dm, "NONEXISTENT")

        assert result is False
        mock_session.delete.assert_not_called()


class TestDatabaseManagerTradeHistory:
    """Тесты истории торгов"""

    def test_get_trade_history_success(self, mock_session):
        """Тест успешного получения истории торгов"""
        from src.db.database_manager import DatabaseManager, TradeHistory

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)

        mock_trades = [
            TradeHistory(
                ticket=12345,
                symbol="BTCUSD",
                trade_type="BUY",
                volume=0.1,
                price_open=50000.0,
                price_close=51000.0,
                time_open=datetime.utcnow(),
                time_close=datetime.utcnow(),
                profit=100.0,
                timeframe="H1",
            )
        ]

        mock_session.query.return_value.order_by.return_value.all.return_value = mock_trades

        trades = DatabaseManager.get_trade_history(dm)

        assert len(trades) == 1
        assert trades[0].ticket == 12345
        assert trades[0].symbol == "BTCUSD"

    def test_get_trade_history_empty(self, mock_session):
        """Тест получения пустой истории торгов"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)
        mock_session.query.return_value.order_by.return_value.all.return_value = []

        trades = DatabaseManager.get_trade_history(dm)

        assert len(trades) == 0

    def test_get_trade_history_error_handling(self, mock_session):
        """Тест обработки ошибок при получении истории торгов"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)
        mock_session.query.side_effect = Exception("DB Error")

        trades = DatabaseManager.get_trade_history(dm)

        assert trades == []


class TestDatabaseManagerXaiData:
    """Тесты XAI данных"""

    def test_get_xai_data_success(self, mock_session):
        """Тест успешного получения XAI данных"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)

        class MockTrade:
            xai_data = json.dumps({"shap_values": {"feature1": 0.5}})

        mock_session.query.return_value.filter_by.return_value.first.return_value = MockTrade()

        result = DatabaseManager.get_xai_data(dm, 12345)

        assert result is not None
        assert "shap_values" in result

    def test_get_xai_data_not_found(self, mock_session):
        """Тест когда XAI данные не найдены"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        result = DatabaseManager.get_xai_data(dm, 99999)

        assert result is None

    def test_get_xai_data_invalid_json(self, mock_session):
        """Тест обработки невалидного JSON"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)

        class MockTrade:
            xai_data = "invalid json{"

        mock_session.query.return_value.filter_by.return_value.first.return_value = MockTrade()

        result = DatabaseManager.get_xai_data(dm, 12345)

        assert result is None


class TestDatabaseManagerChampionInfo:
    """Тесты информации о чемпионе"""

    def test_get_champion_info_success(self, mock_session):
        """Тест успешного получения информации о чемпионе"""
        from src.db.database_manager import DatabaseManager, TrainedModel

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)

        mock_model = TrainedModel(
            id=100,
            symbol="BTCUSD",
            timeframe=60,
            model_type="LSTM",
            model_data=b"model_bytes",
            version=2,
            is_champion=True,
            features_json='["open", "close"]',
            performance_report='{"sharpe": 1.5}',
        )

        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_model

        with patch("src.db.database_manager.pickle.loads", return_value=Mock()):
            result = DatabaseManager.get_champion_info(dm, "BTCUSD", 60)

            assert result is not None
            assert "model" in result
            assert result["model_type"] == "LSTM"
            assert result["version"] == 2

    def test_get_champion_info_not_found(self, mock_session):
        """Тест когда чемпион не найден"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        result = DatabaseManager.get_champion_info(dm, "NONEXISTENT", 60)

        assert result is None


class TestDatabaseManagerCandleData:
    """Тесты данных свечей"""

    def test_get_candle_data_success(self, mock_session):
        """Тест успешного получения данных свечей"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)

        class MockCandle:
            time = datetime.utcnow()
            open = 100
            high = 105
            low = 99
            close = 102
            volume = 1000

        mock_candles = [MockCandle() for _ in range(10)]

        mock_session.query.return_value.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = (
            mock_candles
        )

        df = DatabaseManager.get_candle_data(dm, "BTCUSD", "H1", limit=10)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 10
        assert "close" in df.columns

    def test_get_candle_data_empty(self, mock_session):
        """Тест получения пустых данных свечей"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)
        mock_session.query.return_value.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = []

        df = DatabaseManager.get_candle_data(dm, "BTCUSD", "H1", limit=10)

        assert df is None


class TestDatabaseManagerAuditLog:
    """Тесты аудита торгов"""

    def test_create_trade_audit_success(self, mock_session):
        """Тест успешного создания аудита торговли"""
        from src.db.database_manager import DatabaseManager, TradeAudit

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)

        mock_audit = Mock()
        mock_audit.id = 1

        with patch.object(TradeAudit, "__init__", return_value=None):
            audit_id = DatabaseManager.create_trade_audit(
                dm,
                trade_ticket=12345,
                decision_maker="AI_Model",
                strategy_name="LSTM",
                market_regime="Trend",
                consensus_score=0.8,
            )

            assert audit_id == 1
            mock_session.add.assert_called()
            mock_session.commit.assert_called()

    def test_create_trade_audit_error_handling(self, mock_session):
        """Тест обработки ошибок при создании аудита"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)
        mock_session.commit.side_effect = Exception("DB Error")

        audit_id = DatabaseManager.create_trade_audit(
            dm,
            trade_ticket=12345,
            decision_maker="AI_Model",
        )

        assert audit_id is None
        mock_session.rollback.assert_called()

    def test_get_audit_logs_success(self, mock_session):
        """Тест успешного получения логов аудита"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)

        mock_logs = [Mock(id=1, trade_ticket=12345, decision_maker="AI_Model") for _ in range(5)]

        mock_session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = (
            mock_logs
        )

        logs = DatabaseManager.get_audit_logs(dm, limit=5)

        assert len(logs) == 5


class TestDatabaseManagerHumanFeedback:
    """Тесты обратной связи человека"""

    def test_save_human_feedback_success(self, mock_session):
        """Тест успешного сохранения обратной связи"""
        from src.db.database_manager import DatabaseManager, HumanFeedback

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)

        with patch.object(HumanFeedback, "__init__", return_value=None):
            market_state = {"price": 50000, "volume": 1000}

            result = DatabaseManager.save_human_feedback(
                dm,
                trade_ticket=12345,
                feedback=1,  # Positive
                market_state=market_state,
            )

            assert result is True
            mock_session.add.assert_called()
            mock_session.commit.assert_called()

    def test_save_human_feedback_error_handling(self, mock_session):
        """Тест обработки ошибок при сохранении обратной связи"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)
        mock_session.commit.side_effect = Exception("DB Error")

        result = DatabaseManager.save_human_feedback(
            dm,
            trade_ticket=12345,
            feedback=1,
            market_state={},
        )

        assert result is False
        mock_session.rollback.assert_called()

    def test_get_feedback_data_success(self, mock_session):
        """Тест успешного получения данных обратной связи"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)

        class MockFeedback:
            trade_ticket = 12345
            feedback = 1
            market_state_json = '{"price": 50000}'
            created_at = datetime.utcnow()

        mock_session.query.return_value.all.return_value = [MockFeedback()]

        data = DatabaseManager.get_feedback_data(dm)

        assert len(data) == 1
        assert data[0]["trade_ticket"] == 12345


class TestDatabaseManagerStrategyPerformance:
    """Тесты производительности стратегий"""

    def test_update_strategy_performance_success(self, mock_session):
        """Тест успешного обновления производительности стратегии"""
        from src.db.database_manager import DatabaseManager, StrategyPerformance

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)

        with patch.object(StrategyPerformance, "__init__", return_value=None):
            result = DatabaseManager.update_strategy_performance(
                dm,
                strategy_name="LSTM",
                market_regime="Trend",
                profit=100.0,
                win=False,
                trade_ticket=12345,
            )

            assert result is True
            mock_session.add.assert_called()
            mock_session.commit.assert_called()

    def test_update_strategy_performance_error_handling(self, mock_session):
        """Тест обработки ошибок при обновлении производительности"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)
        mock_session.commit.side_effect = Exception("DB Error")

        result = DatabaseManager.update_strategy_performance(
            dm,
            strategy_name="LSTM",
            market_regime="Trend",
            profit=100.0,
            win=False,
            trade_ticket=12345,
        )

        assert result is False


class TestDatabaseManagerGraphData:
    """Тесты данных графа знаний"""

    def test_get_latest_relations_success(self, mock_session):
        """Тест успешного получения последних отношений"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)

        class MockRelation:
            subject = "FED"
            relation = "announces"
            object = "rate_decision"
            created_at = datetime.utcnow()

        mock_relations = [MockRelation() for _ in range(10)]

        mock_session.query.return_value.order_by.return_value.limit.return_value.all.return_value = mock_relations

        relations = DatabaseManager.get_latest_relations(dm, limit=50)

        assert len(relations) == 10
        assert relations[0]["subject"] == "FED"

    def test_get_graph_data_success(self, mock_session):
        """Тест успешного получения данных графа"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)

        class MockEntity:
            name = "FED"
            entity_type = "Organization"

        class MockRelation:
            subject = "FED"
            relation = "announces"
            object = "rate_decision"

        mock_entities = [MockEntity() for _ in range(5)]
        mock_relations = [MockRelation() for _ in range(5)]

        mock_session.query.return_value.limit.return_value.all.side_effect = [
            mock_entities,
            mock_relations,
        ]

        graph_data = DatabaseManager.get_graph_data(dm, limit=50)

        assert graph_data is not None
        assert "nodes" in graph_data
        assert "edges" in graph_data
        assert len(graph_data["nodes"]) == 5
        assert len(graph_data["edges"]) == 5


class TestDatabaseManagerLogTradeOutcomeToKG:
    """Тесты логирования результатов торгов в граф знаний"""

    def test_log_trade_outcome_to_kg_internal_success(self, mock_session, caplog):
        """Тест успешного логирования в граф знаний"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)

        result = DatabaseManager._log_trade_outcome_to_kg_internal(
            dm,
            trade_ticket=12345,
            profit=100.0,
            market_regime="Trend",
            kg_cb_sentiment=0.5,
        )

        # Метод просто логирует, проверяем что сессия закрыта
        mock_session.close.assert_called()
        assert result is None

    def test_log_trade_outcome_to_kg_internal_error_handling(self, mock_session):
        """Тест обработки ошибок при логировании в граф знаний"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)
        mock_session.close.side_effect = Exception("DB Error")

        # Не должно вызывать исключений
        DatabaseManager._log_trade_outcome_to_kg_internal(
            dm,
            trade_ticket=12345,
            profit=100.0,
            market_regime="Trend",
            kg_cb_sentiment=0.5,
        )


class TestDatabaseManagerHelperMethods:
    """Тесты вспомогательных методов"""

    def test_get_all_logged_trade_tickets_success(self, mock_session):
        """Тест успешного получения всех тикетов торгов"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)

        class MockTrade:
            def __init__(self, ticket):
                self.ticket = ticket

        mock_trades = [MockTrade(12345), MockTrade(12346), MockTrade(12347)]

        mock_session.query.return_value.all.return_value = mock_trades

        tickets = DatabaseManager.get_all_logged_trade_tickets(dm)

        assert len(tickets) == 3
        assert 12345 in tickets

    def test_get_all_logged_trade_tickets_empty(self, mock_session):
        """Тест получения пустого списка тикетов"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)
        mock_session.query.return_value.all.return_value = []

        tickets = DatabaseManager.get_all_logged_trade_tickets(dm)

        assert tickets == set()

    def test_get_all_logged_trade_tickets_error_handling(self, mock_session):
        """Тест обработки ошибок при получении тикетов"""
        from src.db.database_manager import DatabaseManager

        dm = Mock()
        dm.Session = Mock(return_value=mock_session)
        mock_session.query.side_effect = Exception("DB Error")

        tickets = DatabaseManager.get_all_logged_trade_tickets(dm)

        assert tickets == set()
