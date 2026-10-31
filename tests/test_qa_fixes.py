"""Regressions from the multi-user/browser audit."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import db


def start(c, product="insurance", language="en"):
    r = c.post("/api/sessions", json={"product": product, "language": language})
    assert r.status_code == 201
    return r.json()["session_id"]


def turn(c, sid, choice=None, text=""):
    r = c.post("/api/chat", json={"session_id": sid, "choice": choice, "text": text})
    assert r.status_code == 200, r.text
    return r.json()


def plans(c, sid):
    for choice in ("family", "sum:1000000", "ped:no", "grant"):
        r = turn(c, sid, choice)
    return r["chips"][0]["value"]


def test_other_browser_cannot_read_or_modify_private_resources(client):
    sid = start(client)
    plan = plans(client, sid)
    turn(client, sid, plan)
    pid = client.get(f"/api/sessions/{sid}/policies").json()["policies"][0]["id"]
    with TestClient(app) as other:
        other_sid = start(other)
        for path in (f"/api/sessions/{sid}", f"/api/sessions/{sid}/messages", f"/api/sessions/{sid}/consent", f"/api/sessions/{sid}/policies", f"/api/policies/{pid}"):
            assert other.get(path).status_code == 404
        assert other.post("/api/chat", json={"session_id": sid, "choice": "declare"}).status_code == 404
        assert other.post(f"/api/policies/{pid}/declare", json=["none"]).status_code == 404
        assert other.post(f"/api/policies/{pid}/pay").status_code == 404
        assert other.delete(f"/api/sessions/{sid}/consent/paytm.profile").status_code == 404
        assert other.patch(f"/api/sessions/{sid}/language", json={"language": "hi"}).status_code == 404
        assert other.get("/api/history").json() == {"applications": [], "policies": []}
        assert other.get(f"/api/sessions/{other_sid}").status_code == 200
    assert client.get(f"/api/policies/{pid}").json()["policy"]["status"] == "quoted"


def test_other_browser_cannot_access_loan_application(client):
    sid = start(client, "loan")
    client.post(f"/api/sessions/{sid}/consent", json={"scopes": ["paytm.profile", "paytm.income", "paytm.kyc", "lender.share"], "shared_with": "Aditya Birla Capital"})
    r = client.post(f"/api/sessions/{sid}/applications", json={"lender_id": "abc", "amount": 300000})
    assert r.status_code == 201
    aid = r.json()["application"]["id"]
    with TestClient(app) as other:
        start(other)
        for suffix in ("", "/documents", "/summary", "/review"):
            assert other.get(f"/api/applications/{aid}{suffix}").status_code == 404
        assert other.patch(f"/api/applications/{aid}/nominee", json={"name": "Other user"}).status_code == 404
        assert other.post(f"/api/applications/{aid}/submit").status_code == 404


def test_unowned_legacy_session_cannot_be_claimed(client):
    sid = db.create_session()["id"]
    assert client.get(f"/api/sessions/{sid}").status_code == 404


def test_cookie_and_cross_origin_write_guard(client):
    r = client.post("/api/sessions", json={})
    assert "HttpOnly" in r.headers["set-cookie"]
    assert "SameSite=strict" in r.headers["set-cookie"]
    assert client.post("/api/sessions", json={}, headers={"Origin": "https://another-site.example"}).status_code == 403


@pytest.mark.parametrize("family,amount,condition", [("My wife and two children", "10 lakh", "no"), ("मेरा परिवार", "10 लाख", "नहीं")])
def test_insurance_accepts_typed_answers_without_switching(client, family, amount, condition):
    sid = start(client)
    assert turn(client, sid, text=family)["step"] == "ins_sum"
    r = turn(client, sid, text=amount)
    assert r["step"] == "ins_ped"
    assert r["product"] == "insurance"
    assert turn(client, sid, text=condition)["step"] == "ins_consent"
    assert client.get(f"/api/sessions/{sid}").json()["slots"]["ins_sum"] == 1000000


def test_revoked_insurance_permissions_block_chat_and_direct_operations(client):
    sid = start(client)
    plan = plans(client, sid)
    client.delete(f"/api/sessions/{sid}/consent/paytm.profile")
    r = turn(client, sid, plan)
    assert r["step"] == "ins_plans" and r["consent_request"]
    assert client.get(f"/api/sessions/{sid}/policies").json()["policies"] == []
    assert client.post(f"/api/sessions/{sid}/insurance/policies", json={"plan_id": "hdfc"}).status_code == 403
    turn(client, sid, "grant")
    turn(client, sid, plan)
    pid = client.get(f"/api/sessions/{sid}/policies").json()["policies"][0]["id"]
    client.delete(f"/api/sessions/{sid}/consent/paytm.kyc")
    assert client.post(f"/api/policies/{pid}/declare", json=["none"]).status_code == 403
    assert turn(client, sid, "declare")["step"] == "ins_declare"
    turn(client, sid, "grant")
    turn(client, sid, "declare")
    client.delete(f"/api/sessions/{sid}/consent/paytm.profile")
    assert client.post(f"/api/policies/{pid}/pay").status_code == 403


def test_language_changes_preserve_progress_and_actions(client):
    sid = start(client)
    turn(client, sid, "family")
    before = client.get(f"/api/sessions/{sid}").json()
    for language in ("hi", "en"):
        r = client.patch(f"/api/sessions/{sid}/language", json={"language": language})
        assert r.status_code == 200
        after = client.get(f"/api/sessions/{sid}").json()
        assert after["slots"] == before["slots"]
        assert after["messages"] == before["messages"]
        assert after["session"]["step"] == "ins_sum"
        assert after["last_turn"]["chips"][1]["value"] == "sum:1000000"
    assert "How much cover" in after["last_turn"]["reply"]


def test_eligibility_shortcut_and_hindi_chips(client):
    sid = start(client, "loan")
    assert turn(client, sid, "eligibility")["step"] == "purpose"
    sid = start(client, language="hi")
    r = client.get(f"/api/sessions/{sid}").json()["last_turn"]
    assert r["chips"][0] == {"label": "सिर्फ मैं", "value": "self"}


@pytest.mark.parametrize("choice", ["loan:abc", "amount:-1", "tenure:0", "sum:123", "sum:1000000000000000", "budget:NaN"])
def test_invalid_choices_do_not_change_state(client, choice):
    sid = start(client)
    before = client.get(f"/api/sessions/{sid}").json()
    assert client.post("/api/chat", json={"session_id": sid, "choice": choice}).status_code == 422
    after = client.get(f"/api/sessions/{sid}").json()
    assert after["messages"] == before["messages"]
    assert after["slots"] == before["slots"]


def test_policy_history_survives_new_chat_and_tracker_is_honest(client):
    sid = start(client)
    turn(client, sid, plans(client, sid))
    turn(client, sid, "declare")
    r = turn(client, sid, "pay")
    notes = " ".join(s["note"] for s in r["tracker"]["steps"])
    assert "no charge" in notes and "no insurer policy or PDF" in notes
    assert "Paid by UPI" not in notes
    start(client)
    assert any(p["session_id"] == sid and p["status"] == "issued" for p in client.get("/api/history").json()["policies"])
