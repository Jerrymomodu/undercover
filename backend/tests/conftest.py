import pytest
from fastapi.testclient import TestClient

from backend import seed
from backend.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A client for the backend on a freshly seeded database."""
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "undercover.db"))
    seed.seed()
    return TestClient(app)
