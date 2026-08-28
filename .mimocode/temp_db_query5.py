import sqlite3
import json

DB = "C:/Users/zaytc/.local/share/mimocode/mimocode.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

PROJECT_ID = "9cc375d9-0de2-4c71-b9ee-52542fd81595"

# Get sessions for this project that are NOT checkpoint-writer and NOT the current dream session
print("=== USER SESSIONS (non-checkpoint, non-dream) ===")
c.execute("""
    SELECT id, title, time_created
    FROM session
    WHERE project_id = ?
    AND title NOT LIKE 'checkpoint-writer%'
    AND title NOT LIKE 'Auto Dream%'
    AND title NOT LIKE 'ask:%'
    ORDER BY time_created DESC
    LIMIT 10
""", (PROJECT_ID,))
for r in c.fetchall():
    print(f"{r[0]} | {r[1]} | {r[2]}")

# Now look at assistant responses for key errors in main session
MAIN_SESSION = "ses_069afc1c9ffezDHm3qZ0AkKT64"
print("\n=== ASSISTANT TOOL RESULTS WITH ERRORS (main session) ===")
c.execute("""
    SELECT m.id, m.time_created, substr(p.data, 1, 600) as data
    FROM message m
    JOIN part p ON p.message_id = m.id
    WHERE m.session_id = ?
    AND json_extract(m.data, '$.role') = 'assistant'
    AND (p.data LIKE '%Error%' OR p.data LIKE '%error%' OR p.data LIKE '%Traceback%')
    ORDER BY m.time_created DESC
    LIMIT 15
""", (MAIN_SESSION,))
for r in c.fetchall():
    try:
        d = json.loads(r[2])
        ptype = d.get('type', '?')
        if ptype == 'tool':
            tool = d.get('tool', '?')
            state = d.get('state', {})
            output = str(state.get('output', ''))[:300]
            print(f"\n--- tool={tool} at {r[1]} ---")
            print(output)
        elif ptype == 'text':
            text = d.get('text', '')[:300]
            print(f"\n--- text at {r[1]} ---")
            print(text)
    except:
        print(f"\n--- raw at {r[1]} ---")
        print(r[2][:300])

# Check the earlier session ses_06c449051ffeCFXMWp8xTQaazW for additional knowledge
EARLIER_SESSION = "ses_06c449051ffeCFXMWp8xTQaazW"
print(f"\n=== USER MESSAGES IN {EARLIER_SESSION} ===")
c.execute("""
    SELECT m.id, m.time_created, p.data
    FROM message m
    JOIN part p ON p.message_id = m.id
    WHERE m.session_id = ?
    AND json_extract(m.data, '$.role') = 'user'
    AND json_extract(p.data, '$.type') = 'text'
    ORDER BY m.time_created
""", (EARLIER_SESSION,))
for r in c.fetchall():
    try:
        d = json.loads(r[2])
        text = d.get('text', '')[:300]
    except:
        text = str(r[2])[:300]
    # skip system reminders
    if '<system-reminder>' in text:
        continue
    print(f"\n--- at {r[1]} ---")
    print(text)

conn.close()
