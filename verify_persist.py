"""Section 7 checks: complete a loan, reload, restart the server, second loan."""
import base64, json, os, subprocess, threading, time, urllib.request
os.environ["DATABASE_PATH"] = "persist_check.db"
DB = os.path.abspath("persist_check.db")
if os.path.exists(DB):
    os.remove(DB)

import httpx, uvicorn, websocket
from app.main import app

PORT = 8020
def start():
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        if srv.started:
            return srv
        time.sleep(0.1)
    raise RuntimeError("server did not start")

srv = start()
c = httpx.Client(base_url=f"http://127.0.0.1:{PORT}", timeout=20)

proc = subprocess.Popen(["chromium", "--headless=new", "--disable-gpu", "--no-sandbox",
                         "--hide-scrollbars", "--window-size=1440,940",
                         "--remote-debugging-port=9230", "--remote-allow-origins=*", "about:blank"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
targets = None
for _ in range(60):
    try:
        targets = json.load(urllib.request.urlopen("http://127.0.0.1:9230/json/list"))
        if any(t.get("type") == "page" for t in targets):
            break
    except Exception:
        pass
    time.sleep(0.3)
ws = websocket.create_connection(next(t["webSocketDebuggerUrl"] for t in targets if t.get("type") == "page"), timeout=40)
_id = [0]
def cmd(m, p=None):
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": m, "params": p or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == _id[0]:
            return msg.get("result", {})
def ev(e):
    r = ev_raw(e)
    return r.get("result", {}).get("value")
def ev_raw(e):
    return cmd("Runtime.evaluate", {"expression": e, "awaitPromise": True, "returnByValue": True})
def shot(n):
    ev("document.getElementById('modal').classList.remove('on')"); time.sleep(0.2)
    d = cmd("Page.captureScreenshot", {"format": "png"})
    open(f"/scratch/work/ps_{n}.png", "wb").write(base64.b64decode(d["data"]))
    print("  shot:", n)

cmd("Page.enable")
cmd("Page.navigate", {"url": f"http://127.0.0.1:{PORT}/"})
time.sleep(3)

print("1. complete a loan application")
for js in ["send('I need a 5 lakh loan')", "send('', 'purpose:education')", "send('', 'amount:500000')",
           "send('', 'tenure:24')", "send('', 'budget:25000')", "send('', '75k_plus')",
           "send('', 'salaried')", "send('', 'grant')", "send('', 'grant')"]:
    ev(js); time.sleep(0.7)
sid = ev("localStorage.getItem('paypilot.session_id')")
print("   session id in localStorage:", bool(sid))
offer = ev("document.querySelectorAll('[data-cmp]')[0].dataset.cmp")
ev("send('', 'offer:" + offer + "')"); time.sleep(1.2)
ev("send('', 'grant')"); time.sleep(1.4)
app_id = ev("window.__appid || (JSON.parse(localStorage.getItem('paypilot.ui')||'{}').lastTurn||{}).cards?.find(c=>c.type==='prefill')?.data?.application_id")
ev("""(async () => { const id = '%s';
  for (const t of ['salary_slip','bank_statement']) { const fd = new FormData();
    fd.append('file', new Blob([new Uint8Array([37,80,68,70,45,49,46,52])], {type:'application/pdf'}), t+'.pdf');
    await fetch('/api/applications/'+id+'/documents/'+t, {method:'POST', body: fd}); }
  return 1; })()""" % app_id); time.sleep(1.2)
for js in ["send('', 'continue')", "send('', 'refresh_docs')", "send('', 'continue')",
           "send('', 'grant')", "send('', 'check_status')", "send('', 'check_status')"]:
    ev(js); time.sleep(0.9)
msgs_before = ev("document.querySelectorAll('.msg').length")
apps_before = c.get(f"/api/sessions/{sid}/applications").json()["applications"]
print(f"   messages: {msgs_before} | applications: {len(apps_before)} | status: {apps_before[0]['status']}")
shot("1_complete")

print("2. refresh the browser")
cmd("Page.navigate", {"url": f"http://127.0.0.1:{PORT}/"})
time.sleep(3)
msgs_after = ev("document.querySelectorAll('.msg').length")
tracker_active = ev("!!document.querySelector('.tk-head')")
resumed = ev("document.body.innerText.includes('RESUMED')")
print(f"   messages restored: {msgs_after} (was {msgs_before}) | tracker: {tracker_active} | resumed marker: {resumed}")
assert msgs_after >= msgs_before, "conversation did not restore"
shot("2_reloaded")

print("3. restart the backend")
srv.should_exit = True
time.sleep(2.5)
srv = start()
time.sleep(0.8)
app_after = c.get(f"/api/applications/{apps_before[0]['id']}")
print(f"   application after restart: {app_after.status_code} {app_after.json()['application']['status']}")
assert app_after.status_code == 200
cmd("Page.navigate", {"url": f"http://127.0.0.1:{PORT}/"})
time.sleep(3)
print(f"   chat after restart: {ev('document.querySelectorAll(\".msg\").length')} messages")
shot("3_after_restart")

print("4. second loan, first one must stay")
ev("""(async () => { await fetch('/api/sessions/%s/applications',
  {method:'POST', headers:{'Content-Type':'application/json'},
   body: JSON.stringify({lender_id:'hero', amount:200000})}); return 1; })()""" % sid)
time.sleep(1.2)
apps = c.get(f"/api/sessions/{sid}/applications").json()["applications"]
print(f"   applications now: {len(apps)} -> {[(a['reference'], a['status']) for a in apps]}")
assert len(apps) == 2
ev("document.querySelector('#tabs button[data-t=\"apps\"]').click()"); time.sleep(1.5)
rows = ev("document.querySelectorAll('#tabBody [data-app]').length")
print(f"   applications tab rows: {rows}")
assert rows == 2
shot("4_applications")

ev("document.querySelector('#tabBody [data-app]').click()"); time.sleep(1.6)
print("   detail sheet open:", ev("document.getElementById('modal').classList.contains('on')"))
time.sleep(0.5)
d = cmd("Page.captureScreenshot", {"format": "png"})       # no modal-close: we want to see it
open("/scratch/work/ps_5_detail.png", "wb").write(base64.b64decode(d["data"]))
print("  shot: 5_detail")

ev("document.getElementById('modalClose').click()"); time.sleep(0.4)
print("\nALL PERSISTENCE CHECKS PASSED")
ws.close(); proc.terminate(); srv.should_exit = True
