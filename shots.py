"""Drives the real UI through CDP and captures the new screens."""
import base64, json, os, subprocess, threading, time, urllib.request
os.environ["DATABASE_PATH"] = "shots.db"
if os.path.exists("shots.db"):
    os.remove("shots.db")
import uvicorn, websocket
from app.main import app

srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8015, log_level="warning"))
threading.Thread(target=srv.run, daemon=True).start()
for _ in range(80):
    if srv.started:
        break
    time.sleep(0.1)

proc = subprocess.Popen(["chromium", "--headless=new", "--disable-gpu", "--no-sandbox",
                         "--hide-scrollbars", "--window-size=1440,940",
                         "--remote-debugging-port=9225", "--remote-allow-origins=*", "about:blank"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
targets = None
for _ in range(60):
    try:
        targets = json.load(urllib.request.urlopen("http://127.0.0.1:9225/json/list"))
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
    return cmd("Runtime.evaluate", {"expression": e, "awaitPromise": True, "returnByValue": True})
def shot(n):
    ev("document.getElementById('modal').classList.remove('on')")
    time.sleep(0.2)
    d = cmd("Page.captureScreenshot", {"format": "png"})
    open(f"/scratch/work/nx_{n}.png", "wb").write(base64.b64decode(d["data"]))
    print("shot:", n)

cmd("Page.enable")
cmd("Page.navigate", {"url": "http://127.0.0.1:8015/"})
time.sleep(3)
shot("start")

def step(js, wait=1.2):
    ev(js); time.sleep(wait)

step("send('I need a 5 lakh loan for education')")
for ch in ["purpose:education", "amount:500000", "tenure:24", "budget:15000", "75k_plus", "salaried"]:
    step("send('', '%s')" % ch, 0.8)
step("send('', 'grant')", 1.4)
step("send('', 'grant')", 2.0)
ev("document.getElementById('chat').scrollTop = 0")
time.sleep(0.5)
shot("offers")
ev("document.getElementById('chat').scrollTop = 900")
time.sleep(0.4)
shot("offers_mid")

# open the schedule modal for the top offer, then close
step("document.querySelectorAll('[data-sched]')[0].click()", 1.6)
shot("schedule")
step("document.getElementById('modalClose').click()", 0.6)

# side-by-side
step("document.querySelectorAll('[data-cmp]')[0].click(); document.querySelectorAll('[data-cmp]')[1].click()", 0.5)
step("document.querySelector('[data-cmpsubmit]').click()", 1.6)
shot("compare")
step("document.getElementById('modalClose').click()", 0.6)

# apply
ev("window.__offer = document.querySelectorAll('[data-cmp]')[0].dataset.cmp")
step("send('', 'offer:' + window.__offer)", 1.4)
shot("consent_share")
step("send('', 'grant')", 1.6)
shot("prefill")
step("send('', 'continue')", 1.6)
shot("documents")

# upload both documents through the API, then refresh
ev("""(async () => {
  const id = window.__appid;
  for (const t of ['salary_slip','bank_statement']) {
    const fd = new FormData();
    fd.append('file', new Blob([new Uint8Array([37,80,68,70,45,49,46,52])], {type:'application/pdf'}), t + '.pdf');
    await fetch('/api/applications/' + id + '/documents/' + t, {method:'POST', body: fd});
  }
  return 'uploaded';
})()""")
time.sleep(1.5)
step("send('', 'refresh_docs')", 1.6)
shot("documents_done")
step("send('', 'continue')", 1.6)
shot("review")
step("send('', 'grant')", 1.8)
shot("submitted")
step("send('', 'check_status')", 1.4)
step("send('', 'check_status')", 2.0)
shot("approved")
step("document.querySelector('#tabs button[data-t=\"consent\"]').click()", 1.2)
shot("consent")

# conflicts, in a fresh session
step("document.getElementById('resetBtn').click()", 2.0)
step("send('I need a loan')", 1.2)
for ch in ["purpose:business", "amount:500000", "tenure:24", "budget:any", "under_30k", "salaried"]:
    step("send('', '%s')" % ch, 0.8)
shot("conflicts")

ws.close(); proc.terminate(); srv.should_exit = True
print("done")
