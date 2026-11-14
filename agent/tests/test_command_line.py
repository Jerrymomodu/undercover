"""The command line, and the model and the connections it opens."""

from contextlib import nullcontext

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agent import __main__ as cli
from agent import api, harness
from agent.tests.stubs import graph_on, stub


class FakePool:
    """Stands in for psycopg's ConnectionPool, keeping how it was opened and what
    it ran."""

    opened: list["FakePool"] = []

    def __class_getitem__(cls, _):
        return cls

    def __init__(self, conninfo, **settings):
        self.conninfo, self.settings, self.statements = conninfo, settings, []
        self.opened.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def connection(self):
        return nullcontext(self)

    def execute(self, statement):
        self.statements.append(statement)


class FakeSaver:
    """Stands in for LangGraph's PostgresSaver."""

    made: list["FakeSaver"] = []

    def __init__(self, pool):
        self.pool, self.set_up = pool, False
        self.made.append(self)

    def setup(self):
        self.set_up = True


def test_the_connection_settings(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@pooler.example.com/db")
    monkeypatch.setattr(FakePool, "opened", [])
    monkeypatch.setattr(FakeSaver, "made", [])
    monkeypatch.setattr(harness, "Pool", FakePool)
    monkeypatch.setattr(harness, "PostgresSaver", FakeSaver)
    with harness.connections() as opened:
        [pool] = FakePool.opened
        assert opened is pool
        [setup] = FakeSaver.made
        assert (setup.pool, setup.set_up) == (pool, True)
        assert pool.conninfo == "postgresql://u:p@pooler.example.com/db"
        assert (pool.settings["min_size"], pool.settings["max_size"]) == (1, 4)
        assert pool.settings["timeout"] == harness.CONNECTION_WAIT_SECONDS
        kwargs = pool.settings["kwargs"]
        assert (kwargs["autocommit"], kwargs["prepare_threshold"]) == (True, 0)
        assert kwargs["row_factory"] is harness.dict_row
        assert kwargs["options"] == "-c search_path=undercover"
        assert "undercover" in repr(pool.statements[0])

        agent = harness.claim_agent(stub(), opened)
        for _ in range(2):
            agent.saver()
        first, second = FakeSaver.made[1:]
        assert first is not second
        assert first.pool is second.pool is pool


@pytest.fixture
def graph(monkeypatch):
    """Stand in for the connections, the model and the claim graph the command line
    builds, and return the graph."""
    graph = graph_on(stub())
    monkeypatch.setattr(cli, "connections", lambda: nullcontext("pool"))
    monkeypatch.setattr(cli, "model", lambda: "model")
    monkeypatch.setattr(
        cli, "claim_agent", lambda llm, pool: harness.ClaimAgent(llm, InMemorySaver)
    )
    monkeypatch.setattr(harness, "claim_graph", lambda llm, saver: graph)
    return graph


def test_command_line_works_one_claim(monkeypatch, capsys, graph):
    worked = []
    monkeypatch.setattr(cli, "work_claim", lambda *args: worked.append(args))
    cli.main(["CLM-1001"])
    assert worked == [("CLM-1001", graph, None)]

    def refuse(claim_id, claim_graph, run_id):
        raise api.Refused(409, f"Claim {claim_id} is not waiting")

    monkeypatch.setattr(cli, "work_claim", refuse)
    with pytest.raises(SystemExit) as refused:
        cli.main(["CLM-1003"])
    assert refused.value.code == 1
    assert capsys.readouterr().err == (
        "CLM-1003  not started: 409: Claim CLM-1003 is not waiting\n"
    )


def test_model_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    default = harness.model()
    assert default.model_name == "openai/gpt-6-luna"
    assert default.reasoning_effort == "low"
    assert default.request_timeout == 120
    assert default.max_retries == 5
    assert harness.chosen_model() == ("openai/gpt-6-luna", "low")
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert harness.model().model_name == "openrouter/free"
    assert harness.model().reasoning_effort is None
    assert harness.chosen_model() == ("openrouter/free", None)


def test_the_command_line_needs_a_claim(graph):
    for args in ([], ["--cap", "5"], ["CLM-1001", "CLM-1002"]):
        with pytest.raises(SystemExit) as refused:
            cli.main(args)
        assert refused.value.code == 2
