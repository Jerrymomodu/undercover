"""The agent's service, as the backend calls it: to start a dispatch or an evaluation,
and once after each sign-off."""

import logging
import os
from typing import Any

import httpx

AGENT_URL = os.getenv("UNDERCOVER_AGENT", "http://127.0.0.1:8002")
UNAVAILABLE = "The agent's service isn't running"

agent = httpx.Client(base_url=f"{AGENT_URL}/api", timeout=10)

log = logging.getLogger(__name__)


class Refused(Exception):
    """The agent's service didn't start a run, with the status and reason to pass on."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"{status_code}: {detail}")
        self.status_code, self.detail = status_code, detail


def _start(path: str, body: dict[str, Any]) -> None:
    """Ask the agent's service to start a run, or raise Refused with its reason."""
    try:
        response = agent.post(path, json=body)
    except httpx.ConnectError as error:
        raise Refused(503, UNAVAILABLE) from error
    if response.is_error:
        raise Refused(response.status_code, response.json()["detail"])


def start_dispatch(agents: int) -> None:
    """Ask the agent to start a dispatch with up to agents claim agents at once."""
    _start("/dispatches", {"agents": agents})


def start_evaluation(agents: int, eval_set: str, tiny: bool) -> None:
    """Ask the agent to start an evaluation on copies of a labelled set."""
    _start("/evaluations", {"agents": agents, "eval_set": eval_set, "tiny": tiny})


def resume_claim(claim_id: str) -> None:
    """Ask the agent to pick a claim back up after its sign-off."""
    try:
        agent.post(f"/claims/{claim_id}/resume").raise_for_status()
    except httpx.HTTPError as error:  # the sign-off stands without the agent
        log.warning(
            "The agent didn't pick up %s after its sign-off: %s", claim_id, error
        )
