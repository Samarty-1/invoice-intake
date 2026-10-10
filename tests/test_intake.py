import json
from datetime import date

import httpx
import pytest
import yaml

from invoice_intake import demo, evaluate, extract_llm, extract_rules, pipeline, validate
from invoice_intake.pdftext import pdf_text
from invoice_intake.schema import Invoice, Line, gst_rate

MASTER = [{"name": "FreshCo Produce Pte. Ltd.", "uen": "201912345K", "gst_reg_no": "201912345K",
           "bank_account": "DBS 012-345678-9"},
          {"name": "Sparkle Clean Services", "uen": "53412789B", "gst_reg_no": None, "bank_account": "DBS 072-998812-3"}]


def inv(**over) -> Invoice:
    base = dict(supplier_name="FreshCo Produce Pte. Ltd.", supplier_uen="201912345K", gst_reg_no="201912345K",
                invoice_number="FP-1", invoice_date=date(2026, 9, 10), due_date=date(2026, 10, 10),
                lines=[Line("Lemons", 10, 5.20, 52.00), Line("Basil", 2, 2.60, 5.20)],
                subtotal=57.20, gst_amount=5.15, total=62.35, bank_account="DBS 012-345678-9", source="a.pdf")
    base.update(over)
    return Invoice(**base)


def codes(i: Invoice, seen=()):
    return {x.code for x in validate.check(i, MASTER, list(seen)).issues}


# --- GST and arithmetic ---------------------------------------------------------------

def test_gst_rate_history():
    assert [gst_rate(date(y, 6, 1)) for y in (2022, 2023, 2024, 2026)] == [0.07, 0.08, 0.09, 0.09]


def test_clean_invoice_is_ready():
    c = validate.check(inv(), MASTER, [])
    assert c.issues == [] and c.status == "ready" and c.supplier["uen"] == "201912345K"


@pytest.mark.parametrize("over, code", [
    ({"subtotal": 67.20, "gst_amount": 6.05, "total": 73.25}, "LINES_DONT_ADD_UP"),
    ({"total": 70.00}, "TOTAL_DOESNT_ADD_UP"),
    ({"gst_amount": 4.58, "total": 61.78}, "GST_WRONG_RATE"),                       # 8% in 2026
    ({"lines": [Line("Lemons", 10, 5.20, 55.00)], "subtotal": 55.00, "gst_amount": 4.95, "total": 59.95}, "LINE_MATH"),
    ({"due_date": date(2026, 9, 1)}, "DUE_BEFORE_ISSUE"),
    ({"bank_account": "DBS 099-112233-4"}, "BANK_DETAILS_CHANGED"),
    ({"supplier_name": "Unknown Co", "supplier_uen": "202399999Z"}, "NEW_SUPPLIER"),
    ({"invoice_number": None}, "MISSING_FIELDS"),
])
def test_each_check(over, code):
    assert code in codes(inv(**over))


def test_2023_invoice_at_8_percent_is_fine():
    assert "GST_WRONG_RATE" not in codes(inv(invoice_date=date(2023, 5, 1), due_date=date(2023, 6, 1),
                                             gst_amount=4.58, total=61.78))


def test_gst_from_an_unregistered_supplier_is_blocked():
    i = inv(supplier_name="Sparkle Clean Services", supplier_uen="53412789B", gst_reg_no=None,
            bank_account="DBS 072-998812-3")
    c = validate.check(i, MASTER, [])
    assert "GST_WITHOUT_REGISTRATION" in {x.code for x in c.issues} and c.status == "blocked"
    ok = inv(supplier_name="Sparkle Clean Services", supplier_uen="53412789B", gst_reg_no=None, gst_amount=0.0,
             total=57.20, bank_account="DBS 072-998812-3")
    assert validate.check(ok, MASTER, []).status == "ready"


def test_duplicates():
    first = inv()
    assert "DUPLICATE" in codes(inv(source="b.pdf"), [first])
    assert "POSSIBLE_DUPLICATE" in codes(inv(invoice_number="FP-2", source="c.pdf"), [first])
    other_supplier = inv(supplier_name="Sparkle Clean Services", supplier_uen="53412789B", gst_reg_no=None,
                         gst_amount=0.0, total=57.20, bank_account="DBS 072-998812-3")
    assert "DUPLICATE" not in codes(other_supplier, [first])     # same number, different supplier


def test_supplier_matches_by_uen_even_if_name_is_written_differently():
    c = validate.check(inv(supplier_name="FRESHCO PRODUCE"), MASTER, [])
    assert c.supplier is not None and "NEW_SUPPLIER" not in {x.code for x in c.issues}


# --- extraction ---------------------------------------------------------------------------

def test_rule_parsers():
    assert extract_rules.parse_date("05 Sep 2026") == date(2026, 9, 5)
    assert extract_rules.parse_date("15/09/2026") == date(2026, 9, 15)
    assert extract_rules.parse_date("September 3, 2026") == date(2026, 9, 3)
    text = "ACME PTE LTD\nUEN: 201912345K GST Reg No: -\nInvoice No: A-9\nInvoice Date: 01/09/2026\n" \
           "Description Qty Unit Price Amount\nWidgets 2 10.00 20.00\nSubtotal 20.00\nTotal 20.00\n"
    i = extract_rules.extract(text)
    assert (i.supplier_uen, i.gst_reg_no, i.invoice_number, i.total, i.gst_amount) == ("201912345K", None, "A-9", 20.0, 0.0)
    assert i.lines == [Line("Widgets", 2.0, 10.0, 20.0)]


@pytest.fixture(scope="module")
def demo_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("demo")
    demo.generate(d)
    demo.generate_holdout(d)
    return d


def test_demo_rules_find_every_planted_problem(demo_dir):
    master = yaml.safe_load((demo_dir / "suppliers.yaml").read_text())["suppliers"]
    truth = {t["file"]: t for t in json.loads((demo_dir / "truth.json").read_text())}
    checked = pipeline.process(list((demo_dir / "invoices").glob("*.pdf")), master, pipeline.Extractor("rules"))
    for c in checked:
        assert {i.code for i in c.issues} == set(truth[c.invoice.source]["issues"]), c.invoice.source


def test_rules_do_not_generalise_to_unseen_layouts(demo_dir):
    """The honest baseline: rules written for four layouts fail on two new ones,
    which is the gap the local model closes (see the README's evaluation)."""
    truth = json.loads((demo_dir / "holdout_truth.json").read_text())
    pairs = [(extract_rules.extract(pdf_text(demo_dir / "holdout" / t["file"])), Invoice.from_dict(t["invoice"]))
             for t in truth]
    assert evaluate.score(pairs)["all_fields_right"] < 0.5


def fake_llm(reply: dict | str, status: int = 200):
    """An OpenAI-compatible server that answers every request with `reply`."""
    content = reply if isinstance(reply, str) else json.dumps(reply)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})
    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_llm_reply_is_coerced_and_sent_with_the_schema():
    client, seen = fake_llm("```json\n" + json.dumps({
        "supplier_name": "FreshCo Produce Pte. Ltd.", "supplier_uen": "201912345K", "gst_reg_no": "n/a",
        "invoice_number": "FP-1", "invoice_date": "10/09/2026", "due_date": "2026-10-10", "currency": "SGD",
        "lines": [{"description": "Lemons", "quantity": "10", "unit_price": "S$5.20", "amount": "52.00"}],
        "subtotal": "1,052.00", "gst_amount": None, "total": 1052.0, "bank_account": "DBS 012-345678-9"}) + "\n```")
    got = extract_llm.extract("invoice text", extract_llm.LLMConfig(), client)
    assert got.invoice_date == date(2026, 9, 10) and got.subtotal == 1052.0 and got.gst_reg_no is None
    assert got.gst_amount == 0.0                       # no GST line, total == subtotal
    assert got.lines[0].unit_price == 5.20
    schema = seen["body"]["response_format"]["json_schema"]["schema"]
    assert set(schema["required"]) == set(schema["properties"])    # optional fields get skipped


def test_llm_server_down_is_a_clear_error():
    def boom(request):
        raise httpx.ConnectError("refused")
    with pytest.raises(extract_llm.LLMUnavailable, match="no model server"):
        extract_llm.extract("x", extract_llm.LLMConfig(), httpx.Client(transport=httpx.MockTransport(boom)))


# --- outputs ------------------------------------------------------------------------------

def test_xero_bills_only_ready_invoices_and_gst_split_exactly():
    good, bad = validate.check(inv(), MASTER, []), validate.check(inv(total=99.0, source="x.pdf"), MASTER, [])
    rows = pipeline.xero_bills([good, bad]).strip().splitlines()
    assert len(rows) == 1 + 2                                          # header + 2 lines of the good one
    tax = sum(float(r.split(",")[9]) for r in rows[1:])
    assert tax == pytest.approx(5.15)


def test_review_html_lists_blocked_first(demo_dir):
    master = yaml.safe_load((demo_dir / "suppliers.yaml").read_text())["suppliers"]
    checked = pipeline.process(list((demo_dir / "invoices").glob("*.pdf")), master, pipeline.Extractor("rules"))
    page = pipeline.review_html(checked)
    assert page.index("blocked</span>") < page.index("ready</span>")
