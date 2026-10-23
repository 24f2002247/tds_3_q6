import sqlite3, json, re

def classify_action(p_text):
    p_lower = p_text.lower()
    if any(k in p_lower for k in ["duplicate to rejection", "already been paid", "requires rejection", "not a second settlement"]):
        return "reject_duplicate"
    elif any(k in p_lower for k in ["exception case", "exception workflow", "contradictory signed records"]):
        return "open_exception"
    elif any(k in p_lower for k in ["exceeds", "outside autonomous", "managerial approval", "financial approver", "human approval", "requires approval"]):
        return "request_approval"
    elif any(k in p_lower for k in ["freezes", "until", "paused", "callback"]):
        return "hold_invoice"
    else:
        return "settle_invoice"

conn = sqlite3.connect(r'C:\Users\Jayraj\.gemini\antigravity\scratch\tds-ga3\ga3_state.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT task_json FROM a2a_tasks WHERE task_id = 'task_dafa6ba20170'")
row = c.fetchone()
packages = json.loads(row['task_json'])['history'][0]['parts'][0]['data']['packages']

for idx, p in enumerate(packages):
    decisive_p = ""
    for doc in p.get("documents", []):
        for para in doc.get("text", "").split("\n\n"):
            refs = re.findall(r'\[(R_[A-Z0-9]+)\]', para)
            if len(refs) == 3 and not ("archive" in para.lower() or "training appendix" in para.lower()):
                decisive_p = para.strip()
    action = classify_action(decisive_p)
    print(f"Pkg {idx:2d} ({p.get('packageId')}): {action}")
