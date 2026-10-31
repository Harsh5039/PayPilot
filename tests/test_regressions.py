"""Regressions for previously reproduced bugs; no real banking systems involved."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from PIL import Image
from app import db

SAMPLES = Path(__file__).resolve().parents[1] / "static"


def new(client):
    return client.post("/api/sessions", json={}).json()["session_id"]


def test_product_specific_session_entry(client):
    for language in ("en", "hi"):
        loan = client.post("/api/sessions", json={"language": language, "product": "loan"}).json()
        assert loan["step"] == "intent"
        assert "ins" not in {c["value"] for c in loan["chips"]}
        ins = client.post("/api/sessions", json={"language": language, "product": "insurance"}).json()
        assert ins["step"] == "ins_cover"
        assert {c["value"] for c in ins["chips"]} == {"self", "couple", "family"}
        sid = ins["session_id"]
        assert client.get(f"/api/sessions/{sid}").json()["session"]["product"] == "insurance"
        assert ch(client, sid, choice="family")["step"] == "ins_sum"
        assert ch(client, sid, text="start over")["step"] == "ins_cover"


def grant(client, sid, scopes, shared_with=None):
    r = client.post(f"/api/sessions/{sid}/consent", json={"scopes": scopes, "shared_with": shared_with})
    assert r.status_code == 201, r.text


def ch(client, sid, choice=None, text=""):
    r = client.post("/api/chat", json={"session_id": sid, "choice": choice, "text": text})
    assert r.status_code == 200, r.text
    return r.json()


def make_app(client, lender="abc", amount=300000, employment="salaried"):
    sid = new(client)
    names = {"abc": "Aditya Birla Capital", "hero": "Hero Fincorp", "tata": "Tata Capital"}
    grant(client, sid, ["paytm.profile", "paytm.income", "paytm.kyc", "bureau.softpull",
                        "bureau.hardpull", "documents.access", "lender.share"], names[lender])
    r = client.post(f"/api/sessions/{sid}/applications",
                    json={"lender_id": lender, "amount": amount, "employment": employment})
    assert r.status_code == 201, r.text
    return sid, r.json()["application"]["id"]


def upload(client, app_id, typ, sample=None):
    path = SAMPLES / f"demo_{sample or typ}.pdf"
    return client.post(f"/api/applications/{app_id}/documents/{typ}",
                       files={"file": (path.name, path.read_bytes(), "application/pdf")})


def docs_complete(client, app_id, typelist=("salary_slip", "bank_statement")):
    for typ in typelist:
        r = upload(client, app_id, typ)
        assert r.status_code == 200, r.text
        assert r.json()["document"]["verification_status"] == "matched_demo"
    v = client.post(f"/api/applications/{app_id}/documents/verify")
    assert v.status_code == 200, v.text


def test_reset_not_exposed(client):
    assert client.post("/api/admin/reset").status_code == 404


def test_consent_refusal_never_grants(client):
    sid = new(client)
    ch(client, sid, text="I need a loan")
    for choice in ("purpose:personal", "amount:500000", "tenure:24", "budget:any", "75k_plus", "salaried"):
        ch(client, sid, choice=choice)
    r = ch(client, sid, text="I refuse, do not access my information")
    assert r["step"] == "consent_data"
    assert client.get(f"/api/sessions/{sid}/consent").json()["active"] == []
    ch(client, sid, choice="grant")
    r = ch(client, sid, text="I do not permit a credit check")
    assert r["step"] == "consent_bureau"
    assert "bureau.softpull" not in client.get(f"/api/sessions/{sid}/consent").json()["active"]


def test_consent_versions_are_append_only(client):
    sid = new(client)
    grant(client, sid, ["paytm.profile"])
    grant(client, sid, ["paytm.profile"])
    history = [h for h in client.get(f"/api/sessions/{sid}/consent").json()["ledger"] if h["scope"] == "paytm.profile"]
    assert len(history) == 2 and history[0]["status"] == "superseded"
    assert [h["version"] for h in history] == [1, 2]
    assert client.delete(f"/api/sessions/{sid}/consent/paytm.profile").status_code == 200
    assert "paytm.profile" not in client.get(f"/api/sessions/{sid}/consent").json()["active"]


def test_lender_recipient_cannot_be_swapped(client):
    sid = new(client)
    grant(client, sid, ["paytm.profile", "paytm.income", "paytm.kyc", "lender.share"], "Tata Capital")
    r = client.post(f"/api/sessions/{sid}/applications", json={"lender_id": "abc", "amount": 300000})
    assert r.status_code == 403 and r.json()["detail"]["error"] == "recipient_consent_required"


def test_no_file_invalid_pdf_and_wrong_doc_blocked(client):
    _, a = make_app(client)
    assert client.post(f"/api/applications/{a}/documents/salary_slip").status_code == 422
    r = client.post(f"/api/applications/{a}/documents/salary_slip",
                    files={"file": ("fake.pdf", b"%PDF-1.4 not really a pdf", "application/pdf")})
    assert r.status_code == 422 and r.json()["detail"] == "invalid_or_unreadable_pdf"
    r = upload(client, a, "salary_slip", sample="bank_statement")
    assert r.status_code == 200 and r.json()["document"]["verified"] is False
    assert "not_identifiable_as_salary_slip" in r.json()["document"]["failure_reasons"]
    assert client.get(f"/api/applications/{a}/documents").json()["complete"] is False


def test_valid_image_requires_review_not_automatic_approval(client):
    _, a = make_app(client)
    im = Image.new("RGB", (30, 30))
    b = BytesIO(); im.save(b, format="PNG")
    r = client.post(f"/api/applications/{a}/documents/salary_slip",
                    files={"file": ("image.png", b.getvalue(), "image/png")})
    assert r.status_code == 200
    assert r.json()["document"]["verification_status"] == "manual_review"
    assert r.json()["status"]["complete"] is False


def test_verification_route_and_kyc_gate(client):
    _, a = make_app(client)
    docs_complete(client, a)
    assert client.get(f"/api/applications/{a}").json()["application"]["status"] == "documents_verified"
    r = client.post(f"/api/applications/{a}/approve")
    assert r.status_code == 409 and r.json()["detail"] == "kyc_verification_required"
    assert client.post(f"/api/applications/{a}/kyc").json()["verified"] is True
    assert client.post(f"/api/applications/{a}/approve").json()["decision"] == "submitted"
    assert client.post(f"/api/applications/{a}/approve").status_code == 409
    assert client.post(f"/api/applications/{a}/documents/salary_slip",
                       files={"file": ("file.pdf", (SAMPLES / "demo_salary_slip.pdf").read_bytes(), "application/pdf")}).status_code == 409
    assert client.post(f"/api/applications/{a}/documents",
                       files={"file": ("file.pdf", (SAMPLES / "demo_salary_slip.pdf").read_bytes(), "application/pdf")}).status_code == 409


def test_consent_revocation_blocks_submit(client):
    sid, a = make_app(client)
    docs_complete(client, a)
    client.post(f"/api/applications/{a}/kyc")
    client.delete(f"/api/sessions/{sid}/consent/lender.share")
    assert client.post(f"/api/applications/{a}/approve").status_code == 403


def test_lender_specific_document_policy(client):
    _, a = make_app(client, lender="tata")
    r = client.get(f"/api/applications/{a}/documents").json()
    assert [x["doc_type"] for x in r["required"]] == ["bank_statement"]
    assert upload(client, a, "bank_statement").json()["status"]["complete"] is True
    _, b = make_app(client, employment="self_employed")
    r = client.get(f"/api/applications/{b}/documents", params={"employment": "salaried"}).json()
    assert {x["doc_type"] for x in r["required"]} == {"pan", "bank_statement"}


def test_eligibility_capacity_amount_rules(client):
    from app.services.eligibility import assess
    r = assess(10000, "personal", "75k_plus", "salaried")
    assert not r["eligible"]
    r2 = assess(1300000, "personal", "75k_plus", "salaried")
    assert not r2["eligible"]
    assert r2["approved_amount"] == 0
    rs = assess(300000, "business", "75k_plus", "self_employed")
    assert rs["eligible"] is False


def test_loan_comparison_principals_and_offer_selection(client):
    sid = new(client)
    r = client.post(f"/api/sessions/{sid}/loans/compare", json={"amount": 1400000}).json()
    assert all(o["amount"] == 1400000 for o in r["offers"])
    assert len(r["offers"]) == 1
    grant(client, sid, ["paytm.profile", "paytm.income", "paytm.kyc", "lender.share"], "Aditya Birla Capital")
    off = client.post(f"/api/sessions/{sid}/loans/compare", json={"amount": 300000, "tenure_months": 36}).json()["offers"]
    abc = next(o for o in off if o["lender_id"] == "abc")
    good = client.post(f"/api/sessions/{sid}/applications",
                       json={"offer_id": abc["offer_id"], "amount": 300000})
    assert good.status_code == 201 and good.json()["application"]["tenure_months"] == 36
    bad = client.post(f"/api/sessions/{sid}/applications",
                      json={"offer_id": "bogus", "amount": 300000})
    assert bad.status_code == 422


def test_conflicts_and_health_require_consent(client):
    sid = new(client)
    assert client.get(f"/api/sessions/{sid}/conflicts").status_code == 403
    grant(client, sid, ["paytm.income"])
    assert client.get(f"/api/sessions/{sid}/financial-health").status_code == 403
    grant(client, sid, ["bureau.softpull"])
    assert client.get(f"/api/sessions/{sid}/financial-health").status_code == 200


def test_insurance_requires_explicit_declare_and_treats_payment_as_mock(client):
    sid = new(client)
    grant(client, sid, ["paytm.profile", "paytm.kyc"])
    assert client.get("/api/insurance/plans", params={"sum_insured": 100}).status_code == 422
    r = client.post(f"/api/sessions/{sid}/insurance/policies",
                    json={"plan_id": "hdfc", "sum_insured": 1000000, "ped": "yes"})
    assert r.status_code == 201, r.text
    pid = r.json()["policy"]["id"]
    assert client.post(f"/api/policies/{pid}/pay").status_code == 409
    assert client.post(f"/api/policies/{pid}/declare").status_code == 422
    assert client.post(f"/api/policies/{pid}/declare", json=["none"]).status_code == 422
    r = client.post(f"/api/policies/{pid}/declare", json=["diabetes"])
    assert r.status_code == 200, r.text
    issued = client.post(f"/api/policies/{pid}/pay")
    assert issued.status_code == 200 and issued.json()["simulated"] is True
    assert client.post(f"/api/policies/{pid}/pay").status_code == 409


def test_numeric_extremes_do_not_crash(client):
    r = client.get('/api/loans/emi', params={"principal": "1e308", "annual_rate": 60,
                                              "tenure_months": 84})
    assert r.status_code == 422


def test_typed_tenure_budget_work(client):
    sid = new(client)
    ch(client, sid, text="I need a loan")
    ch(client, sid, choice="purpose:personal")
    ch(client, sid, choice="amount:300000")
    r = ch(client, sid, text="36 months")
    assert r["step"] == "budget"
    r = ch(client, sid, text="I can afford 15000")
    assert r["step"] == "income"
    assert client.get(f"/api/sessions/{sid}").json()["slots"]["emi_budget"] == 15000


def test_tool_layer_eligibility_no_foir_keyerror(client):
    from app.services.sarvam import _run_tool
    import asyncio
    sid = new(client)
    grant(client, sid, ["paytm.profile", "paytm.income", "paytm.kyc", "bureau.softpull"])
    r = asyncio.run(_run_tool("check_eligibility", {"amount": 300000}, sid))
    assert "error" not in r and isinstance(r["foir"], float)

def test_chat_stop_start_preempts_consent(client):
    sid = new(client)
    for step in ('consent_data', 'consent_bureau', 'ins_declare'):
        db.save_session(sid, step=step)
        assert ch(client, sid, text='stop chat')['step'] == 'stopped'
        assert ch(client, sid, choice='grant')['step'] == 'stopped'
        assert ch(client, sid, text='start')['step'] == 'intent'
        assert client.get(f'/api/sessions/{sid}/consent').json()['active'] == []


def test_skip_credit_exits_and_unknown_text_does_not_skip(client):
    sid = new(client)
    db.save_session(sid, step='consent_bureau')
    assert ch(client, sid, text='what does this mean')['step'] == 'consent_bureau'
    result = ch(client, sid, choice='skip_bureau')
    assert result['step'] == 'stopped'
    assert [c['value'] for c in result['chips']] == ['start']
    assert ch(client, sid, text='start')['step'] == 'intent'

def test_financial_guard_caps_recommendations():
    from app.services.lending import comparison
    from app.services.eligibility import health_snapshot
    for budget in (None, 999999, 0):
        result = comparison('guard-test', 500000, emi_budget=budget)
        assert result['emi_budget'] <= health_snapshot()['affordable_emi']
        for offer in result['offers']:
            if offer['recommended']:
                assert offer['emi'] <= result['emi_budget']
        if not any(o['within_budget'] for o in result['offers']):
            assert result['recommended_offer_id'] is None
            assert result['budget_note']

def test_nominee_saved_edited_and_reviewed(client):
    from app.services import lending
    sid, app_id = make_app(client)
    url = f'/api/applications/{app_id}/nominee'
    assert client.patch(url, json={'name': '   '}).status_code == 422
    for name in ('Asha Mehta', 'Priya Mehta'):
        result = client.patch(url, json={'name': name})
        assert result.status_code == 200
        assert client.get(f'/api/applications/{app_id}').json()['application']['nominee'] == name
        assert lending.review(app_id)['fields'][-1]['value'] == name
    db.run("UPDATE applications SET status = 'submitted' WHERE id = ?", (app_id,))
    assert client.patch(url, json={'name': 'Another Name'}).status_code == 409
