"""Split-award recommendation: which supplier should get which lines.

The naive version of this is one line of pandas -- take the minimum per row.
The reasons this file is longer than that are all reasons a buyer would refuse
to act on the naive answer:

* **Only comparable prices may win.** A line where the cheapest figure is
  Unresolved or carries an unpriced extra is not awarded to anyone; it is
  listed as still needing a decision.

* **A one-horse race is not a win.** Where only one supplier could price a
  line, that line is marked single-source: it goes to them because there is no
  alternative, not because they were competitive. Buyers negotiate those
  differently.

* **Totals only compare on a common basket.** Suppliers priced different
  subsets, so "supplier A's total vs supplier B's total" is meaningless across
  their whole responses. The split-versus-single comparison is therefore run
  only over the lines every shortlisted supplier priced comparably, and the
  size of that basket is always reported alongside the saving.

* **A split with a tail is not executable.** Winning two lines out of sixty
  does not justify onboarding a supplier, raising a PO and managing a
  relationship. `min_lines` consolidates that tail into the next-cheapest
  supplier, and reports what the consolidation cost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import rfx as rfx_module
from .assemble import Comparison


@dataclass
class LineAward:
    sku: str
    description: str
    quantity: Optional[int]
    unit: str
    winner: Optional[str] = None
    price: Optional[float] = None
    extended: Optional[float] = None
    runner_up: Optional[str] = None
    runner_up_price: Optional[float] = None
    saving_per_unit: Optional[float] = None
    extended_saving: Optional[float] = None
    contenders: int = 0
    status: str = "awarded"        # awarded | single_source | no_comparable
    reason: str = ""
    reassigned_from: Optional[str] = None


@dataclass
class VendorAward:
    vendor: str
    lines: list[str] = field(default_factory=list)
    single_source_lines: list[str] = field(default_factory=list)
    extended_total: Optional[float] = None

    @property
    def line_count(self) -> int:
        return len(self.lines)


@dataclass
class AwardPlan:
    lines: list[LineAward] = field(default_factory=list)
    vendors: list[VendorAward] = field(default_factory=list)
    unawardable: list[LineAward] = field(default_factory=list)

    eligible: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    dropped_for_size: list[str] = field(default_factory=list)
    min_lines: int = 1

    total_extended: Optional[float] = None
    quantities_known: bool = False

    # split versus one supplier, judged only on the basket they all priced
    common_basket: int = 0
    split_on_common: Optional[float] = None
    best_single_vendor: Optional[str] = None
    best_single_total: Optional[float] = None
    saving_vs_single: Optional[float] = None
    # False when no supplier stated a quantity for some shared item: the two
    # totals are then sums of unit prices, which is a different animal from
    # money and has to be labelled as one.
    common_quantities_known: bool = True
    consolidation_cost: Optional[float] = None

    @property
    def awarded_lines(self) -> int:
        return sum(1 for line in self.lines if line.status != "no_comparable")

    @property
    def supplier_count(self) -> int:
        return len(self.vendors)

    def headline(self) -> str:
        """'Vendor A for 10 items, ABC for 6 and PrimePack for 2.'"""
        if not self.vendors:
            return "no supplier, on these responses."
        parts = [f"**{v.vendor}** for {v.line_count} "
                 f"{'item' if v.line_count == 1 else 'items'}" for v in self.vendors]
        if len(parts) == 1:
            return parts[0] + "."
        return ", ".join(parts[:-1]) + " and " + parts[-1] + "."


# ---------------------------------------------------------------------------

def _contenders(comparison: Comparison, sku: str,
                vendors: list[str]) -> list[tuple[str, float]]:
    """(vendor, price) for every comparable quote on this line, cheapest first."""
    offers = []
    for vendor in vendors:
        cell = comparison.cell(sku, vendor)
        if cell and cell.comparable and cell.canonical_value is not None:
            offers.append((vendor, cell.canonical_value))
    # Price first, then supplier name. Without the second key a tie went to
    # whichever file the buyer happened to upload first, so the same two
    # quotes produced a different award depending on drag order -- and it was
    # reported as a normal win rather than a coin toss.
    return sorted(offers, key=lambda pair: (pair[1], pair[0]))


def _allocate(comparison: Comparison, vendors: list[str]) -> list[LineAward]:
    awards: list[LineAward] = []
    for line in rfx_module.active().lines:
        offers = _contenders(comparison, line.sku, vendors)
        award = LineAward(
            sku=line.sku,
            description=line.description,
            quantity=line.quantity,
            unit=line.canonical_unit,
            contenders=len(offers),
        )

        if not offers:
            award.status = "no_comparable"
            award.reason = ("No shortlisted supplier gave a price we can safely "
                            "compare, so we cannot suggest anyone for this item.")
            awards.append(award)
            continue

        award.winner, award.price = offers[0]
        if line.quantity:
            award.extended = round(award.price * line.quantity, 2)

        if len(offers) == 1:
            award.status = "single_source"
            award.reason = ("Only one shortlisted supplier priced this line "
                            "comparably, so there is nothing to compare it with.")
        else:
            award.runner_up, award.runner_up_price = offers[1]
            award.saving_per_unit = round(award.runner_up_price - award.price, 4)
            if line.quantity:
                award.extended_saving = round(award.saving_per_unit * line.quantity, 2)

        awards.append(award)
    return awards


def _win_counts(awards: list[LineAward]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for award in awards:
        if award.winner:
            counts[award.winner] = counts.get(award.winner, 0) + 1
    return counts


def _consolidate(comparison: Comparison, vendors: list[str],
                 min_lines: int) -> tuple[list[LineAward], list[str]]:
    """Drop suppliers who would win too few lines, and reallocate their lines.

    A supplier is only dropped when every line they won has another comparable
    offer behind it -- consolidation must never turn an awarded line into an
    unawardable one.
    """
    active = list(vendors)
    dropped: list[str] = []

    while len(active) > 1:
        awards = _allocate(comparison, active)
        counts = _win_counts(awards)
        small = [v for v in active if 0 < counts.get(v, 0) < min_lines]
        if not small:
            break

        candidate = min(small, key=lambda v: counts.get(v, 0))
        remaining = [v for v in active if v != candidate]

        # would dropping them strand any line?
        strands = any(
            award.winner == candidate
            and not _contenders(comparison, award.sku, remaining)
            for award in awards
        )
        if strands:
            break

        active = remaining
        dropped.append(candidate)

    final = _allocate(comparison, active)
    for award in final:
        original = None
        for previous in _allocate(comparison, vendors):
            if previous.sku == award.sku:
                original = previous.winner
                break
        if original and original != award.winner and original in dropped:
            award.reassigned_from = original
    return final, dropped


def recommend(
    comparison: Comparison,
    min_lines: int = 1,
    min_quality: float = 0.0,
    enforce_requirements: bool = True,
) -> AwardPlan:
    """Build a split-award recommendation.

    A supplier is shortlisted unless they fail a criterion the BUYER marked as
    a must-have, or fall below a quality score the buyer set. Neither of those
    happens by default: the old build eliminated three suppliers out of five
    before anyone had looked at a price.
    """
    summaries = {s.vendor: s for s in comparison.summaries}
    eligible, excluded = [], []
    for summary in comparison.summaries:
        fails_hard = enforce_requirements and not summary.meets_requirements
        below_bar = summary.quality_score < min_quality
        (excluded if (fails_hard or below_bar) else eligible).append(summary.vendor)

    plan = AwardPlan(eligible=eligible, excluded=excluded, min_lines=min_lines)

    if not eligible:
        return plan

    if min_lines > 1:
        awards, dropped = _consolidate(comparison, eligible, min_lines)
        plan.dropped_for_size = dropped
        baseline = _allocate(comparison, eligible)
    else:
        awards = _allocate(comparison, eligible)
        baseline = awards

    plan.lines = awards
    plan.unawardable = [a for a in awards if a.status == "no_comparable"]

    # --- per supplier ------------------------------------------------------
    by_vendor: dict[str, VendorAward] = {}
    for award in awards:
        if not award.winner:
            continue
        entry = by_vendor.setdefault(award.winner, VendorAward(vendor=award.winner))
        entry.lines.append(award.sku)
        if award.status == "single_source":
            entry.single_source_lines.append(award.sku)
        if award.extended is not None:
            entry.extended_total = round((entry.extended_total or 0) + award.extended, 2)

    plan.vendors = sorted(by_vendor.values(), key=lambda v: -v.line_count)

    extendables = [a.extended for a in awards if a.extended is not None]
    awarded = [a for a in awards if a.winner]
    plan.quantities_known = bool(extendables) and len(extendables) == len(awarded)
    if extendables:
        plan.total_extended = round(sum(extendables), 2)

    # --- split versus one supplier, on the basket they all priced ----------
    common = [
        line.sku for line in rfx_module.active().lines
        if all((comparison.cell(line.sku, v) or None) and
               comparison.cell(line.sku, v).comparable for v in eligible)
    ]
    plan.common_basket = len(common)

    if common and len(eligible) > 1:
        quantities = {line.sku: line.quantity for line in rfx_module.active().lines}
        plan.common_quantities_known = all(quantities.get(sku) for sku in common)

        def basket_total(prices: dict[str, float]) -> Optional[float]:
            total = 0.0
            for sku in common:
                quantity = quantities.get(sku) or 1
                total += prices[sku] * quantity
            return round(total, 2)

        # The split total must be the plan actually on screen, not a
        # theoretical cheapest-of-everyone. Where consolidation moved a line
        # off its cheapest supplier, that decision costs money and the saving
        # has to carry the cost, or the headline promises more than the
        # recommendation delivers.
        recommended = {award.sku: award for award in awards if award.winner}
        split_prices = {}
        for sku in common:
            award = recommended.get(sku)
            if award is not None and award.price is not None:
                split_prices[sku] = award.price
            else:  # not recommended for a reason unrelated to price
                split_prices[sku] = min(
                    price for _, price in _contenders(comparison, sku, eligible))
        plan.split_on_common = basket_total(split_prices)

        singles: dict[str, float] = {}
        for vendor in eligible:
            singles[vendor] = basket_total({
                sku: comparison.cell(sku, vendor).canonical_value for sku in common
            })
        plan.best_single_vendor = min(singles, key=singles.get)
        plan.best_single_total = singles[plan.best_single_vendor]
        plan.saving_vs_single = round(plan.best_single_total - plan.split_on_common, 2)

    # --- what consolidation cost ------------------------------------------
    if plan.dropped_for_size:
        before = sum(a.extended for a in baseline if a.extended is not None)
        after = sum(a.extended for a in awards if a.extended is not None)
        if before and after:
            plan.consolidation_cost = round(after - before, 2)

    return plan


def caveats(plan: AwardPlan, comparison: Comparison) -> list[str]:
    """What this recommendation deliberately does not account for."""
    notes: list[str] = []

    if plan.excluded:
        names = ", ".join(plan.excluded)
        notes.append(f"{names} were left out on quality grounds — either they miss "
                     f"a must-have you set, or they score below your minimum. "
                     f"Relax either control to see what changes.")

    single = [v for v in plan.vendors if v.single_source_lines]
    if single:
        total = sum(len(v.single_source_lines) for v in single)
        notes.append(f"{total} of the items we suggest had only one comparable "
                     f"price, so they were not actually contested. Those are the "
                     f"ones worth going back to the market on.")

    if plan.unawardable:
        notes.append(f"We cannot suggest a supplier for {len(plan.unawardable)} "
                     f"items from these responses. They are listed below with "
                     f"what is needed.")

    if plan.dropped_for_size:
        names = ", ".join(plan.dropped_for_size)
        extra = ""
        if plan.consolidation_cost:
            extra = f" That consolidation costs about {plan.consolidation_cost:,.0f}."
        notes.append(f"{names} came out ahead on too few items to be worth "
                     f"onboarding, so those went to the next cheapest "
                     f"supplier.{extra}")

    freight_mixed = len({s.freight_included for s in comparison.summaries}) > 1
    if freight_mixed:
        notes.append("Delivery is not on the same basis across these suppliers and "
                     "nobody quoted an amount, so these figures exclude it.")

    if any(s.discounts for s in comparison.summaries):
        notes.append("Volume discounts are not applied. A split award may fail to "
                     "reach the thresholds a single-supplier award would.")

    if not plan.quantities_known:
        notes.append("Not every line carries a quantity, so spend figures cover "
                     "only the lines that do. Line counts are unaffected.")

    return notes
