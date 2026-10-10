"""Score an extractor field by field against the demo's ground truth."""
from __future__ import annotations

import re
from collections import defaultdict

from .schema import SCORED_FIELDS, Invoice


def norm(field: str, v) -> str | None:
    if v is None or v == "":
        return None
    if field in ("subtotal", "gst_amount", "total"):
        return f"{float(v):.2f}"
    if field in ("invoice_date", "due_date"):
        return str(v)[:10]
    s = str(v).upper()
    if field == "supplier_name":
        s = re.sub(r"\b(PTE|LTD|LLP|PRIVATE|LIMITED)\b", "", s)
    return re.sub(r"[^A-Z0-9]", "", s)


def score(pairs: list[tuple[Invoice, Invoice]]) -> dict:
    """pairs of (extracted, truth) -> accuracy per field, and documents fully right."""
    hits, n = defaultdict(int), len(pairs)
    perfect = 0
    for got, want in pairs:
        ok_all = True
        for f in SCORED_FIELDS:
            ok = norm(f, getattr(got, f)) == norm(f, getattr(want, f))
            hits[f] += ok
            ok_all &= ok
        lines_ok = [(round(a.amount, 2)) for a in got.lines] == [(round(b.amount, 2)) for b in want.lines]
        hits["lines"] += lines_ok
        perfect += ok_all and lines_ok
    fields = {f: round(hits[f] / n, 3) for f in SCORED_FIELDS + ["lines"]} if n else {}
    return {"documents": n, "all_fields_right": round(perfect / n, 3) if n else 0, "fields": fields}
