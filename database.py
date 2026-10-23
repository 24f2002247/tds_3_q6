import sqlite3
import json
import os
from typing import Optional, Dict, Any, List

DB_PATH = os.path.join(os.path.dirname(__file__), "ga3_state.db")

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout = 20000;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # Q2: A2A Tasks
    c.execute("""
    CREATE TABLE IF NOT EXISTS a2a_tasks (
        task_id TEXT PRIMARY KEY,
        context_id TEXT NOT NULL,
        bearer_token TEXT NOT NULL,
        message_id TEXT NOT NULL,
        message_hash TEXT NOT NULL,
        batch_id TEXT,
        state TEXT NOT NULL,
        task_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_a2a_principal_msg 
    ON a2a_tasks(bearer_token, message_id)
    """)

    # Q2: A2A Message Idempotency & Replay Store
    c.execute("""
    CREATE TABLE IF NOT EXISTS a2a_messages (
        bearer_token TEXT NOT NULL,
        message_id TEXT NOT NULL,
        message_hash TEXT NOT NULL,
        task_id TEXT NOT NULL,
        response_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (bearer_token, message_id)
    )
    """)

    # Q2: Package semantic decisions cache
    c.execute("""
    CREATE TABLE IF NOT EXISTS a2a_decision_cache (
        canonical_content_hash TEXT PRIMARY KEY,
        action TEXT NOT NULL,
        action_id TEXT NOT NULL,
        facts_json TEXT NOT NULL,
        evidence_refs_json TEXT NOT NULL,
        rationale TEXT NOT NULL
    )
    """)

    # Q3: Mailroom Evaluations & Proposals
    c.execute("""
    CREATE TABLE IF NOT EXISTS mailroom_evaluations (
        evaluation_id TEXT PRIMARY KEY,
        input_digest TEXT NOT NULL,
        verifier_jwk TEXT NOT NULL,
        status TEXT NOT NULL,
        request_json TEXT NOT NULL,
        response_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Q3: Mailroom Dossier Cache
    c.execute("""
    CREATE TABLE IF NOT EXISTS mailroom_dossier_cache (
        canonical_content_hash TEXT PRIMARY KEY,
        call_id TEXT NOT NULL,
        action TEXT NOT NULL,
        target_json TEXT,
        payload_json TEXT NOT NULL,
        evidence_json TEXT NOT NULL
    )
    """)

    # Q4: Incident Runs
    c.execute("""
    CREATE TABLE IF NOT EXISTS incident_runs (
        run_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        root_cause TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        public_marker TEXT NOT NULL,
        agent_name TEXT NOT NULL,
        incoming_traceparent TEXT,
        incoming_tracestate TEXT,
        trace_id TEXT NOT NULL,
        server_span_id TEXT NOT NULL,
        agent_span_id TEXT NOT NULL,
        chat_span_id TEXT NOT NULL,
        raw_incident_json TEXT NOT NULL,
        current_state_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Q4: Incident Receipts Log
    c.execute("""
    CREATE TABLE IF NOT EXISTS incident_receipts (
        receipt_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        receipt_hash TEXT NOT NULL,
        raw_receipt_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at", DB_PATH)
