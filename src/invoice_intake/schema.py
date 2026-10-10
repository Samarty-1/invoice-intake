"""What an extracted invoice looks like, and the facts the checks rely on."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


@dataclass
class Line:
    description: str
    quantity: float
    unit_price: float
    amount: float


@dataclass
class Invoice:
    supplier_name: str | None = None
    supplier_uen: str | None = None           # Singapore Unique Entity Number
    gst_reg_no: str | None = None             # blank if the supplier isn't GST-registered
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str = "SGD"
    lines: list[Line] = field(default_factory=list)
    subtotal: float | None = None
    gst_amount: float | None = None
    total: float | None = None
    bank_account: str | None = None           # where the supplier asks to be paid
    source: str | None = None                 # file it came from
    extractor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("invoice_date", "due_date"):
            d[k] = d[k].isoformat() if d[k] else None
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Invoice":
        d = dict(d)
        d["lines"] = [Line(**line) for line in d.get("lines") or []]
        for k in ("invoice_date", "due_date"):
            if d.get(k) and not isinstance(d[k], date):
                d[k] = date.fromisoformat(str(d[k])[:10])
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


# Singapore GST rate by supply date: 7% to 2022, 8% in 2023, 9% from 1 Jan 2024
GST_RATES = [(date(2024, 1, 1), 0.09), (date(2023, 1, 1), 0.08), (date(1900, 1, 1), 0.07)]


def gst_rate(on: date) -> float:
    return next(rate for start, rate in GST_RATES if on >= start)


# the fields compared when scoring an extractor against ground truth
SCORED_FIELDS = ["supplier_name", "supplier_uen", "gst_reg_no", "invoice_number", "invoice_date",
                 "due_date", "subtotal", "gst_amount", "total", "bank_account"]

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "supplier_name": {"type": ["string", "null"]},
        "supplier_uen": {"type": ["string", "null"]},
        "gst_reg_no": {"type": ["string", "null"]},
        "invoice_number": {"type": ["string", "null"]},
        "invoice_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "due_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "currency": {"type": "string"},
        "lines": {"type": "array", "items": {
            "type": "object",
            "properties": {"description": {"type": "string"}, "quantity": {"type": "number"},
                           "unit_price": {"type": "number"}, "amount": {"type": "number"}},
            "required": ["description", "quantity", "unit_price", "amount"]}},
        "subtotal": {"type": ["number", "null"]},
        "gst_amount": {"type": ["number", "null"]},
        "total": {"type": ["number", "null"]},
        "bank_account": {"type": ["string", "null"], "description": "bank name and account number to pay into"},
    },
}
# every field required (null allowed): with structured output, an optional
# field is one the model is free to leave out, and it did, every time
JSON_SCHEMA["required"] = list(JSON_SCHEMA["properties"])
