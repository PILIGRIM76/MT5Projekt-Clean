import sqlite3
import json

DB = "C:/Users/zaytc/.local/share/mimocode/mimocode.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

# 1. Tables
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print("=== TABLES ===")
print(tables)

# 2. Session schema
for t in tables[:5]:
    c.execute(f"PRAGMA table_info({t})")
    cols = [r[1] for r in c.fetchall()]
    print(f"\n=== {t} cols: {cols}")

# 3. Recent sessions
print("\n=== RECENT SESSIONS ===")
c.execute("SELECT id, time_created, data FROM session ORDER BY time_created DESC LIMIT 20")
for r in c.fetchall():
    print(f"{r[0]} | {r[1]} | {str(r[2])[:200]}")

conn.close()
