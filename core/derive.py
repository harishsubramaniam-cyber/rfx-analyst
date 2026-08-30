"""Build the request's item list from the responses themselves.

A buyer does not always have the original RFx to hand, and this tool should
not care what category it is pointed at. So the spine is assembled from what
the suppliers actually priced:

  * every item code that appears in at least one response becomes a line
  * its description is the clearest one any supplier gave for it
  * its unit is what most suppliers priced it in, ignoring the odd one out
  * its quantity is whichever figure the suppliers agree on, if any

Two consequences worth being honest about, both surfaced in the interface:

  * with only one response, coverage is always complete, because nothing
    contradicts it. Coverage means "compared with the others", not "compared
    with the buyer's original list".
  * a unit is decided by majority. Where suppliers genuinely disagree, the
    minority is not silently converted -- it lands in the exceptions.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Optional

from .models import VendorResponse
from .normalize import parse_unit
from . import criteria as criteria_module
from .rfx import DEFAULT_CURRENCY, RfxLine, RfxSpec
from .skus import normalize_sku

# A price per kilogram tells you nothing about what the buyer wants a price
# for, so weight never wins the vote for an item's unit.
_NON_CANONICAL_FAMILIES = {"weight", "length"}

# Words that mean "one of them" rather than naming a thing.
_COUNTING_WORDS = {"no", "nos", "ea", "each", "unit", "units",
                   "pc", "pcs", "piece", "pieces"}

_FAMILY_DEFAULT_LABEL = {
    "discrete": "per unit",
    "sheet": "per sheet",
    "roll": "per roll",
    "weight": "per kg",
    "length": "per metre",
}


def _best_description(candidates: list[str]) -> str:
    """The most repeated description; ties broken by the most informative one."""
    cleaned = [c.strip() for c in candidates if c and c.strip()]
    if not cleaned:
        return ""
    counts = Counter(cleaned)
    top = counts.most_common()
    best_count = top[0][1]
    tied = [text for text, count in top if count == best_count]
    return max(tied, key=len)


def _vote_unit(units: list[tuple[Optional[str], Optional[str], str]]) -> tuple[str, str]:
    """Pick a canonical unit from (family, noun, raw) triples.

    Returns (label, family).
    """
    usable = [(family, noun) for family, noun, _ in units
              if family and family not in _NON_CANONICAL_FAMILIES]

    if not usable:
        # Everything was per-kilogram, or nothing said. Fall back to the most
        # common family of any kind, else treat items as countable.
        families = [family for family, _, _ in units if family]
        family = Counter(families).most_common(1)[0][0] if families else "discrete"
        return _FAMILY_DEFAULT_LABEL.get(family, "per unit"), family

    family = Counter(f for f, _ in usable).most_common(1)[0][0]
    nouns = [noun for f, noun in usable if f == family and noun]
    if nouns:
        noun = Counter(nouns).most_common(1)[0][0]
        # "Nos", "ea", "pcs" are ways of writing "one of them", not names for a
        # thing. Echoing them back gives column headings like "per no", which
        # reads as a typo. A noun that describes real packaging -- box, sheet,
        # roll, carton -- is kept, because it tells the buyer what they get.
        if noun in _COUNTING_WORDS:
            return "per unit", family
        return f"per {noun}", family
    return _FAMILY_DEFAULT_LABEL.get(family, "per unit"), family


def _vote_quantity(quantities: list[float]) -> Optional[int]:
    # isfinite before int(): a quantity that came through as Infinity raised
    # OverflowError and took the whole analysis down, from a single bad cell.
    values = [int(q) for q in quantities
              if q and math.isfinite(q) and 0 < q < 1e15]
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def _existing_group(line, descriptions: dict, match_module,
                    vocabulary: set) -> Optional[str]:
    """The group this uncoded line belongs to, if the wording says so.

    Built out of the descriptions already gathered, so a supplier who quotes
    "5-ply box, 400 x 300 x 250 mm" lands on the row another supplier opened
    as "5-ply Corrugated Box - 400 x 300 x 250 mm". The same matcher the
    comparison uses decides, so a merge here means exactly what a match means
    there.
    """
    if not descriptions:
        return None
    candidates = [RfxLine(sku=sku, description=_best_description(texts),
                          quantity=None, canonical_unit="", unit_family="discrete")
                  for sku, texts in descriptions.items()]
    return match_module.match_one(line, candidates, vocabulary).rfx_sku


def derive_spec(responses: list[VendorResponse]) -> RfxSpec:
    """Assemble the comparison spine from a set of supplier responses."""
    descriptions: dict[str, list[str]] = defaultdict(list)
    units: dict[str, list[tuple[Optional[str], Optional[str], str]]] = defaultdict(list)
    quantities: dict[str, list[float]] = defaultdict(list)
    first_seen: dict[str, int] = {}
    currencies: list[str] = []
    stated_currency = False

    # Groups are keyed by item code where the suppliers give one, and matched
    # into by description where they do not. Grouping on the code alone was
    # the old rule, and it quietly defeated the whole exercise whenever two
    # suppliers used different codes -- or none -- for the same product: each
    # got a row of its own, so the two prices a buyer wanted side by side
    # ended up on separate lines that could never be compared.
    from . import match as match_module

    # Learned once, from every description in every response, before any
    # grouping happens. Learning it from the groups gathered so far made the
    # vocabulary -- and therefore which lines contradict which -- depend on how
    # far through the files we were, so the same three quotes produced two rows
    # or three depending purely on which one the buyer dragged in first.
    vocabulary = match_module.marker_vocabulary(
        [line.description or "" for response in responses
         for line in response.lines])

    placeholders = 0
    order = 0
    for response in responses:
        if response.document_currency:
            currencies.append(response.document_currency.upper())
            stated_currency = True
        for line in response.lines:
            sku = normalize_sku(line.vendor_sku)
            if sku is None:
                sku = _existing_group(line, descriptions, match_module,
                                      vocabulary)
            if sku is None:
                text = (line.description or "").strip()
                if not text:
                    continue        # no code and nothing to describe it by
                # A placeholder must not land on a code a supplier actually
                # uses. "ITEM-001" is a perfectly ordinary item code, and
                # minting it blind put a steel drum and a box of gloves on one
                # row.
                placeholders += 1
                sku = f"ITEM-{placeholders:03d}"
                while sku in first_seen:
                    placeholders += 1
                    sku = f"ITEM-{placeholders:03d}"

            if sku not in first_seen:
                first_seen[sku] = order
                order += 1

            if line.description:
                descriptions[sku].append(line.description)

            spec = parse_unit(line.unit_text)
            units[sku].append((spec.family, spec.noun, spec.raw))

            if line.quantity:
                quantities[sku].append(line.quantity)

            if line.currency:
                currencies.append(line.currency.upper())
                stated_currency = True

    lines: list[RfxLine] = []
    for sku in sorted(first_seen, key=lambda s: (s, first_seen[s])):
        label, family = _vote_unit(units[sku])
        lines.append(RfxLine(
            sku=sku,
            description=_best_description(descriptions[sku]) or sku,
            quantity=_vote_quantity(quantities[sku]),
            canonical_unit=label,
            unit_family=family,
        ))

    currency = (Counter(currencies).most_common(1)[0][0]
                if currencies else DEFAULT_CURRENCY)

    # Quality criteria are derived the same way the item list is: from what the
    # suppliers actually answered, in their own words.
    derived_criteria, _ = criteria_module.derive_criteria(responses)

    # A capacity target should come from the basket, not from a round number
    # somebody typed into a template.
    monthly = None
    quantified = [line.quantity for line in lines if line.quantity]
    if quantified:
        monthly = sum(quantified) / 12.0
    for criterion in derived_criteria:
        criterion.suggested_threshold = criteria_module.suggest_threshold(
            criterion, monthly)

    return RfxSpec(
        lines=lines,
        currency=currency,
        criteria=derived_criteria,
        derived=True,
        currency_inferred=not stated_currency,
        basket_units_per_month=monthly,
    )
