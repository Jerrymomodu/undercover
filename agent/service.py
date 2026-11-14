"""The agent's service: the backend calls it to start a dispatch, and after a handler's
sign-off to pick the claim back up. npm run dev starts it beside the backend and the
dashboard."""

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent import api
from agent.console import show_reports
from agent.dispatcher import dispatch
from agent.harness import (
    NO_EFFORT,
    ClaimAgent,
    Run,
    carry_on,
    chosen_model,
    claim_agent,
    connections,
    model,
)

MOST_AGENTS = 25
BUSY = "A dispatch or evaluation is already running"
BACKEND_WAIT_SECONDS = 30

# One dispatch or evaluation at a time, held from its start until it finishes.
running = threading.Lock()
# The claims being picked back up after a sign-off, which a dispatch leaves alone.
resuming: set[str] = set()


def stop_earlier_runs() -> None:
    """Mark any run an earlier service left running as stopped, once the backend
    answers: npm run dev starts the two together."""
    api.wait_for_backend(BACKEND_WAIT_SECONDS)
    api.stop_runs()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Keep the process's connections open while the service runs."""
    show_reports()
    stop_earlier_runs()
    with connections() as pool:
        app.state.pool = pool
        yield


app = FastAPI(title="UnderCover Agent", lifespan=lifespan)


class DispatchRequest(BaseModel):
    agents: int = Field(ge=1, le=MOST_AGENTS, description="Claim agents at once")


@app.exception_handler(api.Refused)
def refused(_: Request, error: api.Refused) -> JSONResponse:
    """Pass on the backend's refusal, such as a claim it doesn't know."""
    return JSONResponse({"detail": error.detail}, status_code=error.status_code)


def build_agent(request: Request) -> ClaimAgent:
    """The claim agent for one request, on the service's connections."""
    return claim_agent(model(), request.app.state.pool)


Agent = Annotated[ClaimAgent, Depends(build_agent)]


def run_dispatch(agents: int, agent: ClaimAgent) -> None:
    """Create a dispatch on the backend and work it, then let another run start."""
    try:
        name, effort = chosen_model()
        run = api.create_dispatch(agents, name, effort or NO_EFFORT)
        try:
            dispatch(Run(run["run_id"], evaluation=False), agent, agents, resuming)
        except Exception:
            api.stop_runs()  # this run is the only one running
            raise
    finally:
        running.release()


def resume(claim_id: str, agent: ClaimAgent) -> None:
    """Carry a signed-off claim on to its payment, then leave it to dispatches again."""
    try:
        carry_on(claim_id, agent.graph(), None)
    finally:
        resuming.discard(claim_id)


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the agent's service is running."""
    return {"status": "ok"}


@app.post("/api/dispatches", operation_id="start_dispatch", status_code=202)
def start_dispatch(
    request: DispatchRequest, agent: Agent, background: BackgroundTasks
) -> dict[str, str]:
    """Start a dispatch with up to N claim agents at once, without waiting for it."""
    if not running.acquire(blocking=False):
        raise HTTPException(409, BUSY)
    background.add_task(run_dispatch, request.agents, agent)
    return {"status": "accepted"}


@app.post("/api/claims/{claim_id}/resume", operation_id="resume_claim", status_code=202)
def resume_claim(
    claim_id: str, agent: Agent, background: BackgroundTasks
) -> dict[str, str]:
    """Pick a claim back up after a handler's sign-off, without waiting for it."""
    claim = api.get_claim(claim_id)
    signed_off = claim["decision"] and claim["decision"]["signed_off_by"]
    if claim["status"] != api.Status.IN_PROGRESS or not signed_off:
        raise HTTPException(409, f"Claim {claim_id} has no sign-off waiting to be paid")
    resuming.add(claim_id)
    background.add_task(resume, claim_id, agent)
    return {"status": "accepted"}
