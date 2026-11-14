"""Work one claim with the UnderCover Agent: uv run -m agent CLM-1001"""

import argparse
import sys

from dotenv import load_dotenv

from agent import api
from agent.console import show_reports
from agent.harness import claim_agent, connections, model, work_claim


def main(args: list[str]) -> None:
    """Work the claim named on the command line, in no dispatch or evaluation."""
    parser = argparse.ArgumentParser(
        prog="uv run -m agent",
        description="Work one claim. Dispatches start from the dashboard.",
    )
    parser.add_argument("claim_id", help="the claim to work, such as CLM-1001")
    options = parser.parse_args(args)
    with connections() as pool:
        graph = claim_agent(model(), pool).graph()
        try:
            work_claim(options.claim_id, graph, None)
        except api.Refused as refusal:
            parser.exit(1, f"{options.claim_id}  not started: {refusal}\n")


if __name__ == "__main__":
    load_dotenv(override=True)
    show_reports()
    main(sys.argv[1:])
