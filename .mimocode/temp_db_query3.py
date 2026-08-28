import sqlite3
import json

DB = "C:/Users/zaytc/.local/share/mimocode/mimocode.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

# Check time format in sessions
print("=== ALL SESSIONS (sample) ===")
c.execute("SELECT id, title, time_created, time_updated FROM session ORDER BY time_created DESC LIMIT 20")
for r in c.fetchall():
    print(f"{r[0]} | {r[1]} | {r[2]} | {r[3]}")

# Check time format in messages
print("\n=== MESSAGE time samples ===")
c.execute("SELECT id, session_id, time_created, data FROM message ORDER BY time_created DESC LIMIT 5")
for r in c.fetchall():
    try:
        d = json.loads(r[3])
        role = d.get('role', '?')
    except:
        role = '?'
    print(f"{r[0]} | {r[1]} | {r[2]} | role={role}")

# Get the project_id for this project
print("\n=== PROJECTS ===")
c.execute("SELECT id, name, worktree FROM project")
for r in c.fetchall():
    print(f"{r[0]} | {r[1]} | {r[2]}")

conn.close()
