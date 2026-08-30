"""Data model.

The single most important rule in this codebase lives here:

    A normalised number NEVER replaces the original. It sits beside it,
    together with the rule and factor that produced it, and the source text
    it came from.

Anything the buyer sees on screen can be walked back to a verbatim snippet of
a vendor document. That is what makes the comparison defensible.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal, Optional

# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------
# Confirmed  - vendor stated it on the buyer's own basis; nothing was done to it
# Normalized - arithmetic was applied, and the factor is recorded and shown
# Needs Review - a number exists but something about it is not trustworthy
# Unresolved - we deliberately refuse to produce a number, and say what is missing
# Not Quoted - the vendor did not answer this line at all

Status = Literal["Confirmed", "Normalized", "Needs Review", "Unresolved", "Not Quoted"]

# Flags are orthogonal to status: a price can be perfectly Confirmed and still
# carry "freight_excluded". Never fold these into the status.
FLAG_LABELS: dict[str, str] = {
    "currency_assumed": "Currency not stated in source; assumed from RFx",
    "unquantified_adder": "Price carries an unpriced extra charge",
    "conditional_price": "Price depends on a condition the RFx cannot verify",
    "freight_excluded": "Freight not included in this price",
    "subject_to_confirmation": "Vendor marked rates as not firm",
    "cross_basis": "Vendor's unit family differs from the RFx line",
    "assumed_family": "Unit family absent from source; assumed from RFx line",
    "spec_deviation": "Priced for something other than what was specified",
    "conditional_freight": "Delivery is only included if a condition is met",
}


@dataclass
class SourceRef:
    """Where a value physically came from. `snippet` must be verbatim."""
    file: str
    locator: str          # "page 1", "sheet 'Quote' row 4", "paragraph 12", "photo"
    snippet: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractedLine:
    """What the model read off the page, before any interpretation."""
    vendor_sku: Optional[str]
    description: Optional[str]
    quoted_value: Optional[float]
    currency: Optional[str]           # as stated; None when the doc never says
    unit_text: Optional[str]          # verbatim, e.g. "per 100 pcs", "/kg"
    quantity: Optional[float] = None
    lead_time_days: Optional[float] = None
    confidence: float = 0.0
    notes: str = ""
    # Verbatim conditions attached to this price: "subject to print plate
    # charges", "rest same as last year's agreed rate". Kept separate from
    # notes because they drive flags, and a buyer must see them.
    conditions: list[str] = field(default_factory=list)
    source: Optional[SourceRef] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class MatchResult:
    """How an extracted line was tied to an RFx line."""
    rfx_sku: Optional[str]
    basis: str            # "exact_sku" | "normalized_sku" | "dimensions" | "description" | "llm" | "unmatched"
    confidence: float
    reason: str = ""


@dataclass
class TermItem:
    kind: str             # "freight" | "payment" | "validity" | "discount" | "tax" | "other"
    text: str             # verbatim
    trigger: Optional[str] = None   # for discounts: the condition
    value: Optional[float] = None   # for discounts: the percentage
    source: Optional[SourceRef] = None


@dataclass
class VendorResponse:
    """One supplier's reply, as extracted. Still on the vendor's own terms."""
    vendor: str
    file: str
    lines: list[ExtractedLine] = field(default_factory=list)
    # Raw questionnaire answers exactly as the supplier gave them: question in
    # their words, verdict, any figure, any evidence. Turned into criteria and
    # scores by core/criteria.py -- never a fixed set of keys.
    questionnaire: list[dict] = field(default_factory=list)
    terms: list[TermItem] = field(default_factory=list)
    document_currency: Optional[str] = None
    freight_included: Optional[bool] = None
    payment_terms_days: Optional[int] = None
    lead_time_days: Optional[float] = None
    unresolved_references: list[str] = field(default_factory=list)
    overall_confidence: float = 0.0
    extraction_notes: str = ""


@dataclass
class Cell:
    """One (RFx line x vendor) intersection: the unit of the comparison grid.

    Carries the original, the canonical, and the complete derivation between
    them. `canonical_value` is None whenever we could not honestly produce one.
    """
    rfx_sku: str
    vendor: str

    # --- as quoted -------------------------------------------------------
    original_text: Optional[str] = None
    original_value: Optional[float] = None
    original_unit: Optional[str] = None
    original_currency: Optional[str] = None

    # --- as normalised ---------------------------------------------------
    canonical_value: Optional[float] = None
    canonical_unit: Optional[str] = None
    canonical_currency: Optional[str] = None

    # --- the derivation --------------------------------------------------
    factor: Optional[str] = None       # human-readable, e.g. "÷ 100 (per 100 pcs → per box)"
    rules: list[str] = field(default_factory=list)
    status: Status = "Not Quoted"
    reason: str = ""
    missing_datum: Optional[str] = None
    flags: list[str] = field(default_factory=list)

    # --- provenance ------------------------------------------------------
    match_basis: str = "unmatched"
    match_confidence: float = 0.0
    extraction_confidence: float = 0.0
    # Why the confidence is not higher, in the buyer's words. Empty means
    # nothing was working against this number.
    confidence_notes: list[str] = field(default_factory=list)
    source_file: Optional[str] = None
    source_locator: Optional[str] = None
    source_snippet: Optional[str] = None

    @property
    def comparable(self) -> bool:
        """True only when this cell may be used in a price comparison."""
        return self.canonical_value is not None and self.status in ("Confirmed", "Normalized")

    def to_row(self) -> dict[str, Any]:
        return {
            "rfx_sku": self.rfx_sku,
            "vendor": self.vendor,
            "original_text": self.original_text,
            "original_value": self.original_value,
            "original_unit": self.original_unit,
            "original_currency": self.original_currency,
            "canonical_value": self.canonical_value,
            "canonical_unit": self.canonical_unit,
            "canonical_currency": self.canonical_currency,
            "factor": self.factor,
            "rules": ",".join(self.rules),
            "status": self.status,
            "reason": self.reason,
            "missing_datum": self.missing_datum,
            "flags": ",".join(self.flags),
            "comparable": int(self.comparable),
            "match_basis": self.match_basis,
            "match_confidence": self.match_confidence,
            "extraction_confidence": self.extraction_confidence,
            "source_file": self.source_file,
            "source_locator": self.source_locator,
            "source_snippet": self.source_snippet,
        }


@dataclass
class DocumentPayload:
    """Whatever we managed to get out of a file, ready for the model.

    A document can yield text, images, or both -- a scanned PDF yields page
    images; a photo yields one image; a spreadsheet yields text.
    """
    file: str
    text: str = ""
    images: list[bytes] = field(default_factory=list)
    image_mime: str = "image/jpeg"
    locator_hint: str = ""
    reader: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def has_content(self) -> bool:
        return bool(self.text.strip()) or bool(self.images)
