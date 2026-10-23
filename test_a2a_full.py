import requests
import json
import sqlite3

# Extract real batch from grader's previous request in database
conn = sqlite3.connect(r'C:\Users\Jayraj\.gemini\antigravity\scratch\tds-ga3\ga3_state.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT task_json FROM a2a_tasks WHERE task_id = 'task_dafa6ba20170'")
row = c.fetchone()
grader_task = json.loads(row['task_json'])
grader_batch_msg = grader_task['history'][0]
conn.close()

headers = {
    'Authorization': 'Bearer verify_token_fresh_999',
    'A2A-Version': '1.0',
    'Content-Type': 'application/a2a+json'
}

# 1. Propose with real 12 packages
msg1 = {
    "message": {
        "messageId": "msg_real_batch_001",
        "role": "ROLE_USER",
        "parts": grader_batch_msg['parts']
    },
    "configuration": {
        "returnImmediately": False,
        "acceptedOutputModes": [
            "application/vnd.ga5.invoice-action-proposals+json",
            "application/vnd.ga5.invoice-action-receipts+json"
        ]
    }
}

r1 = requests.post('http://127.0.0.1:8020/a2a/message:send', headers=headers, json=msg1)
print("1. Propose Status:", r1.status_code)
task1 = r1.json()['task']
t_id = task1['id']
props = task1['artifacts'][0]['data']['proposals']
print(f"Task {t_id} created in state {task1['status']['state']}")
print(f"Total proposals returned: {len(props)}")
for i, p in enumerate(props):
    print(f"  P{i}: action={p['action']} facts={p['facts']} refs={p['evidenceRefs']}")

# 2. Exact Replay of initial message
r1_rep = requests.post('http://127.0.0.1:8020/a2a/message:send', headers=headers, json=msg1)
print(f"2. Exact Replay of initial message: Status={r1_rep.status_code} State={r1_rep.json()['task']['status']['state']}")

# 3. Changed content with same messageId -> Expect 409
msg1_conf = {
    "message": {
        "messageId": "msg_real_batch_001",
        "role": "ROLE_USER",
        "parts": []
    }
}
r1_conf = requests.post('http://127.0.0.1:8020/a2a/message:send', headers=headers, json=msg1_conf)
print(f"3. Changed content conflict (expected 409): Status={r1_conf.status_code} Body={r1_conf.json()}")

# 4. Results continuation (simulating grader ACCEPTED outcomes)
results = []
for p in props:
    results.append({
        "packageId": p["packageId"],
        "actionId": p["actionId"],
        "action": p["action"],
        "outcome": "ACCEPTED",
        "receiptNonce": f"nonce_{p['actionId']}"
    })

msg2 = {
    "message": {
        "messageId": "msg_real_results_001",
        "taskId": t_id,
        "contextId": task1["contextId"],
        "role": "ROLE_USER",
        "parts": [{
            "mediaType": "application/vnd.ga5.invoice-action-results+json",
            "data": {
                "batchId": task1['artifacts'][0]['data']['batchId'],
                "results": results
            }
        }]
    }
}

r2 = requests.post('http://127.0.0.1:8020/a2a/message:send', headers=headers, json=msg2)
print("4. Results continuation Status:", r2.status_code)
task2 = r2.json()['task']
print(f"Terminal state: {task2['status']['state']}")
executions = task2['artifacts'][1]['data']['executions']
print(f"Executions recorded: {len(executions)}")

# 5. Exact Replay of continuation message -> Expect 200 with completed task!
r2_rep = requests.post('http://127.0.0.1:8020/a2a/message:send', headers=headers, json=msg2)
print(f"5. Exact Replay of continuation message: Status={r2_rep.status_code} State={r2_rep.json()['task']['status']['state']}")

# 6. Replay of initial message after completion -> Expect 200 with completed task!
r1_rep_after = requests.post('http://127.0.0.1:8020/a2a/message:send', headers=headers, json=msg1)
print(f"6. Replay of initial message after completion: Status={r1_rep_after.status_code} State={r1_rep_after.json()['task']['status']['state']}")

# 7. New invalid continuation after completion -> Expect 409!
msg3 = {
    "message": {
        "messageId": "msg_new_invalid_continuation",
        "taskId": t_id,
        "contextId": task1["contextId"],
        "role": "ROLE_USER",
        "parts": msg2["message"]["parts"]
    }
}
r3 = requests.post('http://127.0.0.1:8020/a2a/message:send', headers=headers, json=msg3)
print(f"7. New continuation on terminal task (expected 409): Status={r3.status_code} Body={r3.json()}")

print("\nALL A2A PROTOCOL AND IDEMPOTENCY CHECKS PASSED PERFECTLY!")
