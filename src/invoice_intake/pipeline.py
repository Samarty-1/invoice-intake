"""PDF -> text -> extracted invoice -> checks -> Xero bills + a review report."""
from __future__ import annotations

import csv
import html
import io
from dataclasses import dataclass
from pathlib import Path

from . import extract_llm, extract_rules
from .pdftext import NoTextLayer, pdf_text
from .schema import Invoice, gst_rate
from .validate import Checked, Issue, check_batch


@dataclass
class Extractor:
    """'rules', 'llm', or 'auto' (the local model if one is running, else rules)."""
    mode: str = "auto"
    llm: extract_llm.LLMConfig | None = None

    def resolve(self) -> str:
        if self.mode != "auto":
            return self.mode
        return "llm" if self.llm and extract_llm.available(self.llm) else "rules"

    def __call__(self, text: str) -> Invoice:
        if self.resolve() == "llm":
            return extract_llm.extract(text, self.llm)
        return extract_rules.extract(text)


def process(paths: list[Path], master: list[dict], extractor: Extractor,
            history: list[Invoice] | None = None) -> list[Checked]:
    invoices = []
    unreadable = []
    for p in sorted(paths):
        try:
            inv = extractor(pdf_text(p))
        except NoTextLayer as e:
            inv = Invoice(extractor="none")
            unreadable.append((len(invoices), str(e)))
        inv.source = p.name
        invoices.append(inv)
    checked = check_batch(invoices, master, history)
    for i, msg in unreadable:
        checked[i].issues.insert(0, Issue("NO_TEXT", "review", msg, "Scan it to a text PDF, or enter it by hand"))
    return checked


def xero_bills(checked: list[Checked], account_code: str = "300", tax_type_gst: str = "Standard-Rated Purchases",
               tax_type_none: str = "No GST") -> str:
    """Ready invoices in Xero's bill-import columns, one row per line. The
    tax type names must match ones in your Xero organisation; GST is split
    across lines so the lines add up to the invoice's GST exactly."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["*ContactName", "*InvoiceNumber", "*InvoiceDate", "*DueDate", "Description", "*Quantity",
                "*UnitAmount", "*AccountCode", "*TaxType", "TaxAmount", "Currency"])
    for c in checked:
        if c.status != "ready":
            continue
        inv = c.invoice
        name = (c.supplier or {}).get("name") or inv.supplier_name
        lines = inv.lines or []
        gst = inv.gst_amount or 0.0
        shares = []
        if lines and gst:
            rate = gst_rate(inv.invoice_date) if inv.invoice_date else gst / (inv.subtotal or 1)
            shares = [round(ln.amount * rate, 2) for ln in lines]
            shares[-1] = round(gst - sum(shares[:-1]), 2)
        if not lines:   # no line detail: one line for the whole subtotal
            from .schema import Line
            lines = [Line("Invoice total", 1, inv.subtotal or inv.total or 0, inv.subtotal or inv.total or 0)]
            shares = [gst] if gst else []
        for k, ln in enumerate(lines):
            w.writerow([name, inv.invoice_number, inv.invoice_date.isoformat() if inv.invoice_date else "",
                        inv.due_date.isoformat() if inv.due_date else "", ln.description, f"{ln.quantity:g}",
                        f"{ln.unit_price:.2f}", account_code, tax_type_gst if gst else tax_type_none,
                        f"{shares[k]:.2f}" if shares else "0.00", inv.currency])
    return buf.getvalue()


def review_html(checked: list[Checked], title: str = "Invoice review") -> str:
    counts = {s: sum(c.status == s for c in checked) for s in ("ready", "review", "blocked")}
    money = lambda v: "—" if v is None else f"{v:,.2f}"  # noqa: E731
    rows = ""
    for c in sorted(checked, key=lambda c: ({"blocked": 0, "review": 1, "ready": 2}[c.status], c.invoice.source or "")):
        inv = c.invoice
        issues = "".join(f"<div class='{i.severity}'><b>{html.escape(i.code)}</b> {html.escape(i.detail)}"
                         f"<div class=act>→ {html.escape(i.action)}</div></div>" for i in c.issues)
        rows += (f"<tr><td><span class='pill {c.status}'>{c.status}</span></td>"
                 f"<td>{html.escape(inv.supplier_name or '?')}<div class=mut>{html.escape(inv.source or '')}</div></td>"
                 f"<td>{html.escape(inv.invoice_number or '?')}</td><td>{inv.invoice_date or '?'}</td>"
                 f"<td class=n>{money(inv.subtotal)}</td><td class=n>{money(inv.gst_amount)}</td><td class=n>{money(inv.total)}</td>"
                 f"<td>{issues or '<span class=mut>no issues</span>'}</td></tr>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title>
<style>
:root{{--bg:#fff;--fg:#1c1c1a;--mut:#6b6b66;--line:#e2e1dc;--block:#b3261e;--review:#9a6700;--ready:#1f7a4a}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--fg:#ecebe6;--mut:#9c9b95;--line:#2e2d2a;--block:#ff7b72;--review:#e3b341;--ready:#5cc48b}}}}
body{{font:14px/1.5 system-ui,sans-serif;max-width:1150px;margin:24px auto;padding:0 16px;background:var(--bg);color:var(--fg)}}
table{{border-collapse:collapse;width:100%}} th,td{{border-bottom:1px solid var(--line);padding:7px;text-align:left;vertical-align:top}}
th{{font-size:12px;color:var(--mut)}} .n{{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}}
.mut,.act{{color:var(--mut);font-size:12px}} .block b{{color:var(--block)}} .review b{{color:var(--review)}}
.pill{{border-radius:99px;padding:1px 8px;font-size:12px;font-weight:600;border:1px solid}}
.pill.blocked{{color:var(--block)}} .pill.review{{color:var(--review)}} .pill.ready{{color:var(--ready)}}
.scroll{{overflow-x:auto}}
</style></head><body><h1>{html.escape(title)}</h1>
<p><b>{counts['ready']}</b> ready to book · <b>{counts['review']}</b> to review · <b>{counts['blocked']}</b> blocked (don't pay yet)</p>
<div class=scroll><table><tr><th>Status</th><th>Supplier</th><th>Invoice</th><th>Date</th><th class=n>Subtotal</th>
<th class=n>GST</th><th class=n>Total</th><th>Issues</th></tr>{rows}</table></div>
<p class=mut>Generated by invoice-intake. GST checks use Singapore's rate on the invoice date.</p></body></html>"""
