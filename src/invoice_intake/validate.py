"""Checks that decide whether an invoice can go straight to the books.

Each issue has a severity: `block` (don't pay until resolved), `review`
(a person should look) or `info`. The checks use the invoice's own
arithmetic, Singapore's GST rate on the invoice date, the shop's supplier
master, and every invoice seen before.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .schema import Invoice, gst_rate

TOL = 0.011         # a cent of rounding, plus float noise


@dataclass
class Issue:
    code: str
    severity: str           # block | review | info
    detail: str
    action: str


@dataclass
class Checked:
    invoice: Invoice
    issues: list[Issue] = field(default_factory=list)
    supplier: dict | None = None        # the master record it matched

    @property
    def status(self) -> str:
        sev = {i.severity for i in self.issues}
        return "blocked" if "block" in sev else "review" if "review" in sev else "ready"


def _key(s: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _name(s: str | None) -> str:
    return _key(re.sub(r"\b(PTE|LTD|LLP|PRIVATE|LIMITED|CO|COMPANY)\b\.?", "", (s or "").upper()))


def match_supplier(inv: Invoice, master: list[dict]) -> dict | None:
    """By UEN first (it's unique and printed on every invoice), then by name."""
    if inv.supplier_uen:
        hit = next((s for s in master if _key(s.get("uen")) == _key(inv.supplier_uen)), None)
        if hit:
            return hit
    return next((s for s in master if _name(s.get("name")) == _name(inv.supplier_name) and _name(inv.supplier_name)),
                None)


def check(inv: Invoice, master: list[dict], seen: list[Invoice]) -> Checked:
    c = Checked(inv)
    add = lambda *a: c.issues.append(Issue(*a))  # noqa: E731

    missing = [f for f in ("supplier_name", "invoice_number", "invoice_date", "total") if not getattr(inv, f)]
    if missing:
        add("MISSING_FIELDS", "review", f"could not read: {', '.join(missing)}", "Fill them in from the PDF")

    # arithmetic on the invoice itself
    for ln in inv.lines:
        if ln.quantity and ln.unit_price and abs(ln.quantity * ln.unit_price - ln.amount) > max(TOL, 0.005 * ln.amount):
            add("LINE_MATH", "review", f"'{ln.description}': {ln.quantity:g} x {ln.unit_price:.2f} != {ln.amount:.2f}",
                "Ask the supplier which figure is right")
    if inv.lines and inv.subtotal is not None:
        lines_sum = round(sum(ln.amount for ln in inv.lines), 2)
        if abs(lines_sum - inv.subtotal) > TOL:
            add("LINES_DONT_ADD_UP", "block", f"lines add up to {lines_sum:.2f}, subtotal says {inv.subtotal:.2f}",
                f"Ask for a corrected invoice; you may be overcharged {inv.subtotal - lines_sum:.2f}")
    if None not in (inv.subtotal, inv.total):
        gst = inv.gst_amount or 0.0
        if abs(inv.subtotal + gst - inv.total) > TOL:
            add("TOTAL_DOESNT_ADD_UP", "block",
                f"{inv.subtotal:.2f} + GST {gst:.2f} = {inv.subtotal + gst:.2f}, total says {inv.total:.2f}",
                "Ask for a corrected invoice before paying")

    # GST
    sup = match_supplier(inv, master)
    c.supplier = sup
    registered = bool(inv.gst_reg_no) or bool(sup and sup.get("gst_reg_no"))
    if inv.gst_amount and inv.gst_amount > 0:
        if not registered:
            add("GST_WITHOUT_REGISTRATION", "block",
                f"{inv.gst_amount:.2f} GST charged, but no GST registration number on the invoice or on file",
                "Only GST-registered businesses may charge GST: check the supplier on IRAS's GST register")
        elif inv.invoice_date and inv.subtotal:
            rate = gst_rate(inv.invoice_date)
            expected = round(inv.subtotal * rate, 2)
            if abs(inv.gst_amount - expected) > 0.02:
                implied = inv.gst_amount / inv.subtotal
                add("GST_WRONG_RATE", "block",
                    f"GST {inv.gst_amount:.2f} is {implied:.1%} of {inv.subtotal:.2f}; the rate on "
                    f"{inv.invoice_date} is {rate:.0%} ({expected:.2f})",
                    "Ask for a corrected tax invoice; you can only claim the correct GST")
    if inv.gst_amount and inv.gst_amount > 0 and not inv.gst_reg_no and registered:
        add("GST_NO_MISSING", "review", "GST charged but the tax invoice doesn't show the GST registration number",
            "A valid tax invoice must show it; ask for one if you'll claim this GST")

    # the supplier
    if sup is None:
        add("NEW_SUPPLIER", "review", f"'{inv.supplier_name}' (UEN {inv.supplier_uen or 'not shown'}) isn't in your supplier list",
            "Confirm you ordered from them, then add them to the supplier list")
    else:
        if sup.get("bank_account") and inv.bank_account and _key(sup["bank_account"]) != _key(inv.bank_account):
            add("BANK_DETAILS_CHANGED", "block",
                f"pay-to account {inv.bank_account} differs from {sup['bank_account']} on file",
                "Possible invoice fraud: confirm by phone, on a number from your own records, before paying")
        if inv.supplier_uen and sup.get("uen") and _key(sup["uen"]) != _key(inv.supplier_uen):
            add("UEN_MISMATCH", "review", f"UEN {inv.supplier_uen} differs from {sup['uen']} on file",
                "Check it's the same company")

    # duplicates
    who = _key(sup["uen"]) if sup else _name(inv.supplier_name)
    for prev in seen:
        prev_sup = match_supplier(prev, master)
        prev_who = _key(prev_sup["uen"]) if prev_sup else _name(prev.supplier_name)
        if prev_who != who:
            continue
        if inv.invoice_number and _key(prev.invoice_number) == _key(inv.invoice_number):
            add("DUPLICATE", "block", f"invoice {inv.invoice_number} was already received ({prev.source})",
                "Don't pay it twice; reject the copy")
            break
        if (prev.total, prev.invoice_date) == (inv.total, inv.invoice_date) and inv.total:
            add("POSSIBLE_DUPLICATE", "review",
                f"same supplier, date and total ({inv.total:.2f}) as {prev.source}, different number",
                "Check it isn't the same delivery invoiced twice")
            break

    if inv.invoice_date and inv.due_date and inv.due_date < inv.invoice_date:
        add("DUE_BEFORE_ISSUE", "review", f"due {inv.due_date}, issued {inv.invoice_date}", "Check the dates")
    return c


def check_batch(invoices: list[Invoice], master: list[dict], history: list[Invoice] | None = None) -> list[Checked]:
    """Check invoices in order; each is compared with history and the ones before it."""
    seen = list(history or [])
    out = []
    for inv in invoices:
        out.append(check(inv, master, seen))
        seen.append(inv)
    return out
