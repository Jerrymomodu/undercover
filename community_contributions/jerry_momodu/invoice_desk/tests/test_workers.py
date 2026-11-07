import pytest
from conftest import OracleJudge

from invoice_desk.evals import report, run_evals
from invoice_desk.pipeline import LeaseLostError, advance
from invoice_desk.workers import MAX_ATTEMPTS, claim, run_workers, work


def statuses(conn) -> dict[str, str]:
    return dict(conn.execute("SELECT id, status FROM invoices").fetchall())


def test_parallel_workers_settle_every_invoice_once(db, conn, oracle):
    assert run_workers(db, 4, oracle) == 15
    assert (
        conn.execute("SELECT COUNT(*) FROM jobs WHERE stage != 'done'").fetchone()[0]
        == 0
    )
    assert sorted(oracle.calls) == sorted(set(oracle.calls))
    paid = [
        r[0]
        for r in conn.execute("SELECT invoice_id FROM payments ORDER BY invoice_id")
    ]
    assert paid == ["INV-001", "INV-002", "INV-006", "INV-009", "INV-010"]


def test_rules_settle_the_clear_cut_and_the_model_sees_only_the_rest(db, oracle):
    run_workers(db, 2, oracle)
    assert sorted(oracle.calls) == [
        "INV-002",
        "INV-007",
        "INV-008",
        "INV-009",
        "INV-010",
        "INV-011",
        "INV-014",
    ]


def test_a_crashed_worker_is_resumed_without_asking_the_model_again(db, conn, oracle):
    conn.execute("UPDATE jobs SET stage = 'done' WHERE invoice_id != 'INV-002'")
    job = claim(conn, "worker-1", at=0)
    assert job is not None
    assert job.invoice_id == "INV-002"
    stages = [advance(conn, "INV-002", "worker-1", oracle) for _ in range(3)]
    assert stages == ["route", "judge", "guard"]
    # worker-1 dies after the verdict; its lease runs out and worker-2 takes over
    assert work(db, "worker-2", oracle, clock=lambda: 1_000) == 1
    assert oracle.calls == ["INV-002"]
    assert statuses(conn)["INV-002"] == "paid"


def test_a_worker_that_lost_its_lease_cannot_save(conn, oracle):
    claim(conn, "worker-1", at=0)
    conn.execute(
        "UPDATE jobs SET lease_owner = 'worker-2' WHERE invoice_id = 'INV-001'"
    )
    with pytest.raises(LeaseLostError):
        advance(conn, "INV-001", "worker-1", oracle)


def test_an_invoice_that_keeps_failing_is_left_for_a_person(db, conn):
    def broken(case, findings):
        raise TimeoutError("model timed out")

    run_workers(db, 1, broken)
    reasons = dict(conn.execute("SELECT id, reason FROM invoices").fetchall())
    assert statuses(conn)["INV-007"] == "for_review"
    assert reasons["INV-007"] == f"Tried {MAX_ATTEMPTS} times without finishing"
    assert statuses(conn)["INV-001"] == "paid"


def test_evals_pass_with_right_answers_and_catch_a_judge_that_approves_everything(
    tmp_path,
):

    right = run_evals(OracleJudge(), 4, tmp_path / "right.db")
    assert all(r.passed for r in right)
    assert "Passed 15 of 15. Critical errors: 0." in report(right)

    def approve_all(case, findings):
        verdict, _ = OracleJudge()(case, findings)
        return verdict.model_copy(update={"decision": "approve"}), "yes-man"

    wrong = run_evals(approve_all, 4, tmp_path / "wrong.db")
    assert {r.invoice_id for r in wrong if r.critical} == {
        "INV-007",
        "INV-008",
        "INV-011",
        "INV-014",
    }
