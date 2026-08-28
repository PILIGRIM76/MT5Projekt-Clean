import sqlite3
import json

DB = "C:/Users/zaytc/.local/share/mimocode/mimocode.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

PROJECT_ID = "9cc375d9-0de2-4c71-b9ee-52542fd81595"

# Find all sessions for this project
print("=== ALL SESSIONS FOR THIS PROJECT ===")
c.execute("""
    SELECT id, title, time_created, time_updated
    FROM session
    WHERE project_id = ?
    ORDER BY time_created DESC
    LIMIT 20
""", (PROJECT_ID,))
for r in c.fetchall():
    print(f"{r[0]} | {r[1]} | {r[2]} | {r[3]}")

# Find user messages from the main session
MAIN_SESSION = "ses_069afc1c9ffezDHm3qZ0AkKT64"
print(f"\n=== USER MESSAGES IN {MAIN_SESSION} ===")
c.execute("""
    SELECT m.id, m.time_created, p.data
    FROM message m
    JOIN part p ON p.message_id = m.id
    WHERE m.session_id = ?
    AND json_extract(m.data, '$.role') = 'user'
    AND json_extract(p.data, '$.type') = 'text'
    ORDER BY m.time_created
""", (MAIN_SESSION,))
for r in c.fetchall():
    try:
        d = json.loads(r[2])
        text = d.get('text', '')[:400]
    except:
        text = str(r[2])[:400]
    print(f"\n--- msg {r[0]} at {r[1]} ---")
    print(text)

conn.close()
