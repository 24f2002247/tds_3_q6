import sys, os, json, sqlite3
sys.path.insert(0, r'C:\Users\Jayraj\.gemini\antigravity\scratch\tds-ga3')

from fastapi.testclient import TestClient
from server import app

client = TestClient(app)

# 1. Test Agent Card
r_card = client.get('/.well-known/agent-card.json')
print("1. Agent Card Status:", r_card.status_code)
card_data = r_card.json()
print("   Card name:", card_data.get("name"))
print("   Skills:", [s.get("id") for s in card_data.get("skills", [])])
print("   Supported Interfaces:", card_data.get("supportedInterfaces"))
assert r_card.status_code == 200

# 2. Test Auth & Version
r_noauth = client.post('/a2a/message:send', json={"message": {}})
print("2. Missing Auth (expected 401):", r_noauth.status_code)
assert r_noauth.status_code == 401

r_badver = client.get('/a2a/tasks', headers={'Authorization': 'Bearer tok', 'A2A-Version': '2.0'})
print("3. Unsupported Version (expected 400):", r_badver.status_code)
assert r_badver.status_code == 400

# 4. Extract real 12 packages from db
conn = sqlite3.connect(r'C:\Users\Jayraj\.gemini\antigravity\scratch\tds-ga3\ga3_state.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT task_json FROM a2a_tasks WHERE task_id = 'task_dafa6ba20170'")
row = c.fetchone()
grader_task = json.loads(row['task_json'])
grader_batch_msg = grader_task['history'][0]
conn.close()

headers = {
    'Authorization': 'Bearer principal_fresh_test_001',
    'A2A-Version': '1.0',
    'Content-Type': 'application/a2a+json'
}

msg1 = {
    "message": {
        "messageId": "msg_batch_fresh_v3",
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

r1 = client.post('/a2a/message:send', headers=headers, json=msg1)
print("4. Batch Propose Status:", r1.status_code)
assert r1.status_code == 200
task1 = r1.json()['task']
t_id = task1['id']
print(f"   Task {t_id} created in state {task1['status']['state']}")
proposals = task1['artifacts'][0]['data']['proposals']
print(f"   Proposals count: {len(proposals)}")
actions_count = {}
for p in proposals:
    actions_count[p['action']] = actions_count.get(p['action'], 0) + 1
print("   Actions distribution across batch:", actions_count)
assert len(proposals) == 12

# 5. Test Replay of initial message
r1_rep = client.post('/a2a/message:send', headers=headers, json=msg1)
print("5. Exact Replay of initial message:", r1_rep.status_code, r1_rep.json()['task']['status']['state'])
assert r1_rep.status_code == 200
assert r1_rep.json()['task']['id'] == t_id

# 6. Test Changed content on same messageId (expected 409)
msg1_conflict = {
    "message": {
        "messageId": "msg_batch_fresh_v3",
        "role": "ROLE_USER",
        "parts": []
    }
}
r1_conf = client.post('/a2a/message:send', headers=headers, json=msg1_conflict)
print("6. Changed content conflict (expected 409):", r1_conf.status_code, r1_conf.json())
assert r1_conf.status_code == 409

# 7. Test Results Continuation (Simulate Grader ACCEPTED results)
results = []
for p in proposals:
    results.append({
        "packageId": p["packageId"],
        "actionId": p["actionId"],
        "action": p["action"],
        "outcome": "ACCEPTED",
        "receiptNonce": f"nonce_{p['actionId']}"
    })

msg2 = {
    "message": {
        "messageId": "msg_results_fresh_v3",
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

r2 = client.post('/a2a/message:send', headers=headers, json=msg2)
print("7. Results continuation Status:", r2.status_code)
assert r2.status_code == 200
task2 = r2.json()['task']
print(f"   Terminal task state: {task2['status']['state']}")
executions = task2['artifacts'][1]['data']['executions']
print(f"   Executions count: {len(executions)}")
assert task2['status']['state'] == "TASK_STATE_COMPLETED"
assert len(executions) == 12

# 8. Test Replay of continuation message -> Must return 200 with completed task!
r2_rep = client.post('/a2a/message:send', headers=headers, json=msg2)
print("8. Replay of continuation message:", r2_rep.status_code, r2_rep.json()['task']['status']['state'])
assert r2_rep.status_code == 200

# 9. Test Replay of initial message after completion -> Must return 200 with completed task!
r1_rep_after = client.post('/a2a/message:send', headers=headers, json=msg1)
print("9. Replay of initial message after completion:", r1_rep_after.status_code, r1_rep_after.json()['task']['status']['state'])
assert r1_rep_after.status_code == 200

# 10. Test New continuation on terminal task -> Must return 409!
msg3 = {
    "message": {
        "messageId": "msg_new_invalid_continuation",
        "taskId": t_id,
        "contextId": task1["contextId"],
        "role": "ROLE_USER",
        "parts": msg2["message"]["parts"]
    }
}
r3 = client.post('/a2a/message:send', headers=headers, json=msg3)
print("10. New continuation on terminal task (expected 409):", r3.status_code)
assert r3.status_code == 409

# 11. Test User Isolation
r_outsider = client.get(f'/a2a/tasks/{t_id}', headers={'Authorization': 'Bearer outsider_other_user', 'A2A-Version': '1.0'})
print("11. Outsider task access (expected 404):", r_outsider.status_code)
assert r_outsider.status_code == 404

r_outsider_list = client.get('/a2a/tasks', headers={'Authorization': 'Bearer outsider_other_user', 'A2A-Version': '1.0'})
print("12. Outsider list tasks (expected empty):", len(r_outsider_list.json()['tasks']))
assert len(r_outsider_list.json()['tasks']) == 0

print("\n========================================================")
print("ALL 12 RIGOROUS TEST CONTRACT CHECKS PASSED WITH 100% SUCCESS!")
print("========================================================")
