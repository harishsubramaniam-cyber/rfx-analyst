# What I decided, and what I left out

## The problem I chose to solve

Extraction is not the hard part any more. A current model reads all five of
these documents — including the photograph of a rate card taken on a phone — on
the first attempt, with very little prompting effort.

The hard part is **basis**. Five suppliers priced the same thirty items five
different ways, and the differences hide inside numbers that look directly
comparable. On BX-001 alone:

| Supplier | Arrived as | Priced |
|---|---|---|
| Shakti Packaging | Spreadsheet, their own format | ₹41.81 **Nos** |
| Sri Balaji Corrugators | PDF on letterhead | ₹45.23 **INR / box** |
| Meridian Packaging | Word quotation, written as prose | ₹45.95 **per box/set** |
| Northstar Packaging | Photo of a printed rate card | **44 / box** — no currency anywhere |
| Pacific Pack Global | Email from an exporter | **USD 1.25 per kg** |

Four of those are the same thing wearing different clothes. The fifth is not
comparable at all, and a system that ranks it alongside the others is worse than
the spreadsheet it replaced, because it looks authoritative while being wrong.

So the whole design bends around one rule: **a normalised number never replaces
the original.** Every cell keeps the supplier's words, number, unit and
currency, the rule applied, the factor, and the source snippet. The buyer can
toggle the grid between *as quoted* and *made comparable*, and click any number
to see the sentence it came from.

## Judgment calls

**The co-pilot edits the request, not a transcript of it.** Every drafting turn
is a tool loop whose calls mutate the same `RfxSpec` the comparison engine
consumes. There is no "now parse the conversation into a spec" step, because
that step is exactly where a drafting assistant invents a line item nobody asked
for. And a line the co-pilot proposes is stored as **suggested**, shown as
suggested, and refused by the document renderer until a person accepts it — a
supplier must never be asked to price something no human decided to buy. The
model revising its own suggestion does not clear that flag; only a person's edit
does.

**A replenishment request should start in the warehouse, not in a buyer's
memory.** The co-pilot has three sources for line items: the buyer says it, the
buyer attaches a document it reads, or it proposes items itself. The third one
is a stand-in. What should sit there is a connection to the WMS or ERP — pull
every item below its reorder point, take the shortfall as the quantity, and
draft the request against real stock. That is how the job actually starts, and
it is the difference between a drafting toy and something a buyer runs on a
Monday morning.

That connection is not built here, and the system says so in three places
rather than one: the prompt forbids the model from implying it has read stock,
every line proposed this way is stored and displayed as **suggested**, and the
draft page carries a note naming the missing source. Wiring it up changes only
where `add_line` gets its arguments — provenance, acceptance, the document and
the comparison already behave the way they would need to.

**The request wins over the responses, when there is one.** Deriving the item
list from the replies is what makes this work on any category, and it stays as
the fallback. But it has one failure a buyer would never catch: an item everyone
forgot to quote cannot appear, because nothing in the data knows it was ever
asked for. Once a request has been drafted and sent, responses are compared
against it, and that item shows as a gap with four suppliers marked "not priced".

**An identifier beats a heuristic.** Each invitation carries one token —
`RFX-<request>-<supplier>-<checksum>` — in the subject line, the covering note
and the request document. When a reply quotes it, the supplier is *identified*;
without it the system reads a name off a letterhead and hopes, which is what the
extraction side had to do before. A mistyped token resolves to nobody rather
than to the wrong supplier. So the send step, which the brief would have let me
fake entirely, measurably improves the read step.

**Convert what reconciles; refuse what doesn't, out loud.** Northstar's
"5,600 / 100 pcs" and Pacific's "USD 12.50 per 1000 pcs" both divide cleanly and
agree with the other quotes on their lines — refusing them would be
fastidiousness, not rigour. Pacific's "USD 1.25 per kg" for a corrugated box
needs the box's weight, which appears in neither the request nor the response.
That stops as **Unresolved** and names exactly what is missing: *unit weight in
kg of one box of BX-001*. A buyer can act on that — it is one email, not an
investigation.

**Currency is converted, dated and shown.** Pacific quotes FOB Chennai in
dollars. Every converted figure carries `× 87.5 INR/USD @ <date>` beside it,
from a fixed table rather than a live feed, so the same files give the same
answer tomorrow. The rate is fixed; the date it is taken to hold on is today's,
and can be set in the sidebar or pinned in `.env`.

**Silence about currency is not the same as rupees.** Northstar's rate card
never states one. Their prices are used, on the stated assumption that they are
rupees, and every affected figure is flagged — including in a banner the buyer
cannot miss.

**Quality is scored, not gated — and candour is not punished.** My first version
was five fixed yes/no questions joined by AND. It eliminated three of five
suppliers before anyone looked at a price, on unverified self-reports, using a
capacity threshold of 50,000 units/month against a basket that needs 17,042.
Worse, it punished disclosure: Meridian said "No — 91.8%, here is our
remediation plan" and was cut, while Northstar wrote "OTD >95%: Yes" on a
photocopied rate card with nothing behind it and was not. Run that for one cycle
and every supplier learns to write Yes.

So the criteria are now derived from what the suppliers actually answered, in
their own words; each question's target is parsed from its own wording and can
be replaced with one derived from the basket; and the score is deliberately
plain arithmetic — the weight of every criterion satisfied, over the total
weight. A weighted-evidence score was the earlier design and it was worse: no
buyer could reproduce **0.97 vs 0.80** on paper, and a number nobody can
recompute is a number nobody will defend in an award meeting. So what backs an
answer up is now shown beside it — *figure given*, *certificate cited*,
*asserted only* — and left to the buyer's judgement instead of being folded
into a coefficient. Nothing eliminates anyone unless the buyer marks a criterion as a
must-have, because removing a supplier on one self-reported number is a decision
a person should take, not a default.

**"Did not answer" is still not "No".** Northstar left two questions blank.
Those score zero and are counted separately, because a blank is a one-line email
and a No is a negotiation.

**Boilerplate does not poison a whole rate card.** Northstar's sheet says "all
rates subject to confirmation". Treating that as a per-line condition would push
28 prices into review and delete the supplier from every comparison. It is
recorded as a supplier-level term. Conditions attached to a *specific number* do
downgrade their line: Pacific's unpriced plate charge, Sri Balaji's substituted
specification on BX-016, Meridian's market-linked film rate, Shakti's FX clause.

**Conditional freight is neither yes nor no.** Shakti includes delivery only
above two tonnes. Recording that as "included" would flatter them; recording it
as "extra" would penalise them. It is recorded as unstated, with the condition
shown.

**The analyst queries a database.** The obvious build is to paste the extracted
JSON into the prompt and ask the model to reason over it. At 5 × 30 lines that is
hundreds of mental arithmetic operations, and it will be quietly wrong somewhere.
Instead the model writes SQL, SQLite does the arithmetic, and every query is
shown beneath the answer.

**The award recommendation refuses three shortcuts.** Only a comparable price
may win a line. A line only one shortlisted supplier could price is marked
*uncontested* rather than counted as a competitive win. And split-versus-single
totals are computed only across the items every shortlisted supplier priced —
here 18 of 30 — because the responses cover different baskets; the size of that
basket is printed next to the saving. A minimum-lines control consolidates the
tail and reports what the consolidation costs.

**Deterministic before probabilistic.** Line matching walks exact SKU →
normalised SKU → dimensions → description similarity → model adjudication. It
survives Shakti writing the buyer's reference as "BX 004" in their own
spreadsheet, and never reaches the model rung on these five responses.

## The interesting problem is somewhere else

**Freight.** Sri Balaji includes it. Shakti includes it only above two tonnes.
Meridian, Northstar and Pacific charge it separately. *Not one of the five quoted
an amount* — and Pacific's prices are FOB Chennai, which is 350 km from the
buyer's warehouse.

Everything else in this dataset is solvable inside the response set: the unit
collisions convert, the dollars convert, the missing lines are visible. Freight
is not solvable, and it is the larger number. On a basket like this, inland
freight on corrugated packaging plausibly runs 5–15% of line value — several
times the 1.5%, 2% and 4.5% discounts the suppliers are negotiating over, and
comfortably larger than the ₹3.1 lakh the split award saves against the best
single supplier.

The system surfaces this above the grid rather than hiding it, but the real fix
is upstream: **the request should have made the basis non-optional.** The
comparison can only ever be as good as the question that was asked, and the most
valuable thing an RFx co-pilot could do is refuse to send a template that leaves
freight, currency and unit basis to the supplier's discretion.

## What I deliberately left out

- **A real mail server.** Invitations are written to `outbox/` as genuine
  RFC-822 `.eml` files with the request PDF attached — openable, forwardable,
  diffable. `SmtpChannel` implements the same interface and will send them for
  real; nothing above the channel changes. The transport is stubbed, which the
  brief allows. The artefact is not.
- **The stock connection behind a replenishment draft.** See above: the WMS
  or ERP read that should supply the item list and quantities is not built.
  Items proposed in its place are marked `suggested`, kept out of the document
  sent to suppliers, and require a person to accept them.
- **A vendor portal, and inbound mail polling.** Replies arrive by upload.
  Because each invitation carries a quote reference, an inbound integration
  would only need to route on a header — the identity problem is already solved.
- **Attachments as first-class objects.** The suppliers' certificates and test
  reports ship in `sample_data/attachments/`, and the documents that reference
  them are flagged as pointing at things we were not sent. Uploading one is
  recognised and reported as a supporting document rather than a supplier with
  no prices. But the app does not yet bind an attachment to the supplier it
  belongs to, or read a certificate's expiry date into the questionnaire.
- **Applying conditional discounts.** Shakti's slab rates, Sri Balaji's 2% and
  Meridian's 1.5% are recorded with their triggers and shown, but never folded
  into a price. They rest on future volumes nobody can confirm, and the three
  thresholds are not even on the same basis as each other.
- **Multi-round negotiation.** The tool recommends an award from one round of
  responses; it does not model a second round, or what a supplier might concede
  once shown where they lost.

## What would worry me before a real award

The comparison rests on one model call per document. Extraction confidence is
surfaced per line and per supplier, but there is no second pass and no
reconciliation between two independent reads. For a genuine multi-crore award I
would want the photographed rate card read twice and the disagreements flagged —
it scores lowest on read clarity, it is the one document with a handwritten
"confirm rates before PO" on it, and it is the one a human is least likely to
re-check by hand.
