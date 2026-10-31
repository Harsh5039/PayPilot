"""Records a canonical session from the live backend for the offline preview."""
import json, os, threading, time
os.environ["DATABASE_PATH"] = "record.db"
if os.path.exists("record.db"):
    os.remove("record.db")

import httpx, uvicorn
from app.main import app

srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8016, log_level="warning"))
threading.Thread(target=srv.run, daemon=True).start()
for _ in range(80):
    if srv.started:
        break
    time.sleep(0.1)

c = httpx.Client(base_url="http://127.0.0.1:8016", timeout=25)
created = c.post("/api/sessions", json={"language": "en"}).json()
sid = created["session_id"]
steps = [{"choice": "__session__", "text": "", "response": created,
          "consent": c.get(f"/api/sessions/{sid}/consent").json()["ledger"],
          "audit": c.get(f"/api/sessions/{sid}/audit").json()["events"]}]
last = created

def chip(resp, value):
    for ch in resp.get("chips", []):
        if ch["value"] == value:
            return ch
    return None

def first(resp, prefix):
    for ch in resp.get("chips", []):
        if ch["value"].startswith(prefix):
            return ch
    return None

def record(text, choice):
    global last
    r = c.post("/api/chat", json={"session_id": sid, "text": text, "choice": choice}).json()
    steps.append({"choice": choice, "text": text, "response": r,
                  "consent": c.get(f"/api/sessions/{sid}/consent").json()["ledger"],
                  "audit": c.get(f"/api/sessions/{sid}/audit").json()["events"]})
    last = r
    return r

PLAN = ["loan:500000", "purpose:education", "amount:500000", "tenure:24", "budget:15000",
        "75k_plus", "salaried", "grant", "grant", "OFFER", "grant", "continue",
        "UPLOAD", "refresh_docs", "continue", "grant", "check_status", "check_status"]

app_id = None
for target in PLAN:
    if target == "OFFER":
        ch = first(last, "offer:")
    elif target == "UPLOAD":
        app_id = next(s["response"]["cards"][0]["data"]["application_id"] for s in steps
                      if s["response"].get("cards") and s["response"]["cards"][0].get("type") == "prefill")
        for dt in ("salary_slip", "bank_statement"):
            c.post(f"/api/applications/{app_id}/documents/{dt}",
                   files={"file": (f"{dt}.pdf", b"%PDF-1.4 demo", "application/pdf")})
        print("  uploaded both documents")
        continue
    else:
        ch = chip(last, target)
    if not ch:
        print("!! no chip for", target, "| step:", last.get("step"),
              "| chips:", [x["value"] for x in last.get("chips", [])])
        break
    r = record(ch["label"], ch["value"])
    print(f"  {target:14s} -> {r['step']}")

extra = {}
if app_id:
    extra["summary"] = c.get(f"/api/applications/{app_id}/summary").json()
out = {"steps": steps, "extra": extra, "health": c.get("/api/health").json()}
json.dump(out, open("/scratch/work/recording.json", "w"))
print("recorded", len(steps), "steps,", os.path.getsize("/scratch/work/recording.json"), "bytes")
srv.should_exit = True
