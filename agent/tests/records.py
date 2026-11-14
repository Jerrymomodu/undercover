"""What the test backend has recorded on claims and runs."""

from sqlalchemy import select

from backend.database import engine, model_calls, runs, work_times


def rows_of(table, claim_id):
    """A claim's rows in one of the backend's tables, read straight from it."""
    query = select(table).where(table.c.claim_id == claim_id)
    with engine().connect() as db:
        return [dict(row) for row in db.execute(query).mappings()]


def model_calls_of(claim_id):
    return rows_of(model_calls, claim_id)


def work_times_of(claim_id):
    return rows_of(work_times, claim_id)


def claim_of(client, claim_id):
    return client.get(f"/api/claims/{claim_id}").json()


def steps_of(client, claim_id):
    return client.get(f"/api/claims/{claim_id}/steps").json()


def run_ids():
    """The ids of every run the backend has recorded, oldest first."""
    query = select(runs.c.run_id).order_by(runs.c.number)
    with engine().connect() as db:
        return list(db.execute(query).scalars())
