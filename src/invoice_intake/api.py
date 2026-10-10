"""HTTP API and web app. Uploaded PDFs live in a temporary directory for the
request only; with a local model, nothing leaves the machine.

    GET  /                  the app
    GET  /api/status        which extractor is active
    GET  /api/demo.zip      demo invoices + supplier list, to try the app with
    POST /api/process       multipart: files[] (PDF), suppliers (YAML text, optional)
"""
from __future__ import annotations

import io
import os
import tempfile
import zipfile
from importlib import resources
from pathlib import Path

import yaml
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response

from . import demo, extract_llm, pipeline

MAX_FILE = 15 * 1024 * 1024
app = FastAPI(title="invoice-intake", version="0.1.0")
EXTRACTOR = pipeline.Extractor(
    os.environ.get("INVOICE_INTAKE_EXTRACTOR", "auto"),
    extract_llm.LLMConfig(base_url=os.environ.get("INVOICE_INTAKE_LLM_URL", "http://localhost:1234/v1"),
                          model=os.environ.get("INVOICE_INTAKE_MODEL", "local-model")))


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return resources.files("invoice_intake").joinpath("static/index.html").read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/status")
def status() -> dict:
    return {"extractor": EXTRACTOR.resolve(), "model": EXTRACTOR.llm.model if EXTRACTOR.llm else None}


@app.get("/api/demo.zip")
def demo_zip() -> Response:
    with tempfile.TemporaryDirectory() as tmp:
        demo.generate(Path(tmp))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(Path(tmp) / "suppliers.yaml", "suppliers.yaml")
            for f in sorted((Path(tmp) / "invoices").glob("*.pdf")):
                z.write(f, f"invoices/{f.name}")
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": "attachment; filename=invoice-intake-demo.zip"})


@app.post("/api/process")
async def process(files: list[UploadFile] = File(...), suppliers: str = Form("")) -> dict:
    try:
        master = (yaml.safe_load(suppliers) or {}).get("suppliers", []) if suppliers.strip() else []
    except (yaml.YAMLError, AttributeError) as e:
        raise HTTPException(422, f"supplier list: {e}") from e
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for f in files:
            data = await f.read(MAX_FILE + 1)
            if len(data) > MAX_FILE:
                raise HTTPException(413, f"{f.filename}: larger than 15 MB")
            if not data.startswith(b"%PDF"):
                raise HTTPException(422, f"{f.filename}: not a PDF")
            p = Path(tmp) / Path(f.filename or "invoice.pdf").name
            p.write_bytes(data)
            paths.append(p)
        try:
            checked = pipeline.process(paths, master, EXTRACTOR)
        except extract_llm.LLMUnavailable as e:
            raise HTTPException(503, str(e)) from e
    return {
        "extractor": EXTRACTOR.resolve(),
        "invoices": [{**c.invoice.to_dict(), "status": c.status, "issues": [i.__dict__ for i in c.issues]}
                     for c in checked],
        "review_html": pipeline.review_html(checked),
        "xero_csv": pipeline.xero_bills(checked),
    }
