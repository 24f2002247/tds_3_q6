import sqlite3
import json

conn = sqlite3.connect(r'C:\Users\Jayraj\.gemini\antigravity\scratch\tds-ga3\ga3_state.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT task_json FROM a2a_tasks WHERE task_id = 'task_dafa6ba20170'")
row = c.fetchone()
if row:
    d = json.loads(row['task_json'])
    history0 = d['history'][0]
    packages = history0['parts'][0]['data']['packages']
    print(f"Total packages in grader batch: {len(packages)}")
    pkg0 = packages[0]
    print("Package 0 keys:", list(pkg0.keys()))
    print("Package 0 metadata:", {k: v for k, v in pkg0.items() if k != 'documents'})
    print(f"Package 0 documents count: {len(pkg0.get('documents', []))}")
    for doc in pkg0.get('documents', []):
        print(f"--- Doc: {doc.get('title')} ({doc.get('kind', '')}) ---")
        print(doc.get('content', '')[:500])
