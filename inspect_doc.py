import sqlite3
import json

conn = sqlite3.connect(r'C:\Users\Jayraj\.gemini\antigravity\scratch\tds-ga3\ga3_state.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT task_json FROM a2a_tasks WHERE task_id = 'task_dafa6ba20170'")
row = c.fetchone()
if row:
    d = json.loads(row['task_json'])
    packages = d['history'][0]['parts'][0]['data']['packages']
    doc0 = packages[0]['documents'][0]
    print("Doc 0 keys:", list(doc0.keys()))
    print("Doc 0 content:", doc0)
