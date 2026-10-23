import sqlite3
import json

conn = sqlite3.connect(r'C:\Users\Jayraj\.gemini\antigravity\scratch\tds-ga3\ga3_state.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT task_id, bearer_token, message_id, state, task_json FROM a2a_tasks WHERE task_id = 'task_dafa6ba20170'")
row = c.fetchone()
if row:
    d = json.loads(row['task_json'])
    print('Keys:', list(d.keys()))
    print('History len:', len(d.get('history', [])))
    for i, h in enumerate(d.get('history', [])):
        print(f"History {i} messageId: {h.get('messageId')}")
        print(f"History {i} parts: {[p.get('mediaType') for p in h.get('parts', [])]}")
    print('Artifacts len:', len(d.get('artifacts', [])))
    for a in d.get('artifacts', []):
        print('Artifact mediaType:', a.get('mediaType'))
        if a.get('mediaType') == 'application/vnd.ga5.invoice-action-proposals+json':
            print('  proposals count:', len(a.get('data', {}).get('proposals', [])))
            print('  sample proposal:', a.get('data', {}).get('proposals', [])[0])
        elif a.get('mediaType') == 'application/vnd.ga5.invoice-action-receipts+json':
            print('  executions count:', len(a.get('data', {}).get('executions', [])))
            print('  sample execution:', a.get('data', {}).get('executions', [])[0] if a.get('data', {}).get('executions') else 'empty')
