import sqlite3

import pytest

from invoice_desk.db import decide, pay, transaction


def test_an_invoice_cannot_skip_to_paid(conn):
    with pytest.raises(sqlite3.IntegrityError, match="cannot move"):
        decide(conn, "INV-001", "paid", "test", "skip")


def test_a_decided_invoice_cannot_be_reopened(conn):
    decide(conn, "INV-001", "rejected", "test", "no")
    with pytest.raises(sqlite3.IntegrityError, match="cannot move"):
        decide(conn, "INV-001", "approved", "test", "yes")


def test_only_an_approved_invoice_can_be_paid(conn):
    with pytest.raises(sqlite3.IntegrityError, match="only an approved"):
        pay(conn, "INV-001")


def test_paying_marks_paid_and_a_second_payment_is_skipped(conn):
    with transaction(conn):
        decide(conn, "INV-001", "approved", "test", "ok")
        assert pay(conn, "INV-001")
        assert not pay(conn, "INV-001")
    assert (
        conn.execute("SELECT status FROM invoices WHERE id = 'INV-001'").fetchone()[0]
        == "paid"
    )
    assert conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1


def test_the_database_refuses_a_second_payment_of_the_same_vendor_invoice(conn):
    decide(conn, "INV-001", "approved", "test", "ok")
    pay(conn, "INV-001")
    decide(conn, "INV-003", "approved", "a buggy agent", "ok")
    with pytest.raises(sqlite3.IntegrityError, match="already been paid"):
        pay(conn, "INV-003")


def test_the_database_refuses_a_payment_to_another_account(conn):
    decide(conn, "INV-005", "approved", "test", "ok")
    with pytest.raises(sqlite3.IntegrityError, match="account on file"):
        conn.execute(
            "INSERT INTO payments (invoice_id, idempotency_key, amount_pence,"
            " bank_account, paid_at) VALUES (?, ?, ?, ?, ?)",
            ("INV-005", "k", 54000, "GB98REVO00997012345678", "now"),
        )
