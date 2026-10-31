#!/usr/bin/env bash
set -e
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
exec uvicorn app.main:app --reload --port 8000
