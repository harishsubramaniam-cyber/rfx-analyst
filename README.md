# Wexford Consumer Brands — packaging sourcing

*Corrugated packaging, sourced line by line.*

Suppliers answer an RFx in whatever format suits them — a spreadsheet, a PDF, a
Word quotation written as prose, a photograph of a printed rate card, a saved
email. This turns whatever arrives into one comparison a buyer can defend line
by line, and then lets the buyer interrogate it in plain language.

The buyer, the category and the tagline are three strings in `core/brand.py`
(overridable by environment variables). They are display text: no code in
`core/` knows what a corrugated box is, and the sample documents are addressed
from the same constants, so the fabricated dataset and the interface can never
disagree about who sent what to whom.

The flow runs end to end. A buyer **talks the request into existence** with a
co-pilot that builds it by calling tools — scope, items, questions, terms — then
**sends it** to suppliers, each invitation carrying its own quote reference.
Replies come back in any shape, are compared against the request as sent, and
the buyer interrogates the result in plain language.

Nothing is tied to a particular category, item count, supplier count, currency
or questionnaire. Where **no** request exists — someone drops five quotes on the
page and presses go — the item list is built from the responses themselves, every
item code appearing in at least one reply becoming a row. That fallback is what
makes corrugated boxes and IT hardware equally fine. Where a request **does**
exist, it wins: an item the buyer asked for and nobody quoted stays on screen as
a gap, instead of quietly ceasing to exist.

Prices with no stated currency anywhere are assumed to be **INR** (change
`RFX_BASE_CURRENCY` in `.env`) and every affected figure is flagged.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env          # add your GEMINI_API_KEY
streamlit run app.py
```

On Windows, `py -m streamlit run app.py` if `streamlit` is not on your PATH.
If you already installed an earlier version, re-run `pip install -r
requirements.txt` — `reportlab` (the request-document renderer) was added
later. Without it everything still works except the request PDF, and the app
says so rather than failing.

`app.py` is the shell — session state, sidebar, page switcher. The two pages
live in `views/`, and the engine in `core/`.

Two pages, with a switcher across the top. **Draft and send a request** is
where you talk an RFx into existence and send it. Two buttons there load a
worked request out of `examples/` without calling the model — one replenishment
draft of ten to fifteen items drawn at random, one full annual request of thirty to thirty-five with the questionnaire,
terms and the instruction that every charge must be quoted with an amount — so
a demo can start immediately and the page still works when the API is
unreachable. Every part of the draft is editable by hand across six tabs —
scope and suppliers, items, questions, notes, files, terms — so being unable to
reach the model never means being unable to change your own request. Four
things are required before anything can be sent: the open and close date and
time, the vendor category, and at least one supplier. Everything else can wait.
`examples/vendor_directory.json` holds the approved vendor list: four
categories inside packaging, three or four suppliers each, rated out of ten
from four visible scores.
`examples/PO_2025_Corrugated_Packaging.pdf` is last year's
purchase order: attach it and the items are read out of it for real, then the
questions and terms are filled in from the standing template — invitations are written to
`outbox/` as real `.eml` files with the request PDF attached, so you can open
one in any mail client. **AI-Powered Bid Analysis** is the other half, and you
can start there: drop supplier responses on and press **Analyse responses**.

Five fabricated responses ship in `sample_data/` if you want something to try — a
spreadsheet in the supplier's own house format, a PDF on letterhead with the
volume discount in eight-point type at the bottom, a Word quotation with every
rate written out as a sentence and no table anywhere in it, a phone photograph
of a printed rate card, and an exporter's saved
email (`.eml`) quoting FOB in US dollars — read as a real message, headers,
encoded body and attachments included, not as a wall of text. Their certificates and test reports are in
`sample_data/attachments/`.

Both the documents and the offline test fixtures are generated, so they cannot
drift apart:

```bash
python tests/build_sample_data.py    # rewrites the five documents
python tests/make_fixtures.py        # rewrites the fixtures, and verifies them
```

Press **Run connection check** in the sidebar first if you want to confirm which
model you are on. Model IDs are resolved from the live model list rather than
hardcoded, so a renamed model does not break the demo.

Gemini answers a busy moment with `503 UNAVAILABLE`. Every model call retries
three times with backoff and then fails over to the next acceptable model
before giving up, so a load spike costs a few seconds rather than the turn. A
rejected key is not retried — that is not going to fix itself.

## What happens to a document

```
ingest → extract → match → normalise → grid → award → analyst
```

| Stage | File | What it does |
|---|---|---|
| Ingest | `core/ingest.py` | Reads xlsx/docx/pdf/txt/csv/eml/images. An `.eml` is parsed as a message — headers, decoded body, and every attachment opened with the reader its own type deserves. Checks whether a PDF's text layer can be trusted and re-renders the pages as images when it cannot. |
| Extract | `core/extract.py` | One structured model call per document. Every line must carry the verbatim text it was read from, or it is not reported. |
| Match | `core/match.py` | Ties vendor lines to RFx lines: exact SKU → normalised SKU → dimensions → description → model adjudication. The model is the last rung, not the first. Which words distinguish one item from another is learned from the item list in hand, so it works on IT hardware or MRO spares without knowing what a corrugated box is. |
| Normalise | `core/normalize.py` | Restates prices on the buyer's unit and currency, records the factor, and refuses when no honest conversion exists. |
| Assemble | `core/assemble.py` | Builds the grid, coverage, questionnaire verdicts and the comparability warnings. |
| Store | `core/store.py` | Writes SQLite and exposes a guarded read-only query surface. |
| Criteria | `core/criteria.py` | Derives the quality criteria from the answers, parses each question's own target, and scores rather than gates. |
| Award | `core/award.py` | Recommends which supplier should get which items, and what the recommendation ignores. |
| Analyst | `core/analyst.py` | Answers questions by writing SQL against that database, then explaining the rows. |
| Draft | `core/draft.py` | The RFx co-pilot: a tool loop whose calls mutate the real `RfxSpec`. Anything it invents is marked *suggested* until a person accepts it. |
| Dispatch | `core/dispatch.py` | Channel interface, `.eml` invitations, and the quote reference that identifies a reply instead of guessing at it. |
| Request doc | `core/rfxdoc.py` | Renders the request suppliers receive, from the same object the comparison uses. |
| Present | `core/present.py` | Grid, cards, exceptions and export shaping. |
| Theme | `core/theme.py` | The visual identity — palette, type, and the HTML components. Paired with `.streamlit/config.toml`. |

## The decisions that matter

**A normalised number never replaces the original.** Every cell keeps the
vendor's words, the vendor's number, the vendor's unit, the rule applied, the
factor, and the source snippet. The grid has an *as quoted* / *normalised*
toggle, and the Evidence tab walks any number back to the page it came from.

**The system converts what it can and refuses what it cannot, out loud.**
"5,600 / 100 pcs" divides by a hundred with `÷ 100` shown beside it; an
exporter's dollars convert at `× 87.5 INR/USD @ 2026-08-30`, printed in the cell
(the rate is fixed; the date is today's, and is settable in the sidebar).
Refusing those would be useless, since they reconcile cleanly against the other
quotes on the line. But "USD 1.25 per kg" for a corrugated box needs the weight
of the box, which is in neither the request nor the response, so it stops as
**Unresolved** and names the missing datum: *unit weight in kg of one box of
BX-001*. Guessing there would poison every total on the screen invisibly.

**Quality is scored, not gated.** The criteria are derived from whatever the
suppliers answered, each question's target is parsed from its own wording (and
can be replaced with one derived from your basket), and the scoring is
arithmetic a buyer can redo on paper: add the weight of every criterion the
supplier satisfies, divide by the total weight. A bare "Yes" counts the same as
a "Yes" with a figure behind it — what backs each answer up is recorded and
shown next to it, so you can see how much of a score rests on the supplier's
word alone, but it does not move the number. Nothing eliminates a supplier
unless you mark it **Must have**.

**The analyst queries a database instead of reading pasted JSON.** Handing a
model 150 line items and asking it to rank them means asking it to do hundreds
of arithmetic operations in its head. It will get some quietly wrong, and
quietly wrong is fatal when a buyer is about to commit crores. So the model gets
`run_query`, `get_evidence` and `make_chart`; SQLite does the arithmetic; and
every query is shown under the answer so the buyer can check the working.

## Verify it

```bash
python tests/test_pipeline.py
```

146 checks, no network required. They assert the behaviour that actually matters:
that bulk pricing reconciles, that per-kg quotes refuse to convert and say what
they need, that an unanswered questionnaire item is not treated as a "No", that
coverage gaps are visible, and that the analyst's SQL surface stays read-only.

The tests replay recorded extractions from `tests/fixtures/` so the
deterministic layers can be verified without a model. **The application never
reads those fixtures** unless `RFX_OFFLINE_FIXTURES=1` is explicitly set, which
the demo does not do — every document goes through the real model at runtime.
`tests/make_fixtures.py` regenerates them from the sample files.

## What is deliberately not here

See `DECISIONS.md`. Short version: a real mail server, a vendor portal, inbound
mail polling, applied volume discounts and multi-round negotiation. The
transport is stubbed — the artefacts, the identifiers and every AI loop are
not.
