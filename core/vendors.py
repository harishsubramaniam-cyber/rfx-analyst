"""The approved vendor list, and who this request should go to.

A rating out of ten is the easiest number in procurement to get wrong. Left as
a bare figure it is a verdict nobody can argue with, and buyers either trust it
completely or ignore it completely -- both bad. So the headline here is derived,
never stored: it is the mean of four scores the buyer keeps from previous
business, each of which is visible next to it. A category manager who thinks a
supplier's delivery has improved can move that one score and watch the
recommendation change, instead of arguing with a 7.4 that came from nowhere.

Two rules the recommendation follows:

**It recommends a shortlist, not a winner.** Rating decides who gets *asked*.
Nothing here touches who gets *awarded* -- that comes from the prices they send
back, and a well-rated supplier who quotes badly should lose. Confusing the two
is how a preferred-supplier list quietly becomes a closed shop.

**It never shortlists fewer than two.** A request sent to one supplier is not a
request, it is a purchase order with extra steps, so if only one vendor clears
the bar the next best is added and the interface says why.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
DIRECTORY_DIR = os.path.join(os.path.dirname(HERE), "examples")
DEFAULT_DIRECTORY = "vendor_directory.json"

# A supplier at or above this is worth asking by default. Deliberately not a
# high bar: the point of an RFx is to find out, and excluding a 6.8 before they
# have quoted anything is a decision that should be taken by hand.
RECOMMEND_AT = 7.0

# Never send a "competitive" request to fewer than this many suppliers.
MINIMUM_SHORTLIST = 2

SCORE_ORDER = ("quality", "delivery", "commercial", "responsiveness")


@dataclass
class DirectoryVendor:
    """One supplier on the approved list, in one category."""
    name: str
    email: str = ""
    location: str = ""
    note: str = ""
    incumbent: bool = False
    scores: dict = field(default_factory=dict)

    @property
    def rating(self) -> float:
        """Out of ten: the mean of the four scores, to one decimal place."""
        values = [float(self.scores[key]) for key in SCORE_ORDER
                  if self.scores.get(key) is not None]
        if not values:
            return 0.0
        return round(sum(values) / len(values), 1)

    @property
    def recommended(self) -> bool:
        return self.rating >= RECOMMEND_AT

    def why(self) -> str:
        """The one-line case for or against asking them."""
        if not self.scores:
            return self.note
        best = max(SCORE_ORDER, key=lambda k: self.scores.get(k, 0))
        worst = min(SCORE_ORDER, key=lambda k: self.scores.get(k, 10))
        if self.scores.get(best, 0) - self.scores.get(worst, 0) < 1.0:
            shape = f"even across the board at {self.rating:.1f}"
        else:
            shape = (f"strongest on {best} ({self.scores[best]:g}), "
                     f"weakest on {worst} ({self.scores[worst]:g})")
        prefix = "Incumbent. " if self.incumbent else ""
        return f"{prefix}{shape}."


@dataclass
class Category:
    key: str
    name: str
    covers: str = ""
    vendors: list = field(default_factory=list)

    def ranked(self) -> list:
        """Best rated first; an incumbent breaks a tie, because switching costs."""
        return sorted(self.vendors,
                      key=lambda v: (-v.rating, not v.incumbent, v.name))


def load(name: str = DEFAULT_DIRECTORY) -> dict[str, Any]:
    with open(os.path.join(DIRECTORY_DIR, name), encoding="utf-8") as handle:
        return json.load(handle)


def categories(name: str = DEFAULT_DIRECTORY) -> list[Category]:
    data = load(name)
    out = []
    for raw in data.get("categories", []):
        out.append(Category(
            key=raw["key"], name=raw["name"], covers=raw.get("covers", ""),
            vendors=[DirectoryVendor(
                name=v["name"], email=v.get("email", ""),
                location=v.get("location", ""), note=v.get("note", ""),
                incumbent=bool(v.get("incumbent")), scores=v.get("scores", {}),
            ) for v in raw.get("vendors", [])],
        ))
    return out


def category(key_or_name: str, name: str = DEFAULT_DIRECTORY) -> Optional[Category]:
    wanted = (key_or_name or "").strip().lower()
    for item in categories(name):
        if wanted in (item.key.lower(), item.name.lower()):
            return item
    return None


def functional_area(name: str = DEFAULT_DIRECTORY) -> str:
    return load(name).get("functional_area", "")


def score_names(name: str = DEFAULT_DIRECTORY) -> dict:
    return load(name).get("score_names", {})


def recommend(item: Category) -> tuple[list, str]:
    """Who to ask, and the sentence explaining the choice.

    Returns (vendors, reason). The reason is written for the buyer, not the
    log: it says how many cleared the bar and what was done about it if too
    few did.
    """
    ranked = item.ranked()
    if not ranked:
        return [], "No approved suppliers are listed for this category yet."

    clearing = [v for v in ranked if v.recommended]

    if len(clearing) >= MINIMUM_SHORTLIST:
        return clearing, (
            f"{len(clearing)} of {len(ranked)} approved suppliers in "
            f"{item.name.lower()} rate {RECOMMEND_AT:g} or better and are "
            f"selected. Ratings decide who is asked, not who wins — that is "
            f"settled by the prices they send back.")

    topped_up = ranked[:MINIMUM_SHORTLIST]
    short = len(clearing)
    return topped_up, (
        f"Only {short} approved supplier{'' if short == 1 else 's'} in "
        f"{item.name.lower()} rate {RECOMMEND_AT:g} or better, so the next "
        f"best has been added to make {len(topped_up)}. A request sent to one "
        f"supplier is not a competitive request, and a rating is a reason to "
        f"look harder at a quote — not a reason to skip asking for one.")
