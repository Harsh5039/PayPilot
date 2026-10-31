import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DB = ROOT / "test_paypilot.db"
if TEST_DB.exists():
    TEST_DB.unlink()
os.environ["DATABASE_PATH"] = str(TEST_DB)
os.environ.pop("SARVAM_API_KEY", None)   # tests run the offline rule agent

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c
