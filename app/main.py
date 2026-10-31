"""PayPilot API — Phase 1 hackathon MVP.

Run:  uvicorn app.main:app --reload --port 8000
Docs: http://localhost:8000/docs
App:  http://localhost:8000/
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.config import settings
from app.routers import chat, data, insurance, lending
from app.services import sarvam
from app.security import authorize

STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(
    title="PayPilot API",
    version="1.0.0",
    description=(
        "Conversational loan journeys inside the Paytm app. Consent-gated data, "
        "deterministic eligibility, mock partner APIs, and Sarvam-105B for language."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or (["*"] if settings.demo_mode else []),
    allow_methods=["*"],
    allow_headers=["*"],
)

db.init_db()

app.include_router(chat.router, dependencies=[Depends(authorize)])
app.include_router(data.router, dependencies=[Depends(authorize)])
app.include_router(lending.router, dependencies=[Depends(authorize)])
app.include_router(insurance.router, dependencies=[Depends(authorize)])

app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": app.version,
        "llm": sarvam.status(),
        "demo_mode": settings.demo_mode,
        "consent_ttl_days": settings.consent_ttl_days,
        "endpoints": {
            "chat": ["POST /api/sessions", "POST /api/chat", "GET /api/sessions/{id}"],
            "consent": ["GET /api/consent/catalogue", "POST /api/sessions/{id}/consent",
                        "DELETE /api/sessions/{id}/consent/{scope}"],
            "paytm": ["GET /api/sessions/{id}/paytm/{profile|income|kyc|accounts|transactions}"],
            "loans": ["GET /api/loans/emi", "POST /api/sessions/{id}/loans/eligibility",
                      "POST /api/sessions/{id}/loans/compare"],
            "applications": ["POST /api/sessions/{id}/applications", "GET /api/applications/{id}",
                             "POST /api/applications/{id}/documents (multipart)",
                             "POST /api/applications/{id}/kyc", "POST /api/applications/{id}/submit",
                             "GET /api/applications/{id}/summary"],
            "insurance": ["GET /api/insurance/plans", "POST /api/sessions/{id}/insurance/policies",
                          "POST /api/policies/{id}/declare", "POST /api/policies/{id}/pay"],
        },
    }
