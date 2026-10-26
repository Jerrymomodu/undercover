from agent import main as agent


def test_run_agent_starts_the_agent_in_the_background(client, monkeypatch):
    runs = []
    monkeypatch.setattr(agent, "run", lambda c, t: runs.append((c, t)))
    response = client.post("/api/claims/CLM-1001/run")
    assert response.status_code == 200
    thread_id = response.json()["thread_id"]
    assert runs == [("CLM-1001", thread_id)]


def test_run_agent_needs_a_waiting_claim(client, monkeypatch):
    runs = []
    monkeypatch.setattr(agent, "run", lambda c, t: runs.append((c, t)))
    client.post("/api/claims/CLM-1001/start", json={"thread_id": "thread-1"})
    assert client.post("/api/claims/CLM-1001/run").status_code == 409
    assert client.post("/api/claims/CLM-9999/run").status_code == 404
    assert runs == []
