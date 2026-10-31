"""Exploratory audit against an isolated local server; does not modify app code."""
import concurrent.futures
import json
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8019"
latencies = []


def req(c, method, path, **kwargs):
    start = time.perf_counter()
    r = c.request(method, path, **kwargs)
    latencies.append((time.perf_counter() - start) * 1000)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:150]}")
    return r.json()


def chat(c, sid, choice=None, text=""):
    return req(c, "POST", "/api/chat", json={"session_id": sid, "choice": choice, "text": text})


def user(i):
    with httpx.Client(base_url=BASE, timeout=60) as c:
        product = "insurance" if i % 2 else "loan"
        r = req(c, "POST", "/api/sessions", json={"product": product, "language": "hi" if i % 3 == 0 else "en"})
        sid = r["session_id"]
        if product == "insurance":
            for choice in ("family", "sum:1000000", "ped:no", "grant"):
                r = chat(c, sid, choice)
            r = chat(c, sid, next(x["value"] for x in r["chips"] if x["value"].startswith("plan:")))
            chat(c, sid, "declare")
            r = chat(c, sid, "pay")
            policies = req(c, "GET", f"/api/sessions/{sid}/policies")["policies"]
            assert len(policies) == 1 and policies[0]["session_id"] == sid
            assert policies[0]["status"] == "issued"
        else:
            for choice in ("loan:300000", "purpose:personal", "amount:300000", "tenure:36", "budget:any", "75k_plus", "salaried", "grant", "grant"):
                r = chat(c, sid, choice)
            assert r["step"] == "offers", r["step"]
        s = req(c, "GET", f"/api/sessions/{sid}")
        assert s["session"]["product"] == product
        assert len(s["messages"]) == 1 + (14 if product == "insurance" else 18)
        return {"user": i, "product": product, "sid": sid, "step": r["step"], "messages": len(s["messages"])}


def explore():
    findings = {}
    with httpx.Client(base_url=BASE, timeout=60) as a, httpx.Client(base_url=BASE, timeout=60) as b:
        def new(product="loan"):
            return req(a, "POST", "/api/sessions", json={"product": product})["session_id"]

        sid = new()
        findings["eligibility_chip"] = chat(a, sid, "eligibility")
        sid = new("insurance")
        findings["insurance_typed_family"] = chat(a, sid, text="My wife and two children")
        chat(a, sid, "family")
        findings["insurance_typed_cover"] = chat(a, sid, text="10 lakh")
        findings["insurance_after_typed_cover"] = req(a, "GET", f"/api/sessions/{sid}")["session"]

        sid = new("insurance")
        for choice in ("self", "sum:1000000", "ped:no", "grant"):
            r = chat(a, sid, choice)
        plan = next(x["value"] for x in r["chips"] if x["value"].startswith("plan:"))
        req(a, "DELETE", f"/api/sessions/{sid}/consent/paytm.profile")
        req(a, "DELETE", f"/api/sessions/{sid}/consent/paytm.kyc")
        r = chat(a, sid, plan)
        findings["insurance_after_revocation"] = {"step": r["step"], "consents": req(a, "GET", f"/api/sessions/{sid}/consent")["active"]}
        policy = req(a, "GET", f"/api/sessions/{sid}/policies")["policies"][0]
        findings["unrelated_client_read"] = {"session_status": b.get(f"/api/sessions/{sid}").status_code, "policy_status": b.get(f"/api/policies/{policy['id']}").status_code}
        findings["unrelated_client_declare"] = b.post(f"/api/policies/{policy['id']}/declare", json=["none"]).status_code

        sid = new()
        for choice in ("loan:300000", "purpose:personal"):
            chat(a, sid, choice)
        findings["amount_unclear_reply"] = chat(a, sid, text="I am not sure yet")
        findings["amount_after_unclear_reply"] = req(a, "GET", f"/api/sessions/{sid}")["slots"].get("amount")
        sid = new()
        findings["malformed_choice_status"] = a.post("/api/chat", json={"session_id": sid, "choice": "loan:abc"}).status_code
        sid = new("insurance")
        chat(a, sid, "self")
        findings["unsupported_cover_choice"] = a.post("/api/chat", json={"session_id": sid, "choice": "sum:123"}).status_code
        chat(a, sid, "ped:no")
        findings["unsupported_cover_grant"] = a.post("/api/chat", json={"session_id": sid, "choice": "grant"}).status_code
    return findings


if __name__ == "__main__":
    start = time.perf_counter()
    users, errors = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        jobs = {pool.submit(user, i): i for i in range(20)}
        for job in concurrent.futures.as_completed(jobs):
            try:
                users.append(job.result())
            except Exception as exc:
                errors.append({"user": jobs[job], "error": str(exc)})
    duration = time.perf_counter() - start
    timing = sorted(latencies)
    results = {"concurrency": {"users": 20, "completed": len(users), "errors": errors, "duration_seconds": round(duration, 2), "requests": len(timing), "p50_ms": round(timing[len(timing)//2]), "p95_ms": round(timing[int(len(timing)*.95)]), "max_ms": round(max(timing)), "users_detail": users}, "findings": explore()}
    Path("qa_review_results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=True))
