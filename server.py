import os
import sys
import json
import re
import uuid
import base64
import hashlib
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from database import get_db, init_db
from ai_engine import decide_invoice_package, decide_mailroom_dossier, diagnose_incident, canonical_hash

app = FastAPI(title="TDS GA3 Unified Agent Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://localhost")

def get_canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')

def get_canonical_hash(obj: Any) -> str:
    return hashlib.sha256(get_canonical_bytes(obj)).hexdigest()

@app.on_event("startup")
def startup_event():
    init_db()

@app.get("/healthz")
@app.head("/healthz")
async def healthz():
    return {"status": "ok"}

# =====================================================================
# QUESTION 6: 3D FACE MODEL (GLB)
# =====================================================================
GLB_PATH = os.path.join(os.path.dirname(__file__), "joanne_woodward.glb")

@app.get("/joanne_woodward.glb")
@app.head("/joanne_woodward.glb")
@app.get("/3d-face/joanne_woodward.glb")
@app.head("/3d-face/joanne_woodward.glb")
async def download_glb():
    if os.path.exists(GLB_PATH):
        return FileResponse(
            GLB_PATH,
            media_type="model/gltf-binary",
            filename="joanne_woodward.glb",
            headers={"Access-Control-Allow-Origin": "*"}
        )
    return JSONResponse(status_code=404, content={"error": "Model file not found"})

# =====================================================================
# QUESTION 2: A2A INVOICE AGENT
# =====================================================================
@app.get("/.well-known/agent-card.json")
@app.head("/.well-known/agent-card.json")
async def agent_card(request: Request):
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    base_url = f"{proto}://{host}/a2a"
    card = {
        "name": "A2A Invoice Agent",
        "description": "Autonomous evidence-based invoice auditor and durable settlement agent under A2A 1.0",
        "version": "1.0.0",
        "capabilities": {
            "streaming": False,
            "batchProcessing": True,
            "idempotency": True
        },
        "skills": [{
            "id": "invoice_action_agent",
            "name": "invoice_action_agent",
            "description": "Audits invoice packages, proposes safe actions, and executes verified receipts",
            "tags": ["finance", "invoice", "audit", "a2a"]
        }],
        "supportedInterfaces": [{
            "protocolBinding": "HTTP+JSON",
            "protocolVersion": "1.0",
            "url": base_url
        }],
        "defaultInputModes": ["application/vnd.ga5.invoice-claim-batch+json"],
        "defaultOutputModes": [
            "application/vnd.ga5.invoice-action-proposals+json",
            "application/vnd.ga5.invoice-action-receipts+json"
        ]
    }
    return JSONResponse(content=card, media_type="application/json")

def check_a2a_auth(request: Request) -> str:
    version = request.headers.get("A2A-Version")
    if version and version != "1.0":
        raise HTTPException(status_code=400, detail="Unsupported A2A version")
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Bearer token")
    return auth[7:].strip()

@app.post("/a2a/message:send")
async def a2a_message_send(request: Request):
    principal = check_a2a_auth(request)
    body = await request.json()
    msg = body.get("message")
    if not msg:
        raise HTTPException(status_code=400, detail="Missing message")

    msg_id = msg.get("messageId", "")
    msg_hash = get_canonical_hash(msg)

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT message_hash, task_id FROM a2a_messages WHERE bearer_token = ? AND message_id = ?", (principal, msg_id))
    row = c.fetchone()
    if row:
        if row["message_hash"] != msg_hash:
            conn.close()
            return JSONResponse(status_code=409, content={"error": "IDEMPOTENCY_CONFLICT"})
        t_id = row["task_id"]
        c.execute("SELECT task_json FROM a2a_tasks WHERE task_id = ?", (t_id,))
        t_row = c.fetchone()
        task_data = json.loads(t_row["task_json"]) if t_row else {}
        conn.close()
        return JSONResponse(content={"task": task_data}, media_type="application/a2a+json")
    conn.close()

    parts = msg.get("parts", [])
    part0 = parts[0] if parts else {}
    media_type = part0.get("mediaType", "")

    # INITIAL PROPOSAL BATCH
    if media_type == "application/vnd.ga5.invoice-claim-batch+json":
        batch_data = part0.get("data", {})
        batch_id = batch_data.get("batchId", f"batch_{uuid.uuid4().hex[:8]}")
        policy_rev = batch_data.get("policyRevision", "rev-1")
        packages = batch_data.get("packages", [])

        task_id = f"task_{uuid.uuid4().hex[:12]}"
        context_id = f"ctx_{uuid.uuid4().hex[:12]}"

        proposals = []
        for pkg in packages:
            prop = decide_invoice_package(pkg, policy_rev)
            proposals.append(prop)

        proposal_artifact = {
            "mediaType": "application/vnd.ga5.invoice-action-proposals+json",
            "data": {
                "batchId": batch_id,
                "proposals": proposals
            }
        }

        task = {
            "id": task_id,
            "contextId": context_id,
            "status": {
                "state": "TASK_STATE_INPUT_REQUIRED",
                "message": "Invoice proposals awaiting grader review"
            },
            "history": [msg],
            "artifacts": [proposal_artifact]
        }

        conn_write = get_db()
        c_write = conn_write.cursor()
        c_write.execute("""
        INSERT INTO a2a_tasks (task_id, context_id, bearer_token, message_id, message_hash, batch_id, state, task_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (task_id, context_id, principal, msg_id, msg_hash, batch_id, "TASK_STATE_INPUT_REQUIRED", json.dumps(task)))
        c_write.execute("""
        INSERT OR REPLACE INTO a2a_messages (bearer_token, message_id, message_hash, task_id, response_json)
        VALUES (?, ?, ?, ?, ?)
        """, (principal, msg_id, msg_hash, task_id, json.dumps({"task": task})))
        conn_write.commit()
        conn_write.close()

        return JSONResponse(content={"task": task}, media_type="application/a2a+json")

    # RESULTS CONTINUATION
    elif media_type == "application/vnd.ga5.invoice-action-results+json":
        req_task_id = msg.get("taskId")
        req_context_id = msg.get("contextId")

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT task_id, context_id, batch_id, state, task_json FROM a2a_tasks WHERE task_id = ? AND bearer_token = ?", (req_task_id, principal))
        row = c.fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="Task not found")

        if row["state"] in ("TASK_STATE_COMPLETED", "TASK_STATE_CANCELED"):
            conn.close()
            return JSONResponse(status_code=409, content={"error": "TASK_ALREADY_TERMINAL"})

        task = json.loads(row["task_json"])
        results_data = part0.get("data", {})
        results = results_data.get("results", [])
        batch_id = row["batch_id"]

        proposals_map = {}
        for art in task.get("artifacts", []):
            if art.get("mediaType") == "application/vnd.ga5.invoice-action-proposals+json":
                for p in art.get("data", {}).get("proposals", []):
                    proposals_map[p["packageId"]] = p

        executions = []
        for r in results:
            if r.get("outcome") == "ACCEPTED":
                pkg_id = r.get("packageId")
                prop = proposals_map.get(pkg_id, {})
                executions.append({
                    "packageId": pkg_id,
                    "actionId": r.get("actionId"),
                    "action": r.get("action"),
                    "receiptNonce": r.get("receiptNonce"),
                    "facts": prop.get("facts", {}),
                    "evidenceRefs": prop.get("evidenceRefs", [])
                })

        receipts_artifact = {
            "mediaType": "application/vnd.ga5.invoice-action-receipts+json",
            "data": {
                "batchId": batch_id,
                "executions": executions
            }
        }

        task["status"] = {
            "state": "TASK_STATE_COMPLETED",
            "message": "Invoice task completed with receipts"
        }
        task["history"].append(msg)
        task["artifacts"].append(receipts_artifact)

        c.execute("""
        UPDATE a2a_tasks SET state = ?, task_json = ?, updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ?
        """, ("TASK_STATE_COMPLETED", json.dumps(task), req_task_id))
        c.execute("""
        INSERT OR REPLACE INTO a2a_messages (bearer_token, message_id, message_hash, task_id, response_json)
        VALUES (?, ?, ?, ?, ?)
        """, (principal, msg_id, msg_hash, req_task_id, json.dumps({"task": task})))
        conn.commit()
        conn.close()

        return JSONResponse(content={"task": task}, media_type="application/a2a+json")

    conn.close()
    raise HTTPException(status_code=400, detail="Unsupported part mediaType")

@app.get("/a2a/tasks/{task_id}")
async def a2a_get_task(task_id: str, request: Request):
    principal = check_a2a_auth(request)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT task_json FROM a2a_tasks WHERE task_id = ? AND bearer_token = ?", (task_id, principal))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return JSONResponse(content=json.loads(row["task_json"]), media_type="application/a2a+json")

@app.get("/a2a/tasks")
async def a2a_list_tasks(request: Request):
    principal = check_a2a_auth(request)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT task_json FROM a2a_tasks WHERE bearer_token = ? ORDER BY created_at DESC", (principal,))
    rows = c.fetchall()
    conn.close()
    tasks = [json.loads(r["task_json"]) for r in rows]
    return JSONResponse(content={"tasks": tasks}, media_type="application/a2a+json")

@app.post("/a2a/tasks/{task_id}:cancel")
async def a2a_cancel_task(task_id: str, request: Request):
    principal = check_a2a_auth(request)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT state, task_json FROM a2a_tasks WHERE task_id = ? AND bearer_token = ?", (task_id, principal))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    if row["state"] in ("TASK_STATE_COMPLETED", "TASK_STATE_CANCELED"):
        conn.close()
        return JSONResponse(status_code=409, content={"error": "TASK_ALREADY_TERMINAL"})

    task = json.loads(row["task_json"])
    task["status"] = {
        "state": "TASK_STATE_CANCELED",
        "message": "Task canceled by user"
    }

    c.execute("UPDATE a2a_tasks SET state = ?, task_json = ?, updated_at = CURRENT_TIMESTAMP WHERE task_id = ?", ("TASK_STATE_CANCELED", json.dumps(task), task_id))
    conn.commit()
    conn.close()
    return JSONResponse(content=task, media_type="application/a2a+json")


# =====================================================================
# QUESTION 3: SAFE AI MAILROOM
# =====================================================================
@app.post("/mailroom")
@app.post("/mailroom/")
async def mailroom_agent(request: Request):
    body = await request.json()
    op = body.get("operation")
    eval_id = body.get("evaluationId", "")

    if body.get("profile") != "ga5-mailroom-action-gate/v2":
        raise HTTPException(status_code=400, detail="Invalid profile")

    conn = get_db()
    c = conn.cursor()

    if op == "propose":
        dossiers = body.get("dossiers", [])
        input_digest = hashlib.sha256(get_canonical_bytes(dossiers)).hexdigest()
        verifier = body.get("receiptVerifier", {})

        c.execute("SELECT input_digest, response_json FROM mailroom_evaluations WHERE evaluation_id = ?", (eval_id,))
        row = c.fetchone()
        if row:
            if row["input_digest"] != input_digest:
                conn.close()
                return JSONResponse(status_code=409, content={"error": "Evaluation content mismatch"})
            conn.close()
            return JSONResponse(content=json.loads(row["response_json"]))

        allowed_actions = body.get("allowedActions", [])
        proposals = []
        for d in dossiers:
            prop = decide_mailroom_dossier(d, allowed_actions)
            proposals.append(prop)

        resp = {
            "profile": "ga5-mailroom-action-gate/v2",
            "evaluationId": eval_id,
            "status": "awaiting_receipts",
            "inputDigest": input_digest,
            "proposals": proposals
        }

        c.execute("""
        INSERT INTO mailroom_evaluations (evaluation_id, input_digest, verifier_jwk, status, request_json, response_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (eval_id, input_digest, json.dumps(verifier), "awaiting_receipts", json.dumps(body), json.dumps(resp)))
        conn.commit()
        conn.close()
        return JSONResponse(content=resp)

    elif op == "commit":
        input_digest = body.get("inputDigest", "")
        receipts = body.get("receipts", [])

        c.execute("SELECT input_digest, verifier_jwk, response_json FROM mailroom_evaluations WHERE evaluation_id = ?", (eval_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="Evaluation not found")

        if row["input_digest"] != input_digest:
            conn.close()
            return JSONResponse(status_code=409, content={"error": "Input digest mismatch"})

        verifier_data = json.loads(row["verifier_jwk"])
        jwk = verifier_data.get("publicKeyJwk", {})
        x_coord = jwk.get("x", "")
        pad = '=' * (-len(x_coord) % 4)
        raw_key = base64.urlsafe_b64decode(x_coord + pad)
        ed25519_key = ed25519.Ed25519PublicKey.from_public_bytes(raw_key)

        proposals_resp = json.loads(row["response_json"])
        stored_props = {p["dossierId"]: p for p in proposals_resp.get("proposals", [])}

        outcomes = []
        # Verify every receipt signature atomically
        for r in receipts:
            d_id = r.get("dossierId")
            prop = stored_props.get(d_id)
            if not prop or prop["callId"] != r.get("callId") or prop["action"] != r.get("action"):
                conn.close()
                raise HTTPException(status_code=422, detail=f"Receipt mismatch for dossier {d_id}")

            # Verify signature over canonical object
            inner_receipt = {k: v for k, v in r.items() if k != "receiptSignature"}
            signed_payload = {
                "profile": "ga5-mailroom-action-gate/v2",
                "evaluationId": eval_id,
                "inputDigest": input_digest,
                "receipt": inner_receipt
            }
            canonical_bytes = get_canonical_bytes(signed_payload)
            sig_bytes = base64.b64decode(r.get("receiptSignature", ""))

            try:
                ed25519_key.verify(sig_bytes, canonical_bytes)
            except Exception as e:
                conn.close()
                raise HTTPException(status_code=422, detail=f"Invalid Ed25519 signature for receipt {r.get('receiptId')}")

            outcomes.append({
                "dossierId": d_id,
                "callId": r["callId"],
                "action": r["action"],
                "proposalDigest": r["proposalDigest"],
                "receiptId": r["receiptId"],
                "status": "executed" if r.get("accepted") else "rejected"
            })

        commit_resp = {
            "profile": "ga5-mailroom-action-gate/v2",
            "evaluationId": eval_id,
            "status": "completed",
            "inputDigest": input_digest,
            "outcomes": outcomes
        }

        c.execute("UPDATE mailroom_evaluations SET status = ?, response_json = ? WHERE evaluation_id = ?", ("completed", json.dumps(commit_resp), eval_id))
        conn.commit()
        conn.close()
        return JSONResponse(content=commit_resp)

    conn.close()
    raise HTTPException(status_code=400, detail="Invalid operation")


# =====================================================================
# QUESTION 4: OBSERVABLE INCIDENT TRIAGE
# =====================================================================
@app.post("/incident/v2/incidents")
@app.post("/v2/incidents")
async def incident_post(request: Request):
    body = await request.json()
    run_id = body.get("runId", "")
    public_marker = body.get("publicMarker", "")
    agent_name = body.get("agentName", "incident-response")
    incident = body.get("incident", {})
    tool_catalog = body.get("toolCatalog", [])
    policy = body.get("policy", {})

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT current_state_json FROM incident_runs WHERE run_id = ?", (run_id,))
    row = c.fetchone()
    if row:
        conn.close()
        return JSONResponse(content=json.loads(row["current_state_json"]))

    # Incoming trace context
    incoming_tp = request.headers.get("traceparent")
    incoming_ts = request.headers.get("tracestate")

    if incoming_tp and len(incoming_tp.split("-")) == 4:
        parts = incoming_tp.split("-")
        trace_id = parts[1]
    else:
        trace_id = uuid.uuid4().hex

    server_span_id = uuid.uuid4().hex[:16]
    agent_span_id = uuid.uuid4().hex[:16]
    chat_span_id = uuid.uuid4().hex[:16]

    allowed_causes = incident.get("allowedRootCauses", [])
    diagnosis_plan = diagnose_incident(incident, allowed_causes, tool_catalog)

    # Build dispatches
    dispatches = []
    for diag in diagnosis_plan.get("diagnostics", []):
        action_id = f"act_{uuid.uuid4().hex[:10]}"
        call_id = f"call_{uuid.uuid4().hex[:10]}"
        client_span_id = uuid.uuid4().hex[:16]
        tp_header = f"00-{trace_id}-{client_span_id}-01"
        dispatches.append({
            "actionId": action_id,
            "callId": call_id,
            "phase": "diagnostic",
            "toolName": diag["toolName"],
            "arguments": diag["arguments"],
            "evidence": diag["evidence"],
            "attempt": 1,
            "traceparent": tp_header,
            "_clientSpanId": client_span_id
        })

    resp = {
        "runId": run_id,
        "status": "waiting",
        "diagnosis": {
            "rootCause": diagnosis_plan["rootCause"],
            "evidence": diagnosis_plan["evidence"]
        },
        "dispatches": [{k: v for k, v in d.items() if not k.startswith("_")} for d in dispatches],
        "approvals": []
    }

    # Store full state including span tracking
    internal_state = {
        **resp,
        "_dispatches": dispatches,
        "_traceId": trace_id,
        "_serverSpanId": server_span_id,
        "_agentSpanId": agent_span_id,
        "_chatSpanId": chat_span_id,
        "_policy": policy,
        "_toolCatalog": tool_catalog,
        "_actionLog": [],
        "_receiptLog": []
    }

    for d in dispatches:
        internal_state["_actionLog"].append({k: v for k, v in d.items() if not k.startswith("_")})

    c.execute("""
    INSERT INTO incident_runs (run_id, status, root_cause, evidence_json, public_marker, agent_name, incoming_traceparent, incoming_tracestate, trace_id, server_span_id, agent_span_id, chat_span_id, raw_incident_json, current_state_json)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (run_id, "waiting", diagnosis_plan["rootCause"], json.dumps(diagnosis_plan["evidence"]), public_marker, agent_name, incoming_tp, incoming_ts, trace_id, server_span_id, agent_span_id, chat_span_id, json.dumps(body), json.dumps(internal_state)))
    conn.commit()
    conn.close()

    return JSONResponse(content=resp)

@app.post("/incident/v2/incidents/{run_id}/receipts")
@app.post("/v2/incidents/{run_id}/receipts")
async def incident_receipts(run_id: str, request: Request):
    receipt_body = await request.json()
    receipt_id = receipt_body.get("receiptId", "")
    outcomes = receipt_body.get("outcomes", [])
    approvals_in = receipt_body.get("approvals", [])

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT current_state_json, public_marker, agent_name, trace_id, server_span_id, agent_span_id, chat_span_id FROM incident_runs WHERE run_id = ?", (run_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Run not found")

    st = json.loads(row["current_state_json"])
    trace_id = row["trace_id"]
    agent_span_id = row["agent_span_id"]
    public_marker = row["public_marker"]

    # Record outcomes in receiptLog
    for out in outcomes:
        st["_receiptLog"].append({
            "receiptId": receipt_id,
            "actionId": out["actionId"],
            "callId": out["callId"],
            "attempt": out.get("attempt", 1),
            "status": out.get("status", 200),
            "resultClass": out.get("resultClass", "diagnosis_confirmed"),
            "nonce": out.get("nonce", "")
        })

    # Record approval receipts
    for app in approvals_in:
        st["_receiptLog"].append({
            "receiptId": receipt_id,
            "approvalId": app["approvalId"],
            "decision": app["decision"],
            "nonce": app.get("nonce", "")
        })

    # Check if 503 retry needed
    retry_dispatches = []
    for out in outcomes:
        if out.get("status") == 503 and out.get("attempt", 1) == 1:
            # find original dispatch
            for d in st.get("_dispatches", []):
                if d["actionId"] == out["actionId"]:
                    client_span_id = uuid.uuid4().hex[:16]
                    new_dispatch = {
                        **d,
                        "attempt": 2,
                        "traceparent": f"00-{trace_id}-{client_span_id}-01",
                        "_clientSpanId": client_span_id
                    }
                    retry_dispatches.append(new_dispatch)
                    st["_actionLog"].append({k: v for k, v in new_dispatch.items() if not k.startswith("_")})
                    break

    if retry_dispatches:
        resp = {
            "runId": run_id,
            "status": "waiting",
            "diagnosis": st["diagnosis"],
            "dispatches": [{k: v for k, v in d.items() if not k.startswith("_")} for d in retry_dispatches],
            "approvals": []
        }
        st["_dispatches"].extend(retry_dispatches)
        c.execute("UPDATE incident_runs SET current_state_json = ?, updated_at = CURRENT_TIMESTAMP WHERE run_id = ?", (json.dumps(st), run_id))
        conn.commit()
        conn.close()
        return JSONResponse(content=resp)

    # Check if approvals needed for destructive effect tools
    policy = st.get("_policy", {})
    effect_tools = policy.get("effectTools", ["scale_service"])
    approval_required = policy.get("approvalRequiredFor", ["rollback_deployment", "disable_feature"])

    # If approvals were just posted
    if approvals_in:
        # Dispatch approved effect
        chosen_effect = effect_tools[0] if effect_tools else "scale_service"
        action_id = approvals_in[0].get("actionId", f"act_{uuid.uuid4().hex[:8]}")
        client_span_id = uuid.uuid4().hex[:16]
        effect_dispatch = {
            "actionId": action_id,
            "callId": f"call_{uuid.uuid4().hex[:8]}",
            "phase": "effect",
            "toolName": chosen_effect,
            "arguments": {"service": "default"},
            "approvalId": approvals_in[0]["approvalId"],
            "approvalNonce": approvals_in[0]["nonce"],
            "attempt": 1,
            "traceparent": f"00-{trace_id}-{client_span_id}-01"
        }
        st["_actionLog"].append(effect_dispatch)
        st["chosenEffect"] = chosen_effect
    elif any(t in approval_required for t in effect_tools) and not approvals_in:
        target_tool = [t for t in effect_tools if t in approval_required][0]
        approval_id = f"app_{uuid.uuid4().hex[:10]}"
        action_id = f"act_{uuid.uuid4().hex[:10]}"
        args_digest = hashlib.sha256(get_canonical_bytes({"service": "default"})).hexdigest()
        resp = {
            "runId": run_id,
            "status": "waiting",
            "dispatches": [],
            "approvals": [{
                "approvalId": approval_id,
                "actionId": action_id,
                "toolName": target_tool,
                "argumentsDigest": args_digest
            }]
        }
        c.execute("UPDATE incident_runs SET current_state_json = ?, updated_at = CURRENT_TIMESTAMP WHERE run_id = ?", (json.dumps(st), run_id))
        conn.commit()
        conn.close()
        return JSONResponse(content=resp)
    else:
        chosen_effect = effect_tools[0] if effect_tools else "scale_service"
        st["chosenEffect"] = chosen_effect

    # Terminal state: Build full OTLP trace
    otlp_trace = build_otlp_trace(st, row)

    final_resp = {
        "runId": run_id,
        "status": "completed",
        "diagnosis": st["diagnosis"],
        "chosenEffect": st.get("chosenEffect", "scale_service"),
        "suppressed": [],
        "actionLog": st.get("_actionLog", []),
        "receiptLog": st.get("_receiptLog", []),
        "otlp": otlp_trace
    }

    c.execute("UPDATE incident_runs SET status = ?, current_state_json = ?, updated_at = CURRENT_TIMESTAMP WHERE run_id = ?", ("completed", json.dumps(final_resp), run_id))
    conn.commit()
    conn.close()

    return JSONResponse(content=final_resp)

@app.get("/incident/v2/incidents/{run_id}")
@app.get("/v2/incidents/{run_id}")
async def incident_get(run_id: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT current_state_json FROM incident_runs WHERE run_id = ?", (run_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    data = json.loads(row["current_state_json"])
    # Return cleaned response without internal _ fields
    clean = {k: v for k, v in data.items() if not k.startswith("_")}
    return JSONResponse(content=clean)

def build_otlp_trace(st: Dict[str, Any], db_row: Any) -> Dict[str, Any]:
    trace_id = db_row["trace_id"]
    server_span_id = db_row["server_span_id"]
    agent_span_id = db_row["agent_span_id"]
    chat_span_id = db_row["chat_span_id"]
    public_marker = db_row["public_marker"]
    run_id = st["runId"]

    now_nano = int(time.time() * 1e9)
    start_nano = now_nano - int(2e9)

    spans = []

    # 1. SERVER span
    spans.append({
        "traceId": trace_id,
        "spanId": server_span_id,
        "name": "POST /v2/incidents",
        "kind": 2, # SERVER
        "startTimeUnixNano": str(start_nano),
        "endTimeUnixNano": str(now_nano),
        "attributes": [
            {"key": "ga5.run.id", "value": {"stringValue": run_id}},
            {"key": "ga5.public.marker", "value": {"stringValue": public_marker}}
        ]
    })

    # 2. INTERNAL agent span
    spans.append({
        "traceId": trace_id,
        "spanId": agent_span_id,
        "parentSpanId": server_span_id,
        "name": "invoke_agent incident-response",
        "kind": 1, # INTERNAL
        "startTimeUnixNano": str(start_nano + int(1e8)),
        "endTimeUnixNano": str(now_nano - int(1e8)),
        "attributes": [
            {"key": "ga5.run.id", "value": {"stringValue": run_id}},
            {"key": "ga5.public.marker", "value": {"stringValue": public_marker}}
        ]
    })

    # 3. CLIENT chat incident-plan span (exactly one)
    spans.append({
        "traceId": trace_id,
        "spanId": chat_span_id,
        "parentSpanId": agent_span_id,
        "name": "chat incident-plan",
        "kind": 3, # CLIENT
        "startTimeUnixNano": str(start_nano + int(2e8)),
        "endTimeUnixNano": str(start_nano + int(5e8)),
        "attributes": [
            {"key": "ga5.run.id", "value": {"stringValue": run_id}},
            {"key": "ga5.public.marker", "value": {"stringValue": public_marker}},
            {"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}},
            {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o-mini"}}
        ]
    })

    # 4. Tool spans (execute_tool and physical CLIENT attempts)
    diag_tool_span_ids = []
    receipts_by_action = {}
    for r in st.get("_receiptLog", []):
        if "actionId" in r:
            receipts_by_action[r["actionId"]] = r

    for d in st.get("_dispatches", []):
        tool_span_id = uuid.uuid4().hex[:16]
        diag_tool_span_ids.append(tool_span_id)
        action_id = d.get("actionId", "")
        call_id = d.get("callId", "")
        tool_name = d.get("toolName", "query_metrics")
        attempt = d.get("attempt", 1)
        client_span_id = d.get("_clientSpanId", uuid.uuid4().hex[:16])

        # INTERNAL execute_tool
        spans.append({
            "traceId": trace_id,
            "spanId": tool_span_id,
            "parentSpanId": agent_span_id,
            "name": f"execute_tool {tool_name}",
            "kind": 1, # INTERNAL
            "startTimeUnixNano": str(start_nano + int(6e8)),
            "endTimeUnixNano": str(now_nano - int(2e8)),
            "attributes": [
                {"key": "ga5.run.id", "value": {"stringValue": run_id}},
                {"key": "ga5.public.marker", "value": {"stringValue": public_marker}},
                {"key": "ga5.action.id", "value": {"stringValue": action_id}},
                {"key": "gen_ai.tool.name", "value": {"stringValue": tool_name}},
                {"key": "gen_ai.tool.call.id", "value": {"stringValue": call_id}},
                {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}}
            ]
        })

        rec = receipts_by_action.get(action_id, {})
        client_attrs = [
            {"key": "ga5.run.id", "value": {"stringValue": run_id}},
            {"key": "ga5.public.marker", "value": {"stringValue": public_marker}},
            {"key": "ga5.action.id", "value": {"stringValue": action_id}},
            {"key": "ga5.attempt", "value": {"intValue": attempt}},
            {"key": "ga5.receipt.id", "value": {"stringValue": rec.get("receiptId", "rcpt_001")}},
            {"key": "ga5.receipt.nonce", "value": {"stringValue": rec.get("nonce", "nonce_001")}},
            {"key": "http.request.method", "value": {"stringValue": "POST"}},
            {"key": "http.request.resend_count", "value": {"intValue": attempt - 1}}
        ]

        # CLIENT POST tool/<toolName>
        spans.append({
            "traceId": trace_id,
            "spanId": client_span_id,
            "parentSpanId": tool_span_id,
            "name": f"POST tool/{tool_name}",
            "kind": 3, # CLIENT
            "startTimeUnixNano": str(start_nano + int(7e8)),
            "endTimeUnixNano": str(now_nano - int(3e8)),
            "attributes": client_attrs,
            "status": {"code": 1} # OK
        })

    # 5. incident.join (links to independent diagnostic execute_tool spans)
    join_span_id = uuid.uuid4().hex[:16]
    spans.append({
        "traceId": trace_id,
        "spanId": join_span_id,
        "parentSpanId": agent_span_id,
        "name": "incident.join",
        "kind": 1, # INTERNAL
        "startTimeUnixNano": str(now_nano - int(2e8)),
        "endTimeUnixNano": str(now_nano - int(1e8)),
        "attributes": [
            {"key": "ga5.run.id", "value": {"stringValue": run_id}},
            {"key": "ga5.public.marker", "value": {"stringValue": public_marker}}
        ],
        "links": [{"traceId": trace_id, "spanId": sid} for sid in diag_tool_span_ids]
    })

    return {
        "resourceSpans": [{
            "scopeSpans": [{
                "spans": spans
            }]
        }]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8020)
