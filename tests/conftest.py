"""Shared fixture: a fresh test database built from the migrations and sample catalog, and an API client."""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import migrate  # noqa: E402
from oorubridge import db  # noqa: E402
from oorubridge.api import app  # noqa: E402

TEST_URL = os.getenv("DATABASE_URL_TEST", "postgresql:///oorubridge_test")


@pytest.fixture(scope="module")
def client():
    migrate.reset_database(TEST_URL)
    migrate.migrate(TEST_URL)
    migrate.seed(TEST_URL)
    db.DATABASE_URL = TEST_URL
    with TestClient(app) as c:
        yield c
