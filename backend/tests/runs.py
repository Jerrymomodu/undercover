"""Requests the backend's tests send to create a dispatch."""


def create_dispatch(client, agents=3):
    body = {"agents": agents, "model": "openai/gpt-6-luna", "reasoning_effort": "low"}
    return client.post("/api/dispatches", json=body)
