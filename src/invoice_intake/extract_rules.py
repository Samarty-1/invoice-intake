"""A rule-based extractor: label synonyms and patterns, no model.

Fast, free and explainable, and it works well on layouts its patterns were
written for. It is the fallback when no local model is running, and the
baseline the LLM extractor has to beat on layouts it has never seen.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from .schema import Invoice, Line

AMOUNT = r"(?:S\$|SGD|\$)?\s*(-?[\d,]+\.\d{2})"
UEN = r"\b(\d{8}[A-Z]|\d{9}[A-Z]|[STR]\d{2}[A-Z]{2}\d{4}[A-Z])\b"
GST_NO = r"\b([A-Z]\d{8}[A-Z]|\d{8,9}[A-Z]|[STR]\d{2}[A-Z]{2}\d{4}[A-Z])\b"
BANKS = r"(DBS|POSB|OCBC|UOB|Maybank|HSBC|Standard Chartered|Citibank|CIMB|RHB|Bank of China)"
DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d.%m.%Y", "%b %d, %Y", "%B %d, %Y"]
DATE = r"(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}-\d{1,2}-\d{4}|\d{1,2}\.\d{1,2}\.\d{4}|" \
       r"\d{1,2} [A-Z][a-z]+ \d{4}|[A-Z][a-z]+ \d{1,2}, \d{4})"

LABELS = {
    "invoice_number": [r"invoice\s*no\.?:?", r"inv\s*#:?", r"invoice\s*number:?", r"\bref\b", r"invoice\s*#:?"],
    "invoice_date": [r"invoice\s*date:?", r"issued:?", r"dated", r"\bdate:?"],
    "due_date": [r"due\s*date:?", r"payment\s*due:?", r"payable\s*by", r"pay\s*by", r"due:?"],
    "uen": [r"\buen\b:?", r"co\.?\s*reg\.?", r"business\s*registration:?", r"company\s*reg(?:istration)?\s*no\.?:?"],
    "gst_reg_no": [r"gst\s*reg(?:istration)?\s*(?:no\.?)?:?", r"\bgst\b\s+(?=[A-Z0-9]{9,10}\b)"],
}
TOTALS = {
    "subtotal": r"^(?:sub-?\s?total|amount before gst|total before gst|net amount)\b",
    "gst_amount": r"^(?:gst|tax|add:?\s*gst)\b",
    "total": r"^(?:total|amount due|grand total|total payable|balance due)\b",
}
NO_GST = re.compile(r"gst\s*(?:reg(?:istration)?\s*(?:no\.?)?)?:?\s*(?:-|n/?a|not registered)\b", re.I)


def parse_date(text: str) -> date | None:
    text = text.strip().rstrip(".,")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _after(text: str, labels: list[str], value: str) -> str | None:
    for lab in labels:
        m = re.search(lab + r"\s*" + value, text, re.I)
        if m:
            return m.group(1)
    return None


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def supplier_name(lines: list[str]) -> str | None:
    for line in lines[:4]:
        clean = re.sub(r"\b(tax\s+)?invoice\b", "", line, flags=re.I).strip(" -|:")
        if not clean:
            continue
        name = clean.split("|")[0].strip()
        return name or None
    return None


def extract(text: str) -> Invoice:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    inv = Invoice(extractor="rules")
    inv.supplier_name = supplier_name(lines)
    inv.supplier_uen = _after(text, LABELS["uen"], UEN)
    inv.gst_reg_no = None if NO_GST.search(text) else _after(text, LABELS["gst_reg_no"], GST_NO)
    num = _after(text, LABELS["invoice_number"], r"([A-Z0-9][A-Z0-9\-/]{2,})")
    inv.invoice_number = num.rstrip(",.") if num else None
    d = _after(text, LABELS["invoice_date"], DATE)
    inv.invoice_date = parse_date(d) if d else None
    d = _after(text, LABELS["due_date"], DATE)
    inv.due_date = parse_date(d) if d else None

    in_table = False
    for line in lines:
        low = line.lower()
        if re.match(r"^(description|item)\b.*\bamount\b", low):
            in_table = True
            continue
        if in_table:
            m = re.match(r"^(.*\S)\s+(\d+(?:\.\d+)?)\s+" + AMOUNT + r"\s+" + AMOUNT + r"$", line)
            if m:
                inv.lines.append(Line(m.group(1), float(m.group(2)), _num(m.group(3)), _num(m.group(4))))
                continue
        for field, pat in TOTALS.items():
            if re.match(pat, low):
                m = re.search(AMOUNT + r"\s*$", line)
                if m and getattr(inv, field) is None:
                    setattr(inv, field, _num(m.group(1)))
                    in_table = False
    if inv.gst_amount is None and inv.subtotal is not None and inv.total is not None:
        inv.gst_amount = round(inv.total - inv.subtotal, 2)
    m = re.search(BANKS + r"[\s:]*([\d][\d\- ]{5,}\d)", text)
    inv.bank_account = f"{m.group(1)} {m.group(2).strip()}" if m else None
    return inv
