"""Workers that take invoices off the queue in parallel, each on a lease."""

import sqlite3
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from invoice_desk.db import connect, decide, log, transaction
from invoice_desk.judge import Judge
from invoice_desk.pipeline import LeaseLostError, advance

LEASE_SECONDS = 300
MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class Claimed:
    invoice_id: str
    attempts: int


def claim(conn: sqlite3.Connection, owner: str, at: float) -> Claimed | None:
    """Take the next unfinished job whose lease is free or has expired."""
    with transaction(conn):
        rows = conn.execute(
            "UPDATE jobs SET lease_owner = ?, lease_expires = ?,"
            " attempts = attempts + 1"
            " WHERE invoice_id = (SELECT invoice_id FROM jobs WHERE stage != 'done'"
            " AND (lease_expires IS NULL OR lease_expires < ?)"
            " ORDER BY invoice_id LIMIT 1)"
            " RETURNING invoice_id, attempts",
            (owner, at + LEASE_SECONDS, at),
        ).fetchall()
    return Claimed(rows[0]["invoice_id"], rows[0]["attempts"]) if rows else None


def release(conn: sqlite3.Connection, invoice_id: str, owner: str, error: str) -> None:
    """Give a job back after an error, so it can be tried again."""
    with transaction(conn):
        conn.execute(
            "UPDATE jobs SET lease_owner = NULL, lease_expires = NULL"
            " WHERE invoice_id = ? AND lease_owner = ?",
            (invoice_id, owner),
        )
        log(conn, invoice_id, owner, f"Failed, back in the queue: {error}")


def give_up(
    conn: sqlite3.Connection, invoice_id: str, owner: str, attempts: int
) -> None:
    """Stop trying a job that keeps failing, and leave it for a person."""
    reason = f"Tried {attempts - 1} times without finishing"
    with transaction(conn):
        conn.execute(
            "UPDATE jobs SET stage = 'done' WHERE invoice_id = ?", (invoice_id,)
        )
        status = conn.execute(
            "SELECT status FROM invoices WHERE id = ?", (invoice_id,)
        ).fetchone()["status"]
        if status == "received":
            decide(conn, invoice_id, "for_review", "workers", reason)
        log(conn, invoice_id, owner, f"{reason}: left for a person")


def work(
    db_path: Path, owner: str, judge: Judge, clock: Callable[[], float] = time.time
) -> int:
    """Work jobs until none are left, and return how many this worker finished."""
    conn = connect(db_path)
    finished = 0
    while job := claim(conn, owner, clock()):
        if job.attempts > MAX_ATTEMPTS:
            give_up(conn, job.invoice_id, owner, job.attempts)
            continue
        try:
            while advance(conn, job.invoice_id, owner, judge) != "done":
                pass
            finished += 1
        except LeaseLostError:
            continue
        except Exception as error:  # noqa: BLE001 - one bad invoice never stops a worker
            release(conn, job.invoice_id, owner, repr(error))
    conn.close()
    return finished


def run_workers(db_path: Path, count: int, judge: Judge) -> int:
    """Work the whole queue with several workers in parallel."""
    with ThreadPoolExecutor(max_workers=count) as pool:
        results = pool.map(
            lambda n: work(db_path, f"worker-{n}", judge), range(1, count + 1)
        )
        return sum(results)
