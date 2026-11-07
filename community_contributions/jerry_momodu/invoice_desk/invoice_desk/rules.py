"""The checks, the triage that settles clear-cut invoices, and the model's guard."""

from datetime import date
from typing import Any

from invoice_desk.db import pounds
from invoice_desk.models import (
    Case,
    Decision,
    Finding,
    Outcome,
    Severity,
    Status,
    Verdict,
)

AUTO_APPROVE_LIMIT = 500_000
AGENT_LIMIT = 2_500_000
PRICE_TOLERANCE = 0.02
BANK_CHANGE_DAYS = 30
CONFIDENCE_FLOOR = 0.8
DECISIONS: dict[Decision, Status] = {
    "approve": "approved",
    "reject": "rejected",
    "escalate": "for_review",
}
RULED: tuple[tuple[Severity, Status], ...] = (
    ("block", "rejected"),
    ("review", "for_review"),
)


def run_checks(case: Case) -> list[Finding]:
    """Run every deterministic check on an invoice."""
    return [
        *vendor_checks(case),
        *document_checks(case),
        *match_checks(case),
        *amount_checks(case),
    ]


def vendor_checks(case: Case) -> list[Finding]:
    """The vendor exists, isn't blocked, and is paid to a settled account."""
    vendor, invoice = case.vendor, case.invoice
    if vendor is None:
        return [Finding("vendor_unknown", "block", "The vendor is not on record")]
    findings = []
    if vendor["status"] == "blocked":
        findings.append(
            Finding("vendor_blocked", "block", f"{vendor['name']} is blocked")
        )
    if invoice["bank_account"] != vendor["bank_account"]:
        findings.append(
            Finding(
                "bank_mismatch",
                "review",
                "The invoice's bank account differs from the vendor's record",
            )
        )
    if changed := vendor["bank_changed_on"]:
        days = (
            date.fromisoformat(invoice["invoice_date"]) - date.fromisoformat(changed)
        ).days
        if 0 <= days <= BANK_CHANGE_DAYS:
            findings.append(
                Finding(
                    "bank_recently_changed",
                    "review",
                    f"The vendor's bank account changed {days} days before the invoice",
                )
            )
    return findings


def document_checks(case: Case) -> list[Finding]:
    """The invoice isn't a duplicate and its lines add up."""
    invoice, findings = case.invoice, []
    if case.duplicate_of:
        findings.append(
            Finding(
                "duplicate",
                "block",
                f"Same vendor and invoice number as {case.duplicate_of}",
            )
        )
    lines_total = sum(line["qty"] * line["unit_pence"] for line in invoice["lines"])
    if lines_total != invoice["total_pence"]:
        findings.append(
            Finding(
                "arithmetic",
                "block",
                f"Lines add up to {pounds(lines_total)}, total says "
                f"{pounds(invoice['total_pence'])}",
            )
        )
    return findings


def match_checks(case: Case) -> list[Finding]:
    """The three-way match of invoice, purchase order and goods received note."""
    invoice, po = case.invoice, case.po
    if invoice["po_number"] is None:
        return [Finding("no_po", "flag", "The invoice has no PO")]
    if po is None:
        return [
            Finding("po_unknown", "block", f"{invoice['po_number']} is not on record")
        ]
    if po["vendor_id"] != invoice["vendor_id"]:
        return [
            Finding("po_vendor", "block", f"{po['po_number']} is for another vendor")
        ]
    findings = []
    if case.receipt is None:
        findings.append(Finding("not_received", "flag", "No goods have been received"))
    received = {
        line["sku"]: line["qty"] for line in (case.receipt or {"lines": []})["lines"]
    }
    ordered = {line["sku"]: line for line in po["lines"]}
    for line in invoice["lines"]:
        findings.extend(line_checks(line, ordered.get(line["sku"]), received))
    return findings


def line_checks(
    line: dict[str, Any], ordered: dict[str, Any] | None, received: dict[str, int]
) -> list[Finding]:
    """One invoice line against its PO line and the quantity received."""
    if ordered is None:
        return [
            Finding(
                "line_unmatched",
                "flag",
                f"'{line['description']}' has no PO line with the same SKU",
            )
        ]
    findings = []
    variance = line["unit_pence"] / ordered["unit_pence"] - 1
    if variance > PRICE_TOLERANCE:
        findings.append(
            Finding(
                "price_variance",
                "flag",
                f"{line['sku']} is {variance:.1%} above the PO price",
            )
        )
    got = received.get(line["sku"], 0)
    if line["qty"] > got:
        findings.append(
            Finding(
                "qty_over_received",
                "flag",
                f"{line['sku']}: {line['qty']} invoiced, {got} received",
            )
        )
    return findings


def amount_checks(case: Case) -> list[Finding]:
    """The total against the approval limits."""
    total = case.invoice["total_pence"]
    if total > AGENT_LIMIT:
        return [
            Finding(
                "over_agent_limit",
                "review",
                f"{pounds(total)} is above the agent's {pounds(AGENT_LIMIT)} limit",
            )
        ]
    if total > AUTO_APPROVE_LIMIT:
        return [
            Finding(
                "over_auto_limit",
                "flag",
                f"{pounds(total)} is above the auto-approve limit of "
                f"{pounds(AUTO_APPROVE_LIMIT)}",
            )
        ]
    return []


def triage(findings: list[Finding]) -> Outcome | None:
    """Settle an invoice by rule when the checks are clear-cut; None means the model."""
    for severity, status in RULED:
        hits = [f.detail for f in findings if f.severity == severity]
        if hits:
            return Outcome(status, "rules", "; ".join(hits))
    if not findings:
        return Outcome("approved", "rules", "Clean three-way match within the limit")
    return None


def enforce(verdict: Verdict, total_pence: int) -> Outcome:
    """Apply the limits the model can't override to its verdict."""
    if total_pence > AGENT_LIMIT:
        return Outcome("for_review", "guard", "Above the agent's approval limit")
    if verdict.confidence < CONFIDENCE_FLOOR:
        return Outcome(
            "for_review",
            "guard",
            f"The model was unsure ({verdict.confidence:.2f}): {verdict.reasons}",
        )
    return Outcome(DECISIONS[verdict.decision], "model", verdict.reasons)
