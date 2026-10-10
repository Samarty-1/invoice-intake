# invoice-intake as a product

## Who it's for

- **Small businesses that receive supplier invoices by email:** a café gets
  produce, coffee, packaging, cleaning and repairs, 50–500 invoices a month.
- **Bookkeepers and accounting firms** who key those invoices in for
  dozens of clients.

**Why they pay:**
1. **Typing time.** Every invoice is keyed into Xero or QuickBooks by
   hand.
2. **Paying the wrong amount.** Totals that don't add up, last year's GST
   rate, GST from a supplier that isn't registered (and isn't claimable),
   the same invoice paid twice.
3. **Invoice fraud.** A "supplier" email with new bank details is one of the
   most common frauds against small businesses. invoice-intake blocks any
   invoice whose pay-to account differs from the one on file.
4. **Privacy.** Many owners won't upload invoices to a cloud AI.
   invoice-intake runs on a local model, so documents never leave the
   machine.

## How it can be sold

- **Desktop or office box:** a one-off setup plus a subscription. It runs
  on the shop's PC, or on a small GPU box for a bookkeeping firm, with
  LM Studio or Ollama. "Your invoices never leave your office" is a
  selling point in itself.
- **Bookkeeper service:** per-invoice pricing. The firm runs the intake;
  blocked and review items come back to the client as a short list.
- **Hosted:** the same app behind authentication, with a private model
  endpoint, for customers who prefer it.

## What it is (and isn't yet) good for

**Ready now:**
- Text PDFs in any layout, with a local model. The rule extractor covers
  layouts it was written for.
- Every check in the README.
- A review page with blocked invoices first.
- Xero bill import for invoices that pass.
- Supplier matching by UEN.

**Not yet:**
- **Scans and photos:** a scanned PDF is reported as "no text layer".
  Vision models (Qwen-VL class) or OCR are the next step.
- **Email intake:** no forwarding address or mailbox polling yet. Files are
  uploaded or dropped into a folder.
- **Learning from corrections:** when the reviewer fixes a field, that
  isn't yet used to improve extraction for that supplier. Supplier-specific
  hints in the prompt are the cheap first step.
- **Approval workflow:** no approve or reject trail with user accounts.
- **Purchase orders:** no 3-way match against purchase orders and delivery
  notes.
- **Tax treatment:** GST checks use the standard rate by date. Zero-rated
  and exempt supplies, and foreign-currency invoices, need more rules.

## Accuracy, honestly

The numbers in the README come from **synthetic** invoices: four layouts,
plus two held-out layouts written after the rule extractor. They show how
the methods compare and that the checks work. They are not a measure of
real-world accuracy. Real supplier invoices vary far more, so a pilot on a
customer's real invoices, with every field checked by hand, is the first
thing to do before quoting accuracy to anyone.

What makes the approach safe even when extraction is imperfect: an
invoice is only marked **ready** if its own arithmetic holds:
- the lines add up to the subtotal
- the subtotal plus GST equals the total
- the GST matches the rate on the invoice date

A misread number almost always breaks one of these and sends the invoice
to review instead of to the books.

## Data and privacy

- **What invoices contain:** company data, and sometimes individuals'
  names, for example a sole proprietor.
- **Local by default:** with a local model, nothing leaves the machine.
- **Nothing stored:** the web app keeps nothing after a request.
- **Hosted version:** it would need PDPA-compliant retention and access
  control per client.
