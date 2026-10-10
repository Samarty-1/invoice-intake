"""Extraction with a local LLM over an OpenAI-compatible API (LM Studio,
Ollama, llama.cpp server, vLLM). The invoice text never leaves the machine.

The model is asked for JSON matching schema.JSON_SCHEMA (structured output
where the server supports it, plain JSON otherwise), and the reply is
coerced into an Invoice: numbers parsed, dates normalised to ISO, blanks to
None. The checks in validate.py then catch anything the model got wrong
that breaks the invoice's own arithmetic.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from .extract_rules import parse_date
from .schema import JSON_SCHEMA, Invoice, Line

SYSTEM = (
    "You extract data from supplier invoices for a bookkeeper in Singapore. Reply with JSON only, "
    "matching the schema. Copy identifiers exactly as printed (invoice numbers, UEN, GST registration "
    "number, bank account). Dates as YYYY-MM-DD. Amounts as plain numbers without currency symbols or "
    "commas. supplier_name is the company that issued the invoice, not the customer. gst_reg_no is null "
    "if the invoice says the supplier is not GST-registered. bank_account is the bank name and account "
    "number the supplier asks to be paid into. Use null for anything not on the invoice; never guess."
)


@dataclass
class LLMConfig:
    base_url: str = "http://localhost:1234/v1"
    model: str = "local-model"
    api_key: str = "not-needed"
    timeout: float = 120.0
    structured: bool = True        # send response_format json_schema


class LLMUnavailable(RuntimeError):
    pass


def _number(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d.\-]", "", str(v))
    try:
        return float(s)
    except ValueError:
        return None


def _date(v: Any) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return parse_date(str(v))


def _text(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return None if s.lower() in ("", "null", "none", "n/a", "-") else s


def coerce(d: dict[str, Any]) -> Invoice:
    lines = []
    for raw in d.get("lines") or []:
        try:
            lines.append(Line(str(raw.get("description", "")).strip(), _number(raw.get("quantity")) or 0.0,
                              _number(raw.get("unit_price")) or 0.0, _number(raw.get("amount")) or 0.0))
        except AttributeError:
            continue
    inv = Invoice(
        supplier_name=_text(d.get("supplier_name")), supplier_uen=_text(d.get("supplier_uen")),
        gst_reg_no=_text(d.get("gst_reg_no")), invoice_number=_text(d.get("invoice_number")),
        invoice_date=_date(d.get("invoice_date")), due_date=_date(d.get("due_date")),
        currency=_text(d.get("currency")) or "SGD", lines=lines,
        subtotal=_number(d.get("subtotal")), gst_amount=_number(d.get("gst_amount")), total=_number(d.get("total")),
        bank_account=_text(d.get("bank_account")), extractor="llm")
    # no GST line and the total equals the subtotal: the GST is zero, not unknown
    if inv.gst_amount is None and inv.subtotal is not None and inv.total is not None             and abs(inv.total - inv.subtotal) < 0.005:
        inv.gst_amount = 0.0
    return inv


def _first_json(text: str) -> dict[str, Any]:
    """The reply as JSON, tolerating code fences or a preamble."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def extract(text: str, cfg: LLMConfig, client: httpx.Client | None = None) -> Invoice:
    body: dict[str, Any] = {
        "model": cfg.model,
        "temperature": 0,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": f"Invoice text:\n\n{text[:12000]}"}],
    }
    if cfg.structured:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "invoice", "strict": False, "schema": JSON_SCHEMA}}
    own = client is None
    client = client or httpx.Client(timeout=cfg.timeout)
    try:
        r = client.post(f"{cfg.base_url.rstrip('/')}/chat/completions", json=body,
                        headers={"Authorization": f"Bearer {cfg.api_key}"})
    except httpx.HTTPError as e:
        raise LLMUnavailable(f"no model server at {cfg.base_url} ({e.__class__.__name__})") from e
    finally:
        if own:
            client.close()
    if r.status_code >= 400:
        raise LLMUnavailable(f"model server error {r.status_code}: {r.text[:200]}")
    content = r.json()["choices"][0]["message"]["content"]
    return coerce(_first_json(content))


def available(cfg: LLMConfig) -> bool:
    try:
        return httpx.get(f"{cfg.base_url.rstrip('/')}/models", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False
