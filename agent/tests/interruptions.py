"""Stopping and breaking the agent partway, as a crash, a restart or a lost connection
would. KeyboardInterrupt stands in for a crash: the harness doesn't catch it, so the
claim is left as a crash leaves it."""

import pytest

from agent import api, harness
from agent.tests.stubs import graph_on, stub


def stop_while_working(claim_id, saver, *replies):
    """Work a claim until the agent is stopped after the replies given."""
    with pytest.raises(KeyboardInterrupt):
        harness.work_claim(
            claim_id, graph_on(stub(*replies, KeyboardInterrupt()), saver), None
        )


def fail_once(monkeypatch, module, name, error, carry_out=False):
    """Make the next call to a function raise an error, once it has been carried out
    if asked, as a crash or a lost connection at that moment would."""
    function = getattr(module, name)

    def then_fail(*args):
        monkeypatch.setattr(module, name, function)
        if carry_out:
            function(*args)
        raise error

    monkeypatch.setattr(module, name, then_fail)


def calls_to(monkeypatch, name):
    """Count the calls to one of the backend's operations."""
    calls = []
    function = getattr(api, name)

    def count(*args):
        calls.append(args)
        return function(*args)

    monkeypatch.setattr(api, name, count)
    return calls
