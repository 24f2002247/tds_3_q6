import sqlite3, json, re

conn = sqlite3.connect(r'C:\Users\Jayraj\.gemini\antigravity\scratch\tds-ga3\ga3_state.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT task_json FROM a2a_tasks WHERE task_id = 'task_dafa6ba20170'")
row = c.fetchone()
packages = json.loads(row['task_json'])['history'][0]['parts'][0]['data']['packages']

for idx in [3, 6, 7, 9, 10, 11]:
    p = packages[idx]
    for doc in p.get("documents", []):
        for para in doc.get("text", "").split("\n\n"):
            refs = re.findall(r'\[(R_[A-Z0-9]+)\]', para)
            if len(refs) == 3 and not ("archive" in para.lower() or "training appendix" in para.lower()):
                print(f"=== Pkg {idx} ===")
                print(para.strip())
