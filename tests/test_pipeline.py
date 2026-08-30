"""Offline verification of everything that does not need a model.

Run:  python tests/test_pipeline.py

These assertions encode the behaviour the assignment is really testing: what
the system does with the ugly edges, and whether it refuses to guess.

Expected values are derived from the same cost model that writes the sample
documents, so regenerating the dataset cannot leave a stale number behind.
"""

from __future__ import annotations

import glob
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

os.environ["RFX_OFFLINE_FIXTURES"] = "1"
os.environ["RFX_FIXTURE_DIR"] = os.path.join(HERE, "fixtures")

import build_sample_data as gen  # noqa: E402
from core import assemble as assemble_module  # noqa: E402
from core import config, dispatch, pipeline, present, rfxdoc, store  # noqa: E402
from core import draft as draft_module  # noqa: E402
from core import rfx as rfx_module  # noqa: E402

config.OFFLINE_FIXTURES = True
config.FIXTURE_DIR = os.path.join(HERE, "fixtures")

SAMPLES = sorted(glob.glob(os.path.join(ROOT, "sample_data", "*.*")))

SHAKTI = "Shakti Packaging Industries Pvt Ltd"
BALAJI = "Sri Balaji Corrugators Pvt Ltd"
MERIDIAN = "Meridian Packaging LLP"
NORTHSTAR = "Northstar Packaging"
PACIFIC = "Pacific Pack Global Pvt Ltd"

PASS, FAIL = [], []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f"  -- {detail}" if detail and not condition else ""))


def close(a, b, tol=0.02) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


def main() -> int:
    db_path = os.path.join(tempfile.mkdtemp(), "test.db")
    config.DB_PATH = db_path
    result = pipeline.run_paths(SAMPLES, db_path=db_path)

    assert result.comparison is not None, "pipeline produced no comparison"
    comparison = result.comparison
    summaries = {s.vendor: s for s in comparison.summaries}

    print("\nINGESTION  (five suppliers, five formats)")
    for outcome in result.outcomes:
        check(f"{outcome.filename} read via {outcome.reader}", outcome.ok, outcome.error)
    check("all five responses were read", len(comparison.summaries) == 5)

    print("\nCOVERAGE  (a supplier that skipped items must not look complete)")
    for vendor, expected in ((SHAKTI, 28), (BALAJI, 28), (MERIDIAN, 30),
                             (NORTHSTAR, 28), (PACIFIC, 28)):
        actual = summaries[vendor].coverage_quoted
        check(f"{vendor} priced {actual}/30 (expected {expected})", actual == expected)

    check("Shakti did not price BX-005 and BX-019",
          set(summaries[SHAKTI].not_quoted) == {"BX-005", "BX-019"},
          str(summaries[SHAKTI].not_quoted))
    check("Sri Balaji did not price BX-012 and BX-025",
          set(summaries[BALAJI].not_quoted) == {"BX-012", "BX-025"},
          str(summaries[BALAJI].not_quoted))
    check("Northstar did not price BX-008 and BX-019",
          set(summaries[NORTHSTAR].not_quoted) == {"BX-008", "BX-019"},
          str(summaries[NORTHSTAR].not_quoted))
    check("Pacific did not price BX-012 and BX-024",
          set(summaries[PACIFIC].not_quoted) == {"BX-012", "BX-024"},
          str(summaries[PACIFIC].not_quoted))

    print("\nPACK MULTIPLES  (bulk pricing must reconcile, not be thrown away)")
    expected = round(gen.PRICES["northstar"]["BX-009"] * 100) / 100
    cell = comparison.cell("BX-009", NORTHSTAR)
    check("Northstar BX-009 quoted per 100 pcs normalises back to the unit rate",
          close(cell.canonical_value, expected) and cell.status == "Normalized",
          f"{cell.canonical_value} vs {expected} / {cell.status}")
    check("...and shows the division it applied",
          bool(cell.factor and "÷ 100" in cell.factor), str(cell.factor))

    cell = comparison.cell("BX-005", PACIFIC)
    expected = round(gen.PRICES["pacific"]["BX-005"] / gen.USD_INR * 1000) / 1000 \
        * config.FX_TO_BASE["USD"]
    check("Pacific BX-005 quoted per 1000 pcs converts and divides",
          cell.comparable and "÷ 1000" in (cell.factor or ""),
          f"{cell.canonical_value} / {cell.factor}")

    cell = comparison.cell("BX-029", PACIFIC)
    check("Pacific BX-029 quoted per 100 rolls converts and divides",
          cell.comparable and "÷ 100" in (cell.factor or ""),
          f"{cell.canonical_value} / {cell.factor}")

    print("\nCURRENCY  (an exporter quoting dollars must be converted, and shown)")
    cell = comparison.cell("BX-002", PACIFIC)
    check("Pacific BX-002 is read as USD", cell.original_currency == "USD",
          str(cell.original_currency))
    check("...converted into the comparison currency",
          cell.canonical_currency == "INR" and cell.comparable,
          f"{cell.canonical_currency} / {cell.status}")
    check("...at the stated, dated rate",
          bool(cell.factor and "INR/USD" in cell.factor and config.FX_DATE in cell.factor),
          str(cell.factor))
    check("...arriving at the right number",
          close(cell.canonical_value, cell.original_value * config.FX_TO_BASE["USD"], 0.05),
          f"{cell.canonical_value} vs {cell.original_value} x {config.FX_TO_BASE['USD']}")

    print("\nREFUSAL  (weight basis cannot be converted, and must not be guessed)")
    for vendor, sku in ((PACIFIC, "BX-001"), (NORTHSTAR, "BX-016")):
        cell = comparison.cell(sku, vendor)
        check(f"{vendor} {sku} priced per kg is Unresolved",
              cell.status == "Unresolved" and cell.canonical_value is None,
              f"{cell.status} / {cell.canonical_value}")
        check(f"{vendor} {sku} names the missing datum",
              bool(cell.missing_datum and "weight" in cell.missing_datum),
              str(cell.missing_datum))
        check(f"{vendor} {sku} is excluded from comparison", not cell.comparable)

    print("\nCONDITIONS  (a price with strings attached is not a comparable price)")
    for vendor, sku, flag, label in (
        (PACIFIC, "BX-009", "unquantified_adder", "an unpriced plate charge"),
        (PACIFIC, "BX-017", "conditional_price", "a reference to old contract rates"),
        (BALAJI, "BX-016", "spec_deviation", "a substituted specification"),
        (MERIDIAN, "BX-029", "conditional_price", "a market-linked rate"),
        (SHAKTI, "BX-029", "conditional_price", "an FX clause"),
    ):
        cell = comparison.cell(sku, vendor)
        check(f"{vendor.split()[0]} {sku} — {label} → Needs Review",
              cell.status == "Needs Review" and flag in cell.flags,
              f"{cell.status} / {cell.flags}")

    print("\nSILENT CURRENCY  (a rate card with no currency must say so)")
    check("Northstar is flagged as currency-assumed",
          summaries[NORTHSTAR].currency_assumed)
    cell = comparison.cell("BX-002", NORTHSTAR)
    check("...on the cell as well as the supplier", "currency_assumed" in cell.flags,
          str(cell.flags))
    check("...and the price is still usable, because the assumption is stated",
          cell.comparable)
    check("suppliers that stated a currency are not flagged",
          not summaries[SHAKTI].currency_assumed
          and not summaries[PACIFIC].currency_assumed)

    print("\nUNIT WORDING  (Nos / per box / per box/set are the same thing)")
    for vendor, key in ((SHAKTI, "shakti"), (MERIDIAN, "meridian"), (BALAJI, "balaji")):
        cell = comparison.cell("BX-003", vendor)
        check(f"{vendor.split()[0]} BX-003 = {gen.PRICES[key]['BX-003']:.2f}",
              close(cell.canonical_value, gen.PRICES[key]["BX-003"]) and cell.comparable,
              f"{cell.canonical_value} / {cell.status}")

    print("\nCONDITIONAL FREIGHT  (included above 2 tonnes is neither yes nor no)")
    check("Shakti's freight position is recorded as unstated, not as included",
          summaries[SHAKTI].freight_included is None)
    check("Sri Balaji's freight is recorded as included",
          summaries[BALAJI].freight_included is True)
    check("Meridian's freight is recorded as extra",
          summaries[MERIDIAN].freight_included is False)

    print("\nQUALITY CRITERIA  (derived from the answers, not a fixed checklist)")
    from core import criteria as criteria_module

    crits = {c.key: c for c in comparison.criteria}
    check("criteria were derived from the responses", len(crits) == 5, str(len(crits)))
    check("suppliers phrasing the same question are clustered together",
          all(len(c.variants) >= 2 for c in comparison.criteria),
          str({c.key: len(c.variants) for c in comparison.criteria}))
    check("no duplicate criteria are created",
          len(crits) == len({c.question.lower() for c in comparison.criteria}))

    from core.criteria import same_question
    for left, right, want in (
        # terse phrasings off a photographed rate card must fold in
        ("Capacity", "Monthly production capacity above 50,000 units?", True),
        ("OTD >95%", "On-time delivery performance above 95%?", True),
        ("OTIF > 95%", "On time in full delivery above 95%", True),
        ("SLA", "Able to commit to a 30-day delivery SLA?", True),
        ("Rejection rate", "Quality rejection rate below 1%?", True),
        # ...without merging things that are genuinely different
        ("ISO 9001 certified", "ISO 14001 certified", False),
        ("Warranty period 12 months", "Warranty period 24 months", False),
        ("Payment terms 30 days?", "Able to commit to a 30-day delivery SLA?", False),
        ("Are you MSME registered?", "Are you ISO 9001 certified?", False),
    ):
        check(f"{'merges' if want else 'keeps apart'}: {left!r} / {right[:34]!r}",
              same_question(left, right) is want)

    capacity_c = next(c for c in comparison.criteria if c.unit == " units/month")
    check("a numeric target is read out of the question itself",
          capacity_c.threshold == 50000, str(capacity_c.threshold))
    check("...and a better one is suggested from the actual basket",
          capacity_c.suggested_threshold is not None
          and capacity_c.suggested_threshold < capacity_c.threshold,
          str(capacity_c.suggested_threshold))

    reject = next(c for c in comparison.criteria if "rejection" in c.key)
    check("lower-is-better questions are read as such",
          reject.direction == "lower_better", reject.direction)

    print("\nSCORING  (weight x satisfied, and nothing else)")
    cards = {s.vendor: s.scorecard for s in comparison.summaries}
    otd = next(c.key for c in comparison.criteria
               if "delivery" in c.key and c.unit == "%")
    capacity = next(c for c in comparison.criteria if c.unit == " units/month")

    northstar = cards[NORTHSTAR].results[otd]
    meridian = cards[MERIDIAN].results[otd]
    shakti = cards[SHAKTI].results[otd]

    check("a bare Yes with no figure counts in full",
          northstar.answer.value is None and northstar.meets is True
          and northstar.score == 1.0,
          f"{northstar.answer.stated_text} / {northstar.score}")
    check("a stated figure that clears the target counts in full",
          shakti.answer.value == 96.4 and shakti.score == 1.0,
          f"{shakti.answer.value} / {shakti.score}")
    check("a stated figure below the target counts as not met",
          meridian.answer.value == 91.8 and meridian.meets is False
          and meridian.score == 0.0,
          f"{meridian.answer.value} / {meridian.score}")
    check("a question never answered counts as not met",
          cards[NORTHSTAR].results[capacity.key].score is not None
          and cards[NORTHSTAR].results[
              next(k for k in cards[NORTHSTAR].unanswered)].score == 0.0)
    check("evidence is still recorded, it just does not move the score",
          cards[BALAJI].results["iso_9001_certified"].answer.evidence == "documented"
          and cards[BALAJI].results["iso_9001_certified"].score == 1.0)

    print("\nSCORING IS RECOMPUTABLE BY HAND")
    for vendor, card in cards.items():
        counted = [c for c in comparison.criteria if c.requirement != "Ignore"]
        hand = (sum(c.weight for c in counted if card.results[c.key].meets)
                / sum(c.weight for c in counted))
        check(f"{vendor.split()[0]} score is weight x satisfied over total weight",
              abs(hand - card.overall) < 1e-9, f"{hand} vs {card.overall}")

    print("\nWEIGHTS AND IGNORE ACTUALLY MOVE THE SCORE")
    before = {s.vendor: s.quality_score for s in comparison.summaries}
    capacity.weight = 5.0
    assemble_module.rescore(comparison)
    check("raising a weight changes the ranking arithmetic",
          any(abs(before[v] - s.quality_score) > 1e-9
              for v, s in ((x.vendor, x) for x in comparison.summaries)))
    capacity.weight = 1.0

    capacity.requirement = "Ignore"
    assemble_module.rescore(comparison)
    counted = [c for c in comparison.criteria if c.requirement != "Ignore"]
    check("an ignored criterion drops out of the denominator",
          len(counted) == len(comparison.criteria) - 1)
    capacity.requirement = "Scored"
    assemble_module.rescore(comparison)

    print("\nTHE CRITERION LABEL CARRIES THE LIVE TARGET")
    check("a numeric criterion is stated as a test",
          "greater than" in capacity.label and "units/month" in capacity.label, capacity.label)
    original = capacity.threshold
    capacity.threshold = 30000.0
    check("...and follows the target when the buyer changes it",
          "30,000" in capacity.label, capacity.label)
    capacity.threshold = original
    reject = next(c for c in comparison.criteria if "rejection" in c.key)
    check("a lower-is-better criterion reads the right way round",
          "less than" in reject.label, reject.label)

    print("\nNOBODY IS ELIMINATED BY DEFAULT")
    check("every criterion defaults to Scored, not Must have",
          all(c.requirement == "Scored" for c in comparison.criteria))
    check("...so all five suppliers qualify for the award",
          all(s.meets_requirements for s in comparison.summaries),
          str([s.vendor for s in comparison.summaries if not s.meets_requirements]))
    check("unanswered questions are tracked separately from a No",
          len(cards[NORTHSTAR].unanswered) == 2,
          str(cards[NORTHSTAR].unanswered))

    print("\nTHE BUYER'S CONTROLS ACTUALLY MOVE THE ANSWER")
    iso = next(c for c in comparison.criteria if c.kind == "certification")
    iso.requirement = "Must have"
    assemble_module.rescore(comparison)
    excluded = [s.vendor for s in comparison.summaries if not s.meets_requirements]
    check("marking a criterion Must have eliminates whoever misses it",
          excluded == [NORTHSTAR], str(excluded))
    iso.requirement = "Scored"

    was = {s.vendor: s.quality_score for s in comparison.summaries}
    capacity.threshold = capacity.suggested_threshold
    assemble_module.rescore(comparison)
    now = {s.vendor: s.quality_score for s in comparison.summaries}
    check("a basket-derived target lifts the supplier it was unfairly excluding",
          now[PACIFIC] > was[PACIFIC], f"{was[PACIFIC]} -> {now[PACIFIC]}")
    capacity.threshold = 50000.0
    assemble_module.rescore(comparison)

    print("\nTHE VP QUESTION  (cheapest per line among suppliers who cleared)")
    store.write(comparison, path=db_path)
    frame = store.query_frame(
        "SELECT rfx_sku, vendor, canonical_value FROM comparison "
        "WHERE comparable = 1 AND quality_score >= 0.85", path=db_path)
    shortlist = set(frame["vendor"].unique())
    check("a score threshold shortlists on merit, not on a binary",
          NORTHSTAR not in shortlist and SHAKTI in shortlist, str(shortlist))
    winners = frame.loc[frame.groupby("rfx_sku")["canonical_value"].idxmin()]
    counts = winners["vendor"].value_counts().to_dict()
    check("several suppliers still win lines", len(counts) >= 2, str(counts))
    print(f"       -> per-line winners: {counts}")

    print("\nGUARDRAILS  (the analyst's query tool must stay read-only)")
    for bad in ("DROP TABLE quotes", "DELETE FROM quotes",
                "SELECT 1; DROP TABLE quotes", "PRAGMA table_info(quotes)"):
        try:
            store.run_query(bad, path=db_path)
            check(f"rejects: {bad}", False, "query was allowed")
        except store.QueryError:
            check(f"rejects: {bad}", True)

    print("\nANALYST PLUMBING  (tools wired to the database, no model needed)")
    from core import analyst as analyst_module
    from core import llm as llm_module

    captured: dict = {}

    def fake_loop(system_prompt, user_message, tools, declarations, **kwargs):
        captured["schema_in_prompt"] = "comparison" in system_prompt
        captured["tool_names"] = sorted(tools)
        captured["rows"] = tools["run_query"](
            sql="SELECT vendor, COUNT(*) n FROM comparison WHERE comparable = 1 "
                "GROUP BY vendor")["rows"]
        captured["evidence"] = tools["get_evidence"](
            rfx_sku="BX-009", vendor=NORTHSTAR)
        tools["make_chart"](
            title="Comparable lines", kind="bar",
            sql="SELECT vendor, COUNT(*) n FROM comparison WHERE comparable = 1 "
                "GROUP BY vendor", x="vendor", y="n")
        return llm_module.ToolLoopResult(text="ok", calls=[], rounds=1)

    original = llm_module.run_tool_loop
    llm_module.run_tool_loop = fake_loop
    analyst_module.llm.run_tool_loop = fake_loop
    try:
        answer = analyst_module.ask("test", db_path=db_path)
    finally:
        llm_module.run_tool_loop = original
        analyst_module.llm.run_tool_loop = original

    check("schema is given to the analyst", captured.get("schema_in_prompt", False))
    check("all three tools are exposed",
          captured.get("tool_names") == ["get_evidence", "make_chart", "run_query"],
          str(captured.get("tool_names")))
    check("run_query returns real rows", len(captured.get("rows", [])) == 5,
          str(captured.get("rows")))
    check("get_evidence returns the verbatim source and the conversion",
          "/ 100 pcs" in (captured["evidence"].get("source_snippet") or "")
          and "÷ 100" in (captured["evidence"].get("factor") or ""),
          str(captured["evidence"].get("factor")))
    check("every query is recorded for the buyer", len(answer.queries) == 2)
    check("chart rows come from a real query",
          len(answer.charts) == 1 and len(answer.charts[0].rows) == 5)

    print("\nANY NUMBER OF SUPPLIERS  (the item list is built from the responses)")
    two = pipeline.run_paths([SAMPLES[i] for i in (0, 3)],
                             db_path=os.path.join(tempfile.mkdtemp(), "two.db"))
    check("two responses produce a comparison", len(two.comparison.summaries) == 2)
    check("...spanning every item either of them priced",
          rfx_module.active().line_count >= 28, str(rfx_module.active().line_count))

    one = pipeline.run_paths([SAMPLES[2]],
                             db_path=os.path.join(tempfile.mkdtemp(), "one.db"))
    check("a single response is compared against only what it contains",
          rfx_module.active().line_count == len(one.comparison.summaries[0].not_quoted)
          + one.comparison.summaries[0].coverage_quoted)

    print("\nAWARD RECOMMENDATION  (who gets which items, and what it leaves out)")
    from core import award as award_module

    comparison = pipeline.run_paths(SAMPLES, db_path=db_path).comparison

    shortlisted = award_module.recommend(comparison, min_lines=1, min_quality=0.85)
    check("a quality bar shortlists rather than a checklist",
          NORTHSTAR in shortlisted.excluded and SHAKTI in shortlisted.eligible,
          str(shortlisted.excluded))
    check("...and says who it left out", bool(shortlisted.excluded))

    plan = award_module.recommend(comparison, min_lines=1)
    check("with no bar set, every supplier is shortlisted",
          len(plan.eligible) == 5 and not plan.excluded, str(plan.excluded))
    check("the whole market splits across every supplier",
          len(plan.vendors) == 5,
          str([(v.vendor, v.line_count) for v in plan.vendors]))
    print(f"       -> {plan.headline()}")
    allocated = sum(v.line_count for v in plan.vendors)
    check("every awarded line is allocated exactly once",
          allocated == plan.awarded_lines, f"{allocated} vs {plan.awarded_lines}")
    check("no supplier wins a line it did not price comparably",
          all(comparison.cell(sku, v.vendor).comparable
              for v in plan.vendors for sku in v.lines))
    check("the winning price is the cheapest comparable one on that line",
          all(a.price == min(c.canonical_value for vendor in plan.eligible
                             for c in [comparison.cell(a.sku, vendor)]
                             if c and c.comparable)
              for a in plan.lines if a.winner))

    consolidated = award_module.recommend(comparison, min_lines=6)
    check("consolidation removes the tail",
          all(v.line_count >= 6 for v in consolidated.vendors),
          str([(v.vendor, v.line_count) for v in consolidated.vendors]))
    check("...names who was dropped", bool(consolidated.dropped_for_size))
    check("...reports what it cost",
          consolidated.consolidation_cost is not None
          and consolidated.consolidation_cost > 0,
          str(consolidated.consolidation_cost))
    check("consolidation strands no line",
          consolidated.awarded_lines == plan.awarded_lines)
    check("split-vs-single is judged on a stated common basket",
          plan.common_basket > 0 and plan.best_single_vendor is not None,
          f"{plan.common_basket} / {plan.best_single_vendor}")

    notes = award_module.caveats(plan, comparison)
    check("caveats mention delivery and discounts",
          any("Delivery" in n for n in notes) and any("discount" in n for n in notes))

    print("\nTHE DATASET IS UGLY, NOT UNREADABLE")
    # The assignment wants the hard edges -- a per-kg basis, a pack multiple, a
    # photographed rate card. It does not want a demo where nothing lines up.
    # These bounds are the line between the two, and they are asserted so a
    # future edit to the sample documents cannot quietly cross it.
    cells = comparison.cells
    overall = sum(1 for c in cells if c.comparable) / len(cells)
    check(f"at least 80% of all quoted values are comparable ({overall:.1%})",
          overall >= 0.80)
    for summary in comparison.summaries:
        own = [c for c in cells if c.vendor == summary.vendor]
        rate = sum(1 for c in own if c.comparable) / len(own)
        check(f"{summary.vendor.split()[0]}: {rate:.0%} comparable", rate >= 0.80)
    unreadable = sum(1 for c in cells if c.status == "Unresolved")
    check(f"unresolved lines stay a minority ({unreadable} of {len(cells)})",
          unreadable / len(cells) <= 0.05)

    print("\nCONFIDENCE IS EARNED, NOT ASSERTED")
    for summary in comparison.summaries:
        own = [c.extraction_confidence for c in comparison.cells
               if c.vendor == summary.vendor and c.original_value is not None]
        check(f"{summary.vendor.split()[0]}: not one flat number "
              f"({min(own):.2f}–{max(own):.2f}, {len(set(own))} distinct)",
              len(set(own)) > 1)
    photo = [c for c in comparison.cells if c.vendor == NORTHSTAR
             and c.original_value is not None]
    clean = [c for c in comparison.cells if c.vendor == SHAKTI
             and c.original_value is not None]
    check("the photographed rate card reads worse than the spreadsheet",
          max(c.extraction_confidence for c in photo)
          < min(c.extraction_confidence for c in clean))
    check("a marked-down number can say why it was marked down",
          all(c.confidence_notes for c in photo))

    print("\nBOILERPLATE IS A SUPPLIER TERM, NOT A CONDITION ON EVERY PRICE")
    firm = [c for c in comparison.cells if c.vendor == NORTHSTAR
            and c.original_value is not None
            and "subject_to_confirmation" not in c.flags]
    quoted = [c for c in comparison.cells if c.vendor == NORTHSTAR
              and c.original_value is not None]
    check(f"at least 80% of Northstar's prices are firm "
          f"({len(firm)}/{len(quoted)})", len(firm) / len(quoted) >= 0.80)

    spine_before = rfx_module.active()
    print("\nA SAVED EMAIL IS READ AS A MESSAGE, NOT AS A WALL OF TEXT")
    from core import brand, ingest  # noqa: E402
    eml = os.path.join(ROOT, "sample_data", "Pacific_Pack_Global_email.eml")
    payload = ingest.load_path(eml)
    check("the exporter's reply is a real .eml", os.path.exists(eml))
    check("its headers are read, not skipped",
          "[header] From:" in payload.text and "[header] Subject:" in payload.text)
    check("the encoded body is decoded, not shown as escapes",
          "=E2=82" not in payload.text and "Apologies for the delay" in payload.text)
    check("and it still yields every price it did as plain text",
          summaries[PACIFIC].coverage_quoted == 28)

    invitation_dir = os.path.join(tempfile.mkdtemp(), "outbox")
    probe = rfx_module.RfxSpec(derived=False, title="Probe", reference="RFX/PROBE",
                               lines=[rfx_module.RfxLine("P-001", "A thing", 10,
                                                         "per box", "discrete",
                                                         origin="buyer")])
    sent = dispatch.send_request(probe, [dispatch.Vendor("Probe Supplier", "p@x.example")],
                                 dispatch.MailboxChannel(directory=invitation_dir))
    attached = ingest.load_path(sent[0].receipt.location)
    check("an attachment inside an email is opened too, not just noticed",
          "--- ATTACHMENT:" in attached.text and "P-001" in attached.text)

    print("\nONE BUYER, ONE CATEGORY, EVERY DOCUMENT")
    surname = brand.CONTACT.split(",")[0].split()[-1]
    for filename, needle in (("Shakti_Packaging_Quotation.xlsx", brand.COMPANY_LEGAL),
                             ("Meridian_Packaging_Offer.docx", brand.COMPANY_LEGAL),
                             ("Pacific_Pack_Global_email.eml", surname)):
        body = ingest.load_path(os.path.join(ROOT, "sample_data", filename)).text
        check(f"{filename} is addressed to the buyer", needle in body,
              f"{needle!r} not found")

    # Sri Balaji's PDF is deliberately built with a broken text layer, so the
    # pipeline reads it by vision and there is no text to search. Check the
    # page's own words instead of the reader's output.
    from pypdf import PdfReader  # noqa: E402
    raw = "".join(page.extract_text() or "" for page in
                  PdfReader(os.path.join(ROOT, "sample_data",
                                         "Sri_Balaji_Corrugators_Quote.pdf")).pages)
    check("Sri_Balaji_Corrugators_Quote.pdf is addressed to the buyer",
          brand.COMPANY_LEGAL in raw, "not on the page")

    print("\nDRAFTING A REQUEST  (the co-pilot edits the real object)")
    draft_spec = rfx_module.RfxSpec(derived=True)
    changes: list[str] = []
    tools = draft_module._tools(draft_spec, changes)
    tools["set_scope"](title="Corrugated packaging", reference="RFX/CORR/2026-0830",
                       currency="inr", scope="Annual requirement")
    check("scope marks the request as authored, not derived", not draft_spec.derived)
    check("a stated currency stops being an inference", not draft_spec.currency_inferred)

    tools["add_line"](sku="bx 1", description="5-ply box 400x300x250 mm",
                      unit="per box", quantity=10000)
    check("a loosely typed code is normalised to the matcher's form",
          draft_spec.lines[0].sku == "BX-001", draft_spec.lines[0].sku)

    tools["add_line"](sku="BX-002", description="5-ply box 450x350x300 mm",
                      unit="Nos", quantity=8000, origin="suggested")
    check("'Nos' becomes a unit a supplier can read",
          draft_spec.lines[1].canonical_unit == "per unit",
          draft_spec.lines[1].canonical_unit)
    check("a line the co-pilot invented is marked suggested",
          [l.sku for l in draft_spec.suggested_lines] == ["BX-002"])

    tools["revise_line"](sku="BX-002", quantity=9000)
    check("the co-pilot revising its own suggestion does not launder it",
          draft_spec.lines[1].origin == "suggested")
    check("a suggested line is kept out of the document sent to suppliers",
          len(rfxdoc.sendable_lines(draft_spec)) == 1
          and len(draft_spec.lines) == 2)

    frame = present.draft_lines_frame(draft_spec)
    frame.loc[1, "Description"] = "5-ply box 450x350x300 mm, 200 GSM"
    present.apply_draft_edits(draft_spec, frame)
    check("...until a person edits it, which is what accepting it means",
          draft_spec.lines[1].origin == "buyer")

    tools["add_question"](question="Monthly production capacity above 50,000 units?",
                          threshold=50000, direction="higher_better",
                          unit=" units/month")
    duplicate = tools["add_question"](question="Do you have capacity above 50,000 units a month?")
    check("the same question cannot be asked twice in one request",
          "error" in duplicate, str(duplicate))
    check("a numeric question is stored as testable, not as prose",
          draft_spec.criteria[0].threshold == 50000
          and draft_spec.criteria[0].direction == "higher_better")

    print("\nWORKED EXAMPLES  (loaded from file, and labelled as such)")
    from core import examples as examples_module  # noqa: E402
    seeded = rfx_module.RfxSpec()
    replenish = examples_module.seed_replenishment(seeded)
    low, high = examples_module.REPLENISHMENT_RANGE
    check(f"the replenishment example loads {replenish['lines']} items "
          f"({low}-{high})", low <= replenish["lines"] <= high)

    sizes = set()
    for _ in range(40):
        scratch = rfx_module.RfxSpec()
        sizes.add(examples_module.seed_replenishment(scratch)["lines"])
    check(f"the count varies too, not just which items ({sorted(sizes)})",
          len(sizes) > 1 and min(sizes) >= low and max(sizes) <= high)

    # Stock does not run down in catalogue order, so neither should this.
    draws = set()
    for _ in range(12):
        scratch = rfx_module.RfxSpec()
        examples_module.seed_replenishment(scratch)
        draws.add(tuple(line.sku for line in scratch.lines))
    check(f"the items are drawn fresh each time ({len(draws)} distinct draws in 12)",
          len(draws) > 1)
    check("...and are not simply taken off the top of the list",
          any(list(draw) != [item.sku for item in gen.CATALOGUE[:10]] for draw in draws))

    # The gate, and the way out of it. A replenishment draft cannot be sent
    # until a person accepts the lines -- but the page must offer that decision
    # where the buyer is standing, or the whole send step reads as missing.
    gated = rfx_module.RfxSpec()
    examples_module.seed_replenishment(gated)
    check("a replenishment draft has nothing sendable until it is accepted",
          len(rfxdoc.sendable_lines(gated)) == 0 and gated.line_count > 0)
    check("...and every one of its lines says why",
          len(gated.suggested_lines) == gated.line_count)
    present.accept_suggestions(gated)
    check("accepting them makes the whole request sendable",
          len(rfxdoc.sendable_lines(gated)) == gated.line_count
          and gated.suggested_lines == [])
    check("...and the request document then renders",
          len(rfxdoc.build_pdf(gated)) > 2000)
    seeded_a, seeded_b = rfx_module.RfxSpec(), rfx_module.RfxSpec()
    examples_module.seed_replenishment(seeded_a, seed=7)
    examples_module.seed_replenishment(seeded_b, seed=7)
    check("...but a seeded draw is reproducible, so this stays testable",
          [l.sku for l in seeded_a.lines] == [l.sku for l in seeded_b.lines])
    check("the drawn items are still in catalogue order on the page",
          [l.sku for l in seeded_a.lines] == sorted(l.sku for l in seeded_a.lines))
    check("every one is marked suggested, because no stock system was read",
          len(seeded.suggested_lines) == len(seeded.lines))
    check("...so none of them would be sent to a supplier unchecked",
          rfxdoc.sendable_lines(seeded) == [])
    check("the questionnaire comes with it",
          len(seeded.criteria) == 5, str(len(seeded.criteria)))

    full = rfx_module.RfxSpec()
    loaded = examples_module.seed_full_request(full)
    import json as _json                                  # noqa: E402
    _example = _json.load(open(os.path.join(ROOT, "examples",
                                            "corrugated_packaging.json"),
                               encoding="utf-8"))
    check("the item list is written once, not typed out twice",
          _example["lines"] == gen.catalogue_rows(),
          "examples/corrugated_packaging.json has drifted from CATALOGUE — "
          "re-run tests/build_sample_data.py")

    low, high = examples_module.FULL_REQUEST_RANGE
    check(f"the full example loads {loaded['lines']} items ({low}-{high})",
          low <= loaded["lines"] <= high, loaded["lines"])
    annual = {examples_module.seed_full_request(rfx_module.RfxSpec())["lines"]
              for _ in range(40)}
    check(f"...and this year's list is not last year's ({sorted(annual)})",
          len(annual) > 1)
    check("its lines are the buyer's own, so they can be sent",
          len(rfxdoc.sendable_lines(full)) == full.line_count)
    check("it carries the instruction that charges must be quoted with amounts",
          any("at actuals" in text or "amount" in text
              for text in full.terms.values()))
    # The standing items are the contract being renewed, so they are always on
    # the request however long this year's list runs. Anything beyond them is
    # this year's addition, and shows as an item nobody quoted -- which is the
    # coverage gap the tool exists to make visible.
    check("every item the sample responses quote is still on the request",
          {item.sku for item in gen.CATALOGUE} <= {line.sku for line in full.lines},
          "the seeded request and the fabricated replies have drifted apart")
    for _ in range(20):
        rolled = rfx_module.RfxSpec()
        examples_module.seed_full_request(rolled)
        if not {item.sku for item in gen.CATALOGUE} <= {l.sku for l in rolled.lines}:
            check("...on every draw, not just this one", False, "a draw dropped a core item")
            break
    else:
        check("...on every draw, not just this one", True)

    po = os.path.join(ROOT, "examples", "PO_2025_Corrugated_Packaging.pdf")
    check("last year's purchase order ships as a document to start from",
          os.path.exists(po))
    from pypdf import PdfReader as _Reader  # noqa: E402
    po_text = "".join(page.extract_text() or "" for page in _Reader(po).pages)
    check("...dated last year", "2025" in po_text, "no 2025 date on the PO")
    check("...with 15 of the 30 lines on it",
          all(item.sku in po_text for item in gen.CATALOGUE[:15])
          and gen.CATALOGUE[15].sku not in po_text)
    check("...addressed by the buyer to a supplier",
          brand.COMPANY_LEGAL in po_text and "Shakti" in po_text)

    from_doc = rfx_module.RfxSpec(lines=[rfx_module.RfxLine(
        "BX-001", "5-ply box", 100, "per box", "discrete", origin="document")])
    completed = examples_module.complete_from_document(from_doc)
    check("a document's items become a request, not just a list",
          completed["questions"] == 5 and completed["terms"] >= 4)
    check("...without touching the items that were actually read",
          len(from_doc.lines) == 1 and from_doc.lines[0].origin == "document")

    print("\nTHE TOOL LOOP IS MANUAL ON PURPOSE")
    from google.genai import types as _types, _extra_utils  # noqa: E402
    probe = _types.GenerateContentConfig(
        temperature=0,
        tools=[_types.Tool(function_declarations=[_types.FunctionDeclaration(
            name="probe",
            parameters=_types.Schema(type=_types.Type.OBJECT, properties={}))])],
        automatic_function_calling=_types.AutomaticFunctionCallingConfig(disable=True))
    check("automatic function calling is switched off on every call we make",
          _extra_utils.should_disable_afc(probe),
          "AFC on means the buyer cannot see which tools ran")

    import logging as _logging  # noqa: E402
    noisy = _logging.getLogger("google_genai.models")
    record = noisy.makeRecord(
        noisy.name, _logging.WARNING, __file__, 0,
        "Direct use of automatic function calling (AFC) in "
        "Models.generate_content is not recommended.", (), None)
    real = noisy.makeRecord(noisy.name, _logging.WARNING, __file__, 0,
                            "something genuinely wrong", (), None)
    check("the SDK's AFC advice is filtered out of the console",
          not all(f.filter(record) for f in noisy.filters))
    check("...but every other warning from that logger still gets through",
          all(f.filter(real) for f in noisy.filters))

    print("\nA BUSY MODEL IS RIDDEN OUT, NOT REPORTED AS A FAILURE")
    from core import llm as llm_module  # noqa: E402
    check("a 503 'high demand' is recognised as temporary",
          llm_module.is_transient(RuntimeError(
              "503 UNAVAILABLE. This model is currently experiencing high demand.")))
    check("so is a 429 and a 500",
          llm_module.is_transient(RuntimeError("429 RESOURCE_EXHAUSTED"))
          and llm_module.is_transient(RuntimeError("500 INTERNAL")))
    check("a rejected key is NOT treated as temporary",
          not llm_module.is_transient(RuntimeError("403 permission denied")))

    attempts = {"n": 0}

    def flaky(model):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("503 UNAVAILABLE, high demand")
        return f"answered by {model}"

    original = llm_module.candidate_models
    llm_module.candidate_models = lambda kind: ["model-a", "model-b"]
    try:
        result = llm_module._attempt(flaky, "analyst", "Test", max_tries=3)
        check("a call that fails twice and then succeeds still returns an answer",
              result == "answered by model-a" and attempts["n"] == 3)

        attempts["n"] = 0

        def dead(model):
            attempts["n"] += 1
            raise RuntimeError("403 permission denied")

        try:
            llm_module._attempt(dead, "analyst", "Test", max_tries=3)
            check("a permanent error is raised without retrying", False)
        except RuntimeError:
            check("a permanent error is raised without retrying", attempts["n"] == 1,
                  f"retried {attempts['n']} times")

        attempts["n"] = 0

        def always_busy(model):
            attempts["n"] += 1
            raise RuntimeError("503 UNAVAILABLE, high demand")

        try:
            llm_module._attempt(always_busy, "analyst", "Test", max_tries=1)
            check("...and a genuinely busy service tries the other model too", False)
        except RuntimeError as exc:
            check("...and a genuinely busy service tries the other model too",
                  attempts["n"] == 2 and "busy rather than broken" in str(exc),
                  str(exc)[:80])
    finally:
        llm_module.candidate_models = original

    print("\nOPTIONAL DEPENDENCIES DEGRADE, THEY DO NOT CRASH")
    check("the app can tell whether it can render a request document",
          isinstance(rfxdoc.pdf_available(), bool))
    check("...and has an installation sentence ready if it cannot",
          "pip install" in rfxdoc.PDF_HINT and "reportlab" in rfxdoc.PDF_HINT)
    check("the PDF library is not imported at module scope",
          "\nfrom reportlab" not in open(
              os.path.join(ROOT, "core", "rfxdoc.py"), encoding="utf-8").read(),
          "a top-level reportlab import would break every other feature too")

    print("\nTHE BUYER CAN EDIT EVERY PART OF THE DRAFT BY HAND")
    import pandas as _pd  # noqa: E402
    hand = rfx_module.RfxSpec()
    examples_module.seed_full_request(hand)

    lines_frame = present.draft_lines_frame(hand)
    lines_frame.loc[0, "Quantity"] = 12500
    lines_frame.loc[1, "Price per"] = "per 100 sheets"
    lines_frame = lines_frame.drop(index=2).reset_index(drop=True)
    lines_frame.loc[len(lines_frame)] = {
        "Item": "BX-099", "Description": "Pallet wrap 500 mm",
        "Quantity": 400, "Price per": "per roll"}
    present.apply_draft_edits(hand, lines_frame)
    edited_lines = {line.sku: line for line in hand.lines}
    check("a quantity typed into the table is kept",
          edited_lines["BX-001"].quantity == 12500)
    check("a pack multiple survives the edit ('per 100 sheets')",
          edited_lines["BX-002"].canonical_unit == "per 100 sheets",
          edited_lines["BX-002"].canonical_unit)
    check("a deleted row is deleted", "BX-003" not in edited_lines)
    check("a row typed in by hand is the buyer's, not a suggestion",
          edited_lines["BX-099"].origin == "buyer")
    check("the item table no longer carries a locked Source column",
          "Source" not in present.draft_lines_frame(hand).columns)
    check("...but origin is still tracked, so suggestions stay held back",
          all(hasattr(line, "origin") for line in hand.lines))

    stray_rows = present.draft_criteria_frame(hand)
    stray_rows.loc[len(stray_rows)] = {
        "Question": "", "Target": 95, "Unit": "%", "Direction": "at least",
        "Requirement": "Scored", "Weight": 1}
    check("a target with no question is counted, not silently dropped",
          present.blank_questions(stray_rows) == 1)
    before = len(hand.criteria)
    present.apply_criteria_edits(hand, stray_rows)
    check("...and never becomes a criterion", len(hand.criteria) == before)

    questions_frame = present.draft_criteria_frame(hand)
    questions_frame.loc[0, "Requirement"] = "Must have"
    questions_frame.loc[1, "Target"] = 30000
    questions_frame.loc[len(questions_frame)] = {
        "Question": "Do you hold FSC chain-of-custody certification?",
        "Target": None, "Unit": "", "Direction": "yes / no",
        "Requirement": "Scored", "Weight": 2}
    present.apply_criteria_edits(hand, questions_frame)
    check("a question can be promoted to a must-have by hand",
          hand.criteria[0].requirement == "Must have")
    check("a target moved by hand shows on the criterion",
          "30,000" in hand.criteria[1].label, hand.criteria[1].label)
    check("...with a space between the number and its unit",
          "30,000 units" in hand.criteria[1].label, hand.criteria[1].label)
    check("a question typed in by hand is added with its weight",
          len(hand.criteria) == 6 and hand.criteria[-1].weight == 2)

    numbered = present.draft_criteria_frame(hand)
    check("the questions table is numbered for the reader",
          list(numbered["S. No."]) == list(range(1, len(hand.criteria) + 1)),
          list(numbered["S. No."]))
    check("...and the serial number is not read back as a question",
          "S. No." not in [c.question for c in hand.criteria])

    empty_spec = rfx_module.RfxSpec(derived=False)
    empty_questions = present.draft_criteria_frame(empty_spec)
    check("a request with no questions still gets its headings",
          list(empty_questions.columns) == present.CRITERIA_COLUMNS,
          list(empty_questions.columns))
    check("...and a row to type the first question into",
          len(empty_questions) == 1 and empty_questions.loc[0, "Question"] == "")
    empty_questions.loc[0, "Question"] = "Are you ISO 9001 certified?"
    present.apply_criteria_edits(empty_spec, empty_questions)
    check("a question typed into an empty request is kept",
          len(empty_spec.criteria) == 1
          and empty_spec.criteria[0].question == "Are you ISO 9001 certified?")

    terms_frame = present.draft_terms_frame(hand)
    terms_frame.loc[0, "What suppliers are told"] = "60 days from date of invoice."
    present.apply_terms_edits(hand, terms_frame)
    check("a term can be rewritten by hand",
          hand.terms["payment"] == "60 days from date of invoice.")

    print("\nTERMS AS A TEXTBOX")
    round_trip = present.draft_terms_text(hand)
    check("terms are offered as one line each, labelled",
          round_trip.splitlines()[0].startswith("Payment: "),
          round_trip.splitlines()[0])
    before_terms = dict(hand.terms)
    present.apply_terms_text(hand, round_trip)
    check("...and reading them back changes nothing", hand.terms == before_terms)

    typed_spec = rfx_module.RfxSpec(derived=False)
    present.apply_terms_text(typed_spec, (
        "Payment: 45 days from receipt of invoice\n"
        "\n"
        "Delivery: DDP Bengaluru, freight included\n"
        "All rates to be firm, no escalation clauses\n"
        "Payment: net 30 for the first order\n"))
    check("a labelled line becomes its term",
          typed_spec.terms.get("payment") == "45 days from receipt of invoice")
    check("blank lines are skipped", len(typed_spec.terms) == 4,
          list(typed_spec.terms))
    check("a line with no label is kept as written, not dropped",
          typed_spec.terms.get("note 1")
          == "All rates to be firm, no escalation clauses")
    check("a repeated label does not silently overwrite the line above it",
          typed_spec.terms.get("payment (2)") == "net 30 for the first order")
    check("the terms keep the order they were typed in",
          list(typed_spec.terms)[:2] == ["payment", "delivery"],
          list(typed_spec.terms))
    present.apply_terms_text(typed_spec, "   \n\n")
    check("clearing the textbox clears the terms", typed_spec.terms == {})

    print("\nTWO SUPPLIERS DESCRIBING ONE PRODUCT LAND ON ONE ROW")
    from core import derive as derive_module          # noqa: E402
    from core import match as match_module            # noqa: E402
    from core import skus as skus_module              # noqa: E402
    from core.models import ExtractedLine as _EL, VendorResponse as _VR  # noqa: E402

    check("a description with no code no longer invents one",
          skus_module.normalize_sku("5-ply box, 400 x 300 x 250 mm") is None,
          skus_module.normalize_sku("5-ply box, 400 x 300 x 250 mm"))
    check("...while a real code is still read, however it is written",
          (skus_module.normalize_sku("CP-001"),
           skus_module.normalize_sku("BX 004"),
           skus_module.normalize_sku("For BX-001, 5-ply box"))
          == ("CP-001", "BX-004", "BX-001"))
    check("a unit word next to a number is not a code either",
          skus_module.normalize_sku("kraft 180 GSM, MM 400") is None)

    def _line(code, text, value, unit):
        return _EL(vendor_sku=code, description=text, quoted_value=value,
                   currency="INR", unit_text=unit)

    coded = _VR(vendor="Eastern", file="e.xlsx", document_currency="INR", lines=[
        _line("CP-001", "5-ply Corrugated Box – 400 x 300 x 250 mm", 43.2, "box"),
        _line("CP-003", "3-ply Corrugated Box – 300 x 200 x 150 mm", 24.8, "box"),
        _line("CP-009", "Corrugated Roll – 1200 mm width", 185, "roll"),
        _line("CP-008", "Corrugated Partition – 6-cell", 14.25, "piece")])
    uncoded = _VR(vendor="Western", file="w.eml", document_currency="INR", lines=[
        _line(None, "5-ply box, 400 x 300 x 250 mm", 44.10, "per box"),
        _line(None, "3-ply box, 300 x 200 x 150 mm", 25.60, "per box"),
        _line(None, "Corrugated roll, 1200 mm width", 192, "per roll"),
        _line(None, "6-cell corrugated partition", 14.90, "each")])

    merged = derive_module.derive_spec([coded, uncoded])
    check("four products quoted by two suppliers make four rows, not eight",
          merged.line_count == 4, merged.line_count)
    check("...and the rows keep the supplier's real codes",
          {line.sku for line in merged.lines}
          == {"CP-001", "CP-003", "CP-008", "CP-009"},
          sorted(line.sku for line in merged.lines))

    rfx_module.set_active(merged)
    both = assemble_module.build([coded, uncoded])
    priced = [c for c in both.cells if c.original_value is not None]
    check("every one of the eight quotes lands on a row",
          len(priced) == 8, len(priced))
    check("...so each row can actually be compared across the two",
          all(len([c for c in both.cells
                   if c.rfx_sku == line.sku and c.original_value is not None]) == 2
              for line in merged.lines))

    print("\nA SHARED SIZE IS NOT A SHARED PRODUCT")
    # Against a real item list, not a single line: which words distinguish an
    # item is learned from the catalogue, so one line in isolation has no
    # vocabulary to be judged against -- and neither would a buyer.
    catalogue = [
        rfx_module.RfxLine("BX-001", "5-ply corrugated box 400x300x250 mm",
                           10, "per box", "discrete"),
        rfx_module.RfxLine("BX-013", "Die-cut box 300x200x150 mm",
                           10, "per box", "discrete"),
        rfx_module.RfxLine("BX-025", "5-ply roll, 1200 mm width",
                           10, "per roll", "roll"),
        rfx_module.RfxLine("BX-021", "Partition set, 12-cell",
                           10, "per set", "discrete"),
        rfx_module.RfxLine("BX-023", "Corrugated sheet 1000x800 mm",
                           10, "per sheet", "sheet"),
    ]
    check("a 3-ply box does not match a die-cut box of the same size",
          match_module.match_one(
              _line("CP-003", "3-ply Corrugated Box – 300 x 200 x 150 mm", 1, "box"),
              catalogue).rfx_sku is None)
    check("...but the same roll described two ways does match",
          match_module.match_one(
              _line(None, "Corrugated Roll – 1200 mm width", 1, "roll"),
              catalogue).rfx_sku == "BX-025")

    print("\nA REPEATED LABEL MUST NOT TAKE THE PAGE DOWN")
    # pandas' Styler refuses a non-unique index outright, so a buyer typing
    # one item code twice, or two questions reducing to the same wording, did
    # not merely confuse the grid -- it raised, and took the page with it.
    twinned = rfx_module.RfxSpec(lines=[
        rfx_module.RfxLine("BX-001", "Box one", 10, "per box", "discrete"),
        rfx_module.RfxLine("BX-001", "Box two", 10, "per box", "discrete")])
    rfx_module.set_active(twinned)
    twin_cmp = assemble_module.build([_VR(
        vendor="A", file="a", document_currency="INR",
        lines=[_line("BX-001", "Box one", 45.0, "per box")])])
    shown, states = present.grid(twin_cmp)
    check("a duplicated item code still renders, both rows kept",
          list(shown.index) == ["BX-001", "BX-001 (2)"], list(shown.index))
    present.style_grid(shown, states,
                       present.cheapest_by_line(twin_cmp)).to_html()
    check("...and the styler does not raise on it", True)

    twin_cmp.criteria = [
        criteria_module.Criterion(key="a", question="Are you ISO 9001 certified?",
                                  variants=["a"]),
        criteria_module.Criterion(key="b", question="Are you ISO 9001 certified?",
                                  variants=["b"])]
    twin_cmp.scorecards = {"A": criteria_module.build_scorecard(
        "A", twin_cmp.criteria, {})}
    answers, answer_state = present.questionnaire_frame(twin_cmp)
    present.style_questionnaire(answers, answer_state).to_html()
    check("a duplicated question renders too", len(answers.index) == 3,
          list(answers.index))

    print("\nA NUMBER IN A UNIT IS NOT ALWAYS A PACK SIZE")
    from core import normalize as normalize_module              # noqa: E402
    probe_line = rfx_module.RfxLine("BX-001", "Corrugated box", 100,
                                    "per box", "discrete")

    def _priced(unit, value=45.0, currency="INR"):
        return normalize_module.normalize(
            probe_line, _EL(vendor_sku="BX-001", description="box",
                            quoted_value=value, currency=currency,
                            unit_text=unit, confidence=0.9), "V")

    for unit in ("per 5 ply carton", "per 3 ply box", "per 250 gsm box",
                 "per 400 mm box", "per 2024 price list"):
        cell = _priced(unit)
        check(f"'{unit}' does not divide the price",
              cell.canonical_value == 45.0, cell.canonical_value)
    for unit, expected in (("per 100 pcs", 0.45), ("/ 100 pcs", 0.45),
                           ("per 1000 pcs", 0.045), ("per 100 rolls", 0.45),
                           ("/100", 0.45)):
        cell = _priced(unit)
        check(f"'{unit}' still divides, because it counts something",
              cell.canonical_value is not None
              and abs(cell.canonical_value - expected) < 1e-9,
              cell.canonical_value)

    check("a per-metre price refuses however it is spelled",
          normalize_module.parse_unit("per meters").family == "length"
          and normalize_module.parse_unit("per metre").family == "length")

    print("\nA CURRENCY IS READ HOWEVER IT IS WRITTEN")
    for written, expected in (("₹", 45.0), ("Rs", 45.0), ("Rs.", 45.0),
                              ("INR ", 45.0), ("$", 45.0 * 87.5),
                              ("usd ", 45.0 * 87.5)):
        cell = _priced("per box", currency=written)
        check(f"{written!r} is understood, not refused",
              cell.canonical_value is not None
              and abs(cell.canonical_value - expected) < 1e-6,
              f"{cell.status} {cell.canonical_value}")
    check("a currency with no configured rate is still refused, out loud",
          _priced("per box", currency="JPY").status == "Needs Review")

    print("\nA NUMBER THAT IS NOT A NUMBER NEVER REACHES THE COMPARISON")
    for bad in (float("nan"), float("inf"), float("-inf")):
        cell = _priced("per box", value=bad)
        check(f"{bad} is refused rather than compared",
              cell.status == "Unresolved" and not cell.comparable, cell.status)
    survives = derive_module.derive_spec([_VR(vendor="A", file="a", lines=[
        _EL(vendor_sku="BX-001", description="Box", quoted_value=1.0,
            currency="INR", unit_text="per box", quantity=float("inf"))])])
    check("an impossible quantity does not take the run down",
          survives.line_count == 1 and survives.lines[0].quantity is None)

    print("\nTWO QUESTIONS THAT DIFFER BY ONE DIGIT ARE TWO QUESTIONS")
    for a, b, same in (("Rejection rate below 2%?", "Rejection rate below 5%?", False),
                       ("Do you supply Grade 2 steel?", "Do you supply Grade 5 steel?", False),
                       ("ISO 9001 certified?", "ISO 14001 certified?", False),
                       ("On-time delivery above 95%?", "OTD above 95%?", True)):
        check(f"{'same' if same else 'different'}: {a[:26]} / {b[:26]}",
              criteria_module.same_question(a, b) is same)

    print("\nA TIED PRICE IS NOT DECIDED BY DRAG ORDER")
    def _tied(reverse):
        pair = [_VR(vendor="Alpha", file="a", document_currency="INR", lines=[
                    _line("BX-001", "Box A", 40.0, "per box"),
                    _line("BX-002", "Box B", 60.0, "per box")]),
                _VR(vendor="Beta", file="b", document_currency="INR", lines=[
                    _line("BX-001", "Box A", 40.0, "per box"),
                    _line("BX-002", "Box B", 60.0, "per box")])]
        if reverse:
            pair.reverse()
        rfx_module.set_active(derive_module.derive_spec(pair))
        from core import award as _award                      # noqa: E402
        return [(l.sku, l.winner) for l in _award.recommend(
            assemble_module.build(pair)).lines]
    check("the same two quotes award the same way either way round",
          _tied(False) == _tied(True), (_tied(False), _tied(True)))

    print("\nA CATALOGUE THAT VARIES ONLY BY A NUMBER STAYS A CATALOGUE")
    # Every one of these collapsed onto a single row before: the figures that
    # tell the items apart were being thrown away as too short to matter.
    import itertools as _it                                    # noqa: E402
    for catalogue in (
        ["Grade 5 Hex Nut M10", "Grade 8 Hex Nut M10"],
        ["Patch Cable Cat6 5 m", "Patch Cable Cat6 10 m"],
        ["Safety Helmet Yellow", "Safety Helmet Blue"],
        ["A4 Copier Paper 75 GSM", "A4 Copier Paper 80 GSM"],
        ["LED Monitor 24-inch Full HD", "LED Monitor 27-inch Full HD"],
        ["Ball Bearing 6204 2RS", "Ball Bearing 6205 2RS", "Ball Bearing 6206 2RS"],
        ["Corrugated Box 3-ply 400x300x250 mm",
         "Corrugated Box 5-ply 400x300x250 mm",
         "Corrugated Box 7-ply 400x300x250 mm"],
    ):
        rows = derive_module.derive_spec([_VR(
            vendor="A", file="a",
            lines=[_line(None, text, 10.0 + n, "per unit")
                   for n, text in enumerate(catalogue)])]).line_count
        check(f"{len(catalogue)} items differing by a number stay "
              f"{len(catalogue)} rows — {catalogue[0][:34]}",
              rows == len(catalogue), rows)

    big = [f"Component {chr(65 + i % 26)}{i} spec {i * 7} / {i * 3} / {i * 11} mm"
           for i in range(60)]
    wide = derive_module.derive_spec([
        _VR(vendor=f"V{k}", file="f",
            lines=[_line(None, text, 1.0, "per unit") for text in big])
        for k in range(3)])
    check("60 distinct items quoted by 3 suppliers make 60 rows",
          wide.line_count == 60, wide.line_count)

    print("\nTHE COMPARISON DOES NOT DEPEND ON UPLOAD ORDER")
    three = [_VR(vendor="Alpha", file="a", lines=[
                 _line(None, "3-ply Corrugated Box 300 x 200 x 150 mm", 20.0, "per box")]),
             _VR(vendor="Beta", file="b", lines=[
                 _line(None, "5-ply Corrugated Box 400 x 300 x 250 mm", 45.0, "per box")]),
             _VR(vendor="Gamma", file="c", lines=[
                 _line(None, "Die-cut Mailer Box 400 x 300 x 250 mm", 120.0, "per box")])]
    shapes = {derive_module.derive_spec(list(order)).line_count
              for order in _it.permutations(three)}
    check(f"every upload order gives the same comparison ({sorted(shapes)})",
          shapes == {3}, sorted(shapes))
    inner = {derive_module.derive_spec([_VR(vendor="V", file="v",
                                            lines=list(order))]).line_count
             for order in _it.permutations([r.lines[0] for r in three])}
    check(f"...and so does every line order within a file ({sorted(inner)})",
          inner == {3}, sorted(inner))

    print("\nA PRICE IS NEVER DROPPED IN SILENCE")
    twice = _VR(vendor="Alpha", file="a", document_currency="INR", lines=[
        _line(None, "5-ply Corrugated Box 400 x 300 x 250 mm", 45.0, "per box"),
        _line(None, "5-ply Corrugated Box 400 x 300 x 250 mm", 95.0, "per box")])
    rfx_module.set_active(derive_module.derive_spec([twice]))
    doubled = assemble_module.build([twice])
    check("a second price for one row is reported, not discarded",
          len(doubled.summaries[0].unplaced) == 1
          and doubled.summaries[0].unplaced[0]["value"] == 95.0,
          doubled.summaries[0].unplaced)
    check("...and the buyer is told above the grid",
          "could not place" in " ".join(
              assemble_module.comparability_warnings(doubled)))

    print("\nA PLACEHOLDER NEVER LANDS ON A REAL ITEM CODE")
    collide = derive_module.derive_spec([
        _VR(vendor="A", file="a", lines=[
            _line("ITEM-001", "Steel drum 200 litre", 3500.0, "per unit")]),
        _VR(vendor="B", file="b", lines=[
            _line(None, "Nitrile gloves size L, box of 100", 450.0, "per unit")])])
    check("a vendor's own ITEM-001 is not overwritten by a placeholder",
          collide.line_count == 2, collide.line_count)

    print("\nTHE MATCHER KNOWS NOTHING ABOUT PACKAGING")
    # The same ladder, on categories nothing in this codebase has heard of.
    def _cat(rows):
        return [rfx_module.RfxLine(code, text, 10, "per unit", "discrete")
                for code, text in rows]

    hardware = _cat([("IT-01", "Laptop 14-inch, 16 GB RAM, 512 GB SSD"),
                     ("IT-02", "Laptop 14-inch, 32 GB RAM, 1 TB SSD"),
                     ("IT-03", "Docking station, USB-C, dual monitor"),
                     ("IT-04", "Monitor 27-inch 4K IPS"),
                     ("IT-05", "Monitor 24-inch 1080p"),
                     ("IT-06", "Wireless keyboard and mouse set")])
    spares = _cat([("SP-01", "Ball bearing 6204 2RS, 20mm bore"),
                   ("SP-02", "Ball bearing 6205 2RS, 25mm bore"),
                   ("SP-03", "V-belt A-section, 1200 mm"),
                   ("SP-04", "Hydraulic hose 1/2 inch, 3 metre"),
                   ("SP-05", "Air filter cartridge, 150 mm")])

    for label, lines, trials in (
        ("IT hardware", hardware,
         [('14" notebook, 16GB RAM / 512GB SSD', "IT-01"),
          ("Laptop 14in, 32GB RAM, 1TB SSD", "IT-02"),
          ("27 inch 4K monitor, IPS panel", "IT-04"),
          ("USB-C docking station with dual display", "IT-03"),
          ("Keyboard + mouse, wireless", "IT-06")]),
        ("MRO spares", spares,
         [("Bearing 6204-2RS (20 mm bore)", "SP-01"),
          ("Bearing 6205 2RS 25 mm", "SP-02"),
          ("A section V belt 1200mm", "SP-03"),
          ("Filter cartridge for air, 150mm", "SP-05")]),
    ):
        wrong = [(text, match_module.match_one(_line(None, text, 1, "ea"),
                                               lines).rfx_sku, want)
                 for text, want in trials]
        wrong = [w for w in wrong if w[1] != w[2]]
        check(f"{label}: all {len(trials)} differently-worded lines still match",
              not wrong, wrong)

    check("a join is not evidence — 16GB, 16 GB and 16-GB read alike",
          match_module._tokens("16GB") & match_module._tokens("16 GB")
          & match_module._tokens("16-GB") >= {"16", "gb"})

    packaging_words = match_module.marker_vocabulary(
        [item.description for item in gen.CATALOGUE])
    check("the distinguishing words are learned, not listed",
          {"die-cut", "partition", "roll"} <= packaging_words
          and "box" not in packaging_words,
          "'box' is on 20 of 30 lines and marks nothing; 'die-cut' is on 3 "
          "and marks them sharply")
    check("...and the same code learns a different vocabulary elsewhere",
          "laptop" in match_module.marker_vocabulary(
              [r.description for r in hardware]),
          sorted(match_module.marker_vocabulary(
              [r.description for r in hardware]))[:6])

    # Two suppliers, a category nothing here has heard of, and no request at
    # all: the whole flow has to hold up on input it was never shaped around.
    def _usd(code, text, value, unit):
        return _EL(vendor_sku=code, description=text, quoted_value=value,
                   currency="USD", unit_text=unit)

    foreign_a = _VR(vendor="Northbridge", file="nb.xlsx", document_currency="USD",
                    lines=[_usd("NB-1", "Laptop 14-inch, 16 GB RAM, 512 GB SSD", 940, "each"),
                           _usd("NB-2", "Monitor 27-inch 4K IPS", 310, "each"),
                           _usd("NB-3", "Docking station, USB-C, dual monitor", 145, "each")])
    foreign_b = _VR(vendor="Delta", file="d.eml", document_currency="USD",
                    lines=[_usd(None, '14" notebook, 16GB RAM / 512GB SSD', 965, "per unit"),
                           _usd(None, "27 inch 4K monitor, IPS panel", 298, "per unit"),
                           _usd(None, "USB-C docking station with dual display", 151, "per unit")])
    foreign = derive_module.derive_spec([foreign_a, foreign_b])
    check("three products from two suppliers make three rows, in any category",
          foreign.line_count == 3, foreign.line_count)
    rfx_module.set_active(foreign)
    built = assemble_module.build([foreign_a, foreign_b])
    check("...and every row carries both suppliers' prices",
          all(len([c for c in built.cells
                   if c.rfx_sku == line.sku and c.original_value is not None]) == 2
              for line in foreign.lines))
    check("...priced in the currency they actually used", foreign.currency == "USD")

    print("\nA LINE WE CANNOT PLACE IS SHOWN, NOT DISCARDED")
    off_list = rfx_module.RfxSpec(
        lines=[rfx_module.RfxLine("BX-001", "5-ply corrugated box 400x300x250 mm",
                                  10, "per box", "discrete")])
    rfx_module.set_active(off_list)
    stray = assemble_module.build([coded])
    summary = stray.summaries[0]
    check("lines that answer nothing on the list are kept on the summary",
          len(summary.unplaced) == 3, len(summary.unplaced))
    check("...with the supplier's own wording and price",
          all(item["description"] and item["value"] for item in summary.unplaced))
    warned = " ".join(assemble_module.comparability_warnings(stray))
    check("...and the buyer is told above the grid",
          "could not place on your item list" in warned)
    rows = present.exceptions_frame(stray)
    check("...and they appear under Needs attention",
          int(rows["Status"].str.contains("Not on your list").sum()) == 3)
    check("the warning does not write \"Industries's\"",
          assemble_module._possessive("Eastern Packaging Industries")
          == "Eastern Packaging Industries'")

    print("\nTHE BUYER IS TOLD EXACTLY WHAT WAS DRAFTED")
    # The receipt counts the request itself rather than repeating the model's
    # account of its own work, so these assert against the object.
    told = rfx_module.RfxSpec(derived=False)
    examples_module.seed_full_request(told)
    receipt = present.draft_receipt(told, ["30 items added"])
    check("it opens by saying the draft was generated",
          receipt.startswith("**The draft RFQ has been generated.**"))
    check("it counts the items that are actually on the request",
          f"**{told.line_count} items**" in receipt, receipt.splitlines()[6:8])
    check("...the questions", f"**{len(told.criteria)} questions**" in receipt)
    check("...and the terms", f"**{len(told.terms)} terms**" in receipt)
    check("it names the currency suppliers must quote in",
          f"**{told.currency}**" in receipt)
    check("it prints the window in words a person would use",
          told.stamp(told.ends_at) in receipt, told.stamp(told.ends_at))
    check("a complete request is not told it is blocked",
          "Before you can send it" not in receipt)

    held = rfx_module.RfxSpec(derived=False)
    examples_module.seed_replenishment(held)
    held.starts_at = held.ends_at = held.vendor_category = ""
    blocked = present.draft_receipt(held)
    check("items awaiting acceptance are called out as such",
          "awaiting your acceptance" in blocked)
    check("...and everything outstanding is listed in one line",
          all(phrase in blocked for phrase in
              ("accept the proposed items", "set the open and close dates",
               "choose a vendor category")), blocked.splitlines()[-1])

    nothing = present.draft_receipt(rfx_module.RfxSpec(derived=False))
    check("an empty draft is NOT announced as generated",
          "has been generated" not in nothing
          and nothing.startswith("**No request was generated"))

    print("\nAN EDIT THAT CHANGES NOTHING MUST NOT LOOK LIKE AN EDIT")
    # Each of these normalises to the value already held. The page reruns on
    # what apply_criteria_edits reports, so a False here is the difference
    # between a working tab and one that spins forever.
    loopy = rfx_module.RfxSpec(derived=False)
    examples_module.seed_full_request(loopy)

    same = present.draft_criteria_frame(loopy)
    check("re-applying an untouched table reports no change",
          present.apply_criteria_edits(loopy, same) is False)

    zeroed = present.draft_criteria_frame(loopy)
    zeroed.loc[0, "Weight"] = 0
    check("a weight of zero is a real answer, not a missing one",
          present.apply_criteria_edits(loopy, zeroed) is True
          and loopy.criteria[0].weight == 0.0,
          loopy.criteria[0].weight)
    check("...and applying it twice settles",
          present.apply_criteria_edits(loopy, present.draft_criteria_frame(loopy))
          is False)

    stray_only = present.draft_criteria_frame(loopy)
    stray_only.loc[len(stray_only)] = {
        "S. No.": None, "Question": "", "Target": 95, "Unit": "%",
        "Direction": "at least", "Requirement": "Scored", "Weight": 1}
    check("a target typed before its question reports no change",
          present.apply_criteria_edits(loopy, stray_only) is False)

    spaced = present.draft_criteria_frame(loopy)
    spaced.loc[0, "Unit"] = "   "
    check("a whitespace-only unit reports no change",
          present.apply_criteria_edits(loopy, spaced) is False)

    renamed = present.draft_criteria_frame(loopy)
    previous_variants = list(loopy.criteria[0].variants)
    previous_key = loopy.criteria[0].key
    renamed.loc[0, "Question"] = loopy.criteria[0].question + " (updated)"
    present.apply_criteria_edits(loopy, renamed)
    check("renaming a question keeps the phrasings suppliers used",
          all(v in loopy.criteria[0].variants for v in previous_variants),
          loopy.criteria[0].variants)
    check("...and keeps its key, so the answers stay attached to it",
          loopy.criteria[0].key == previous_key, loopy.criteria[0].key)

    collide = present.draft_criteria_frame(loopy)
    collide.loc[1, "Question"] = collide.loc[0, "Question"]
    present.apply_criteria_edits(loopy, collide)
    check("two questions never share a key, which would overwrite a score",
          len({c.key for c in loopy.criteria}) == len(loopy.criteria))

    ignored = present.draft_criteria_frame(loopy)
    ignored.loc[0, "Requirement"] = "Ignore"
    present.apply_criteria_edits(loopy, ignored)
    check("'Ignore' survives the table instead of being forced to 'Scored'",
          loopy.criteria[0].requirement == "Ignore",
          loopy.criteria[0].requirement)

    check("an emptied number cell falls back instead of becoming NaN",
          present.number_or(float("nan"), 1.0) == 1.0
          and present.number_or(None, 1.0) == 1.0
          and present.number_or(0, 1.0) == 0.0)

    print("\nTHE TERMS TEXTBOX SURVIVES A ROUND TRIP")
    for label, terms in [
        ("a term whose text runs to several lines",
         {"charges": "Packaging must be quoted.\nTooling must be quoted."}),
        ("a long term name", {"packaging, palletisation and handling": "quote it"}),
        ("a term with no text yet", {"payment": "45 days", "delivery": ""}),
        ("a name that itself contains a colon", {"incoterm: 2020": "DDP Bengaluru"}),
        ("unicode and rupees", {"tax": "GST 18% — ₹50 lakh threshold"}),
    ]:
        probe = rfx_module.RfxSpec(derived=False)
        probe.terms.update(terms)
        rendered = present.draft_terms_text(probe)
        present.apply_terms_text(probe, rendered)
        first = dict(probe.terms)
        present.apply_terms_text(probe, present.draft_terms_text(probe))
        check(f"{label} survives being saved unchanged",
              probe.terms == first and all(
                  value.strip() in "\n".join(first.values())
                  for value in terms.values() if value.strip()),
              f"{terms} -> {first}")

    print("\nWHAT A REQUEST MAY NOT BE SENT WITHOUT")
    bare = rfx_module.RfxSpec(derived=False)
    check("an untouched request names all four things it is missing",
          rfx_module.missing_mandatory(bare, 0) == [
              "RFQ start date and time", "RFQ end date and time",
              "Vendor category", "At least one supplier"],
          rfx_module.missing_mandatory(bare, 0))
    bare.starts_at = "2026-09-01T09:00"
    bare.ends_at = "2026-09-12T17:00"
    check("setting the window clears both date requirements",
          rfx_module.missing_scope(bare) == ["Vendor category"],
          rfx_module.missing_scope(bare))
    bare.vendor_category = "Corrugated boxes"
    check("...and the scope is then complete",
          rfx_module.missing_scope(bare) == [])
    check("but a request addressed to nobody still cannot go",
          rfx_module.missing_mandatory(bare, 0) == ["At least one supplier"])
    check("one supplier is enough to clear the last of it",
          rfx_module.missing_mandatory(bare, 1) == [])
    check("a fully drafted request has nothing outstanding",
          rfx_module.missing_mandatory(hand, len(hand.invited) or 3) == [],
          rfx_module.missing_mandatory(hand, 3))

    check("and the edited request is still what gets sent",
          len(rfxdoc.sendable_lines(hand)) == len(hand.lines)
          and len(rfxdoc.build_pdf(hand)) > 2000)

    print("\nTHE APPROVED VENDOR LIST, AND WHO GETS ASKED")
    from core import vendors as vendors_module  # noqa: E402
    directory = vendors_module.categories()
    check(f"{len(directory)} vendor categories in one functional area "
          f"({vendors_module.functional_area()})", 3 <= len(directory) <= 5)
    check("each carries 3-4 approved suppliers",
          all(3 <= len(c.vendors) <= 4 for c in directory),
          str({c.name: len(c.vendors) for c in directory}))

    every = [v for c in directory for v in c.vendors]
    check("every supplier has a rating out of ten",
          all(0 < v.rating <= 10 for v in every))
    check("...derived from its four scores, not stored as a bare number",
          all(abs(v.rating - round(sum(v.scores[k] for k in vendors_module.SCORE_ORDER)
                                   / 4, 1)) < 0.05 for v in every))
    check("the five suppliers who actually quote are on the list",
          {SHAKTI, BALAJI, MERIDIAN, NORTHSTAR, PACIFIC}
          <= {v.name for v in every})

    boxes = vendors_module.category("corrugated_boxes")
    picked, why = vendors_module.recommend(boxes)
    check("the recommendation is ordered best-rated first",
          [v.name for v in boxes.ranked()][0] == SHAKTI)
    check(f"it shortlists the {len(picked)} clearing "
          f"{vendors_module.RECOMMEND_AT:g}, and drops the one that does not",
          NORTHSTAR not in {v.name for v in picked} and len(picked) == 3)
    check("...and says so in words a buyer can act on",
          "rate 7 or better" in why and "who is asked, not who wins" in why)

    lonely = vendors_module.Category(
        key="x", name="Thin category",
        vendors=[vendors_module.DirectoryVendor(
                     name="Only Good One",
                     scores={k: 9 for k in vendors_module.SCORE_ORDER}),
                 vendors_module.DirectoryVendor(
                     name="Next Best",
                     scores={k: 5 for k in vendors_module.SCORE_ORDER})])
    thin, thin_why = vendors_module.recommend(lonely)
    check("a category with one good supplier still shortlists two",
          len(thin) == vendors_module.MINIMUM_SHORTLIST)
    check("...and explains why the second was added",
          "not a competitive request" in thin_why)

    print("\nDATES, NOTES AND ATTACHMENTS REACH THE SUPPLIER")
    full_request = rfx_module.RfxSpec()
    examples_module.seed_full_request(full_request)
    check("the worked example opens with a live sourcing window",
          bool(full_request.starts_at) and bool(full_request.ends_at)
          and full_request.ends_at > full_request.starts_at)
    check("...with a time on each end, not a bare date",
          "T" in full_request.starts_at and "T" in full_request.ends_at,
          f"{full_request.starts_at} / {full_request.ends_at}")
    check("...and a countable number of days between them",
          full_request.window_days == 12, str(full_request.window_days))
    check("both ends read as a person would write them",
          full_request.stamp(full_request.ends_at).endswith("17:00"),
          full_request.stamp(full_request.ends_at))
    check("...and a vendor category the directory recognises",
          vendors_module.category(full_request.vendor_category) is not None,
          full_request.vendor_category)
    check("...and the issuer's own notes", "shutdown" in full_request.notes)

    full_request.attachments = [
        {"name": "BX-011_drawing_revC.pdf", "data": b"%PDF-1.4 drawing",
         "size": 16, "note": "Drawing for the 7-ply, rev C"},
        {"name": "delivery_schedule.csv", "data": b"month,qty", "size": 9, "note": ""},
    ]
    document = rfxdoc.build_pdf(full_request, token="RFX-A-B-1234", vendor="Someone")
    from pypdf import PdfReader as _R  # noqa: E402
    import io as _io  # noqa: E402
    printed = "".join(page.extract_text() or ""
                      for page in _R(_io.BytesIO(document)).pages)
    check("the request prints both ends of the window, not just a deadline",
          full_request.stamp(full_request.starts_at) in printed
          and full_request.stamp(full_request.ends_at) in printed)
    check("...labelled as the RFQ starting and ending",
          "RFQ starts" in printed and "RFQ ends" in printed)
    check("...the category it is aimed at", "Corrugated boxes" in printed)
    check("...the buyer's notes", "shutdown" in printed)
    check("...and what was enclosed, so a supplier can tell if a file is missing",
          "BX-011_drawing_revC.pdf" in printed and "Enclosed" in printed)

    box = os.path.join(tempfile.mkdtemp(), "outbox")
    sent_with_files = dispatch.send_request(
        full_request, [dispatch.Vendor("Someone", "s@example.com")],
        dispatch.MailboxChannel(directory=box))
    carried = ingest.load_path(sent_with_files[0].receipt.location)
    check("every attachment rides along on the invitation itself",
          "BX-011_drawing_revC.pdf" in " ".join(carried.warnings)
          and "delivery_schedule.csv" in " ".join(carried.warnings),
          str(carried.warnings[:1]))

    files_frame = present.attachment_frame(full_request)
    files_frame.loc[0, "What it is"] = "Rev C drawing, supersedes rev B"
    files_frame = files_frame.drop(index=1).reset_index(drop=True)
    present.apply_attachment_edits(full_request, files_frame)
    check("an attachment note can be edited and a file removed",
          len(full_request.attachments) == 1
          and full_request.attachments[0]["note"].startswith("Rev C"))
    check("...and the bytes survive the edit, because they never went near the table",
          full_request.attachments[0]["data"] == b"%PDF-1.4 drawing")

    ticked = present.directory_frame(boxes, {SHAKTI})
    check("the supplier table marks who is ticked",
          list(ticked["Ask"]) == [True, False, False, False])
    check("...and converts a tick into an addressable supplier",
          [v.name for v in present.selected_vendors(ticked)] == [SHAKTI])

    print("\nSENDING IT  (stubbed transport, real artefact, real identifier)")
    invited = [dispatch.Vendor("Shakti Packaging Industries Pvt Ltd", "s@example.com"),
               dispatch.Vendor("Meridian Packaging LLP", "m@example.com")]
    outbox = os.path.join(tempfile.mkdtemp(), "outbox")
    invitations = dispatch.send_request(
        draft_spec, invited, dispatch.MailboxChannel(directory=outbox))
    check("every supplier got an invitation",
          len(invitations) == 2 and all(i.status == "sent" for i in invitations))
    check("each carries its own quote reference",
          invitations[0].token != invitations[1].token)
    written = os.path.join(outbox, f"{invitations[0].token}.eml")
    check("the invitation is a real mail file on disk, not a print statement",
          os.path.getsize(written) > 2000)

    body = open(written, encoding="utf-8", errors="replace").read()
    check("the request document is attached to it", "application/pdf" in body)
    found = dispatch.match_response(body, invitations)
    check("a reply quoting the reference identifies its supplier exactly",
          found is not None and found.vendor.name == invited[0].name)
    check("a mistyped reference resolves to nobody rather than the wrong supplier",
          dispatch.match_response("our ref RFX-RFXCORR202-SHAKTI-0000", invitations) is None)
    check("a reply carrying its reference is identified, and says so",
          dispatch.identify(body, invitations)[1] == "token")
    check("a reply that only carries a letterhead is a name match, not an "
          "identification",
          dispatch.identify("Quotation from Meridian Packaging LLP",
                            invitations)[1] == "name")
    check("...and nothing recognisable is neither",
          dispatch.identify("Dear sir, please find our rates.",
                            invitations)[1] == "none")

    check("a reply with no reference still falls back to the supplier's name",
          (dispatch.match_response("Quotation from Meridian Packaging LLP",
                                   invitations) or invitations[0]).vendor.name
          == invited[1].name)

    print("\nCOMPARING AGAINST THE REQUEST AS SENT")
    sent_spec = rfx_module.RfxSpec(derived=True)
    sent_tools = draft_module._tools(sent_spec, [])
    sent_tools["set_scope"](title="Corrugated packaging", currency="INR")
    for item in gen.CATALOGUE:
        unit = {"sheet": "per sheet", "roll": "per roll",
                "consumable": "per roll"}.get(item.family, "per box")
        sent_tools["add_line"](sku=item.sku, description=item.description,
                               unit=unit, quantity=item.quantity)
    # An item the buyer asked for and nobody quoted. On a spine derived from
    # the replies this line cannot exist at all -- which is exactly the failure
    # a buyer would never catch.
    sent_tools["add_line"](sku="BX-099", description="Pallet wrap 500 mm",
                           unit="per roll", quantity=400)
    rfx_module.set_active(sent_spec)
    against = pipeline.run_paths(SAMPLES,
                                 db_path=os.path.join(tempfile.mkdtemp(), "sent.db"),
                                 build_spine=False)
    check("the comparison uses the buyer's list, not one inferred from replies",
          rfx_module.active().line_count == len(gen.CATALOGUE) + 1)
    unpriced = [line.sku for line in rfx_module.active().lines
                if all((against.comparison.cell(line.sku, vendor) is None
                        or against.comparison.cell(line.sku, vendor).status == "Not Quoted")
                       for vendor in against.comparison.vendors)]
    check("an item nobody quoted survives as a gap instead of disappearing",
          unpriced == ["BX-099"], str(unpriced))
    rfx_module.set_active(spine_before)

    print("\nCOMPARABILITY WARNINGS")
    from core.assemble import comparability_warnings
    warnings = comparability_warnings(comparison)
    check("delivery asymmetry is surfaced",
          any("Delivery is not included the same way" in w for w in warnings))
    check("assumed currency is surfaced",
          any("had to guess the currency" in w for w in warnings))
    check("incomplete coverage is surfaced",
          any("did not price everything" in w for w in warnings))
    check("unsupplied references are surfaced",
          any("documents we were never sent" in w for w in warnings))
    check("warnings avoid procurement jargon",
          not any(word in w for w in warnings
                  for word in ("ex-freight", "landed cost", "annualized")))

    print("\nHOSTILE AND ORDINARY INPUT THE IO LAYER USED TO FALL OVER ON")
    import io as _io
    import math as _math
    from core import extract as extract_module
    from core import ingest as ingest_module
    from core import llm as llm_module
    from core.models import DocumentPayload
    from core.rfx import RfxLine, RfxSpec

    # ReportLab reads a Paragraph as mini-HTML, so an unescaped "<" in a
    # description ended the parse with an unclosed tag and took Preview and
    # Send down together.
    angry = RfxSpec(
        title="Q3 Packaging & Print <all sites>",
        reference="RFQ/2026<01>",
        lines=[RfxLine(sku="BX-1<A", description="Grade A<B carton & liner",
                       quantity=100, canonical_unit="per box",
                       unit_family="discrete", note="R&D <see drawing>")],
        terms={"payment": "60 days & 2% <net>"},
        notes="Tolerance < 2mm & no substitutions",
    )
    try:
        rendered = rfxdoc.build_pdf(angry, token="RFX-A-B-abcd", vendor="Böx & Co <IN>")
        pdf_ok = rendered.startswith(b"%PDF")
    except Exception as exc:                       # noqa: BLE001
        rendered, pdf_ok = b"", False
        print(f"       {type(exc).__name__}: {exc}")
    check("an ampersand or a '<' in the buyer's own words still renders a PDF",
          pdf_ok)

    # Two suppliers whose names share their first six letters used to get the
    # same token -- and the mailbox channel names the file after the token, so
    # one invitation overwrote the other.
    check("similarly-named suppliers get different quote references",
          dispatch.make_token(angry, "Prime Packaging Ltd")
          != dispatch.make_token(angry, "Prime Packers"))
    twins = dispatch.send_request(
        angry,
        [dispatch.Vendor("Prime Packaging Ltd"), dispatch.Vendor("Prime Packers")],
        channel=dispatch.MailboxChannel(directory=tempfile.mkdtemp()))
    check("...and two invitations, not one written over the other",
          len({inv.receipt.location for inv in twins}) == 2)

    short = [dispatch.Invitation(dispatch.Vendor("AB"), "RFX-A-AB-1111"),
             dispatch.Invitation(dispatch.Vendor("Meridian Packaging"),
                                 "RFX-A-MERIDI-2222")]
    check("a two-letter supplier name does not match every document",
          dispatch.identify("available fabrication table", short)[1] == "none")
    check("a letterhead still identifies its supplier",
          dispatch.identify("Quotation from Meridian Packaging", short)[1] == "name")
    both = [dispatch.Invitation(dispatch.Vendor("Meridian Packaging"), "RFX-A-M-1111"),
            dispatch.Invitation(dispatch.Vendor("Shakti Packaging"), "RFX-A-S-2222")]
    check("two supplier names in one document identify nobody, rather than the "
          "first one listed",
          dispatch.identify("we forward the note sent to Meridian Packaging "
                            "and Shakti Packaging", both)[0] is None)

    check("a stated range gives up its first figure instead of being discarded",
          extract_module._as_float("30-35 days") == 30.0)
    check("an Indian-grouped figure reads correctly",
          extract_module._as_float("₹1,05,000") == 105000.0)
    check("Infinity and NaN never become a price",
          extract_module._as_float(float("inf")) is None
          and extract_module._as_float(float("nan")) is None
          and extract_module._as_int(float("inf")) is None)

    malformed = extract_module.parse_response(
        ["a bare list where an object was asked for"],
        DocumentPayload(file="odd.txt", text="x"))
    check("a document returned in the wrong shape reads as empty, not a crash",
          malformed.lines == [])
    stringy = extract_module.parse_response(
        {"vendor": "Odd Ltd",
         "lines": ["not an object",
                   {"description": "5-ply box", "quoted_value": 42,
                    "conditions": "subject to plate charges"}],
         "terms": ["E&OE"]},
        DocumentPayload(file="odd.txt", text="x"))
    check("a malformed line is skipped and the good one kept",
          len(stringy.lines) == 1 and stringy.lines[0].quoted_value == 42)
    check("a condition sent as a string stays one condition, not 26 letters",
          stringy.lines[0].conditions == ["subject to plate charges"])
    check("a term sent as a string is still recorded",
          [t.text for t in stringy.terms] == ["E&OE"])

    # A CSV saved by Excel on Windows is cp1252: decoding it as UTF-8 with
    # errors="ignore" deleted the currency symbol and the whole document then
    # read as currency-silent.
    pound = ingest_module.read_csv(
        _io.BytesIO("BX-001,5-ply box,£4.20 per kg\n".encode("cp1252")), "w.csv")
    check("a Windows-encoded CSV keeps its currency symbol", "£" in pound.text)
    check("an Outlook .msg says what it is instead of reading as an empty quote",
          ingest_module.load(_io.BytesIO(b"\xd0\xcf\x11\xe0"), "reply.msg").reader
          == "unsupported")
    deep = ingest_module.read_eml(_io.BytesIO(b"Subject: x\n\nbody"), "n.eml",
                                  depth=ingest_module.MAX_EMAIL_DEPTH + 1)
    check("a message nested past the limit is read flat rather than recursing",
          "nesting limit" in deep.reader)

    check("a token count quoting '500' is not mistaken for a busy model",
          not llm_module.is_transient(
              ValueError("INVALID_ARGUMENT: input exceeds 1500000 tokens")))
    check("...but a real 503 still is",
          llm_module.is_transient(RuntimeError("503 UNAVAILABLE: high demand")))

    print("\nTHE DATABASE THE ANALYST IS GIVEN")
    check("a fresh comparison starts with an empty recommendation table, not "
          "the previous one's winners",
          store.query_frame("SELECT * FROM award", path=db_path).empty)
    check("replace() is a string function, not a forbidden write",
          not store.query_frame(
              "SELECT replace(description, '-', ' ') AS d FROM rfx_lines LIMIT 1",
              path=db_path).empty)
    for forbidden in ("DELETE FROM quotes", "SELECT 1; DROP TABLE quotes",
                      "PRAGMA table_info(quotes)", "UPDATE vendors SET vendor='x'"):
        try:
            store.run_query(forbidden, path=db_path)
            refused = False
        except store.QueryError:
            refused = True
        check(f"the analyst's SQL surface refuses: {forbidden[:28]}", refused)
    awkward = store.get_evidence("BX-001; DROP", "O'Brien & Co (update)",
                                 path=db_path)
    check("an item code or supplier name that looks like SQL is data, not syntax",
          awkward["found"] is False)
    check("every browser session gets its own comparison database",
          config.new_session_db_path() != config.new_session_db_path())
    check("no cell survives as a non-finite number",
          all(cell.canonical_value is None or _math.isfinite(cell.canonical_value)
              for cell in comparison.cells))

    total = len(PASS) + len(FAIL)
    print(f"\n{'=' * 64}\n{len(PASS)}/{total} checks passed")
    if FAIL:
        print("FAILED:")
        for label in FAIL:
            print(f"  - {label}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
