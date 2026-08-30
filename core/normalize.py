"""Unit and currency normalisation.

The ladder, in order, and the reasoning behind each rung:

1. WORDING. "per unit", "per box", "each", "per box/set" all mean the same
   thing for a line whose product is a box. This is a vocabulary problem, not
   a maths problem -- resolve it deterministically, never ask a model.

2. PACK MULTIPLES. "5,600 / 100", "per 100 pcs", "per 100 rolls" are the same
   basis expressed in bulk. Divide, and record the factor. A system that
   refuses these is not being careful, it is being useless: every one of them
   reconciles cleanly against the other quotes on the same line.

3. CURRENCY. Convert at a dated, fixed rate. Print the rate beside the number.

4. STOP. "₹42/kg" for a corrugated box needs the weight of the box. That
   number is not in the RFx and not in the response, so no amount of cleverness
   produces it. Return Unresolved and name the missing datum precisely, so the
   buyer knows exactly which one-line email to send.

Rung 4 is the one that earns trust. Guessing there would poison every total on
the screen and nobody would ever know.
"""

from __future__ import annotations

import math

import re
from dataclasses import dataclass
from typing import Optional

from . import config
from . import confidence as confidence_module
from .models import Cell, ExtractedLine
from .rfx import RfxLine

# ---------------------------------------------------------------------------
# unit vocabulary
# ---------------------------------------------------------------------------

# Words that mean "one of them" -- what a pack multiple counts. A number is
# only a pack size when something like this follows it, or nothing does.
_COUNTING_NOUNS = {"pc", "pcs", "piece", "pieces", "no", "nos", "num", "ea",
                   "each", "unit", "units", "qty", "count", "off"}

_FAMILY_WORDS: dict[str, str] = {}
for word in ("box", "boxes", "unit", "units", "each", "ea", "pc", "pcs", "piece",
             "pieces", "no", "nos", "set", "sets", "carton", "cartons", "bundle"):
    _FAMILY_WORDS[word] = "discrete"
for word in ("sheet", "sheets"):
    _FAMILY_WORDS[word] = "sheet"
for word in ("roll", "rolls"):
    _FAMILY_WORDS[word] = "roll"
for word in ("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms", "mt", "ton",
             "tonne", "tonnes"):
    _FAMILY_WORDS[word] = "weight"
for word in ("m", "metre", "metres", "meter", "meters", "ft", "feet"):
    _FAMILY_WORDS[word] = "length"

_CURRENCY_TOKENS = {"inr", "usd", "eur", "gbp", "rs", "rs.", "₹", "$", "€", "£"}

_SYMBOL_TO_CODE = {"₹": "INR", "$": "USD", "€": "EUR", "£": "GBP",
                   "rs": "INR", "rs.": "INR", "inr": "INR", "usd": "USD",
                   "eur": "EUR", "gbp": "GBP"}


def _currency_code(raw: Optional[str]) -> Optional[str]:
    """A currency as a code, however the supplier or the model wrote it.

    The model hands back whatever the document said -- "₹", "Rs.", "INR ",
    "$". Uppercasing that and looking it up in the rate table fails, so the
    line was marked Needs Review and the supplier dropped out of every price
    comparison and out of the award: a whole quote lost to a symbol the app
    already knows how to read three lines away.
    """
    if not raw:
        return None
    token = str(raw).strip().lower().rstrip(".")
    if token in _SYMBOL_TO_CODE:
        return _SYMBOL_TO_CODE[token]
    if f"{token}." in _SYMBOL_TO_CODE:
        return _SYMBOL_TO_CODE[f"{token}."]
    return str(raw).strip().upper() or None


@dataclass
class UnitSpec:
    family: Optional[str]     # None = the source never said
    pack: float = 1.0         # how many canonical units one quoted price covers
    raw: str = ""
    currency: Optional[str] = None
    noun: Optional[str] = None  # the supplier's own word: "box", "sheet", "set"


def parse_unit(unit_text: Optional[str]) -> UnitSpec:
    """Read a vendor's unit string into a family and a pack multiple."""
    raw = (unit_text or "").strip()
    if not raw:
        return UnitSpec(family=None, pack=1.0, raw=raw)

    lowered = raw.lower().replace("–", "-")

    currency: Optional[str] = None
    for token, code in _SYMBOL_TO_CODE.items():
        if re.search(rf"(?<![a-z]){re.escape(token)}(?![a-z])", lowered):
            currency = code
            break

    # Strip currency markers so they cannot be mistaken for unit words.
    cleaned = lowered
    for token in sorted(_CURRENCY_TOKENS, key=len, reverse=True):
        # Whole words only. A blind replace turned "per meters" into "per
        # mete " by eating the "rs", which cost the line its unit family --
        # so a per-metre price, which must refuse to convert, was accepted as
        # a per-unit one. A spelling variant should not change refuse to
        # convert.
        cleaned = re.sub(rf"(?<![a-z]){re.escape(token)}(?![a-z])", " ", cleaned)

    # Pack multiple: "per 100 pcs", "/ 100", "/100 rolls", "per 1,000".
    # A pack multiple is a number that COUNTS something: "per 100 pcs",
    # "/ 100", "per 1,000 sheets". A number that describes the thing being
    # priced is not -- "per 5 ply carton", "per 250 gsm box", "per 400 mm
    # box". Dividing by those turned a ₹45 box into ₹9, ₹0.18 and ₹0.11, and
    # the buyer had no way to see it: the price simply looked cheap.
    pack = 1.0
    pack_match = re.search(
        r"(?:per|/|por)\s*([\d][\d,]*)\s*([a-z.]*)", cleaned)
    if pack_match:
        try:
            candidate = float(pack_match.group(1).replace(",", ""))
        except ValueError:
            candidate = 1.0
        follower = pack_match.group(2).strip(". ")
        counts = (not follower                      # "/ 100" -- nothing after
                  or follower in _COUNTING_NOUNS    # "per 100 pcs"
                  or follower in _FAMILY_WORDS      # "per 100 sheets"
                  or (follower.endswith("s") and follower[:-1] in _FAMILY_WORDS))
        if candidate > 1 and counts:
            pack = candidate

    # Family: the last recognised unit word wins ("per 100 rolls" -> roll).
    family: Optional[str] = None
    noun: Optional[str] = None
    for token in re.findall(r"[a-z.]+", cleaned):
        if token in _FAMILY_WORDS:
            family = _FAMILY_WORDS[token]
            noun = token.rstrip(".")

    if noun and noun.endswith("s") and noun[:-1] in _FAMILY_WORDS:
        noun = noun[:-1]          # "boxes" -> "box", so labels read naturally

    return UnitSpec(family=family, pack=pack, raw=raw, currency=currency, noun=noun)


def describe_unit(spec: UnitSpec, canonical_unit: str) -> str:
    if spec.pack > 1:
        return f"{spec.raw or 'bulk'} → {canonical_unit}"
    return f"{spec.raw or 'unstated'} → {canonical_unit}"


# ---------------------------------------------------------------------------
# condition detection
# ---------------------------------------------------------------------------

_CONDITION_PATTERNS: list[tuple[str, str]] = [
    (r"plate charge|tooling|die charge|setup charge|set-up charge", "unquantified_adder"),
    (r"in place of|instead of|alternative to|in lieu of|equivalent grade|"
     r"offered in .* in place", "spec_deviation"),
    (r"moves with|market.linked|reconfirm at the time|subject to fx|"
     r"subject to exchange", "conditional_price"),
    (r"same as last year|previous year|as per last|standard \d{4} rate card|"
     r"\d{4} contract rate|refer to our standard|rest same|balance grades",
     "conditional_price"),
    (r"subject to confirmation|indicative|not firm|budgetary", "subject_to_confirmation"),
    (r"subject to", "conditional_price"),
]


def flags_from_conditions(conditions: list[str], notes: str = "") -> tuple[list[str], list[str]]:
    """Map free-text conditions onto flags. Returns (flags, reasons)."""
    flags: list[str] = []
    reasons: list[str] = []
    haystack = " ; ".join(list(conditions) + ([notes] if notes else [])).lower()
    for pattern, flag in _CONDITION_PATTERNS:
        if re.search(pattern, haystack) and flag not in flags:
            flags.append(flag)
    if conditions:
        reasons.extend(conditions)
    return flags, reasons


# ---------------------------------------------------------------------------
# the normaliser
# ---------------------------------------------------------------------------

def not_quoted(rfx_line: RfxLine, vendor: str, reason: str = "") -> Cell:
    return Cell(
        rfx_sku=rfx_line.sku,
        vendor=vendor,
        status="Not Quoted",
        reason=reason or "This line does not appear anywhere in the vendor's response.",
        canonical_unit=rfx_line.canonical_unit,
        canonical_currency=config.BASE_CURRENCY,
    )


def normalize(
    rfx_line: RfxLine,
    extracted: ExtractedLine,
    vendor: str,
    document_currency: Optional[str] = None,
    match_basis: str = "exact_sku",
    match_confidence: float = 1.0,
    freight_included: Optional[bool] = None,
) -> Cell:
    """Produce one comparison cell from one extracted vendor line."""

    cell = Cell(
        rfx_sku=rfx_line.sku,
        vendor=vendor,
        original_text=(extracted.source.snippet if extracted.source else None)
        or extracted.notes or None,
        original_value=extracted.quoted_value,
        original_unit=extracted.unit_text,
        canonical_unit=rfx_line.canonical_unit,
        canonical_currency=config.BASE_CURRENCY,
        match_basis=match_basis,
        match_confidence=match_confidence,
        extraction_confidence=extracted.confidence,
        source_file=extracted.source.file if extracted.source else None,
        source_locator=extracted.source.locator if extracted.source else None,
        source_snippet=extracted.source.snippet if extracted.source else None,
    )

    # The model's self-reported confidence is only an input; what we show is
    # earned against evidence we can re-check. See core/confidence.py.
    cell.extraction_confidence, cell.confidence_notes = confidence_module.score(
        extracted.confidence,
        snippet=cell.source_snippet,
        match_basis=match_basis,
        match_confidence=match_confidence,
        unit_stated=bool(extracted.unit_text),
        currency_stated=bool(extracted.currency or document_currency),
        source_file=cell.source_file,
        source_locator=cell.source_locator,
    )

    condition_flags, condition_reasons = flags_from_conditions(
        extracted.conditions, extracted.notes
    )
    cell.flags.extend(condition_flags)

    if freight_included is False:
        cell.flags.append("freight_excluded")

    # --- no usable number -------------------------------------------------
    if extracted.quoted_value is None:
        cell.status = "Unresolved"
        cell.reason = (
            "; ".join(condition_reasons)
            or extracted.notes
            or "The vendor referenced this line but did not state a price."
        )
        cell.missing_datum = f"a stated price for {rfx_line.sku}"
        return cell

    spec = parse_unit(extracted.unit_text)
    cell.original_currency = (
        _currency_code(extracted.currency) or spec.currency
        or _currency_code(document_currency) or None
    )

    value = float(extracted.quoted_value)
    if not math.isfinite(value):
        cell.status = "Unresolved"
        cell.reason = ("The price came through as a number that is not a "
                       "number, so nothing can be computed from it.")
        cell.missing_datum = f"a readable price for {rfx_line.sku}"
        return cell
    rules: list[str] = []
    factor_parts: list[str] = []

    # --- rung 4 first: refuse what cannot be honestly converted -----------
    if spec.family == "weight" and rfx_line.unit_family != "weight":
        cell.status = "Unresolved"
        cell.reason = (
            f"Quoted {_money(value, cell.original_currency)} {spec.raw}, but the RFx "
            f"asks for a price {rfx_line.canonical_unit}. Converting weight to "
            f"pieces needs the unit weight of this item, which appears in neither "
            f"the RFx nor this response."
        )
        cell.missing_datum = (
            f"unit weight in kg of one {rfx_line.canonical_unit.replace('per ', '')} "
            f"of {rfx_line.sku}"
        )
        cell.rules.append("weight_basis_unconvertible")
        return cell

    if spec.family == "length" and rfx_line.unit_family != "length":
        cell.status = "Unresolved"
        cell.reason = (
            f"Quoted per length, but the RFx asks {rfx_line.canonical_unit}. "
            "Converting needs the length contained in one unit."
        )
        cell.missing_datum = f"length per {rfx_line.canonical_unit} for {rfx_line.sku}"
        cell.rules.append("length_basis_unconvertible")
        return cell

    # --- rung 1: wording --------------------------------------------------
    cross_basis = False
    if spec.family is None:
        cell.flags.append("assumed_family")
        rules.append("family_assumed_from_rfx")
    elif spec.family != rfx_line.unit_family:
        cross_basis = True
        cell.flags.append("cross_basis")
        rules.append("cross_basis_mismatch")
    else:
        rules.append("unit_alias")

    # --- rung 2: pack multiples -------------------------------------------
    if spec.pack > 1:
        value = value / spec.pack
        rules.append("pack_multiple")
        pack_label = f"÷ {_num(spec.pack)}"
        factor_parts.append(f"{pack_label} ({spec.raw} → {rfx_line.canonical_unit})")

    # --- rung 3: currency --------------------------------------------------
    currency = cell.original_currency
    if currency is None:
        currency = config.BASE_CURRENCY
        cell.original_currency = None
        cell.flags.append("currency_assumed")
        rules.append("currency_assumed_from_rfx")

    currency = currency.upper()
    if currency != config.BASE_CURRENCY:
        rate = config.FX_TO_BASE.get(currency)
        if rate is None:
            cell.status = "Needs Review"
            cell.reason = (
                f"Quoted in {currency}, for which no conversion rate is configured."
            )
            cell.missing_datum = f"{currency}/{config.BASE_CURRENCY} rate"
            cell.canonical_value = None
            cell.rules.extend(rules + ["unknown_currency"])
            return cell
        value = value * rate
        rules.append("fx_conversion")
        factor_parts.append(
            f"× {rate:g} {config.BASE_CURRENCY}/{currency} @ {config.FX_DATE}"
        )

    cell.canonical_value = round(value, 4)
    cell.factor = "  ".join(factor_parts) if factor_parts else None
    cell.rules = rules

    # --- status ------------------------------------------------------------
    downgrading = {"unquantified_adder", "conditional_price",
                   "subject_to_confirmation", "cross_basis", "spec_deviation"}
    if cross_basis:
        cell.status = "Needs Review"
        cell.reason = (
            f"Vendor quoted {spec.raw or 'an unstated unit'} ({spec.family}) but the "
            f"RFx line is priced {rfx_line.canonical_unit} ({rfx_line.unit_family}). "
            "The number is shown but excluded from price comparisons."
        )
    elif any(flag in downgrading for flag in cell.flags):
        cell.status = "Needs Review"
        cell.reason = "; ".join(condition_reasons) or "Price carries an unresolved condition."
    elif spec.pack > 1 or "fx_conversion" in rules:
        cell.status = "Normalized"
        cell.reason = f"Converted from “{spec.raw}” to {rfx_line.canonical_unit}."
    elif "family_assumed_from_rfx" in rules or "currency_assumed_from_rfx" in rules:
        cell.status = "Normalized"
        bits = []
        if "family_assumed_from_rfx" in rules:
            bits.append("unit not stated in source, assumed to be the RFx unit")
        if "currency_assumed_from_rfx" in rules:
            bits.append(
                f"currency not stated anywhere in the document, assumed "
                f"{config.BASE_CURRENCY} from the RFx"
            )
        cell.reason = "; ".join(bits).capitalize() + "."
    else:
        cell.status = "Confirmed"
        cell.reason = "Quoted directly on the RFx basis."

    return cell


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _num(value: float) -> str:
    return f"{int(value)}" if float(value).is_integer() else f"{value:g}"


def _money(value: float, currency: Optional[str]) -> str:
    symbol = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}.get(currency or "", "")
    return f"{symbol}{value:,.2f}" if symbol else f"{value:,.2f} {currency or ''}".strip()
