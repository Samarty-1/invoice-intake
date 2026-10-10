"""Synthetic supplier invoices for a fictional café, as real PDFs in four
different layouts, with known problems planted in some of them.

Writes `invoices/*.pdf`, `suppliers.yaml` (the café's supplier master) and
`truth.json` (every invoice's true fields and planted problems), so the demo
can score extraction field by field and the checks problem by problem.
Every supplier, UEN and bank account here is made up.
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

import yaml
from fpdf import FPDF

from .schema import Invoice, Line, gst_rate

SUPPLIERS = [
    {"name": "FreshCo Produce Pte. Ltd.", "uen": "201912345K", "gst_reg_no": "201912345K",
     "bank_account": "DBS 012-345678-9", "layout": "classic",
     "items": [("Romaine lettuce (kg)", 6.40), ("Cherry tomatoes (box)", 12.80), ("Lemons (kg)", 5.20),
               ("Avocado (each)", 1.95), ("Fresh basil (bunch)", 2.60)]},
    {"name": "Kopi Bean Traders Pte. Ltd.", "uen": "201705678M", "gst_reg_no": "M90375678X",
     "bank_account": "OCBC 601-234567-001", "layout": "modern",
     "items": [("Espresso blend 1kg", 38.00), ("Decaf beans 1kg", 42.50), ("Oat milk 1L (case of 12)", 46.80)]},
    {"name": "PackRight Supplies LLP", "uen": "T15LL0421D", "gst_reg_no": "T15LL0421D",
     "bank_account": "UOB 451-302-998-1", "layout": "statement",
     "items": [("Paper cups 12oz (1000)", 68.00), ("Lids 12oz (1000)", 32.00), ("Kraft bags (500)", 41.50),
               ("Wooden stirrers (2000)", 18.90)]},
    {"name": "Sparkle Clean Services", "uen": "53412789B", "gst_reg_no": None,
     "bank_account": "DBS 072-998812-3", "layout": "simple",
     "items": [("Kitchen deep clean", 280.00), ("Grease trap service", 150.00), ("Pest control visit", 95.00)]},
    {"name": "Ocean Catch Seafood Pte. Ltd.", "uen": "202001122N", "gst_reg_no": "202001122N",
     "bank_account": "Maybank 04-1234567-8", "layout": "classic",
     "items": [("Salmon fillet (kg)", 32.50), ("Prawns 21/25 (kg)", 24.00), ("Barramundi (kg)", 19.80)]},
]
NEW_SUPPLIER = {"name": "QuickFix Equipment Pte. Ltd.", "uen": "202398765C", "gst_reg_no": "202398765C",
                "bank_account": "DBS 033-554433-2", "layout": "modern",
                "items": [("Espresso machine repair", 420.00), ("Group head gasket", 35.00)]}


def _money(v: float) -> str:
    return f"{v:,.2f}"


def _date(d: date, layout: str) -> str:
    return {"classic": d.strftime("%d/%m/%Y"), "modern": d.strftime("%d %b %Y"),
            "statement": d.isoformat(), "simple": d.strftime("%d %B %Y")}[layout]


def render_holdout(inv: Invoice, layout: str, path: Path) -> None:
    """Layouts written after the rule extractor, to test it (and the LLM) on
    formats neither was built around: different labels, the supplier block at
    the bottom, 'S$' amounts, US-style dates, and a reordered line table."""
    pdf = FPDF(format="A4")
    pdf.add_page()
    pdf.set_font("Helvetica", "", 10)
    if layout == "holdout_receipt":
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 9, "Billing Document", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, f"Document No. {inv.invoice_number}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, f"Date of Issue {inv.invoice_date:%B %d, %Y}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, f"Settle Before {inv.due_date:%B %d, %Y}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
        for line in inv.lines:
            pdf.cell(0, 6, f"{line.quantity:g} x {line.description} @ S$ {_money(line.unit_price)} = S$ {_money(line.amount)}",
                     new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        pdf.cell(0, 6, f"Net Amount: S$ {_money(inv.subtotal)}", new_x="LMARGIN", new_y="NEXT")
        if inv.gst_amount:
            pdf.cell(0, 6, f"Tax ({gst_rate(inv.invoice_date):.0%}): S$ {_money(inv.gst_amount)}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, f"Grand Total: S$ {_money(inv.total)}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(8)
        pdf.set_font("Helvetica", "", 8)
        gst = f"GST Regn. {inv.gst_reg_no}" if inv.gst_reg_no else "Not GST registered"
        pdf.multi_cell(0, 4, f"Issued by {inv.supplier_name}, registered in Singapore, UEN {inv.supplier_uen}. {gst}. "
                             f"Funds to {inv.bank_account}.")
    else:   # holdout_columns
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(95, 6, "Bill From")
        pdf.cell(0, 6, "Bill To", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(95, 5, inv.supplier_name)
        pdf.cell(0, 5, "Makan Lab (demo)", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(95, 5, f"Entity No {inv.supplier_uen}")
        pdf.cell(0, 5, f"Our ref {inv.invoice_number}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(95, 5, f"GST No {inv.gst_reg_no}" if inv.gst_reg_no else "")
        pdf.cell(0, 5, f"Invoiced {inv.invoice_date:%b %d, %Y}; due {inv.due_date:%b %d, %Y}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)
        for w, h in zip((95, 30, 20, 35), ("Item", "Line total", "Qty", "Rate")):
            pdf.cell(w, 7, h, border="B")
        pdf.ln()
        for line in inv.lines:
            for w, v in zip((95, 30, 20, 35), (line.description, _money(line.amount), f"{line.quantity:g}",
                                               _money(line.unit_price))):
                pdf.cell(w, 6, v)
            pdf.ln()
        pdf.ln(3)
        pdf.cell(0, 6, f"Nett {_money(inv.subtotal)}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, f"GST {_money(inv.gst_amount or 0)}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, f"Payable SGD {_money(inv.total)}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, f"Pay to: {inv.bank_account}", new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


def generate_holdout(out: Path, seed: int = 99, count: int = 12) -> dict:
    """Clean invoices (no planted problems) in the two held-out layouts."""
    rng = random.Random(seed)
    folder = out / "holdout"
    folder.mkdir(parents=True, exist_ok=True)
    truth = []
    for i in range(count):
        sup = SUPPLIERS[i % len(SUPPLIERS)]
        layout = "holdout_receipt" if i % 2 == 0 else "holdout_columns"
        inv = _invoice(rng, sup, 500 + i, date(2026, 9, 1) + timedelta(days=rng.randint(0, 28)))
        name = f"h{i:02d}_{inv.invoice_number}.pdf"
        render_holdout(inv, layout, folder / name)
        truth.append({"file": name, "layout": layout, "issues": [], "invoice": inv.to_dict()})
    (out / "holdout_truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    return {"invoices": count}


def render(inv: Invoice, layout: str, path: Path) -> None:
    pdf = FPDF(format="A4")
    pdf.add_page()
    pdf.set_auto_page_break(True, 15)
    title = "TAX INVOICE" if inv.gst_reg_no else "INVOICE"
    if layout == "classic":
        pdf.set_font("Helvetica", "B", 15)
        pdf.cell(0, 8, inv.supplier_name, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, f"UEN: {inv.supplier_uen}   GST Reg No: {inv.gst_reg_no or '-'}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for k, v in (("Invoice No:", inv.invoice_number), ("Invoice Date:", _date(inv.invoice_date, layout)),
                     ("Due Date:", _date(inv.due_date, layout)), ("Bill To:", "Makan Lab (demo), 1 Example Road")):
            pdf.cell(35, 6, k)
            pdf.cell(0, 6, v, new_x="LMARGIN", new_y="NEXT")
    elif layout == "modern":
        pdf.set_font("Helvetica", "B", 20)
        pdf.cell(0, 10, title.title(), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, f"{inv.supplier_name} | UEN {inv.supplier_uen} | GST Registration {inv.gst_reg_no or 'n/a'}",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        pdf.cell(0, 6, f"Inv #: {inv.invoice_number}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, f"Issued: {_date(inv.invoice_date, layout)}    Payment due: {_date(inv.due_date, layout)}",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, "Customer: Makan Lab (demo)", new_x="LMARGIN", new_y="NEXT")
    elif layout == "statement":
        pdf.set_font("Courier", "B", 12)
        pdf.cell(0, 7, f"{inv.supplier_name.upper()}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Courier", "", 10)
        pdf.cell(0, 5, f"Co. Reg. {inv.supplier_uen} / GST {inv.gst_reg_no or 'NOT REGISTERED'}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 5, f"{title} REF {inv.invoice_number} DATED {_date(inv.invoice_date, layout)}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 5, f"TERMS: PAYABLE BY {_date(inv.due_date, layout)}", new_x="LMARGIN", new_y="NEXT")
    else:   # simple
        pdf.set_font("Times", "B", 14)
        pdf.cell(0, 8, f"{inv.supplier_name} - {title}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Times", "", 11)
        pdf.cell(0, 6, f"Business Registration: {inv.supplier_uen}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, f"Invoice number {inv.invoice_number}, dated {_date(inv.invoice_date, layout)}",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, f"Please pay by {_date(inv.due_date, layout)}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    widths = (95, 20, 35, 35)
    pdf.set_font(pdf.font_family, "B", 10)
    for w, h in zip(widths, ("Description", "Qty", "Unit Price", "Amount")):
        pdf.cell(w, 7, h, border="B", align="L" if h == "Description" else "R")
    pdf.ln()
    pdf.set_font(pdf.font_family, "", 10)
    for line in inv.lines:
        qty = f"{line.quantity:g}"
        for w, v, a in zip(widths, (line.description, qty, _money(line.unit_price), _money(line.amount)),
                           ("L", "R", "R", "R")):
            pdf.cell(w, 6, v, align=a)
        pdf.ln()
    pdf.ln(3)
    labels = {
        "classic": ("Subtotal", f"GST {inv_rate(inv):.0%}", "Total (SGD)"),
        "modern": ("Amount before GST", f"GST @ {inv_rate(inv):.0%}", "Amount Due"),
        "statement": ("SUB-TOTAL", "GST", "TOTAL PAYABLE SGD"),
        "simple": ("Subtotal", "GST", "Total"),
    }[layout]
    rows = [(labels[0], inv.subtotal)]
    if inv.gst_amount:
        rows.append((labels[1], inv.gst_amount))
    rows.append((labels[2], inv.total))
    for label, v in rows:
        pdf.cell(150, 6, label, align="R")
        pdf.cell(35, 6, _money(v), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.set_font(pdf.font_family, "", 9)
    pay = {"classic": f"Payment by bank transfer to {inv.bank_account}",
           "modern": f"Bank details: {inv.bank_account}",
           "statement": f"REMIT TO A/C: {inv.bank_account}",
           "simple": f"Please transfer to {inv.bank_account}. Thank you for your business."}[layout]
    pdf.multi_cell(0, 5, pay)
    pdf.output(str(path))


def inv_rate(inv: Invoice) -> float:
    return round(inv.gst_amount / inv.subtotal, 2) if inv.gst_amount and inv.subtotal else 0.0


def _invoice(rng: random.Random, sup: dict, n: int, on: date) -> Invoice:
    lines = []
    for desc, price in rng.sample(sup["items"], k=rng.randint(1, len(sup["items"]))):
        qty = rng.choice([1, 2, 3, 4, 5, 6, 10, 12])
        lines.append(Line(desc, qty, price, round(qty * price, 2)))
    sub = round(sum(line.amount for line in lines), 2)
    gst = round(sub * gst_rate(on), 2) if sup["gst_reg_no"] else 0.0
    prefix = "".join(w[0] for w in sup["name"].split()[:2]).upper()
    return Invoice(sup["name"], sup["uen"], sup["gst_reg_no"], f"{prefix}-{on:%y%m}-{n:04d}", on,
                   on + timedelta(days=30), "SGD", lines, sub, gst, round(sub + gst, 2), sup["bank_account"])


def generate(out: Path, seed: int = 11, count: int = 24) -> dict:
    rng = random.Random(seed)
    folder = out / "invoices"
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.pdf"):
        old.unlink()
    docs: list[tuple[Invoice, str, list[str]]] = []
    for i in range(count):
        sup = SUPPLIERS[i % len(SUPPLIERS)]
        on = date(2026, 9, 1) + timedelta(days=rng.randint(0, 28))
        docs.append((_invoice(rng, sup, 100 + i, on), sup["layout"], []))

    def plant(i: int, code: str, change) -> None:
        inv, layout, issues = docs[i]
        change(inv)
        issues.append(code)

    # lines that don't add up to the subtotal (the subtotal was typed wrong)
    plant(0, "LINES_DONT_ADD_UP", lambda v: (setattr(v, "subtotal", round(v.subtotal + 10, 2)),
                                             setattr(v, "gst_amount", round(v.subtotal * 0.09, 2)),
                                             setattr(v, "total", round(v.subtotal + v.gst_amount, 2))))
    # GST at last year's 8% on a 2026 invoice
    plant(1, "GST_WRONG_RATE", lambda v: (setattr(v, "gst_amount", round(v.subtotal * 0.08, 2)),
                                          setattr(v, "total", round(v.subtotal + v.gst_amount, 2))))
    # GST charged by a supplier that isn't GST-registered
    plant(3, "GST_WITHOUT_REGISTRATION", lambda v: (setattr(v, "gst_amount", round(v.subtotal * 0.09, 2)),
                                                    setattr(v, "total", round(v.subtotal + v.gst_amount, 2))))
    # total that isn't subtotal + GST
    plant(7, "TOTAL_DOESNT_ADD_UP", lambda v: setattr(v, "total", round(v.total + 50, 2)))
    # same supplier, new bank account: the classic invoice-fraud signal
    plant(9, "BANK_DETAILS_CHANGED", lambda v: setattr(v, "bank_account", "DBS 099-112233-4"))
    # the same invoice sent twice
    dup_src = docs[5][0]
    dup = Invoice.from_dict(dup_src.to_dict())
    docs.append((dup, SUPPLIERS[5 % len(SUPPLIERS)]["layout"], ["DUPLICATE"]))
    # a supplier the café has never paid before
    docs.append((_invoice(rng, NEW_SUPPLIER, 1, date(2026, 9, 18)), NEW_SUPPLIER["layout"], ["NEW_SUPPLIER"]))

    truth = []
    for k, (inv, layout, issues) in enumerate(docs):
        name = f"{k:02d}_{inv.supplier_name.split()[0].lower()}_{inv.invoice_number}.pdf"
        render(inv, layout, folder / name)
        truth.append({"file": name, "layout": layout, "issues": issues, "invoice": inv.to_dict()})
    master = [{k: s[k] for k in ("name", "uen", "gst_reg_no", "bank_account")} for s in SUPPLIERS]
    (out / "suppliers.yaml").write_text(yaml.safe_dump({"suppliers": master}, sort_keys=False), encoding="utf-8")
    (out / "truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    return {"invoices": len(docs)}
