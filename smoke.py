"""Boots the real server on a thread and walks both journeys over HTTP."""
import os, threading, time
os.environ["DATABASE_PATH"] = "smoke.db"
if os.path.exists("smoke.db"):
    os.remove("smoke.db")

import httpx, uvicorn
from app.main import app

srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8014, log_level="warning"))
threading.Thread(target=srv.run, daemon=True).start()
for _ in range(80):
    if srv.started:
        break
    time.sleep(0.1)

c = httpx.Client(base_url="http://127.0.0.1:8014", timeout=25)
h = c.get("/api/health").json()
print("health:", h["status"], "| mode:", h["llm"]["mode"])

sid = c.post("/api/sessions", json={"language": "en"}).json()["session_id"]
def chat(text="", choice=None):
    return c.post("/api/chat", json={"session_id": sid, "text": text, "choice": choice}).json()

chat("I need a 5 lakh loan for my daughter's education")
print("purpose chips:", len(chat("", "purpose:education")["chips"]))
chat("", "amount:500000"); chat("", "tenure:24"); chat("", "budget:15000")
chat("", "75k_plus"); r = chat("", "salaried")
print("after employment ->", r["step"])
chat("", "grant"); r = chat("", "grant")
print("offers step:", r["step"], "| cards:", [x["type"] for x in r["cards"]])
snap = r["cards"][0]["data"]
print(f"  health: income {snap['health']['monthly_income']} spend {snap['health']['monthly_expenses']} "
      f"disposable {snap['health']['disposable_income']} affordable EMI {snap['health']['affordable_emi']} "
      f"score {snap['health']['credit_score']} grade {snap['health']['grade_label']}")
offers = r["cards"][1]["data"]
hl = r["cards"][1]["highlights"]
for o in offers:
    print(f"  {o['lender_name']:22s} {o['tenure_months']}m EMI {o['emi']:>9.0f} rate {o['annual_rate']:5.2f}% "
          f"APR {o['apr']:5.2f}% fee {o['processing_fee']:>7.0f} total {o['total_payable']:>10.0f} "
          f"budget={'ok' if o['within_budget'] else 'over'}")
    print(f"     {o['why']}")
print("  highlights:", {k: (v if not isinstance(v, dict) else v.get('lender_name')) for k, v in hl.items()})

r = chat("", "change_tenure"); r = chat("", "tenure:36")
print("after tenure change ->", r["step"], "| offers:", [(o['lender_name'], o['tenure_months']) for o in r["cards"][0]["data"]])
best = r["cards"][0]["data"][0]

cmp_ = c.post(f"/api/sessions/{sid}/loans/compare-selected",
              json={"offer_ids": [o["offer_id"] for o in r["cards"][0]["data"][:2]], "amount": 500000}).json()
print("side-by-side:", cmp_["cheapest_total"], "vs", cmp_["cheapest_rate"])

r = chat("", "offer:" + best["offer_id"]); print("consent share ->", r["step"], r["consent_request"]["scopes"], "| shared_with:", r["consent_request"].get("shared_with"))
r = chat("", "grant"); app_id = r["cards"][0]["data"]["application_id"]
print("prefill ->", r["step"], "| ref:", r["cards"][0]["data"]["reference"])
r = chat("", "continue"); print("docs ->", r["step"], "| missing:", [m["doc_type"] for m in r["cards"][0]["data"]["missing"]])

for dt in ("salary_slip", "bank_statement"):
    up = c.post(f"/api/applications/{app_id}/documents/{dt}",
                files={"file": (f"{dt}.pdf", b"%PDF-1.4 demo", "application/pdf")}).json()
    print(f"  uploaded {dt}: {up['document']['confidence']} -> {up['document']['extracted']}")

r = chat("", "refresh_docs"); print("docs complete:", r["cards"][0]["data"]["complete"])
r = chat("", "continue"); print("review ->", r["step"], "| consent:", r["consent_request"]["scopes"],
                                 "| docs:", [d["label"] for d in r["cards"][0]["data"]["documents"]])
r = chat("", "grant"); print("submitted ->", r["step"], "| notifs:", len(r["notifications"]))
r = chat("", "check_status"); print("status ->", r["step"], r["cards"][0]["data"]["status"])
r = chat("", "check_status"); print("final ->", r["step"], r["cards"][0]["data"]["status"])
s = c.get(f"/api/applications/{app_id}/summary").json()
print("summary:", s["reference"], s["status"], "| payable", s["total_payable"], "| docs", len(s["documents"]))

# conflicts path
sid2 = c.post("/api/sessions", json={"language": "en"}).json()["session_id"]
c.post("/api/chat", json={"session_id": sid2, "text": "I need a loan", "choice": None})
for ch in ["purpose:business", "amount:500000", "tenure:24", "budget:any", "under_30k", "salaried"]:
    r = c.post("/api/chat", json={"session_id": sid2, "text": "", "choice": ch}).json()
print("conflicts:", [c_["field"] for c_ in r["cards"][0]["data"]], "| step:", r["step"])

# insurance
sid3 = c.post("/api/sessions", json={"language": "en"}).json()["session_id"]
def chat3(t="", ch=None):
    return c.post("/api/chat", json={"session_id": sid3, "text": t, "choice": ch}).json()
chat3("I need health insurance for my family")
for ch in ["family", "sum:1000000", "ped:no", "grant"]:
    r = chat3("", ch)
plans = r["cards"][0]["data"]
for ch in [f"plan:{plans[0]['plan_id']}", "declare", "pay"]:
    r = chat3("", ch)
print("insurance:", r["step"], r["cards"][0]["data"]["status"])
print("notifications total:", len(c.get(f"/api/sessions/{sid}/notifications").json()["notifications"]))
srv.should_exit = True
