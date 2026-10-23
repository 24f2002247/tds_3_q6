import subprocess
import time
import re
import sys
import os
import json
import requests

sys.stdout.reconfigure(line_buffering=True)
DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_PORT = 8020
CLOUDFLARED_PATH = r"C:\Users\Jayraj\cloudflared.exe"

def start():
    print(f"Starting Unified Agent Server on port {SERVER_PORT}...")
    server_log_path = os.path.join(DIR, "server.log")
    server_log_file = open(server_log_path, "w", encoding="utf-8")
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(SERVER_PORT)],
        cwd=DIR,
        stdout=server_log_file,
        stderr=subprocess.STDOUT,
        text=True
    )

    # Health check
    for _ in range(25):
        time.sleep(1)
        try:
            r = requests.get(f"http://127.0.0.1:{SERVER_PORT}/healthz", timeout=1)
            if r.status_code == 200:
                print(f"Unified server is UP on port {SERVER_PORT}!")
                break
        except Exception:
            pass
    else:
        print("Server failed to respond to health check.")
        return

    cf_log_path = os.path.join(DIR, "cf_tunnel.log")
    if os.path.exists(cf_log_path):
        try:
            os.remove(cf_log_path)
        except Exception:
            pass

    cf_log_file = open(cf_log_path, "a", encoding="utf-8")
    print(f"Launching Cloudflare tunnel for port {SERVER_PORT}...")
    cf_proc = subprocess.Popen(
        [CLOUDFLARED_PATH, "tunnel", "--url", f"http://127.0.0.1:{SERVER_PORT}"],
        stdout=cf_log_file,
        stderr=subprocess.STDOUT,
        text=True
    )

    tunnel_url = None
    for _ in range(40):
        time.sleep(1)
        if os.path.exists(cf_log_path):
            with open(cf_log_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                matches = re.findall(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com", content)
                if matches:
                    tunnel_url = matches[-1]
                    break

    if not tunnel_url:
        print("Could not retrieve Cloudflare tunnel URL.")
        return

    print("=================================================================")
    print(f"CLOUDFLARE TUNNEL LIVE: {tunnel_url}")
    print("=================================================================")

    endpoints = {
        "base_url": tunnel_url,
        "q6_glb_url": f"{tunnel_url}/joanne_woodward.glb",
        "q2_a2a_base_url": f"{tunnel_url}/a2a",
        "q2_agent_card": f"{tunnel_url}/.well-known/agent-card.json",
        "q3_mailroom_url": f"{tunnel_url}/mailroom",
        "q4_incident_base_url": f"{tunnel_url}/incident"
    }

    urls_path = os.path.join(DIR, "submission_urls.json")
    with open(urls_path, "w") as f:
        json.dump(endpoints, f, indent=2)

    for k, v in endpoints.items():
        print(f"  {k}: {v}")

    # Supervisor keep-alive loop
    while True:
        try:
            time.sleep(5)
            # Check server
            if server_proc.poll() is not None:
                print("Server exited unexpectedly, restarting...")
                server_proc = subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(SERVER_PORT)],
                    cwd=DIR,
                    stdout=server_log_file,
                    stderr=subprocess.STDOUT,
                    text=True
                )
            # Check tunnel
            if cf_proc.poll() is not None:
                print("Tunnel exited, restarting...")
                cf_proc = subprocess.Popen(
                    [CLOUDFLARED_PATH, "tunnel", "--url", f"http://127.0.0.1:{SERVER_PORT}"],
                    stdout=cf_log_file,
                    stderr=subprocess.STDOUT,
                    text=True
                )
        except Exception as e:
            time.sleep(2)

if __name__ == "__main__":
    start()
