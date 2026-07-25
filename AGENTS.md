# Genesis Trading System — AI Agent Instructions

## AI Mimo Protocol

**Полный протокол:** `F:\Obsidian_Vaults\Genesis\00_Meta\AI_Mimo_Protocol.md`

### Краткие правила:
1. **Obsidian First** — проверяй `F:\Obsidian_Vaults\Genesis` перед любым действием
2. **Bidirectional Sync** — код ↔ заметки всегда синхронны
3. **Integrity Check** — в конце каждого ответа: `🛡️ Integrity Check`

## Project Location
- **Код:** `F:\MT5Projekt-Clean`
- **Obsidian:** `F:\Obsidian_Vaults\Genesis`
- **Логи:** `F:\Enjen\database\logs\genesis_system.log`

## Run
```bash
cd F:\MT5Projekt-Clean
python main_pyside.py
```

## Architecture
- GUI: PySide6 (panels.py, charts.py, signals.py — миксины)
- Core: TradingSystem → EventBus → Services (ML, Orchestrator, Risk, Execution)
- Data: MT5 API → DataProvider → FeatureEngineer → ML Models
- DB: SQLite (local), PostgreSQL/TimescaleDB/QuestDB/Redis/Qdrant (Docker)

## Key Files
| File | Purpose |
|------|---------|
| `main_pyside.py` | Entry point (479 lines) |
| `src/gui/main_window_parts/panels.py` | GUI panels (1015 lines) |
| `src/gui/main_window_parts/signals.py` | Signal handlers (917 lines) |
| `src/gui/main_window_parts/charts.py` | Chart updates (354 lines) |
| `src/gui/live_data.py` | Live data timers (14 timers) |
| `src/core/trading_system.py` | Core trading logic |
| `src/core/services/` | ML, Orchestrator, Risk services |
| `configs/settings.json` | Configuration |

## MT5 Connection
- Login: 53057252
- Server: Alpari-MT5-Demo
- AutoTrading: Enabled
- Crypto: BITCOIN, BITCOIN CASH, ETHEREUM (trade on weekends)

## Critical Gotchas
| Issue | Fix |
|-------|-----|
| pyparsing ImportError | Use pyparsing==3.2.3 |
| MT5 Authorization failed | Check account expiry, create new demo |
| Chart shows single point | Timestamps already in seconds, don't divide by 1e9 |
| Candles appear as stripes | Use viewBox transform for X/Y scaling |
