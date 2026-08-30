"""The request being answered: the spine every response is matched against.

Nothing about this application is tied to corrugated packaging, or to thirty
items, or to rupees. The spine is an `RfxSpec`, and it is normally built from
the supplier responses themselves (see core/derive.py) so the tool works for
any category, any number of items, and any number of suppliers.

The quality criteria are derived too: suppliers are asked to report whatever
questionnaire they were sent, in their own words, and core/criteria.py clusters
those into one set. Nothing in this file is category-specific.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

UnitFamily = Literal["discrete", "sheet", "roll", "weight", "length"]


@dataclass(frozen=True)
class RfxLine:
    sku: str
    description: str
    quantity: Optional[int]
    canonical_unit: str          # what a price should be per
    unit_family: UnitFamily
    # Where this line came from. "buyer" -- they typed or attached it;
    # "document" -- read out of a file they handed over; "suggested" -- the
    # co-pilot proposed it and a person has not yet accepted it; "derived" --
    # inferred from supplier responses because no request existed.
    # A suggested line is never sent to a supplier until it is accepted.
    origin: str = "derived"
    note: str = ""


DEFAULT_CURRENCY = "INR"


@dataclass
class RfxSpec:
    """One request: its item list, its currency, its questions."""
    lines: list[RfxLine] = field(default_factory=list)
    currency: str = DEFAULT_CURRENCY
    # Quality/compliance criteria, derived from the responses -- see
    # core/criteria.py. Nothing here is fixed for a category.
    criteria: list = field(default_factory=list)
    # True when the item list was inferred from the responses rather than
    # supplied by the buyer. Surfaced in the interface, because it changes what
    # a coverage figure means.
    derived: bool = True
    currency_inferred: bool = True
    basket_units_per_month: Optional[float] = None

    # --- set when a buyer drafted this request rather than it being inferred
    title: str = ""
    reference: str = ""
    scope: str = ""              # what the buyer is actually buying, in prose
    delivery_location: str = ""
    terms: dict = field(default_factory=dict)   # payment / delivery / validity / tax
    invited: list = field(default_factory=list)  # Vendor records, see dispatch

    # --- the sourcing window -----------------------------------------------
    # Two timestamps rather than one deadline, and both carry a time. A
    # supplier needs to know when the request opens as well as when it shuts:
    # "responses due Friday" sent on Thursday is a different request from the
    # same words sent a fortnight earlier, and quoting time is the first thing
    # a salesperson checks. The clock matters at the other end too -- "closes
    # on the 9th" is read as midnight by the supplier and as start of business
    # by the buyer, and somebody loses a bid to that gap every year.
    starts_at: str = ""          # ISO "YYYY-MM-DDTHH:MM", or "" while unset
    ends_at: str = ""

    # Which slice of the category this is for. Drives which vendors are
    # recommended, and is printed on the request so a supplier can tell at a
    # glance whether it is aimed at them.
    vendor_category: str = ""

    # The issuer's own notes to suppliers: anything that is not an item, a
    # question or a term. Free text, sent verbatim.
    notes: str = ""

    # Supporting files sent with the request: drawings, specifications, a
    # delivery schedule. Each is {"name", "size", "data", "note"}.
    attachments: list = field(default_factory=list)

    @property
    def window_days(self) -> Optional[int]:
        """How long suppliers have, in whole days. None until both ends are set."""
        if not (self.starts_at and self.ends_at):
            return None
        from datetime import datetime
        try:
            start = datetime.fromisoformat(self.starts_at)
            end = datetime.fromisoformat(self.ends_at)
        except ValueError:
            return None
        return (end - start).days

    @staticmethod
    def stamp(value: str) -> str:
        """An ISO timestamp as a person would write it: '9 Sep 2026, 17:00'."""
        if not value:
            return ""
        from datetime import datetime
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            return value
        return f"{moment.day} {moment:%b %Y}, {moment:%H:%M}"

    @property
    def by_sku(self) -> dict[str, RfxLine]:
        return {line.sku: line for line in self.lines}

    @property
    def suggested_lines(self) -> list[RfxLine]:
        """Lines the co-pilot proposed that nobody has accepted yet."""
        return [line for line in self.lines if line.origin == "suggested"]

    @property
    def is_drafted(self) -> bool:
        """True when a person authored this request, rather than it being
        reverse-engineered from the replies."""
        return not self.derived

    @property
    def criteria_by_key(self) -> dict:
        return {item.key: item for item in self.criteria}

    @property
    def line_count(self) -> int:
        return len(self.lines)

    def prompt_table(self) -> str:
        return "\n".join(
            f"{line.sku} | {line.description}"
            + (f" | qty {line.quantity}" if line.quantity else "")
            + f" | wanted {line.canonical_unit}"
            for line in self.lines
        )


# ---------------------------------------------------------------------------
# what a request may not be sent without
# ---------------------------------------------------------------------------
# Four things, and each one is here because leaving it out breaks something
# downstream rather than merely looking untidy:
#
#   the window   -- a supplier's first question is always how long they have,
#                   and a request with no closing time cannot be chased, cannot
#                   be closed, and cannot say whether a late quote was late.
#   the category -- it decides which approved suppliers are recommended, and it
#                   is printed on the request so a supplier can tell at a glance
#                   whether it is aimed at them.
#   a supplier   -- a request addressed to nobody is a document, not a request.
#
# One list, consulted by the scope form and by the send step, so the two can
# never disagree about what is outstanding.

SCOPE_MANDATORY = ("starts_at", "ends_at", "vendor_category")

_MANDATORY_LABELS = {
    "starts_at": "RFQ start date and time",
    "ends_at": "RFQ end date and time",
    "vendor_category": "Vendor category",
}


def _unreadable(value: str) -> bool:
    """A timestamp that is set but cannot be read back.

    The co-pilot writes these, and a model that answers "9 Sep 2026, 09:00"
    has left the field unusable rather than filled in. Treating it as present
    would let a request go out with a window nothing downstream can compute.
    """
    from datetime import datetime
    try:
        datetime.fromisoformat(value)
        return False
    except ValueError:
        return True


def missing_scope(spec: "RfxSpec") -> list[str]:
    """The mandatory fields on the scope form that are still empty."""
    outstanding = []
    for name in SCOPE_MANDATORY:
        value = str(getattr(spec, name, "") or "").strip()
        if not value or (name in ("starts_at", "ends_at") and _unreadable(value)):
            outstanding.append(_MANDATORY_LABELS[name])
    return outstanding


def missing_mandatory(spec: "RfxSpec", supplier_count: int) -> list[str]:
    """Everything mandatory that is still outstanding, in reading order.

    The supplier count is passed in rather than read off the spec: who is
    ticked lives in the browser session until the request is actually sent, and
    a rule that only noticed the omission after sending would be no rule.
    """
    outstanding = missing_scope(spec)
    # Both ends set, in the wrong order. The scope tab already says so in
    # words; without this the send button stayed live under it, which is the
    # one thing this list exists to prevent.
    span = spec.window_days
    if not outstanding and span is not None and span < 0:
        outstanding.append("A closing time later than the opening time")
    if supplier_count < 1:
        outstanding.append("At least one supplier")
    return outstanding


# ---------------------------------------------------------------------------
# the active request
# ---------------------------------------------------------------------------

_ACTIVE = RfxSpec()


def active() -> RfxSpec:
    return _ACTIVE


def set_active(spec: RfxSpec) -> RfxSpec:
    global _ACTIVE
    _ACTIVE = spec
    return _ACTIVE


def reset_active() -> RfxSpec:
    return set_active(RfxSpec())


def has_lines() -> bool:
    return bool(_ACTIVE.lines)
