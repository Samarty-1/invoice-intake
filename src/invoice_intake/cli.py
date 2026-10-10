"""invoice-intake command line.

    invoice-intake demo                         synthetic invoices: extract, check, score
    invoice-intake process invoices/ --suppliers suppliers.yaml --out out/
    invoice-intake serve                        web app on http://127.0.0.1:8000

Extraction uses a local model when one is running (LM Studio / Ollama, any
OpenAI-compatible server: --llm-url, --model), otherwise the rule extractor.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import demo, evaluate, extract_llm, pipeline
from .schema import Invoice


def _extractor(a) -> pipeline.Extractor:
    return pipeline.Extractor(a.extractor, extract_llm.LLMConfig(base_url=a.llm_url, model=a.model))


def _show(checked) -> None:
    for c in checked:
        inv = c.invoice
        print(f"{c.status:<8} {inv.source:<40} {inv.supplier_name or '?':<30} {inv.total if inv.total is not None else '?':>10}")
        for i in c.issues:
            print(f"           {i.severity:<6} {i.code}: {i.detail}")


def _score(checked, truth: list[dict]) -> dict:
    by_file = {t["file"]: t for t in truth}
    ext = evaluate.score([(c.invoice, Invoice.from_dict(by_file[c.invoice.source]["invoice"])) for c in checked])
    found = missed = extra = 0
    for c in checked:
        want, got = set(by_file[c.invoice.source]["issues"]), {i.code for i in c.issues}
        found += len(want & got)
        missed += len(want - got)
        extra += len(got - want)
    return {"extraction": ext, "problems": {"planted": found + missed, "found": found, "false_alarms": extra}}


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="invoice-intake", description="Supplier invoices to checked, bookable data")
    ap.add_argument("--extractor", choices=["auto", "llm", "rules"], default="auto")
    ap.add_argument("--llm-url", default="http://localhost:1234/v1")
    ap.add_argument("--model", default="local-model")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="synthetic invoices with planted problems: extract, check, score")
    d.add_argument("--out", type=Path, default=Path("demo-data"))
    d.add_argument("--holdout", action="store_true", help="also score two layouts the rules were not written for")
    p = sub.add_parser("process", help="process a folder of PDF invoices")
    p.add_argument("folder", type=Path)
    p.add_argument("--suppliers", type=Path, help="supplier master (YAML: suppliers: [{name, uen, gst_reg_no, bank_account}])")
    p.add_argument("--out", type=Path, default=Path("intake"))
    s = sub.add_parser("serve", help="run the web app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("invoice_intake.api:app", host=a.host, port=a.port)
        return 0
    ext = _extractor(a)
    if a.cmd == "demo":
        demo.generate(a.out)
        master = yaml.safe_load((a.out / "suppliers.yaml").read_text(encoding="utf-8"))["suppliers"]
        print(f"extractor: {ext.resolve()}")
        checked = pipeline.process(list((a.out / "invoices").glob("*.pdf")), master, ext)
        _show(checked)
        sc = _score(checked, json.loads((a.out / "truth.json").read_text(encoding="utf-8")))
        print(f"\nextraction: {sc['extraction']['all_fields_right']:.0%} of invoices with every field right")
        print(f"problems: found {sc['problems']['found']}/{sc['problems']['planted']}, "
              f"false alarms {sc['problems']['false_alarms']}")
        if a.holdout:
            demo.generate_holdout(a.out)
            held = pipeline.process(list((a.out / "holdout").glob("*.pdf")), master, ext)
            hs = _score(held, json.loads((a.out / "holdout_truth.json").read_text(encoding="utf-8")))
            print(f"held-out layouts: {hs['extraction']['all_fields_right']:.0%} of invoices with every field right "
                  f"({ext.resolve()})")
        return 0 if sc["problems"]["found"] == sc["problems"]["planted"] else 1
    if a.cmd == "process":
        master = yaml.safe_load(a.suppliers.read_text(encoding="utf-8"))["suppliers"] if a.suppliers else []
        pdfs = list(a.folder.glob("*.pdf"))
        if not pdfs:
            print(f"error: no PDFs in {a.folder}", file=sys.stderr)
            return 2
        checked = pipeline.process(pdfs, master, ext)
        _show(checked)
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "review.html").write_text(pipeline.review_html(checked), encoding="utf-8")
        (a.out / "xero_bills.csv").write_text(pipeline.xero_bills(checked), encoding="utf-8")
        (a.out / "invoices.json").write_text(json.dumps(
            [{**c.invoice.to_dict(), "status": c.status, "issues": [i.__dict__ for i in c.issues]} for c in checked],
            indent=1), encoding="utf-8")
        print(f"\nwrote {a.out}/review.html, xero_bills.csv (ready invoices only), invoices.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
