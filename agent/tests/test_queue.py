import sqlite3
from contextlib import closing

import pytest

from agent import __main__ as cli
from agent import main


@pytest.fixture
def three_waiting(database):
    """Leave only CLM-1001, CLM-1002 and CLM-1003 waiting in the queue."""
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "UPDATE claims SET status = 'decided'"
            " WHERE claim_id NOT IN ('CLM-1001', 'CLM-1002', 'CLM-1003')"
        )


def test_work_queue_works_each_waiting_claim(monkeypatch, capsys, three_waiting):
    monkeypatch.setattr(main, "work_claim", lambda claim_id: f"{claim_id}  refer")
    cli.main([])
    assert capsys.readouterr().out.splitlines() == [
        "CLM-1001  refer",
        "CLM-1002  refer",
        "CLM-1003  refer",
        "Worked 3 claims",
    ]
