def start_run(client, run_id="run-1", cap: int | None = 5):
    return client.post("/api/runs", json={"run_id": run_id, "cap": cap})


def write_todos(client, todos, run_id="run-1"):
    return client.put(f"/api/runs/{run_id}/todos", json={"todos": todos})


def finish(client, run_id="run-1"):
    return client.post(f"/api/runs/{run_id}/finish", json={"summary": "All done."})


def test_no_run_yet(client):
    response = client.get("/api/runs/current")
    assert response.status_code == 200
    assert response.json() is None


def test_start_run(client):
    run = start_run(client).json()
    assert run["run_id"] == "run-1"
    assert run["cap"] == 5
    assert run["todos"] == []
    assert run["finished_at"] is None
    assert run["summary"] is None
    assert client.get("/api/runs/current").json() == run
    assert start_run(client).status_code == 409


def test_a_run_over_the_whole_queue(client):
    assert start_run(client, cap=None).json()["cap"] is None


def test_cap_must_be_positive(client):
    assert start_run(client, cap=0).status_code == 422


def test_current_run_is_the_latest(client):
    start_run(client, "run-1")
    start_run(client, "run-2")
    assert client.get("/api/runs/current").json()["run_id"] == "run-2"


def test_write_todos_replaces_the_list(client):
    start_run(client)
    write_todos(client, [{"content": "CLM-1001", "status": "to_do"}])
    todos = [
        {"content": "CLM-1002", "status": "done"},
        {"content": "CLM-1001", "status": "in_progress"},
        {"content": "CLM-1003", "status": "for_handler"},
    ]
    assert write_todos(client, todos).json()["todos"] == todos
    assert client.get("/api/runs/current").json()["todos"] == todos


def test_write_todos_checks_each_item(client):
    start_run(client)
    assert write_todos(client, [{"content": "x", "status": "maybe"}]).status_code == 422
    assert write_todos(client, [{"content": "", "status": "done"}]).status_code == 422


def test_unknown_run(client):
    assert write_todos(client, [], run_id="nope").status_code == 404
    assert finish(client, run_id="nope").status_code == 404


def test_finish_run(client):
    start_run(client)
    run = finish(client).json()
    assert run["summary"] == "All done."
    assert run["finished_at"] is not None
    assert finish(client).status_code == 409
    assert write_todos(client, []).status_code == 409


def test_finish_needs_a_summary(client):
    start_run(client)
    response = client.post("/api/runs/run-1/finish", json={"summary": ""})
    assert response.status_code == 422
