"""Requests the backend's tests send to create a dispatch or an evaluation."""


def create_dispatch(client, agents=3):
    body = {"agents": agents, "model": "openai/gpt-6-luna", "reasoning_effort": "low"}
    return client.post("/api/dispatches", json=body)


def create_evaluation(client, eval_set, tiny, agents=3):
    body = {
        "agents": agents,
        "eval_set": eval_set,
        "tiny": tiny,
        "model": "openai/gpt-6-luna",
        "reasoning_effort": "low",
    }
    return client.post("/api/evaluations", json=body)
