# SnackFlow ERP: Order-to-Audit Management System for Snack Manufacturing

Internship shortlisting task, Centre for Digital Infrastructure, NIT Tiruchirappalli.
One system from a salesman's order to the auditor's monthly report, for a small South Indian snack factory.

- **Demo video (unlisted):** PASTE-YOUR-VIDEO-LINK-HERE
- **Design note:** see `DESIGN.md`

## Stack and why
- **Python 3.12 + Flask**: one language for all logic, small enough to explain line by line.
- **SQLite** (built into Python): a real relational database with foreign keys, with nothing to install.
- **HTML templates (Jinja) + CSS, no JavaScript**: pages are mobile friendly and every button is a normal form, so there is no second language to maintain.
- **fpdf2** for PDFs, **csv** and **zipfile** for exports, **pytest** for tests.

## Run it
```
python -m venv venv
venv\Scripts\activate          (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
python reset_demo.py           (creates the database with the section 5 master data)
python app.py                  (open http://127.0.0.1:5000)
python -m pytest -v            (16 tests, including the benchmark numbers)
```
`reset_demo.py` also loads five extra demo products (Mixture, Potato Chips, Mysore Pak, Palgova, Laddu) with opening stock. They are not used by the tests or the benchmark, so the section 5 numbers are unaffected.

## Test logins
| Role | Email ID | Password |
|---|---|---|
| Salesman | sales@snackflow.com | sales123 |
| Admin | admin@snackflow.com | admin123 |
| Production | prod@snackflow.com | prod123 |
| Accountant | acc@snackflow.com | acc123 |
| Owner | owner@snackflow.com | owner123 |

## What is built (against the section 6 tiers)
**Must have: all built**
- Login with 5 roles and "Remember me"; each role opens only its own pages.
- Masters for products (admin can edit price, GST and HSN), customers, suppliers, raw and packing materials, and BOM.
- Mobile-friendly order entry; admin approval with a stock check before approval.
- GST invoice as PDF: CGST + SGST inside Tamil Nadu, IGST for other states, numbering by financial year (INV/2026-27/0001).
- Production run updates raw, packing and finished-goods stock automatically through the ledger.
- Planned vs actual consumption and yield with variance flags (tolerance 3%).
- Stock summary and stock ledger with the source document of every movement.
- Sales register and stock report, exportable as CSV and PDF.

**Should have: all built**
- Purchases with a supplier master; payments, outstanding and ageing (0-30, 31-60, over 60 days).
- Cost per packet with labour and gas/power, and margin; GST summary by place of supply.
- Variance alerts on the production run report and the material variance report.
- Owner Business Summary: orders, stock, variance, cost per packet and dues.

**Extras built**
- **Order-to-Audit Trace page:** enter an order, invoice or credit note number to see the order, approval, invoice, dispatch, payments, credit note, stock ledger rows and audit entries on one timeline.
- **Audit Pack:** one button downloads all 9 reports plus the audit log as a ZIP of PDFs for the auditor.
- Credit note to cancel an invoice (stock returns through the ledger); an invoice is never deleted.
- Stock adjustment with a mandatory reason, written to the ledger and the audit log.
- Audit log of approvals, quantity edits, price changes, invoices, dispatch, payments, cancellations, adjustments and production runs.
- Reports Centre with date filters and CSV/PDF export for: sales register, GST summary, purchase register, stock summary, stock ledger, production, material variance, collections and outstanding.
- Invoice share links for WhatsApp and email.

## Benchmark results (section 5)
| Check | Expected | My result |
|---|---|---|
| Flour closing | 120 kg | 120.0 kg |
| Oil closing | 19.5 L | 19.5 L |
| Pouches closing | 306 | 306 |
| Finished goods after run | 238 | 238 |
| After Retailer A dispatch | 88 | 88 |
| Yield variance | -6%, flagged | -6.00%, flagged |
| Oil variance | +5%, flagged | +5.00%, flagged |
| Retailer A invoice | 7,500 + 187.50 + 187.50 = 7,875 | same |
| Retailer A outstanding | 3,875 | 3,875 |
| Distributor B | shortage 32, IGST | shortage 32, invoice blocked, IGST Rs 300.00 if invoiced |
| Cost per packet | my own figure | **Rs 31.14** (margin Rs 18.86, 37.71%) |

All of these are checked by `tests/test_benchmark.py`.

**Differences, explained**
- The run report also flags **cartons at -10%** (standard 10 per batch, the scenario uses 9). The scenario does not list it, but it is true to the data.
- **Pouches at -3.00%** (194 used vs 200 standard) are not flagged, because the rule flags variance *beyond* 3%.

## Costing method
- **Valuation: weighted average** of all purchases of the item, including opening stock.
  Flour: (100 kg at Rs 42 + 60 kg at Rs 45) / 160 kg. Chosen because it is simple to audit and smooths price changes.
- **Materials** = quantity used (damaged pouches included) x weighted average rate = Rs 4,055.00.
- **Overheads rule:** labour (Rs 1,200) and gas/power (Rs 600) of the run are added in full, then **divided by good packets only** (188).
- Cost per packet = (4,055 + 1,200 + 600) / 188 = **Rs 31.14**.

## Assumptions
- Seller name, seller GSTIN and customer GSTINs are made-up demo values. HSN 2106 is assumed for snacks and sweets, 2005 for potato chips.
- All finished goods carry GST 5%, as given in the scenario.
- Salesman A and Salesman B in the scenario are placed from the same salesman login.
- Audit times are stored in UTC.
- The PDF shows "Rs" instead of the rupee symbol, because the standard PDF fonts do not include it.
- Quantities are stored in base units (g, ml, pieces) and money in paise (whole numbers), so nothing drifts through rounding.
- Production runs are not edited after saving. A correction is a new entry, so the ledger stays complete.
- The Email ID on the login page is stored in the `username` column.

## Known gaps
- No offline order capture with sync (stretch goal).
- No batch numbers or expiry tracking, and no reorder alerts.
- No Tally-compatible export and no e-invoice format.
- Partial dispatch and sales returns (other than full invoice cancellation) are not supported.
- The WhatsApp and email share links open a prepared message; the PDF link works for the receiver only when the app is hosted, since the PDF needs a login.
- No hosted link; the app runs locally with the commands above.