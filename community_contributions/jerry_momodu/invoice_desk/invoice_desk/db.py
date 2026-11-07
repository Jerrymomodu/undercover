"""The database: the schema, the invoice state machine and the data."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from invoice_desk.models import Case

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEFAULT_DB = ROOT / "invoice_desk.db"

SCHEMA = """
CREATE TABLE vendors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'blocked')),
    bank_account TEXT NOT NULL,
    bank_changed_on TEXT
);

CREATE TABLE purchase_orders (
    po_number TEXT PRIMARY KEY,
    vendor_id TEXT NOT NULL REFERENCES vendors (id),
    lines TEXT NOT NULL
);

CREATE TABLE receipts (
    po_number TEXT PRIMARY KEY REFERENCES purchase_orders (po_number),
    received_on TEXT NOT NULL,
    lines TEXT NOT NULL
);

CREATE TABLE invoices (
    id TEXT PRIMARY KEY,
    vendor_id TEXT NOT NULL,
    invoice_number TEXT NOT NULL,
    po_number TEXT,
    invoice_date TEXT NOT NULL,
    bank_account TEXT NOT NULL,
    lines TEXT NOT NULL,
    total_pence INTEGER NOT NULL,
    note TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'received'
        CHECK (status IN ('received', 'approved', 'rejected', 'for_review', 'paid')),
    decided_by TEXT,
    reason TEXT
);

CREATE TABLE payments (
    id INTEGER PRIMARY KEY,
    invoice_id TEXT NOT NULL UNIQUE REFERENCES invoices (id),
    idempotency_key TEXT NOT NULL UNIQUE,
    amount_pence INTEGER NOT NULL,
    bank_account TEXT NOT NULL,
    paid_at TEXT NOT NULL
);

CREATE TABLE jobs (
    invoice_id TEXT PRIMARY KEY REFERENCES invoices (id),
    stage TEXT NOT NULL DEFAULT 'checks',
    checkpoint TEXT NOT NULL DEFAULT '{}',
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_expires REAL
);

CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    invoice_id TEXT NOT NULL,
    at TEXT NOT NULL,
    actor TEXT NOT NULL,
    message TEXT NOT NULL
);

CREATE TABLE transitions (
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    PRIMARY KEY (from_status, to_status)
);

INSERT INTO transitions VALUES
    ('received', 'approved'), ('received', 'rejected'), ('received', 'for_review'),
    ('for_review', 'approved'), ('for_review', 'rejected'), ('approved', 'paid');

CREATE TRIGGER invoice_transition BEFORE UPDATE OF status ON invoices
WHEN NOT EXISTS (
    SELECT 1 FROM transitions WHERE from_status = OLD.status AND to_status = NEW.status
)
BEGIN
    SELECT RAISE(ABORT, 'an invoice cannot move between these states');
END;

CREATE TRIGGER payment_needs_approval BEFORE INSERT ON payments
WHEN (SELECT status FROM invoices WHERE id = NEW.invoice_id) IS NOT 'approved'
BEGIN
    SELECT RAISE(ABORT, 'only an approved invoice can be paid');
END;

CREATE TRIGGER payment_matches_records BEFORE INSERT ON payments
WHEN NEW.amount_pence != (SELECT total_pence FROM invoices WHERE id = NEW.invoice_id)
    OR NEW.bank_account != (
        SELECT v.bank_account FROM vendors v JOIN invoices i ON i.vendor_id = v.id
        WHERE i.id = NEW.invoice_id
    )
BEGIN
    SELECT RAISE(ABORT, 'a payment must be the invoice total, to the account on file');
END;

CREATE TRIGGER payment_not_duplicate BEFORE INSERT ON payments
WHEN EXISTS (
    SELECT 1 FROM payments p
    JOIN invoices paid ON paid.id = p.invoice_id
    JOIN invoices this ON this.id = NEW.invoice_id
    WHERE paid.vendor_id = this.vendor_id AND paid.invoice_number = this.invoice_number
)
BEGIN
    SELECT RAISE(ABORT, 'this vendor invoice number has already been paid');
END;

CREATE TRIGGER payment_marks_paid AFTER INSERT ON payments
BEGIN
    UPDATE invoices SET status = 'paid' WHERE id = NEW.invoice_id;
END;
"""


def connect(path: Path) -> sqlite3.Connection:
    """Open the database for one thread, in autocommit mode with WAL."""
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block as one write transaction, taking the write lock up front."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def now() -> str:
    """The current time, for events and payments."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def pence(pounds: float) -> int:
    """Convert pounds to whole pence."""
    return round(pounds * 100)


def pounds(amount: int) -> str:
    """Format whole pence as pounds."""
    return f"£{amount / 100:,.2f}"


def create(path: Path, data: Path = DATA) -> None:
    """Make a fresh database at path and load the data into it."""
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)
    conn = connect(path)
    conn.executescript(SCHEMA)
    with transaction(conn):
        load(conn, data)
    conn.close()


def read(data: Path, name: str) -> list[dict[str, Any]]:
    """Read one of the data files."""
    return json.loads((data / f"{name}.json").read_text(encoding="utf-8"))


def priced(lines: list[dict[str, Any]]) -> str:
    """Store lines as JSON with unit prices in pence."""
    return json.dumps(
        [
            {
                "sku": line["sku"],
                "description": line["description"],
                "qty": line["qty"],
                "unit_pence": pence(line["unit_price"]),
            }
            for line in lines
        ]
    )


def load(conn: sqlite3.Connection, data: Path) -> None:
    """Insert the vendors, POs, receipts and invoices, with a job per invoice."""
    for v in read(data, "vendors"):
        conn.execute(
            "INSERT INTO vendors VALUES (?, ?, ?, ?, ?, ?)",
            (
                v["id"],
                v["name"],
                v["category"],
                v["status"],
                v["bank_account"],
                v["bank_changed_on"],
            ),
        )
    for po in read(data, "purchase_orders"):
        conn.execute(
            "INSERT INTO purchase_orders VALUES (?, ?, ?)",
            (po["po_number"], po["vendor_id"], priced(po["lines"])),
        )
    for r in read(data, "receipts"):
        conn.execute(
            "INSERT INTO receipts VALUES (?, ?, ?)",
            (r["po_number"], r["received_on"], json.dumps(r["lines"])),
        )
    for i in read(data, "invoices"):
        conn.execute(
            "INSERT INTO invoices (id, vendor_id, invoice_number, po_number,"
            " invoice_date, bank_account, lines, total_pence, note)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                i["id"],
                i["vendor_id"],
                i["invoice_number"],
                i["po_number"],
                i["invoice_date"],
                i["bank_account"],
                priced(i["lines"]),
                pence(i["total"]),
                i["note"],
            ),
        )
        conn.execute("INSERT INTO jobs (invoice_id) VALUES (?)", (i["id"],))


def row(conn: sqlite3.Connection, sql: str, *args: Any) -> dict[str, Any] | None:
    """Return one row as a dict, decoding its lines, or None."""
    found = conn.execute(sql, args).fetchone()
    if found is None:
        return None
    result = dict(found)
    if "lines" in result:
        result["lines"] = json.loads(result["lines"])
    return result


def load_case(conn: sqlite3.Connection, invoice_id: str) -> Case:
    """Gather an invoice, its vendor, PO, receipt and any earlier duplicate."""
    invoice = row(conn, "SELECT * FROM invoices WHERE id = ?", invoice_id)
    if invoice is None:
        raise KeyError(invoice_id)
    duplicate = conn.execute(
        "SELECT id FROM invoices WHERE vendor_id = ? AND invoice_number = ? AND id < ?"
        " AND status != 'rejected' ORDER BY id LIMIT 1",
        (invoice["vendor_id"], invoice["invoice_number"], invoice_id),
    ).fetchone()
    return Case(
        invoice=invoice,
        vendor=row(conn, "SELECT * FROM vendors WHERE id = ?", invoice["vendor_id"]),
        po=row(
            conn,
            "SELECT * FROM purchase_orders WHERE po_number = ?",
            invoice["po_number"],
        ),
        receipt=row(
            conn, "SELECT * FROM receipts WHERE po_number = ?", invoice["po_number"]
        ),
        duplicate_of=duplicate["id"] if duplicate else None,
    )


def log(conn: sqlite3.Connection, invoice_id: str, actor: str, message: str) -> None:
    """Record an event on an invoice's audit trail."""
    conn.execute(
        "INSERT INTO events (invoice_id, at, actor, message) VALUES (?, ?, ?, ?)",
        (invoice_id, now(), actor, message),
    )


def pay(conn: sqlite3.Connection, invoice_id: str) -> bool:
    """Pay an approved invoice once, to the account on file. False if already paid."""
    key = f"pay-{invoice_id}"
    if conn.execute(
        "SELECT 1 FROM payments WHERE idempotency_key = ?", (key,)
    ).fetchone():
        return False
    conn.execute(
        "INSERT INTO payments (invoice_id, idempotency_key, amount_pence, bank_account,"
        " paid_at) SELECT i.id, ?, i.total_pence, v.bank_account, ? FROM invoices i"
        " JOIN vendors v ON v.id = i.vendor_id WHERE i.id = ?",
        (key, now(), invoice_id),
    )
    return True


def decide(
    conn: sqlite3.Connection, invoice_id: str, status: str, by: str, reason: str
) -> None:
    """Move an invoice to a decision; the triggers refuse a move that isn't allowed."""
    conn.execute(
        "UPDATE invoices SET status = ?, decided_by = ?, reason = ? WHERE id = ?",
        (status, by, reason, invoice_id),
    )
