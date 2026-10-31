"""The conversational flow controller.

The LLM understands language; this module owns the journey. Every step is
explicit, every transition is logged, and no branch can approve a loan — the
partner's decision comes back from lending.advance() and is passed through
verbatim.
"""
from __future__ import annotations

import re
import json
from pathlib import Path

from app import db
from app.seed import DOCUMENT_TYPES, EMI_BUDGETS, INCOME_BANDS, PURPOSES, TENURES
from app.services import consent, eligibility, insurance, lending, sarvam

# ---------------------------------------------------------------- copy
COPY = {
    "greet": {
        "en": "Namaste, Arjun! I'm PayPilot — your money co-pilot inside Paytm. "
              "I can take you from \"I need a loan\" to money in your account, without a form.",
        "hi": "नमस्ते अर्जुन! मैं PayPilot हूँ — Paytm के अंदर आपका मनी को-पायलट। "
              "मैं आपको \"मुझे लोन चाहिए\" से पैसा अकाउंट में आने तक ले जा सकता हूँ, बिना कोई फॉर्म भरे।",
    },
    "ask_intent": {"en": "What do you need today?", "hi": "आज आपको क्या चाहिए?"},
    "ask_purpose": {
        "en": "What is the loan for? It changes which partners will look at it.",
        "hi": "लोन किसलिए है? इससे तय होता है कि कौन से पार्टनर इसे देखेंगे।",
    },
    "ask_amount": {
        "en": "How much do you need? Say it however you like — \"5 lakh\" is fine.",
        "hi": "आपको कितना चाहिए? जैसे बोलें वैसे लिखें — \"5 लाख\" भी चलेगा।",
    },
    "ask_tenure": {
        "en": "How long would you like to take to repay? A longer tenure means a smaller EMI but more interest.",
        "hi": "आप कितने समय में चुकाना चाहेंगे? लंबी अवधि में EMI छोटी होती है, ब्याज ज़्यादा।",
    },
    "ask_budget": {
        "en": "What monthly EMI is comfortable? I'll flag any offer that goes over it.",
        "hi": "कितनी मासिक EMI ठीक रहेगी? जो ऑफर इससे ऊपर जाएगा, मैं बता दूँगा।",
    },
    "ask_income": {"en": "And your monthly income?", "hi": "और आपकी मंथली इनकम?"},
    "ask_employment": {"en": "Are you salaried or self-employed?", "hi": "आप सैलरीड हैं या सेल्फ-एम्प्लॉयड?"},
    "conflict_intro": {
        "en": "Before I go further — two things you told me don't match what Paytm can see. Worth fixing now rather than having a lender reject it later.",
        "hi": "आगे बढ़ने से पहले — आपने जो बताया और Paytm जो देख सकता है, इनमें दो फ़र्क हैं। अभी ठीक कर लेना बेहतर है।",
    },
    "consent_data": {
        "en": "To work out what you can afford I need three things from your Paytm account. Each one is listed with what it actually contains.",
        "hi": "आप कितना चुका सकते हैं यह देखने के लिए मुझे आपके Paytm अकाउंट से तीन चीज़ें चाहिए। हर एक के साथ उसका डेटा भी दिखा रहा हूँ।",
    },
    "consent_bureau": {
        "en": "Next, a credit check. This one is a soft enquiry — it shows your score to us and does not affect it. Lenders will need a hard enquiry later, and I'll ask separately.",
        "hi": "अब क्रेडिट चेक। यह सॉफ्ट इंक्वायरी है — स्कोर हमें दिखता है, प्रभावित नहीं होता। लेंडर को बाद में हार्ड इंक्वायरी चाहिए होगी, उसके लिए अलग से पूछूँगा।",
    },
    "consent_share": {
        "en": "Last consent before the application opens: sharing your details with the lender you picked, and reading the documents you upload. Nobody else receives anything.",
        "hi": "आवेदन शुरू करने से पहले आखिरी सहमति: आपके चुने लेंडर के साथ जानकारी साझा करना, और आपके अपलोड किए दस्तावेज़ पढ़ना। किसी और को कुछ नहीं जाता।",
    },
    "consent_hard": {
        "en": "One more, and it is the one that matters: a formal bureau enquiry, which is recorded on your credit report. Lenders require it before sanction.",
        "hi": "एक और, और यही अहम है: औपचारिक ब्यूरो इंक्वायरी, जो आपकी क्रेडिट रिपोर्ट पर दर्ज होती है। सैंक्शन से पहले लेंडर इसे ज़रूरी मानते हैं।",
    },
    "consent_ok": {
        "en": "That's on the record. You can revoke any scope from the consent tab, and it takes effect immediately.",
        "hi": "यह रिकॉर्ड पर है। कंसेंट टैब से कोई भी स्कोप हटा सकते हैं, तुरंत लागू होगा।",
    },
    "pre_eligible": {
        "en": "Here's what this looks like. Indicative only — no lender has seen it yet.",
        "hi": "यह स्थिति है। सिर्फ संकेत — किसी लेंडर ने अभी नहीं देखा।",
    },
    "not_eligible": {
        "en": "I can't pre-qualify {amount} on this profile. {reason} A smaller amount or a longer tenure is worth trying.",
        "hi": "इस प्रोफाइल पर {amount} प्री-क्वालिफाई नहीं हो रहा। {reason} कम रकम या लंबी अवधि आज़माएँ।",
    },
    "budget_none": {
        "en": "Every offer's EMI is above the ₹{budget} you said was comfortable — the lowest is {cheapest}. "
              "I won't nudge you into applying for something that doesn't fit. The two honest options are a "
              "smaller amount or a longer tenure.",
        "hi": "हर ऑफर की EMI आपके ₹{budget} बजट से ऊपर है — सबसे कम {cheapest} है। जो आपके लिए ठीक है उससे "
              "यह मेल नहीं खाता, इसलिए मैं अप्लाई करने के लिए नहीं कहूँगा। दो सही विकल्प: कम रकम या लंबी अवधि।",
    },
    "simulated_note": {
        "en": "This is a simulated decision from a mock partner — no sanction letter exists and no money moves.",
        "hi": "यह एक मॉक पार्टनर का सिम्युलेटेड फैसला है — कोई सैंक्शन लेटर नहीं है और कोई पैसा नहीं जाता।",
    },
    "offers_intro": {
        "en": "Ranked by total repayment, fees included. Tap one to apply, or change the amount or tenure and I'll re-quote without losing anything.",
        "hi": "कुल भुगतान के हिसाब से क्रम में, फीस सहित। अप्लाई करने के लिए एक चुनें, या रकम/अवधि बदलें — कुछ नहीं खोएगा।",
    },
    "apply_consent": {
        "en": "Good choice. I'll open the application with {lender}.",
        "hi": "अच्छा चुनाव। मैं {lender} के साथ आवेदन खोलता हूँ।",
    },
    "prefill_done": {
        "en": "Filled from your Paytm data — six of eight fields, one nominee left for you. Now the documents.",
        "hi": "Paytm डेटा से भर गया — आठ में छह फ़ील्ड, नॉमिनी आपको भरना है। अब दस्तावेज़।",
    },
    "docs_ask": {
        "en": "I need {docs}. Upload them and I'll read each one — you don't type anything.",
        "hi": "मुझे {docs} चाहिए। अपलोड करें, मैं पढ़ लूँगा — कुछ लिखना नहीं है।",
    },
    "docs_complete": {
        "en": "Everything is read and matched. Nothing left to upload.",
        "hi": "सब पढ़ लिया और मिलान हो गया। अब कुछ अपलोड नहीं करना।",
    },
    "docs_missing": {
        "en": "Still needed: {missing}. The rest are read and matched.",
        "hi": "अभी बाकी: {missing}. बाकी पढ़ लिए गए हैं।",
    },
    "review_intro": {
        "en": "This is exactly what will leave Paytm and reach {lender}. Read it before you approve.",
        "hi": "यही जानकारी Paytm से निकलकर {lender} तक जाएगी। मंज़ूरी से पहले पढ़ लें।",
    },
    "submitted": {
        "en": "Submitted. {lender} usually answers within {eta} hours — I'll post it here the moment it lands.",
        "hi": "भेज दिया। {lender} आमतौर पर {eta} घंटे में जवाब देते हैं — जवाब आते ही यहीं बताऊँगा।",
    },
    "under_review": {
        "en": "{lender} has picked up the file. Nothing needed from you right now.",
        "hi": "{lender} ने फ़ाइल ले ली है। अभी आपसे कुछ नहीं चाहिए।",
    },
    "approved": {
        "en": "Approved. {amount} sanctioned by {lender} at {rate}% p.a. Money reaches your Paytm account in about {eta} hours.",
        "hi": "अप्रूव्ड। {lender} ने {amount} मंज़ूर किए, {rate}% सालाना पर। पैसा लगभग {eta} घंटे में आपके Paytm अकाउंट में आ जाएगा।",
    },
    "rejected": {
        "en": "The lender declined this one — {reason}. That is their call, not mine. I can show you another partner.",
        "hi": "लेंडर ने इसे अस्वीकार किया — {reason}. फैसला उनका है, मेरा नहीं। दूसरा पार्टनर दिखा सकता हूँ।",
    },
    "documents_required": {
        "en": "The lender needs more before deciding: {missing}. Upload them and I'll resume this application — nothing else is lost.",
        "hi": "फैसले से पहले लेंडर को और चाहिए: {missing}. अपलोड करें, मैं यही आवेदन आगे बढ़ा दूँगा — बाकी कुछ नहीं खोएगा।",
    },
    "tracking": {
        "en": "Here's where it stands. The tracker tab keeps this live, and the reference number works on the lender's side too.",
        "hi": "यह मौजूदा स्थिति है। ट्रैकर टैब इसे लाइव रखता है, और संदर्भ संख्या लेंडर के पास भी चलती है।",
    },
    "done": {
        "en": "That journey is complete. Say \"new loan\" if you want to start another.",
        "hi": "यह जर्नी पूरी हो गई। दूसरी शुरू करनी हो तो \"नया लोन\" कहें।",
    },
    "insurance_soon": {"en": "Insurance is a separate journey — ask me for health cover and I'll switch.",
                       "hi": "इंश्योरेंस अलग जर्नी है — हेल्थ कवर माँगें, मैं बदल दूँगा।"},
    "off_topic": {
        "en": "I'm built for loans right now. Give me an amount and I'll take it from there.",
        "hi": "मैं अभी लोन के लिए बना हूँ। रकम बताइए, वहीं से शुरू करते हैं।",
    },
}

INS_COPY = {
    "ask_cover": {"en": "Happy to help with health cover. Who should it protect — just you, you and your spouse, or the whole family?",
                  "hi": "हेल्थ कवर में मदद करता हूँ। किसे सुरक्षित करना है — सिर्फ आप, आप और जीवनसाथी, या पूरा परिवार?"},
    "ask_sum": {"en": "How much cover do you want? ₹5 lakh, ₹10 lakh or ₹25 lakh.",
                "hi": "कितना कवर चाहिए? ₹5 लाख, ₹10 लाख या ₹25 लाख।"},
    "ask_ped": {"en": "Is there any existing condition I should declare? It changes the waiting period.",
                "hi": "कोई पहले से बीमारी है जो बतानी हो? इससे वेटिंग पीरियड बदल जाता है।"},
    "consent": {"en": "I'll need your Paytm profile and KYC status to fill the proposal — two scopes, revocable.",
                "hi": "प्रस्ताव भरने के लिए आपकी Paytm प्रोफाइल और KYC स्टेटस चाहिए — दो स्कोप, कभी भी हटा सकते हैं।"},
    "plans": {"en": "Here are the plans that fit. Premiums are yearly, and what is excluded is shown with what is covered.",
              "hi": "ये प्लान आपके लिए ठीक हैं। प्रीमियम सालाना है, और क्या कवर नहीं है वह भी साथ दिखा रहा हूँ।"},
    "proposal": {"en": "Proposal filled from your Paytm data. One medical declaration left, then payment.",
                 "hi": "प्रस्ताव Paytm डेटा से भर गया। एक मेडिकल डिक्लेरेशन बाकी है, फिर भुगतान।"},
    "declared": {"en": "Demo declaration recorded: no existing condition. A real insurer would assess any medical test requirement.",
                 "hi": "डेमो घोषणा दर्ज: पहले से कोई बीमारी नहीं। मेडिकल टेस्ट की आवश्यकता वास्तविक बीमा कंपनी तय करेगी।"},
    "declared_diabetes": {"en": "Demo declaration recorded: diabetes. A real insurer would assess the condition and any medical test requirement.",
                          "hi": "डेमो घोषणा दर्ज: डायबिटीज़। वास्तविक बीमा कंपनी बीमारी और मेडिकल टेस्ट की आवश्यकता का आकलन करेगी।"},
    "issued": {"en": "DEMO: Mock policy marked issued. No payment was charged and no insurer-issued PDF exists.",
               "hi": "डेमो: पॉलिसी जारी होने का अनुकरण पूरा हुआ। कोई भुगतान नहीं हुआ और बीमा कंपनी की PDF नहीं बनी।"},
    "done": {"en": "That demo policy journey is complete. Say 'new policy' to start another.",
             "hi": "डेमो पॉलिसी की प्रक्रिया पूरी हुई। दूसरी शुरू करने के लिए 'नई पॉलिसी' कहें।"},
}


STEPS = ["Application created", "Documents verified", "Submitted to lender", "Lender review", "Decision"]

PURPOSE_CHIPS = [{"label": p["label"], "value": f"purpose:{p['id']}"} for p in PURPOSES]
INCOME_CHIPS = [{"label": b["label"], "value": b["id"]} for b in INCOME_BANDS]
BUDGET_CHIPS = [{"label": b["label"], "value": f"budget:{b['id']}"} for b in EMI_BUDGETS]
TENURE_CHIPS = [{"label": f"{t} months", "value": f"tenure:{t}"} for t in TENURES]
AMOUNT_CHIPS = [{"label": "₹1,00,000", "value": "amount:100000"},
                {"label": "₹3,00,000", "value": "amount:300000"},
                {"label": "₹5,00,000", "value": "amount:500000"},
                {"label": "₹10,00,000", "value": "amount:1000000"}]


def inr(n: float) -> str:
    s = str(int(round(n)))
    if len(s) <= 3:
        return "₹" + s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return "₹" + ",".join(parts) + "," + tail


def say(lang: str, key: str, **fmt) -> str:
    text = COPY[key].get(lang) or COPY[key]["en"]
    return text.format(**fmt) if fmt else text


def _consent_wait(session: dict, lang: str, key: str, scopes: list[str], **extra) -> dict:
    """Only a dedicated affirmative choice or a separately recorded consent API grant advances."""
    declined = "I have not accessed or shared that data. Choose Share to continue."
    return _out(session, declined + " " + say(lang, key), lang=lang,
                chips=[{"label": "Share these and continue", "value": "grant"}],
                consent_request=_consent_card(session["id"], scopes, **extra))


def detect_language(text: str, fallback: str = "en") -> str:
    if not text:
        return fallback
    if any("\u0900" <= ch <= "\u097f" for ch in text):
        return "hi"
    return fallback


def parse_amount(text: str) -> int | None:
    if not text:
        return None
    t = text.lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(lakhs?|lac|crore|cr|k|लाख|करोड़)?", t)
    if not m:
        return None
    value = float(m.group(1))
    unit = (m.group(2) or "").lower()
    if unit.startswith("lakh") or unit in ("lac", "लाख"):
        value *= 100_000
    elif unit in ("crore", "cr", "करोड़"):
        value *= 10_000_000
    elif unit == "k":
        value *= 1_000
    if value < 10_000:
        return None
    return int(round(value / 1000) * 1000) if value <= 5_000_000 else None


def parse_tenure(text: str) -> int | None:
    m = re.search(r"\b(12|24|36|48|60)\s*(?:months?|mos?|m)?\b", text.lower())
    return int(m.group(1)) if m else None


def parse_budget(text: str) -> int | None:
    m = re.search(r"(?:emi|budget|afford|monthly)\D{0,20}([\d,]+)\b", text.lower())
    if not m:
        return None
    value = int(m.group(1).replace(",", ""))
    return value if 1000 <= value <= 500000 else None


def rule_intent(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"insur|policy|बीमा|इंश्योर", t):
        return "insurance"
    if re.search(r"eligib|eligible|क्या मैं|पात्र", t):
        return "check_eligibility"
    if re.search(r"track|status|स्थिति", t):
        return "track"
    if re.search(r"compare|option|offer|ऑप्शन", t):
        return "compare"
    if re.search(r"loan|borrow|emi|लोन|कर्ज|apply", t):
        return "start_loan"
    if re.search(r"hi|hello|hey|namaste|नमस्ते", t):
        return "greeting"
    return "off_topic"


def rule_slots(text: str) -> dict:
    t = (text or "").lower()
    out = {}
    for p in PURPOSES:
        if p["id"].replace("_", " ") in t:
            out["purpose"] = p["id"]
    if "business" in t or "बिज़नेस" in t:
        out["purpose"] = "business"
    if re.search(r"self.?employ|freelanc|सेल्फ", t):
        out["employment"] = "self_employed"
    elif re.search(r"salaried|salary|नौकरी|सैलरी", t):
        out["employment"] = "salaried"
    return out


# ---------------------------------------------------------------- tracker
def _tracker(offer: dict, purpose: str, ref: str) -> dict:
    return {
        "active": True,
        "title": f"{purpose.replace('_', ' ').title()} loan · {offer['lender_name']}",
        "ref": ref,
        "status": "in_progress",
        "meta": [
            {"k": "Amount", "v": inr(offer["amount"])},
            {"k": "Tenure", "v": f"{offer['tenure_months']} months"},
            {"k": "Rate", "v": f"{offer['annual_rate']}% p.a."},
            {"k": "EMI", "v": inr(offer["emi"])},
        ],
        "steps": [{"label": s, "note": "", "state": "run" if i == 0 else "pending"}
                  for i, s in enumerate(STEPS)],
    }


def _advance_tracker(session: dict, index: int, note: str = "", status: str | None = None) -> dict:
    tr = session["tracker"] or {}
    if not tr.get("active"):
        return tr
    for i, step in enumerate(tr["steps"]):
        if i < index:
            step["state"] = "done"
        elif i == index:
            step["state"] = "done" if status == "complete" else "run"
            if note:
                step["note"] = note
    if status:
        tr["status"] = status
    if status == "complete":
        for step in tr["steps"]:
            step["state"] = "done"
    return tr


HI_LABELS = json.loads((Path(__file__).resolve().parents[2] / "static" / "hi.json").read_text(encoding="utf-8"))


def localize_turn(turn: dict, lang: str) -> dict:
    translations = dict(HI_LABELS)
    translations.update({copy["en"]: copy["hi"] for copy in [*COPY.values(), *INS_COPY.values()] if "en" in copy and "hi" in copy})
    reverse = {v: k for k, v in translations.items()}

    def translate(text):
        original = reverse.get(text, text)
        if lang != "hi":
            return original
        if original in translations:
            return translations[original]
        if re.fullmatch(r"\d+ months", original):
            return original.replace(" months", " महीने")
        if re.fullmatch(r"₹\d+ lakh", original):
            return original.replace(" lakh", " लाख")
        if original.startswith("Simulate payment "):
            return original.replace("Simulate payment", "भुगतान का अनुकरण करें").replace("(no charge)", "(कोई शुल्क नहीं)")
        return original

    display_keys = {"reply", "label", "title", "note", "k", "v", "members_label", "purpose", "features", "tag", "data"}
    def walk(value, key=""):
        if isinstance(value, dict):
            return {k: walk(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v, key) for v in value]
        if isinstance(value, str) and key in display_keys:
            return translate(value)
        return value

    result = walk(turn)
    result["language"] = lang
    return result


def _out(session: dict, reply: str, *, chips=None, cards=None, consent_request=None,
         lang=None, notifications=None) -> dict:
    db.add_message(session["id"], "assistant", reply)
    turn = {
        "session_id": session["id"],
        "reply": reply,
        "chips": chips or [],
        "cards": cards or [],
        "consent_request": consent_request,
        "language": lang or session["language"],
        "step": session["step"],
        "tracker": session["tracker"],
        "notifications": notifications or [],
        "product": session["product"],
    }
    db.run("UPDATE sessions SET last_turn = ? WHERE id = ?", (json.dumps(turn), session["id"]))
    return localize_turn(turn, lang or session["language"])


def _offer_chips(offers: list[dict]) -> list[dict]:
    chips = [{"label": f"{o['lender_name']} · {inr(o['emi'])}/mo", "value": f"offer:{o['offer_id']}"}
             for o in offers[:3]]
    chips += [{"label": "Change amount", "value": "change_amount"},
              {"label": "Change tenure", "value": "change_tenure"}]
    return chips


def greeting(session: dict) -> dict:
    lang = session["language"]
    if session.get("product") == "insurance":
        session["step"] = "ins_cover"
        db.save_session(session["id"], step="ins_cover", language=lang)
        return _out(session, _ins(lang, "ask_cover"), lang=lang, chips=[
            {"label": "Just me", "value": "self"},
            {"label": "Me and my spouse", "value": "couple"},
            {"label": "Family of four", "value": "family"},
        ])
    session["step"] = "intent"
    db.save_session(session["id"], step="intent", language=lang)
    return _out(session, say(lang, "greet"), lang=lang, chips=[
        {"label": "I need a ₹5 lakh loan", "value": "loan:500000"},
        {"label": "Am I eligible?", "value": "eligibility"},
    ])


def _comparison(sid: str, slots: dict) -> dict:
    return lending.comparison(sid, slots["amount"], slots.get("employment", "salaried"),
                              slots.get("tenure"), slots.get("emi_budget"))


def _budget_guard(lang: str, comp: dict, slots: dict):
    """If nothing fits the stated EMI budget, say so and do not offer to apply."""
    budget = comp.get("emi_budget")
    if not comp.get("budget_note"):
        return None
    cheapest = min(o["emi"] for o in comp["offers"]) if comp["offers"] else 0
    return say(lang, "budget_none", budget=f"{int(budget):,}", cheapest=inr(cheapest))


def _offers_response(session: dict, lang: str, slots: dict) -> dict:
    comp = _comparison(session["id"], slots)
    slots["offers"] = comp["offers"]
    session.update({"language": lang, "slots": slots, "step": "offers"})
    db.save_session(session["id"], language=lang, slots=slots, step="offers")

    guard = _budget_guard(lang, comp, slots)
    if guard:
        return _out(session, guard, lang=lang,
                    chips=[{"label": "Change amount", "value": "change_amount"},
                           {"label": "Change tenure", "value": "change_tenure"},
                           {"label": "Show them anyway", "value": "show_offers"}],
                    cards=[{"type": "offers", "data": comp["offers"], "highlights": comp["highlights"],
                            "tenures": comp["tenures"], "selected_tenure": slots.get("tenure"),
                            "savings_vs_worst": comp["savings_vs_worst"],
                            "emi_budget": slots.get("emi_budget"),
                            "budget_note": comp.get("budget_note")}])

    return _out(session, say(lang, "offers_intro"), lang=lang,
                chips=_offer_chips(comp["offers"]),
                cards=[{"type": "offers", "data": comp["offers"], "highlights": comp["highlights"],
                        "tenures": comp["tenures"], "selected_tenure": slots.get("tenure"),
                        "savings_vs_worst": comp["savings_vs_worst"],
                        "emi_budget": slots.get("emi_budget")}])


def _consent_card(sid: str, scopes: list[str], **extra) -> dict:
    return {"scopes": scopes, "items": [consent.CATALOGUE[s] for s in scopes],
            "grant_url": f"/api/sessions/{sid}/consent", **extra}


# ---------------------------------------------------------------- main handler
async def handle(session: dict, text: str = "", choice: str | None = None,
                 language: str | None = None) -> dict:
    sid = session["id"]
    db.add_message(sid, "user", text or (choice or ""))

    lang = language or detect_language(text, session["language"])
    slots = dict(session["slots"])
    step = session["step"]

    # Lifecycle commands take precedence over extraction and consent handling.
    command = (choice or text).strip().lower().rstrip(".!?")
    restart_commands = {"start", "start chat", "new chat", "new session", "restart", "restart chat", "start over"}
    stop_commands = {"stop", "stop chat", "end chat", "cancel chat"}
    if command in restart_commands:
        session.update(language=lang, step="intent", slots={}, tracker={})
        db.save_session(sid, language=lang, step="intent", slots={}, tracker={})
        return greeting(session)
    if command in stop_commands:
        session.update(step="stopped")
        db.save_session(sid, step="stopped")
    if session["step"] == "stopped":
        return _out(session, "Chat stopped. Type start or select New chat to begin again.",
                    lang=lang, chips=[{"label": "New chat", "value": "start"}])

    # Answers belong to the active product. A coverage amount is not a loan request.
    explicit_loan = (choice or "").startswith("loan:") or (not choice and bool(re.search(r"\b(?:loan|borrow)\b|लोन|कर्ज", text, re.I)))
    if session.get("product") == "insurance" and not explicit_loan:
        return await _handle_insurance(session, text, choice, lang)

    # A chip click is explicit: `choice` is the value, `text` is only its label.
    parsed = None
    if text and not choice:
        parsed = await sarvam.extract(text, lang, slots)
    if parsed:
        lang = parsed.get("language") or lang
        if parsed.get("amount"):
            slots["amount"] = int(parsed["amount"])
        for key in ("purpose", "income_band", "employment"):
            if parsed.get(key):
                slots[key] = parsed[key]
        intent = parsed.get("intent") or "off_topic"
    elif choice:
        intent = "choice"
    else:
        intent = rule_intent(text) if text else "off_topic"
        slots.update(rule_slots(text))
        amount = parse_amount(text)
        if amount:
            slots["amount"] = amount
            intent = "start_loan"

    db.audit(sid, "nlu", f"intent={intent} via {'sarvam' if parsed else 'rules'}", 46)

    # --- product routing
    wants_insurance = intent == "insurance" or choice == "ins" or session.get("product") == "insurance"
    back_to_loan = intent == "start_loan" or (choice or "").startswith("loan:")
    if wants_insurance and not back_to_loan:
        return await _handle_insurance(session, text, choice, lang)
    if back_to_loan and session.get("product") == "insurance":
        slots, step = {}, "intent"
        session.update({"product": "loan", "step": "intent", "slots": {}, "tracker": {}})
        db.save_session(sid, product="loan", step="intent", slots={}, tracker={})

    # --- entry
    if step == "intent":
        if intent in ("start_loan", "check_eligibility") or choice == "eligibility" or (choice or "").startswith("loan:"):
            if (choice or "").startswith("loan:"):
                slots["amount"] = int(choice.split(":")[1])
            session.update({"language": lang, "slots": slots, "step": "purpose"})
            db.save_session(sid, language=lang, slots=slots, step="purpose")
            return _out(session, say(lang, "ask_purpose"), lang=lang, chips=PURPOSE_CHIPS)
        if intent == "greeting":
            session.update({"language": lang})
            db.save_session(sid, language=lang)
            return greeting(session)
        if intent == "off_topic" and text:
            reply = (await sarvam.run_tools(text, lang, db.messages(sid), sid)
                     or await sarvam.smalltalk(text, lang, db.messages(sid))
                     or say(lang, "off_topic"))
            session.update({"language": lang})
            db.save_session(sid, language=lang)
            return _out(session, reply, lang=lang, chips=[
                {"label": "I need a ₹5 lakh loan", "value": "loan:500000"}])
        session.update({"language": lang})
        db.save_session(sid, language=lang)
        return _out(session, say(lang, "ask_intent"), lang=lang, chips=[
            {"label": "Personal loan", "value": "loan:500000"},
            {"label": "Business loan", "value": "loan:200000"}])

    # --- purpose
    if step == "purpose":
        if (choice or "").startswith("purpose:"):
            slots["purpose"] = choice.split(":", 1)[1]
        if not slots.get("purpose"):
            return _out(session, say(lang, "ask_purpose"), lang=lang, chips=PURPOSE_CHIPS)
        consent_ok = consent  # noqa: F841  (kept for readability of the block below)
        db.audit(sid, "loan.purpose", slots["purpose"], 6)
        session.update({"language": lang, "slots": slots, "step": "amount"})
        db.save_session(sid, language=lang, slots=slots, step="amount")
        return _out(session, say(lang, "ask_amount"), lang=lang, chips=AMOUNT_CHIPS)

    # --- amount
    if step == "amount":
        if (choice or "").startswith("amount:"):
            slots["amount"] = int(choice.split(":")[1])
        if not slots.get("amount"):
            return _out(session, say(lang, "ask_amount"), lang=lang, chips=AMOUNT_CHIPS)
        if slots.pop("revisit", None) == "offers":
            session.update({"language": lang, "slots": slots})
            return _offers_response(session, lang, slots)
        session.update({"language": lang, "slots": slots, "step": "tenure"})
        db.save_session(sid, language=lang, slots=slots, step="tenure")
        return _out(session, say(lang, "ask_tenure"), lang=lang, chips=TENURE_CHIPS)

    # --- tenure
    if step == "tenure":
        if (choice or "").startswith("tenure:"):
            slots["tenure"] = int(choice.split(":")[1])
        elif text:
            t = parse_tenure(text)
            if t and t in TENURES:
                slots["tenure"] = t
        if not slots.get("tenure"):
            return _out(session, say(lang, "ask_tenure"), lang=lang, chips=TENURE_CHIPS)
        if slots.pop("revisit", None) == "offers":
            session.update({"language": lang, "slots": slots})
            return _offers_response(session, lang, slots)
        session.update({"language": lang, "slots": slots, "step": "budget"})
        db.save_session(sid, language=lang, slots=slots, step="budget")
        return _out(session, say(lang, "ask_budget"), lang=lang, chips=BUDGET_CHIPS)

    # --- EMI budget
    if step == "budget":
        if (choice or "").startswith("budget:"):
            raw = choice.split(":", 1)[1]
            slots["emi_budget"] = None if raw == "any" else int(raw)
        if "emi_budget" not in slots and text:
            v = parse_budget(text)
            if v is not None:
                slots["emi_budget"] = v
            elif text.lower().strip() in ("any", "no budget", "no preference"):
                slots["emi_budget"] = None
        if "emi_budget" not in slots:
            return _out(session, say(lang, "ask_budget"), lang=lang, chips=BUDGET_CHIPS)
        session.update({"language": lang, "slots": slots, "step": "income"})
        db.save_session(sid, language=lang, slots=slots, step="income")
        return _out(session, say(lang, "ask_income"), lang=lang, chips=INCOME_CHIPS)

    # --- income band
    if step == "income":
        if choice in ("under_30k", "30k_75k", "75k_plus"):
            slots["income_band"] = choice
        elif text and (m := re.search(r"\b([\d,]{4,7})\b", text)):
            amount = int(m.group(1).replace(",", ""))
            slots["income_band"] = ("under_30k" if amount < 30000 else
                                     "30k_75k" if amount < 75000 else "75k_plus")
        if not slots.get("income_band"):
            return _out(session, say(lang, "ask_income"), lang=lang, chips=INCOME_CHIPS)
        session.update({"language": lang, "slots": slots, "step": "employment"})
        db.save_session(sid, language=lang, slots=slots, step="employment")
        return _out(session, say(lang, "ask_employment"), lang=lang, chips=[
            {"label": "Salaried", "value": "salaried"},
            {"label": "Self-employed", "value": "self_employed"}])

    # --- employment
    if step == "employment":
        if choice in ("salaried", "self_employed"):
            slots["employment"] = choice
        if not slots.get("employment"):
            return _out(session, say(lang, "ask_employment"), lang=lang, chips=[
                {"label": "Salaried", "value": "salaried"},
                {"label": "Self-employed", "value": "self_employed"}])

        conflicts = eligibility.detect_conflicts(slots)
        slots["conflicts"] = conflicts
        if conflicts:
            session.update({"language": lang, "slots": slots, "step": "conflicts"})
            db.save_session(sid, language=lang, slots=slots, step="conflicts")
            db.audit(sid, "conflict.detect", ",".join(c["id"] for c in conflicts), 12)
            return _out(session, say(lang, "conflict_intro"), lang=lang,
                        chips=[{"label": "Use the Paytm figures", "value": "conflict:paytm"},
                               {"label": "Keep what I told you", "value": "conflict:mine"}],
                        cards=[{"type": "conflicts", "data": conflicts}])

        session.update({"language": lang, "slots": slots, "step": "consent_data"})
        db.save_session(sid, language=lang, slots=slots, step="consent_data")
        scopes = ["paytm.profile", "paytm.income", "paytm.kyc"]
        return _out(session, say(lang, "consent_data"), lang=lang,
                    chips=[{"label": "Share these and continue", "value": "grant"}],
                    consent_request=_consent_card(sid, scopes, group="identity"))

    # --- conflicts
    if step == "conflicts":
        conflicts = slots.get("conflicts", [])
        if choice == "conflict:paytm":
            for c in conflicts:
                if c["field"] == "income_band":
                    slots["income_band"] = "75k_plus"
                if c["field"] == "purpose":
                    slots["purpose"] = "personal"
            slots["corrections"] = [{"field": c["field"], "resolved": "paytm"} for c in conflicts]
            db.audit(sid, "conflict.resolve", "used Paytm values", 8)
        elif choice == "conflict:mine":
            slots["corrections"] = [{"field": c["field"], "resolved": "user"} for c in conflicts]
            db.audit(sid, "conflict.resolve", "kept user values", 8)
        else:
            return _out(session, say(lang, "conflict_intro"), lang=lang,
                        chips=[{"label": "Use the Paytm figures", "value": "conflict:paytm"},
                               {"label": "Keep what I told you", "value": "conflict:mine"}],
                        cards=[{"type": "conflicts", "data": conflicts}])
        session.update({"language": lang, "slots": slots, "step": "consent_data"})
        db.save_session(sid, language=lang, slots=slots, step="consent_data")
        scopes = ["paytm.profile", "paytm.income", "paytm.kyc"]
        return _out(session, say(lang, "consent_data"), lang=lang,
                    chips=[{"label": "Share these and continue", "value": "grant"}],
                    consent_request=_consent_card(sid, scopes, group="identity"))

    # --- consent: data
    if step == "consent_data":
        if choice != "grant":
            return _consent_wait(session, lang, "consent_data",
                                 ["paytm.profile", "paytm.income", "paytm.kyc"], group="identity")
        consent.grant(sid, ["paytm.profile", "paytm.income", "paytm.kyc"])
        session.update({"language": lang, "step": "consent_bureau"})
        db.save_session(sid, language=lang, step="consent_bureau")
        return _out(session, say(lang, "consent_bureau"), lang=lang,
                    chips=[{"label": "Run the soft credit check", "value": "grant"},
                           {"label": "Skip the credit check", "value": "skip_bureau"}],
                    consent_request=_consent_card(sid, ["bureau.softpull"], group="credit"))

    # --- consent: bureau
    if step == "consent_bureau":
        if choice == "skip_bureau":
            session.update(step="stopped")
            db.save_session(sid, step="stopped")
            return _out(session, "Credit check skipped. No score was accessed. This loan journey has stopped because pre-eligibility requires consent. You can start a new chat whenever you want.",
                        lang=lang, chips=[{"label": "New chat", "value": "start"}])
        if choice != "grant":
            return _out(session, "No credit check has been run. Choose Run to give consent, or Skip to stop this journey.",
                        lang=lang, chips=[{"label": "Run the soft credit check", "value": "grant"},
                                          {"label": "Skip the credit check", "value": "skip_bureau"}],
                        consent_request=_consent_card(sid, ["bureau.softpull"], group="credit"))
        consent.grant(sid, ["bureau.softpull"])
        result = eligibility.assess(slots["amount"], slots.get("purpose", "personal"),
                                    slots.get("income_band", "30k_75k"),
                                    slots.get("employment", "salaried"), slots.get("emi_budget"))
        slots["eligibility"] = result
        session.update({"language": lang, "slots": slots, "step": "offers"})
        db.save_session(sid, language=lang, slots=slots, step="offers")
        db.audit(sid, "eligibility.assess",
                 f"eligible={result['eligible']} · {result['eligible_partner_count']} partners", 88)

        if not result["eligible"]:
            reason = result["reasons"][0] if result["reasons"] else "No partner matches this profile yet."
            return _out(session, say(lang, "not_eligible", amount=inr(slots["amount"]), reason=reason),
                        lang=lang, chips=[{"label": "Try ₹3,00,000", "value": "amount:300000"}],
                        cards=[{"type": "snapshot", "data": result}])

        comp = _comparison(sid, slots)
        if not comp["offers"]:
            return _out(session, "No lender currently offers that full amount for this tenure. Please change the amount or tenure.",
                        lang=lang, chips=[{"label": "Change amount", "value": "change_amount"},
                                          {"label": "Change tenure", "value": "change_tenure"}])
        slots["offers"] = comp["offers"]
        db.save_session(sid, slots=slots)

        guard = _budget_guard(lang, comp, slots)
        if guard:
            return _out(session, guard, lang=lang,
                        chips=[{"label": "Change amount", "value": "change_amount"},
                               {"label": "Change tenure", "value": "change_tenure"},
                               {"label": "Show them anyway", "value": "show_offers"}],
                        cards=[{"type": "snapshot", "data": result},
                               {"type": "offers", "data": comp["offers"], "highlights": comp["highlights"],
                                "tenures": comp["tenures"], "selected_tenure": slots.get("tenure"),
                                "emi_budget": slots.get("emi_budget"),
                                "budget_note": comp.get("budget_note")}])

        return _out(session, say(lang, "pre_eligible") + " " + say(lang, "offers_intro"), lang=lang,
                    chips=_offer_chips(comp["offers"]),
                    cards=[{"type": "snapshot", "data": result},
                           {"type": "offers", "data": comp["offers"], "highlights": comp["highlights"],
                            "tenures": comp["tenures"], "selected_tenure": slots.get("tenure"),
                            "savings_vs_worst": comp["savings_vs_worst"],
                            "emi_budget": slots.get("emi_budget")}])

    # --- offers
    if step in ("offers", "apply"):
        if choice == "change_amount":
            slots["revisit"] = "offers"
            session.update({"language": lang, "slots": slots, "step": "amount"})
            db.save_session(sid, language=lang, slots=slots, step="amount")
            return _out(session, say(lang, "ask_amount"), lang=lang, chips=AMOUNT_CHIPS)
        if choice == "show_offers":
            comp = {"offers": slots.get("offers", [])}
            return _out(session, say(lang, "offers_intro"), lang=lang,
                        chips=_offer_chips(comp["offers"]),
                        cards=[{"type": "offers", "data": comp["offers"],
                                "tenures": lending.all_tenures(),
                                "selected_tenure": slots.get("tenure"),
                                "emi_budget": slots.get("emi_budget")}])
        if choice == "change_tenure":
            slots["revisit"] = "offers"
            session.update({"language": lang, "slots": slots, "step": "tenure"})
            db.save_session(sid, language=lang, slots=slots, step="tenure")
            return _out(session, say(lang, "ask_tenure"), lang=lang, chips=TENURE_CHIPS)

        if (choice or "").startswith("offer:"):
            offer = next((o for o in slots.get("offers", []) if o["offer_id"] == choice.split(":", 1)[1]), None)
            if offer:
                slots["selected_offer"] = offer
                session.update({"language": lang, "slots": slots, "step": "consent_share"})
                db.save_session(sid, language=lang, slots=slots, step="consent_share")
                db.audit(sid, "offer.select", f"{offer['lender_name']} · {offer['offer_id']}", 6)
                return _out(session, say(lang, "apply_consent", lender=offer["lender_name"]), lang=lang,
                            chips=[{"label": "Share with this lender", "value": "grant"}],
                            consent_request=_consent_card(
                                sid, ["lender.share", "documents.access"],
                                group="sharing", shared_with=offer["lender_name"]))

        comp = {"offers": slots.get("offers", [])}
        return _out(session, say(lang, "offers_intro"), lang=lang, chips=_offer_chips(comp["offers"]),
                    cards=[{"type": "offers", "data": comp["offers"],
                            "tenures": lending.all_tenures(),
                            "selected_tenure": slots.get("tenure")}])

    # --- consent: sharing with the lender
    if step == "consent_share":
        offer = slots["selected_offer"]
        if choice != "grant":
            return _out(session, "I have not shared your data. Select the consent button to continue.",
                        lang=lang, chips=[{"label": "Share with this lender", "value": "grant"}],
                        consent_request=_consent_card(sid, ["lender.share", "documents.access"],
                                                      group="sharing", shared_with=offer["lender_name"]))
        consent.grant(sid, ["lender.share", "documents.access"], shared_with=offer["lender_name"])
        app = lending.create_application(sid, offer, slots.get("purpose", "personal"),
                                         slots.get("employment", "salaried"))
        slots["application_id"] = app["id"]
        slots["reference"] = app["reference"]
        session["tracker"] = _tracker(offer, slots.get("purpose", "personal"), app["reference"])
        session.update({"language": lang, "slots": slots, "step": "prefill"})
        db.save_session(sid, language=lang, slots=slots, step="prefill", tracker=session["tracker"])
        return _out(session, say(lang, "prefill_done"), lang=lang,
                    chips=[{"label": "Looks right, continue", "value": "continue"}],
                    cards=[{"type": "prefill", "data": {
                        "application_id": app["id"], "reference": app["reference"],
                        "lender_name": offer["lender_name"], "amount": offer["amount"],
                        "tenure_months": offer["tenure_months"], "annual_rate": offer["annual_rate"],
                        "emi": offer["emi"], "fields": lending.prefill_fields()}}])

    # --- documents
    if step in ("prefill", "docs"):
        app_id = slots["application_id"]
        employment = slots.get("employment", "salaried")
        st = lending.document_status(app_id, employment)
        need = [d["label"] for d in st["required"]]
        missing = [d["label"] for d in st["missing"]]

        if step == "prefill" or choice == "refresh_docs":
            if st["complete"]:
                reply = say(lang, "docs_complete")
            elif step == "prefill":
                reply = say(lang, "docs_ask", docs=" and ".join(need))
            else:
                reply = say(lang, "docs_missing", missing=", ".join(missing))
            session.update({"language": lang, "step": "docs"})
            db.save_session(sid, language=lang, step="docs")
            return _out(session, reply, lang=lang,
                        chips=([{"label": "Continue to review", "value": "continue"}] if st["complete"]
                               else [{"label": "Check again", "value": "refresh_docs"}]),
                        cards=[{"type": "documents", "data": {**st, "application_id": app_id}}])

        if not st["complete"]:
            return _out(session, say(lang, "docs_missing", missing=", ".join(missing)), lang=lang,
                        chips=[{"label": "Check again", "value": "refresh_docs"}],
                        cards=[{"type": "documents", "data": {**st, "application_id": app_id}}])

        lending.mark_documents_verified(app_id, employment)
        from app.seed import PAYTM_KYC
        if PAYTM_KYC["status"] == "verified" and "paytm.kyc" in db.active_scopes(sid):
            db.run("UPDATE applications SET kyc_verified = 1 WHERE id = ?", (app_id,))
            db.audit(sid, "kyc.demo_match", "mock Paytm KYC status for demo", 5)
        session["tracker"] = _advance_tracker(session, 1, "Demo documents matched")
        session.update({"language": lang, "step": "review"})
        db.save_session(sid, language=lang, step="review", tracker=session["tracker"])
        rev = lending.review(app_id, employment)
        return _out(session, say(lang, "review_intro", lender=rev["lender"]), lang=lang,
                    chips=[{"label": "Approve and submit", "value": "grant"}],
                    cards=[{"type": "review", "data": rev}],
                    consent_request=_consent_card(sid, ["bureau.hardpull"], group="credit"))

    # --- review / hard bureau consent
    if step == "review":
        app_id = slots["application_id"]
        employment = slots.get("employment", "salaried")
        if choice != "grant":
            return _out(session, "Your loan has not been submitted. Select Approve and submit if you consent.",
                        lang=lang, chips=[{"label": "Approve and submit", "value": "grant"}],
                        consent_request=_consent_card(sid, ["bureau.hardpull"], group="credit"))
        consent.grant(sid, ["bureau.hardpull"], shared_with=slots["selected_offer"]["lender_name"])
        res = lending.approve_and_submit(app_id, employment)
        if res["decision"] == "documents_required":
            missing = ", ".join(m["label"] for m in res["missing"])
            session.update({"language": lang, "step": "docs"})
            db.save_session(sid, language=lang, step="docs")
            return _out(session, say(lang, "documents_required", missing=missing), lang=lang,
                        chips=[{"label": "Check again", "value": "refresh_docs"}],
                        cards=[{"type": "documents",
                                "data": {**lending.document_status(app_id, employment),
                                         "application_id": app_id}}])

        offer = slots["selected_offer"]
        session["tracker"] = _advance_tracker(session, 2, f"Submitted to {offer['lender_name']}")
        session.update({"language": lang, "step": "submitted"})
        db.save_session(sid, language=lang, step="submitted", tracker=session["tracker"])
        eta = res["estimated_decision_hours"]
        return _out(session, say(lang, "submitted", lender=offer["lender_name"], eta=eta) + " "
                    + say(lang, "simulated_note"), lang=lang,
                    chips=[{"label": "Check status", "value": "check_status"}],
                    cards=[{"type": "status", "data": res["application"], "eta_hours": eta}],
                    notifications=db.notifications_for(sid, 3))

    # --- tracking
    if step == "submitted":
        app_id = slots["application_id"]
        res = lending.advance(app_id)
        decision = res["decision"]
        session["tracker"] = _advance_tracker(session, 3, "Lender reviewing the file")
        notes = db.notifications_for(sid, 3)

        if decision == "under_review":
            session.update({"language": lang})
            db.save_session(sid, language=lang, tracker=session["tracker"])
            return _out(session, say(lang, "under_review", lender=slots["selected_offer"]["lender_name"]),
                        lang=lang, chips=[{"label": "Check status", "value": "check_status"}],
                        cards=[{"type": "status", "data": res["application"]}], notifications=notes)

        if decision == "approved":
            offer = slots["selected_offer"]
            session["tracker"] = _advance_tracker(session, 4, "Sanctioned", status="complete")
            session.update({"language": lang, "step": "done"})
            db.save_session(sid, language=lang, step="done", tracker=session["tracker"])
            return _out(session, say(lang, "approved", amount=inr(offer["amount"]),
                                     lender=offer["lender_name"], rate=offer["annual_rate"],
                                     eta=res["disbursal_eta_hours"]) + " "
                        + say(lang, "simulated_note") + " " + say(lang, "tracking"),
                        lang=lang, chips=[{"label": "Start a new loan", "value": "restart"}],
                        cards=[{"type": "status", "data": res["application"]}], notifications=notes)

        session.update({"language": lang, "step": "done"})
        db.save_session(sid, language=lang, step="done", tracker=session["tracker"])
        return _out(session, say(lang, "rejected", reason=res.get("reason", "")) + " "
                    + say(lang, "simulated_note"), lang=lang,
                    chips=[{"label": "Try another partner", "value": "restart"}],
                    cards=[{"type": "status", "data": res["application"]}], notifications=notes)

    # --- done
    if choice == "restart" or intent == "start_loan":
        session.update({"slots": {}, "step": "intent", "tracker": {}})
        db.save_session(sid, slots={}, step="intent", tracker={})
        return greeting(session)
    return _out(session, say(lang, "done"), lang=lang,
                chips=[{"label": "Start a new loan", "value": "restart"}])


# ---------------------------------------------------------------- insurance
INS_STEPS = ["Quote locked", "Proposal and declaration", "Payment", "Policy issued"]


def _ins(lang: str, key: str) -> str:
    return INS_COPY[key].get(lang) or INS_COPY[key]["en"]


def _ins_tracker(plan: dict, ref: str) -> dict:
    return {
        "active": True,
        "title": f"{plan['insurer']} · {plan['product']}",
        "ref": ref,
        "status": "in_progress",
        "meta": [
            {"k": "Cover", "v": inr(plan["sum_insured"])},
            {"k": "Members", "v": plan["members_label"]},
            {"k": "Premium", "v": inr(plan["annual_premium"]) + "/yr"},
            {"k": "Waiting", "v": f"{plan['ped_waiting_years']} years"},
        ],
        "steps": [{"label": s, "note": "", "state": "run" if i == 0 else "pending"}
                  for i, s in enumerate(INS_STEPS)],
    }


async def _handle_insurance(session: dict, text: str, choice: str | None, lang: str) -> dict:
    sid = session["id"]
    slots = dict(session["slots"])
    step = session["step"]

    def save(**kw) -> None:
        db.save_session(sid, language=lang, product="insurance", **kw)

    if not choice:
        answer = text.strip().lower()
        if step == "ins_cover":
            if re.search(r"family|children|kids|परिवार|बच्च", answer):
                choice = "family"
            elif re.search(r"spouse|wife|husband|couple|पत्नी|पति|जीवनसाथी", answer):
                choice = "couple"
            elif re.search(r"just me|myself|self|only me|सिर्फ|केवल", answer):
                choice = "self"
        elif step == "ins_sum":
            amount = parse_amount(text)
            if amount in insurance.SUM_INSURED_FACTOR:
                choice = f"sum:{amount}"
        elif step == "ins_ped":
            if answer in {"no", "none", "no conditions", "नहीं", "कोई नहीं"}:
                choice = "ped:no"
            elif re.search(r"diabet|मधुमेह|डायबिटीज", answer):
                choice = "ped:yes"
        elif step == "ins_done" and answer in {"new policy", "नई पॉलिसी"}:
            choice = "restart"

    scopes = ["paytm.profile", "paytm.kyc"]
    if step in {"ins_plans", "ins_declare", "ins_pay"} and not set(scopes).issubset(db.active_scopes(sid)):
        if choice == "grant":
            consent.grant(sid, scopes)
        else:
            return _out(session, _ins(lang, "consent"), lang=lang,
                        chips=[{"label": "Share these and continue", "value": "grant"}],
                        consent_request=_consent_card(sid, scopes))

    # --- entry / restart
    if not step.startswith("ins_") or step == "ins_done":
        if step == "ins_done" and choice != "restart":
            return _out(session, _ins(lang, "done"), lang=lang,
                        chips=[{"label": "New policy", "value": "restart"},
                               {"label": "Back to loans", "value": "loan:500000"}])
        slots = {}
        session.update({"product": "insurance", "step": "ins_cover", "slots": slots, "tracker": {}})
        save(step="ins_cover", slots=slots, tracker={})
        return _out(session, _ins(lang, "ask_cover"), lang=lang, chips=[
            {"label": "Just me", "value": "self"},
            {"label": "Me and my spouse", "value": "couple"},
            {"label": "Family of four", "value": "family"}])

    if step == "ins_cover":
        cover = choice if choice in ("self", "couple", "family") else slots.get("ins_members")
        if not cover:
            return _out(session, _ins(lang, "ask_cover"), lang=lang, chips=[
                {"label": "Just me", "value": "self"},
                {"label": "Me and my spouse", "value": "couple"},
                {"label": "Family of four", "value": "family"}])
        slots["ins_members"] = cover
        session.update({"language": lang, "slots": slots, "step": "ins_sum"})
        save(step="ins_sum", slots=slots)
        return _out(session, _ins(lang, "ask_sum"), lang=lang, chips=[
            {"label": "₹5 lakh", "value": "sum:500000"},
            {"label": "₹10 lakh", "value": "sum:1000000"},
            {"label": "₹25 lakh", "value": "sum:2500000"}])

    if step == "ins_sum":
        if choice and choice.startswith("sum:"):
            slots["ins_sum"] = int(choice.split(":")[1])
        if not slots.get("ins_sum"):
            return _out(session, _ins(lang, "ask_sum"), lang=lang, chips=[
                {"label": "₹5 lakh", "value": "sum:500000"},
                {"label": "₹10 lakh", "value": "sum:1000000"},
                {"label": "₹25 lakh", "value": "sum:2500000"}])
        session.update({"language": lang, "slots": slots, "step": "ins_ped"})
        save(step="ins_ped", slots=slots)
        return _out(session, _ins(lang, "ask_ped"), lang=lang, chips=[
            {"label": "No conditions", "value": "ped:no"},
            {"label": "Yes — diabetes", "value": "ped:yes"}])

    if step == "ins_ped":
        if choice not in ("ped:yes", "ped:no"):
            return _out(session, _ins(lang, "ask_ped"), lang=lang, chips=[
                {"label": "No conditions", "value": "ped:no"},
                {"label": "Yes — diabetes", "value": "ped:yes"}])
        ped = "yes" if choice == "ped:yes" else "no"
        slots["ins_ped"] = ped
        session.update({"language": lang, "slots": slots, "step": "ins_consent"})
        save(step="ins_consent", slots=slots)
        scopes = ["paytm.profile", "paytm.kyc"]
        return _out(session, _ins(lang, "consent"), lang=lang,
                    chips=[{"label": "Share these and continue", "value": "grant"}],
                    consent_request={"scopes": scopes,
                                     "items": [consent.CATALOGUE[x] for x in scopes],
                                     "grant_url": f"/api/sessions/{sid}/consent"})

    if step == "ins_consent":
        if choice != "grant":
            return _out(session, "No Paytm data was shared. Choose Share to continue.", lang=lang,
                        chips=[{"label": "Share these and continue", "value": "grant"}],
                        consent_request=_consent_card(sid, ["paytm.profile", "paytm.kyc"]))
        consent.grant(sid, ["paytm.profile", "paytm.kyc"])
        plans = insurance.plans(sid, slots.get("ins_members", "self"),
                                slots.get("ins_sum", 1000000), slots.get("ins_ped", "no"))
        slots["ins_plans"] = plans
        session.update({"language": lang, "slots": slots, "step": "ins_plans"})
        save(step="ins_plans", slots=slots)
        db.audit(sid, "insurer.quote", f"{len(plans)} plans matched", 118)
        return _out(session, _ins(lang, "plans"), lang=lang,
                    chips=[{"label": f"{p['insurer']} · {inr(p['annual_premium'])}/yr", "value": f"plan:{p['plan_id']}"}
                           for p in plans],
                    cards=[{"type": "plans", "data": plans}])

    if step == "ins_plans":
        plan = None
        if choice and choice.startswith("plan:"):
            plan = next((p for p in slots.get("ins_plans", []) if p["plan_id"] == choice.split(":", 1)[1]), None)
        if not plan:
            return _out(session, _ins(lang, "plans"), lang=lang,
                        chips=[{"label": f"{p['insurer']} · {inr(p['annual_premium'])}/yr", "value": f"plan:{p['plan_id']}"}
                               for p in slots.get("ins_plans", [])],
                        cards=[{"type": "plans", "data": slots.get("ins_plans", [])}])
        slots["ins_selected"] = plan
        policy = insurance.create_policy(sid, plan, slots.get("ins_members", "self"), slots.get("ins_ped", "no"))
        slots["policy_id"] = policy["id"]
        session["tracker"] = _ins_tracker(plan, policy["id"])
        session.update({"language": lang, "slots": slots, "step": "ins_declare"})
        save(step="ins_declare", slots=slots, tracker=session["tracker"])
        return _out(session, _ins(lang, "proposal"), lang=lang,
                    chips=[{"label": "Declare and continue", "value": "declare"}],
                    cards=[{"type": "proposal", "data": {
                        "policy_id": policy["id"], "plan": plan,
                        "fields": [{"label": "Proposer", "value": "Arjun Mehta", "source": "Paytm KYC"},
                                   {"label": "Members", "value": plan["members_label"], "source": "you"},
                                   {"label": "Sum insured", "value": inr(plan["sum_insured"]), "source": "you"},
                                   {"label": "Annual premium", "value": inr(plan["annual_premium"]), "source": "insurer"},
                                   {"label": "Medical declaration", "value": "Not yet given", "source": "needs you"}]}}])

    if step == "ins_declare":
        if choice != "declare":
            return _out(session, "Please review and explicitly confirm the medical declaration.",
                        lang=lang, chips=[{"label": "Declare and continue", "value": "declare"}])
        insurance.declare(slots["policy_id"],
                          ["diabetes"] if slots.get("ins_ped") == "yes" else ["none"])
        session["tracker"] = _advance_tracker(session, 1, "Demo declaration recorded; no insurer assessment")
        session.update({"language": lang, "step": "ins_pay"})
        save(step="ins_pay", tracker=session["tracker"])
        return _out(session, _ins(lang, "declared_diabetes" if slots.get("ins_ped") == "yes" else "declared"), lang=lang,
                    chips=[{"label": f"Simulate payment {inr(slots['ins_selected']['annual_premium'])} (no charge)", "value": "pay"}])

    if step == "ins_pay":
        if choice != "pay":
            return _out(session, "This is a payment simulator: no real payment or insurance is issued.",
                        lang=lang, chips=[{"label": "Simulate payment (no charge)", "value": "pay"}])
        policy = insurance.pay_and_issue(slots["policy_id"])
        session["tracker"] = _advance_tracker(session, 2, "Simulated payment — no charge")
        session["tracker"] = _advance_tracker(session, 3, "Demo issuance — no insurer policy or PDF", status="complete")
        session.update({"language": lang, "step": "ins_done"})
        save(step="ins_done", tracker=session["tracker"])
        return _out(session, _ins(lang, "issued"), lang=lang,
                    chips=[{"label": "New policy", "value": "restart"},
                           {"label": "Back to loans", "value": "loan:500000"}],
                    cards=[{"type": "policy", "data": policy}])

    return _out(session, _ins(lang, "done"), lang=lang,
                chips=[{"label": "New policy", "value": "restart"}])
