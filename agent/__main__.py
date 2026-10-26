"""Run the UnderCover Agent: uv run -m agent [claim ids], or every waiting claim."""

import sys
import uuid

from agent import main as agent


def work(claim_ids: list[str]) -> None:
    """Run the agent on each claim given, or on every waiting claim."""
    queue = claim_ids or [
        c["claim_id"]
        for c in agent.send("GET", "/api/claims")
        if c["status"] == "waiting"
    ]
    for claim_id in queue:
        print(f"{claim_id}: {agent.run(claim_id, str(uuid.uuid4()))}")


if __name__ == "__main__":
    work(sys.argv[1:])
