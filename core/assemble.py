"""Assemble extracted responses into the comparison.

extraction (vendor's terms) → matching (buyer's line index) → normalisation
(buyer's units and currency) → the grid.

Nothing here talks to a model. Given the same extractions it produces the same
comparison every time, which is what makes the result auditable.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd

from . import config, criteria as criteria_module, normalize
from .match import MatchReport, match_lines
from .models import Cell, VendorResponse
from . import rfx as rfx_module


@dataclass
class VendorSummary:
    vendor: str
    file: str
    coverage_quoted: int
    coverage_total: int
    comparable_lines: int
    not_quoted: list[str]
    extra_lines: int
    scorecard: object                      # criteria.Scorecard
    quality_score: float
    meets_requirements: bool
    hard_failures: list[str]
    unanswered: list[str]
    disclosed_figures: int
    freight_included: Optional[bool]
    payment_terms_days: Optional[int]
    lead_time_days: Optional[float]
    document_currency: Optional[str]
    currency_assumed: bool
    unresolved_references: list[str]
    overall_confidence: float
    discounts: list[dict] = field(default_factory=list)
    # The lines themselves, not only how many. A count told the buyer nothing
    # they could act on -- and it was never shown anywhere, so a supplier
    # whose whole quote sat outside the request looked like a supplier whose
    # file could not be read.
    unplaced: list[dict] = field(default_factory=list)

    @property
    def coverage_label(self) -> str:
        return f"{self.coverage_quoted}/{self.coverage_total}"


@dataclass
class Comparison:
    responses: list[VendorResponse] = field(default_factory=list)
    reports: dict[str, MatchReport] = field(default_factory=dict)
    cells: list[Cell] = field(default_factory=list)
    summaries: list[VendorSummary] = field(default_factory=list)
    criteria: list = field(default_factory=list)
    scorecards: dict = field(default_factory=dict)

    @property
    def vendors(self) -> list[str]:
        return [summary.vendor for summary in self.summaries]

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame([cell.to_row() for cell in self.cells])

    def cell(self, sku: str, vendor: str) -> Optional[Cell]:
        for item in self.cells:
            if item.rfx_sku == sku and item.vendor == vendor:
                return item
        return None

    def price_matrix(self, normalized: bool = True) -> pd.DataFrame:
        """RFx lines as rows, vendors as columns. Non-comparable cells are NaN."""
        records = []
        for cell in self.cells:
            if normalized:
                value = cell.canonical_value if cell.comparable else None
            else:
                value = cell.original_value
            records.append({"rfx_sku": cell.rfx_sku, "vendor": cell.vendor, "value": value})
        if not records:
            return pd.DataFrame()
        frame = pd.DataFrame(records).pivot(index="rfx_sku", columns="vendor", values="value")
        return frame.reindex([line.sku for line in rfx_module.active().lines])


def build(
    responses: list[VendorResponse],
    adjudicate: Optional[Callable] = None,
) -> Comparison:
    comparison = Comparison(responses=list(responses))

    # Quality answers are scored against the derived criteria, not gated on a
    # fixed checklist. See core/criteria.py for why.
    spec_criteria = rfx_module.active().criteria
    _, raw_answers = criteria_module.derive_criteria(responses)
    scorecards = {
        response.vendor: criteria_module.build_scorecard(
            response.vendor, spec_criteria, raw_answers.get(response.vendor, {}))
        for response in responses
    }
    # A copy, not the buyer's own objects. The compare page lets a buyer
    # change a weight or mark a question must-have while judging the replies,
    # and those controls wrote straight through to the criteria on the drafted
    # request -- so the document already sent to suppliers silently acquired a
    # requirement nobody put in it, and re-analysing could not undo it. The
    # answers are the suppliers'; the scoring is the buyer's; the request as
    # issued is neither's to edit after the fact.
    comparison.criteria = [copy.deepcopy(item) for item in spec_criteria]
    comparison.scorecards = scorecards

    for response in responses:
        spec = rfx_module.active()
        report = match_lines(response.lines, spec.lines, adjudicate=adjudicate)
        comparison.reports[response.vendor] = report

        # A document is "currency silent" only if nothing anywhere stated one.
        line_currencies = {
            (line.currency or "").upper() for line in response.lines if line.currency
        }
        currency_assumed = not line_currencies and not response.document_currency

        for rfx_line in spec.lines:
            extracted = report.by_sku.get(rfx_line.sku)
            if extracted is None:
                comparison.cells.append(
                    normalize.not_quoted(rfx_line, response.vendor)
                )
                continue

            match_result = report.match_by_sku[rfx_line.sku]
            comparison.cells.append(
                normalize.normalize(
                    rfx_line=rfx_line,
                    extracted=extracted,
                    vendor=response.vendor,
                    document_currency=response.document_currency,
                    match_basis=match_result.basis,
                    match_confidence=match_result.confidence,
                    freight_included=response.freight_included,
                )
            )

        card = scorecards[response.vendor]
        comparable = sum(
            1 for cell in comparison.cells
            if cell.vendor == response.vendor and cell.comparable
        )

        comparison.summaries.append(
            VendorSummary(
                vendor=response.vendor,
                file=response.file,
                coverage_quoted=len(report.by_sku),
                coverage_total=spec.line_count,
                comparable_lines=comparable,
                not_quoted=report.not_quoted,
                extra_lines=len(report.extra_lines),
                # Both kinds of dropped line. `extra_lines` answer nothing on
                # the list; `duplicates` were beaten to a row by a
                # higher-confidence line from the same supplier. The second
                # kind used to vanish in silence, under a warning that said
                # "Nothing here is lost" -- and a supplier quoting two
                # genuinely different products that happened to match one row
                # lost a real price that way.
                unplaced=[{
                    "code": extra.vendor_sku or "—",
                    "description": extra.description or "—",
                    "value": extra.quoted_value,
                    "currency": extra.currency,
                    "unit": extra.unit_text or "",
                    "why": "not on your list",
                } for extra in report.extra_lines] + [{
                    "code": dropped.vendor_sku or "—",
                    "description": dropped.description or "—",
                    "value": dropped.quoted_value,
                    "currency": dropped.currency,
                    "unit": dropped.unit_text or "",
                    "why": f"a second price for {sku}",
                } for sku, dropped in report.duplicates],
                scorecard=card,
                quality_score=card.overall,
                meets_requirements=card.meets_requirements,
                hard_failures=list(card.hard_failures),
                unanswered=list(card.unanswered),
                disclosed_figures=card.disclosed,
                freight_included=response.freight_included,
                payment_terms_days=response.payment_terms_days,
                lead_time_days=response.lead_time_days,
                document_currency=response.document_currency,
                currency_assumed=currency_assumed,
                unresolved_references=list(response.unresolved_references),
                overall_confidence=response.overall_confidence,
                discounts=[
                    {"text": term.text, "trigger": term.trigger, "value": term.value}
                    for term in response.terms if term.kind == "discount"
                ],
            )
        )

    return comparison


def rescore(comparison: Comparison) -> None:
    """Recompute quality scores after the buyer changes a target or a weight.

    The suppliers' answers never change -- only what the buyer decided to
    require, weight or ignore. Keeping those two things separate is the whole
    point: the data is theirs, the judgement is the buyer's.
    """
    answers = {
        summary.vendor: {key: scored.answer
                         for key, scored in summary.scorecard.results.items()}
        for summary in comparison.summaries
    }
    for summary in comparison.summaries:
        card = criteria_module.build_scorecard(
            summary.vendor, comparison.criteria, answers[summary.vendor])
        summary.scorecard = card
        summary.quality_score = card.overall
        summary.meets_requirements = card.meets_requirements
        summary.hard_failures = list(card.hard_failures)
        summary.unanswered = list(card.unanswered)
        summary.disclosed_figures = card.disclosed
        comparison.scorecards[summary.vendor] = card


# ---------------------------------------------------------------------------
# comparability warnings -- things that make a naive ranking wrong
# ---------------------------------------------------------------------------

def _join(names: list[str]) -> str:
    """'A', 'A and B', 'A, B and C' -- reads like a sentence, not a CSV."""
    names = list(names)
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " and " + names[-1]


def _possessive(name: str) -> str:
    """Kavitha's, but Industries' -- a name already ending in s takes a bare
    apostrophe, and "Industries's" is the sort of small wrongness that makes a
    careful reader distrust the careful things."""
    name = (name or "").strip()
    return f"{name}'" if name.endswith(("s", "S")) else f"{name}'s"


def comparability_warnings(comparison: Comparison) -> list[str]:
    """Reasons the cheapest price on screen may not be the cheapest real price.

    Written in plain language and put above the grid rather than in a footnote.
    A buyer skimming this should understand the risk without knowing what
    "ex-freight" or "basis" mean.
    """
    warnings: list[str] = []

    # First, because it is the one that makes the rest of the screen
    # misleading. Everything else here qualifies a comparison; this says part
    # of what a supplier sent is not in the comparison at all.
    unplaced = [s for s in comparison.summaries if s.unplaced]
    if unplaced:
        total = sum(len(s.unplaced) for s in unplaced)
        parts = ", ".join(f"**{s.vendor}** {len(s.unplaced)}" for s in unplaced)
        worst = max(unplaced, key=lambda s: len(s.unplaced))
        whole = [s for s in unplaced if s.coverage_quoted == 0]
        warnings.append(
            f"**{total} priced line{'' if total == 1 else 's'} we read but "
            f"could not place on your item list.**\n\n"
            f"These were extracted correctly — they simply do not correspond to "
            f"anything you asked for: {parts}. They are listed under "
            f"**Needs attention**, with the supplier's own wording and price.\n\n"
            + ("Every line from "
               + _join([s.vendor for s in whole])
               + " is in that position, which usually means "
               + ("they are" if len(whole) > 1 else "it is")
               + " quoting a different catalogue from the one your request "
                 "describes. Compare these responses without a request loaded, "
                 "or add the items to your request, and they will line up.\n\n"
               if whole else "")
            + f"Nothing here is lost — but a total that ignores "
              f"{_possessive(worst.vendor)} unplaced lines is not that "
              f"supplier's whole offer.")

    freight_in = [s.vendor for s in comparison.summaries if s.freight_included is True]
    freight_out = [s.vendor for s in comparison.summaries if s.freight_included is False]
    freight_silent = [s.vendor for s in comparison.summaries if s.freight_included is None]
    freight_extra = freight_out + freight_silent

    if freight_in and freight_extra:
        includes = "includes" if len(freight_in) == 1 else "include"
        charges = "charges" if len(freight_extra) == 1 else "charge"
        warnings.append(
            "**Delivery is not included the same way.**\n\n"
            f"{_join(freight_in)} {includes} delivery in their prices. "
            f"{_join(freight_extra)} {charges} it on top. No supplier said how "
            "much delivery costs.\n\n"
            "Every price below is shown exactly as that supplier quoted it. "
            "Nothing was added and nothing was taken out — so the prices are "
            "**not on the same footing**: some already carry delivery and some "
            "do not.\n\n"
            f"{_join(freight_in)} therefore "
            f"{'looks' if len(freight_in) == 1 else 'look'} more expensive than "
            f"{'it is' if len(freight_in) == 1 else 'they are'}. "
            "Ask the others what delivery costs before you decide; until then "
            "the cheapest price on a line is not necessarily the cheapest "
            "delivered cost."
        )

    assumed = [s.vendor for s in comparison.summaries if s.currency_assumed]
    if assumed:
        currency_name = {"INR": "rupees", "USD": "US dollars",
                         "EUR": "euros", "GBP": "pounds"}.get(
                             config.BASE_CURRENCY, config.BASE_CURRENCY)
        warnings.append(
            f"**We had to guess the currency for {_join(assumed)}.**\n\n"
            "Their document never says which currency the prices are in. We assumed "
            f"{currency_name}, because that is what the RFx asked for.\n\n"
            "Check this with them before you award anything."
        )

    discounting = [s for s in comparison.summaries if s.discounts]
    if discounting:
        offers = []
        for summary in discounting:
            for discount in summary.discounts:
                percent = f"{discount['value']:g}%" if discount.get("value") else "a discount"
                offers.append(f"**{summary.vendor}** offers {percent}")
        warnings.append(
            "**Discounts are not included in the prices below.**\n\n"
            + _join(offers) + ", but only if you buy enough.\n\n"
            "Each supplier counts \"enough\" differently, so the offers cannot be "
            "compared to each other. Treat the prices below as before-discount."
        )

    partial = [s for s in comparison.summaries if s.coverage_quoted < s.coverage_total]
    if partial:
        detail = _join([f"**{s.vendor}** priced {s.coverage_quoted} of "
                        f"{s.coverage_total}" for s in partial])
        warnings.append(
            "**Some suppliers did not price everything.**\n\n"
            f"{detail}.\n\n"
            "Do not compare their totals — they are adding up different lists of "
            "items. Compare one line at a time instead."
        )

    unresolved: dict[str, list[str]] = {}
    for summary in comparison.summaries:
        if summary.unresolved_references:
            unresolved.setdefault(summary.vendor, []).extend(summary.unresolved_references)
    if unresolved:
        lines = [f"**{vendor}** points to {_join([chr(8220) + r + chr(8221) for r in refs])}"
                 for vendor, refs in unresolved.items()]
        warnings.append(
            "**Some prices point to documents we were never sent.**\n\n"
            + ". ".join(lines) + ".\n\n"
            "We cannot see those documents, so those lines are marked **Unresolved** "
            "and left out of the comparison."
        )

    return warnings
