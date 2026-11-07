"""Invoice Desk from the command line."""

import argparse
import sys
import tempfile
from pathlib import Path

from invoice_desk.db import (
    DEFAULT_DB,
    connect,
    create,
    decide,
    log,
    pay,
    pounds,
    transaction,
)
from invoice_desk.evals import report, run_evals
from invoice_desk.judge import ModelJudge, flush_traces
from invoice_desk.workers import run_workers


def status(db: Path) -> None:
    conn = connect(db)
    for r in conn.execute(
        "SELECT i.id, v.name, i.total_pence, i.status, i.decided_by FROM invoices i"
        " JOIN vendors v ON v.id = i.vendor_id ORDER BY i.id"
    ):
        print(
            f"{r['id']:<9}{r['name']:<28}{pounds(r['total_pence']):>12}  "
            f"{r['status']:<11}{r['decided_by'] or ''}"
        )


def show(db: Path, invoice_id: str) -> None:
    conn = connect(db)
    invoice = conn.execute(
        "SELECT * FROM invoices WHERE id = ?", (invoice_id,)
    ).fetchone()
    print(f"{invoice_id}: {invoice['status']}, {pounds(invoice['total_pence'])}")
    print(f"Reason: {invoice['reason'] or '-'}\n")
    for e in conn.execute(
        "SELECT at, actor, message FROM events WHERE invoice_id = ? ORDER BY id",
        (invoice_id,),
    ):
        print(f"{e['at']}  {e['actor']:<36}{e['message']}")


def review(db: Path) -> None:
    conn = connect(db)
    rows = conn.execute(
        "SELECT id, total_pence, reason FROM invoices WHERE status = 'for_review'"
        " ORDER BY id"
    ).fetchall()
    for r in rows:
        print(f"{r['id']:<9}{pounds(r['total_pence']):>12}  {r['reason']}")
    print(f"\n{len(rows)} invoices waiting for a person.")


def human_decision(
    db: Path, invoice_id: str, choice: str, name: str, reason: str
) -> None:
    conn = connect(db)
    status = "approved" if choice == "approve" else "rejected"
    with transaction(conn):
        decide(conn, invoice_id, status, f"human:{name}", reason)
        log(conn, invoice_id, f"human:{name}", f"{status}: {reason}")
        if status == "approved":
            pay(conn, invoice_id)
            log(conn, invoice_id, "payments", "Paid to the account on file")
    print(f"{invoice_id} {status}.")


def evaluate(workers: int) -> int:
    with tempfile.TemporaryDirectory() as folder:
        results = run_evals(ModelJudge(), workers, Path(folder) / "evals.db")
    flush_traces()
    print(report(results))
    return 1 if any(r.critical for r in results) else 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="invoice_desk", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed", help="Make a fresh database from data/")
    run = commands.add_parser("run", help="Work the queue")
    run.add_argument("--workers", type=int, default=4)
    commands.add_parser("status", help="List every invoice")
    commands.add_parser("review", help="List the invoices waiting for a person")
    show_cmd = commands.add_parser("show", help="An invoice's audit trail")
    show_cmd.add_argument("invoice_id")
    decide_cmd = commands.add_parser(
        "decide", help="Decide an invoice left for a person"
    )
    decide_cmd.add_argument("invoice_id")
    decide_cmd.add_argument("choice", choices=["approve", "reject"])
    decide_cmd.add_argument("--by", required=True)
    decide_cmd.add_argument("--reason", required=True)
    evals_cmd = commands.add_parser("evals", help="Score the agent on a fresh queue")
    evals_cmd.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    match args.command:
        case "seed":
            create(DEFAULT_DB)
            print(f"Fresh database at {DEFAULT_DB}")
        case "run":
            finished = run_workers(DEFAULT_DB, args.workers, ModelJudge())
            flush_traces()
            print(f"Finished {finished} invoices.")
            status(DEFAULT_DB)
        case "status":
            status(DEFAULT_DB)
        case "review":
            review(DEFAULT_DB)
        case "show":
            show(DEFAULT_DB, args.invoice_id)
        case "decide":
            human_decision(
                DEFAULT_DB, args.invoice_id, args.choice, args.by, args.reason
            )
        case "evals":
            return evaluate(args.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
