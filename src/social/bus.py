# src/social/bus.py
"""
Шина данных для социального трейдинга.
Использует SQLite для межпроцессного взаимодействия (IPC).
Это позволяет запускать Мастера и Подписчика в разных процессах/терминалах.
"""

import logging
import sqlite3
import time
import json
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent.parent.parent / "social_signals.db"

class SocialSignalDB:
    def __init__(self):
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._create_table()
    
    def _create_table(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                master_ticket INTEGER,
                action TEXT,
                symbol TEXT,
                type INTEGER,
                volume REAL,
                price REAL,
                sl REAL,
                tp REAL,
                timestamp REAL,
                processed INTEGER DEFAULT 0
            )
        """)
        self.conn.commit()

    def publish(self, signal_data):
        """Сохранить сигнал в БД."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO signals (
                master_ticket, action, symbol, type, volume, price, sl, tp, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal_data.get('ticket'),
            signal_data.get('action'),
            signal_data.get('symbol'),
            signal_data.get('type'),
            signal_data.get('volume'),
            signal_data.get('price'),
            signal_data.get('sl'),
            signal_data.get('tp'),
            time.time()
        ))
        self.conn.commit()
        logger.info(f"[SocialBus] Сигнал сохранен в БД: {signal_data['action']} {signal_data['symbol']}")

    def get_new_signals(self) -> list:
        """Получить необработанные сигналы."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM signals WHERE processed = 0 ORDER BY id ASC")
        rows = cursor.fetchall()
        
        signals = []
        for row in rows:
            signals.append({
                'db_id': row[0],
                'master_ticket': row[1],
                'action': row[2],
                'symbol': row[3],
                'type': row[4],
                'volume': row[5],
                'price': row[6],
                'sl': row[7],
                'tp': row[8],
                'timestamp': row[9]
            })
        return signals

    def mark_processed(self, db_id):
        """Отметить сигнал как обработанный."""
        cursor = self.conn.cursor()
        cursor.execute("UPDATE signals SET processed = 1 WHERE id = ?", (db_id,))
        self.conn.commit()

# Глобальный экземпляр
trade_db = SocialSignalDB()
