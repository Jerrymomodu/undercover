import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, ForeignKey, MetaData, Table, Text, inspect
from sqlalchemy.pool import QueuePool

from backend.database import engine, location, seed
from backend.main import app

SUPABASE = "postgresql://postgres.ref:secret@pooler.example.com:5432/db"


def test_postgres_is_used_when_database_url_is_set(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", SUPABASE)
    db = engine()
    assert db.url.drivername == "postgresql+psycopg"
    assert db.url.query["options"] == "-c search_path=undercover"
    assert isinstance(db.pool, QueuePool)
    assert (db.pool.size(), db.pool._max_overflow, db.pool._pre_ping) == (4, 0, True)
    assert location(db) == "the undercover schema on Postgres"


def test_the_settings_in_database_url_are_kept(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"{SUPABASE}?sslmode=require")
    query = engine().url.query
    assert (query["sslmode"], query["options"]) == (
        "require",
        "-c search_path=undercover",
    )


def test_sqlite_is_used_otherwise(database):
    db = engine()
    assert db.url.drivername == "sqlite"
    assert db.url.database == str(database)
    assert location(db) == "undercover.db"


@pytest.mark.parametrize("empty", [False, True])
def test_startup_seeds_a_missing_or_empty_database(database, empty):
    database.unlink()
    if empty:
        database.touch()
    with TestClient(app) as client:
        assert len(client.get("/api/claims").json()) == 25


def test_seeding_drops_the_queue_agent_s_old_to_do_table():
    db = engine()
    old = MetaData()
    Table("runs", old, Column("run_id", Text, primary_key=True))
    Table("todos", old, Column("run_id", Text, ForeignKey("runs.run_id")))
    old.create_all(db, tables=[old.tables["todos"]])
    assert inspect(db).has_table("todos")
    seed(db)
    assert not inspect(db).has_table("todos")
    assert {"runs", "run_claims"} <= set(inspect(db).get_table_names())
