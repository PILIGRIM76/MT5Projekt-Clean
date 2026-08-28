import sqlite3
import json

DB = "C:/Users/zaytc/.local/share/mimocode/mimocode.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

# 1. Recent sessions
print("=== RECENT SESSIONS (7 days) ===")
c.execute("""
    SELECT id, title, time_created, project_id 
    FROM session 
    WHERE time_created > datetime('now', '-7 days')
    ORDER BY time_created DESC 
    LIMIT 20
""")
for r in c.fetchall():
    print(f"{r[0]} | {r[1]} | {r[2]} | {r[3]}")

# 2. Message schema
print("\n=== MESSAGE cols ===")
c.execute("PRAGMA table_info(message)")
for r in c.fetchall():
    print(f"  {r[1]} ({r[2]})")

# 3. Part schema
print("\n=== PART cols ===")
c.execute("PRAGMA table_info(part)")
for r in c.fetchall():
    print(f"  {r[1]} ({r[2]})")

# 4. User messages with rule-like keywords in recent sessions
print("\n=== USER MESSAGES WITH RULE/NEVER/ALWAYS ===")
c.execute("""
    SELECT m.id, m.session_id, m.time_created, substr(p.data, 1, 500) as text_data
    FROM message m
    JOIN part p ON p.message_id = m.id
    WHERE json_extract(m.data, '$.role') = 'user'
    AND m.time_created > datetime('now', '-7 days')
    AND (
        p.data LIKE '%remember%' OR p.data LIKE '%always%' OR p.data LIKE '%never%' 
        OR p.data LIKE '%rule%' OR p.data LIKE '%don''t%'
        OR p.data LIKE '%никогда%' OR p.data LIKE '%всегда%'
        OR p.data LIKE '%запомни%' OR p.data LIKE '%правило%'
        OR p.data LIKE '%не делай%'
    )
    ORDER BY m.time_created DESC
    LIMIT 30
""")
for r in c.fetchall():
    print(f"\n--- {r[0]} | {r[1]} | {r[2]} ---")
    # Try to extract text from JSON
    try:
        d = json.loads(r[3])
        if isinstance(d, dict):
            text = d.get('text', d.get('content', str(d)))
            print(str(text)[:300])
        else:
            print(str(d)[:300])
    except:
        print(r[3][:300])

conn.close()
