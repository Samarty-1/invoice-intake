# invoice-intake

**Supplier invoices in; checked, bookable data out, on a local model, so
invoices never leave the machine.** It catches what costs small businesses
money before they pay:
- GST at the wrong rate
- GST from a supplier that isn't registered
- totals that don't add up
- the same invoice twice
- a "supplier" asking to be paid into a new bank account

```
PDF → text → extract (local LLM, or rules) → check → ready / review / blocked → Xero bills CSV
```

| Check | Catches | Severity |
|---|---|---|
| Lines vs subtotal, subtotal + GST vs total, qty × price | Arithmetic errors, often in the supplier's favour | block / review |
| GST at the rate in force on the invoice date (7% → 8% in 2023 → 9% from 2024) | Last year's rate, rounding games | block |
| GST charged without a GST registration (on the invoice or on file) | GST you can't claim and shouldn't pay | block |
| Pay-to account vs the supplier master | **Invoice fraud**: new bank details | block |
| Supplier matched by UEN, then name | New suppliers, UEN mismatches | review |
| Same supplier + invoice number; same supplier + date + total | Duplicates and likely duplicates | block / review |
| Missing fields, due date before issue date, no text layer (scans) | Things a person must look at | review |

An invoice is **ready** only if nothing blocks it. Its own arithmetic has
to hold, so a misread number nearly always sends it to review instead of to
the books. Ready invoices go out as a Xero bill-import CSV, with GST split
across the lines to the cent.

## Try it

```bash
pip install -e ".[api,demo]"
invoice-intake --extractor rules demo --holdout
```

The demo renders 26 synthetic supplier invoices as real PDFs:
- **Suppliers:** five fictional ones, in four different layouts, plus a
  supplier the café has never used.
- **Supplier master:** a list of the café's known suppliers.
- **Planted problems, one of each kind:** lines that don't add up, GST at
  8% in 2026, GST from an unregistered supplier, a total that doesn't add
  up, changed bank details, a duplicate, a new supplier.

With a local model (LM Studio or Ollama, any OpenAI-compatible server):

```bash
invoice-intake --extractor llm --model gemma-4-12b-it-qat demo --holdout
invoice-intake process inbox/ --suppliers suppliers.yaml --out intake/    # your invoices
invoice-intake serve                                                       # web app
```

## Evaluation, and why there are two extractors

The **rule extractor** (label synonyms, Singapore UEN and GST-number
patterns, several date formats) is fast, free and explainable. It scores
100% on the four demo layouts, which proves nothing, because it was written
against them. So the demo has a **held-out set**: two layouts written
*after* the rules. They use different labels, put the supplier block at the
bottom, write amounts as "S$", use US-style dates and reorder the line
table.

| Synthetic invoices, every scored field right | Demo layouts (26) | Held-out layouts (12) | Planted problems found | False alarms |
|---|---|---|---|---|
| Rule extractor | 100% | **0%** | 7 / 7 | 0 |
| Local LLM: gemma-4-12b-it (QAT, ~7 GB), RTX 4070 | 100% | **100%** | 7 / 7 | 0 |

The local model costs about 33 s per invoice on an RTX 4070, against
milliseconds for rules. That's fine for a batch run overnight; a smaller
model would be faster. Getting the model to 100% took two fixes, both found
on the held-out set:

1. **Required fields.** With structured output, any field the schema didn't
   mark required was one the model left out. UEN, GST number and due date
   came back empty on every held-out invoice. Every field is now required
   but allowed to be null. A test pins this.
2. **No GST line.** On a non-GST invoice the model returned no GST amount
   rather than zero. A missing GST line when the total equals the subtotal
   now means zero, which is a rule about invoices, not a patch for one test.

**These are synthetic invoices.** The numbers show that the checks work and
how the extractors compare. They don't measure real-world accuracy, which
needs a pilot on real supplier invoices: see [docs/PRODUCT.md](docs/PRODUCT.md).

## Supplier master

```yaml
suppliers:
  - {name: FreshCo Produce Pte. Ltd., uen: 201912345K, gst_reg_no: 201912345K, bank_account: DBS 012-345678-9}
  - {name: Sparkle Clean Services, uen: 53412789B, gst_reg_no: null, bank_account: DBS 072-998812-3}
```

It's optional, but it's what catches changed bank details and GST from
unregistered suppliers, so keep it current.

## Tests

```bash
pip install -e ".[dev]" && pytest
```

There are 24 tests, and none need a model:
- The GST rate history, and every check in isolation, including an 8%
  invoice that is fine in 2023 and wrong in 2026.
- Duplicates within a supplier but not across suppliers, and matching a
  supplier by UEN when the name is written differently.
- Rule parsing.
- The demo finds every planted problem and nothing else.
- The rules fail on held-out layouts. That's the honest baseline, and it's
  asserted.
- The LLM path runs against a mock OpenAI-compatible server: code fences,
  "S$5.20", day-first dates, "n/a", the required-fields schema, and a clear
  error when no server is running.
- The Xero CSV includes only ready invoices, with GST split exactly; the
  review page lists blocked invoices first; the web API rejects non-PDFs.

CI runs the tests on Linux and Windows and checks that the Docker image
serves the app. The app falls back to rules when no model server is
reachable.
