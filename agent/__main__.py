"""Work the queue with the UnderCover Agent: uv run -m agent [--cap 5] [CLM-1001]"""

import argparse
import sys

from agent.main import work_claim
from agent.queue import work_queue


def main(args: list[str]) -> None:
    """Work the claim named on the command line, or the queue up to a cap."""
    parser = argparse.ArgumentParser(
        prog="uv run -m agent",
        description="Work the claims queue with the UnderCover Agent.",
    )
    parser.add_argument("claim_id", nargs="?", help="work this one claim")
    parser.add_argument("--cap", type=int, help="work at most this many claims")
    options = parser.parse_args(args)
    if options.cap is not None and options.cap < 1:
        parser.error("--cap must be at least 1")
    if options.claim_id:
        print(work_claim(options.claim_id))
    else:
        work_queue(options.cap)


if __name__ == "__main__":
    main(sys.argv[1:])
