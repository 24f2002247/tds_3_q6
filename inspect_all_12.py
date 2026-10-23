import sqlite3
import json
import re

conn = sqlite3.connect(r'C:\Users\Jayraj\.gemini\antigravity\scratch\tds-ga3\ga3_state.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT task_json FROM a2a_tasks WHERE task_id = 'task_dafa6ba20170'")
row = c.fetchone()
if row:
    d = json.loads(row['task_json'])
    packages = d['history'][0]['parts'][0]['data']['packages']
    for idx, pkg in enumerate(packages):
        pkg_id = pkg.get('packageId')
        # Find intake cover sheet facts
        vendor = ""
        inv_num = ""
        amount_minor = 0
        currency = ""
        
        all_paras = []
        for doc in pkg.get('documents', []):
            text = doc.get('text', '')
            # Match cover sheet
            m = re.search(r'Supplier\s+([^;]+);\s*invoice\s+([^;]+);\s*stated total\s+([A-Z]{3})\s+([0-9\.]+)', text)
            if m:
                vendor = m.group(1).strip()
                inv_num = m.group(2).strip()
                currency = m.group(3).strip()
                amount_minor = int(round(float(m.group(4).strip().rstrip('.')) * 100))
            
            # Split into paragraphs
            for p in text.split('\n\n'):
                p_clean = p.strip()
                if not p_clean: continue
                # Find bracketed references
                refs = re.findall(r'\[(R_[A-Z0-9]+)\]', p_clean)
                if len(refs) == 3:
                    all_paras.append((doc.get('name'), p_clean, refs))
                    
        print(f"\n--- Package {idx}: {pkg_id} ---")
        print(f"Facts: Vendor='{vendor}', Inv='{inv_num}', Cur='{currency}', AmountMinor={amount_minor}")
        for doc_name, p_text, refs in all_paras:
            print(f"  Decisive candidate ({doc_name}): {refs}")
            print(f"    Text: {p_text[:120]}...")
