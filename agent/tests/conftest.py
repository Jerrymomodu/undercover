import pytest
from fastapi.testclient import TestClient

from agent import main
from backend import seed
from backend.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A freshly seeded backend, which the agent reaches in-process."""
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "undercover.db"))
    seed.seed()
    monkeypatch.setattr(main, "backend", lambda: TestClient(app))
    return TestClient(app)
