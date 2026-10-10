import io
import zipfile

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from invoice_intake import api, pipeline  # noqa: E402

api.EXTRACTOR = pipeline.Extractor("rules")          # CI has no model server
client = TestClient(api.app)


def test_demo_zip_round_trip():
    z = zipfile.ZipFile(io.BytesIO(client.get("/api/demo.zip").content))
    pdfs = [n for n in z.namelist() if n.endswith(".pdf")]
    r = client.post("/api/process", data={"suppliers": z.read("suppliers.yaml").decode()},
                    files=[("files", (n.split("/")[-1], z.read(n), "application/pdf")) for n in pdfs])
    assert r.status_code == 200, r.text
    d = r.json()
    statuses = [i["status"] for i in d["invoices"]]
    assert statuses.count("blocked") == 6 and "ready" in statuses
    assert d["xero_csv"].startswith("*ContactName")


def test_non_pdf_is_rejected():
    r = client.post("/api/process", files=[("files", ("x.pdf", b"hello", "application/pdf"))])
    assert r.status_code == 422 and "not a PDF" in r.json()["detail"]


def test_status_reports_the_extractor():
    assert client.get("/api/status").json()["extractor"] == "rules"
